"""JSON API for the web UI.

Everything the page shows is either the site file (names, zones, schedules) or
the gateway's live state; everything it changes goes through the same paths
the CLI uses. The site file is the source of truth for configuration and this
app owns it on the machine it runs on: edits are written straight back, and
``/api/plan`` and ``/api/apply`` are the CLI's ``plan`` and ``apply``.
Control (on/off/level/scene) goes to the gateway directly and never through
the site model. No gateway id leaves this module: devices are addresses,
zones and sequences are names.
"""

from __future__ import annotations

import dataclasses
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal

import requests
import yaml
from fastapi import APIRouter, FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .. import lookup
from .. import plan as planner
from .. import site as sitefile
from ..client import Client, off_features, on_features
from ..refs import format_ref
from ..schedule import ScheduleSpec

STATIC_DIR = Path(__file__).parent / "static"


@dataclasses.dataclass
class State:
    site_path: Path
    make_client: Callable[[], Client]
    gateway_url: str
    lock: threading.Lock = dataclasses.field(default_factory=threading.Lock)

    def site(self) -> sitefile.Site:
        return sitefile.load(self.site_path)

    def raw(self) -> dict[str, Any]:
        with self.site_path.open() as f:
            return yaml.safe_load(f) or {}

    def edit(self, change: Callable[[dict[str, Any]], None]) -> sitefile.Site:
        """Apply ``change`` to the file's plain dict, validate the result, write it."""
        with self.lock:
            raw = self.raw()
            change(raw)
            site = sitefile.Site.model_validate(raw)  # ValidationError -> 422
            sitefile.save(site, self.site_path)
            return site


# --- request bodies ---


class ControlRequest(BaseModel):
    """One command for one target. Exactly one of switch/level/scene."""

    model_config = ConfigDict(extra="forbid")
    kind: Literal["device", "zone", "group", "broadcast"]
    target: str | int | None = None  # address ref, zone name, group number, line
    switch: bool | None = None
    level: int | None = Field(None, ge=0, le=100)
    fade: float = Field(0.0, ge=0)
    scene: int | None = Field(None, ge=0, le=15)

    def features(self) -> dict:
        given = [k for k in ("switch", "level", "scene") if getattr(self, k) is not None]
        if len(given) != 1:
            raise ValueError("give exactly one of switch, level, scene")
        if self.scene is not None:
            if self.fade > 0:
                return {"sceneWithFade": {"scene": self.scene, "fadeTime": self.fade}}
            return {"scene": self.scene}
        if self.level is not None:
            return on_features(self.level, self.fade) if self.level > 0 else off_features(self.fade)
        return on_features(100, self.fade) if self.switch else off_features(self.fade)


class DeviceEdit(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1)
    groups: list[int] | None = None
    type: str | None = None


class ApplyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    prune: bool = False


# --- helpers ---


def _ref(d: dict) -> str:
    return str(format_ref(int(d.get("line", 0)), int(d.get("address", 0))))


def _device_state(d: dict) -> dict[str, Any]:
    feats = d.get("features") or {}
    level = (feats.get("dimmable") or {}).get("status")
    on = bool((feats.get("switchable") or {}).get("status")) or bool(level)
    return {"on": on, "level": round(level) if level is not None else None}


def _change(c: planner.Change) -> dict[str, Any]:
    return {"op": c.op, "what": c.what, "detail": c.detail, "applies": c.apply is not None}


def _find(items: list[dict], name: str, kind: str) -> int:
    for i, it in enumerate(items):
        if it.get("name") == name:
            return i
    raise lookup.NotFound(f"no {kind} named {name!r} in the site file")


def _dump(model: BaseModel) -> dict[str, Any]:
    return model.model_dump(exclude_none=True, exclude_defaults=True)


# --- the API ---


def _router(state: State) -> APIRouter:
    api = APIRouter(prefix="/api")

    @api.get("/info")
    def info() -> dict:
        c = state.make_client()
        return {"gateway": state.gateway_url, "site": str(state.site_path), "info": c.info()}

    # control: live gateway state, names from the site file

    @api.get("/control")
    def control_state() -> dict:
        c = state.make_client()
        site = state.site()
        names = {(line, d.address): d.name for line, d in site.devices()}
        devices = []
        for d in sorted(c.devices(), key=lambda d: (d.get("line", 0), d.get("address", 0))):
            key = (int(d.get("line", 0)), int(d.get("address", -1)))
            devices.append(
                {
                    "ref": _ref(d),
                    "name": names.get(key) or d.get("name") or _ref(d),
                    "type": sitefile.type_name(d.get("daliTypes") or []),
                    "groups": sorted(d.get("groups") or []),
                    "scenes": sorted(int(s) for s in (d.get("scenes") or []) if isinstance(s, int)),
                    **_device_state(d),
                }
            )
        zones = [
            {"name": z.get("name"), "targets": len(z.get("targets") or [])}
            for z in c.zones()
            if z.get("name")
        ]
        sequences = [sq.get("name") for sq in c.automations("sequence") if sq.get("name")]
        return {"devices": devices, "zones": zones, "sequences": sequences}

    @api.post("/control")
    def control(req: ControlRequest) -> dict:
        c = state.make_client()
        feats = req.features()
        if req.kind == "device":
            c.control_device(lookup.device_at(c, str(req.target))["id"], feats)
        elif req.kind == "zone":
            c.control_zone(lookup.zone_named(c, str(req.target))["id"], feats)
        elif req.kind == "group":
            g = int(req.target or 0)
            if not 0 <= g <= 15:
                raise ValueError("group must be 0-15")
            c.control_group(g, feats)
        else:
            c.control_broadcast(feats, line=int(req.target) if req.target is not None else None)
        return {"sent": feats}

    @api.post("/sequences/{name}/{verb}")
    def sequence_verb(name: str, verb: Literal["run", "stop"]) -> dict:
        c = state.make_client()
        sq = lookup.sequence_named(c, name)
        (c.start_automation if verb == "run" else c.stop_automation)("sequence", sq["id"])
        return {"ok": True}

    # devices: the site file's lines table against the gateway

    @api.get("/devices")
    def devices() -> dict:
        c = state.make_client()
        site = state.site()
        gw = {(int(d.get("line", 0)), int(d["address"])): d for d in c.devices() if "address" in d}
        rows = []
        seen = set()
        for line, spec in site.devices():
            d = gw.get((line, spec.address))
            seen.add((line, spec.address))
            rows.append(
                {
                    "line": line,
                    "address": spec.address,
                    "ref": str(format_ref(line, spec.address)),
                    "name": spec.name,
                    "type": spec.type,
                    "groups": spec.groups,
                    "serial": spec.serial,
                    "product": spec.product,
                    "in_site": True,
                    "on_gateway": d is not None,
                    "gateway_name": d.get("name") if d else None,
                    "gateway_type": sitefile.type_name(d.get("daliTypes") or []) if d else None,
                    "gateway_groups": sorted(d.get("groups") or []) if d else None,
                }
            )
        for key, d in sorted(gw.items()):
            if key in seen:
                continue
            rows.append(
                {
                    "line": key[0],
                    "address": key[1],
                    "ref": _ref(d),
                    "name": d.get("name"),
                    "type": None,
                    "groups": None,
                    "serial": None,
                    "product": None,
                    "in_site": False,
                    "on_gateway": True,
                    "gateway_name": d.get("name"),
                    "gateway_type": sitefile.type_name(d.get("daliTypes") or []),
                    "gateway_groups": sorted(d.get("groups") or []),
                }
            )
        return {"devices": rows, "types": list(sitefile.TYPES)}

    @api.put("/devices/{line}/{address}")
    def edit_device(line: int, address: int, body: DeviceEdit) -> dict:
        def change(raw: dict[str, Any]) -> None:
            lines = raw.setdefault("lines", {})
            spec = lines.setdefault(line, {"devices": []})
            devs = spec.setdefault("devices", [])
            for d in devs:
                if d.get("address") == address:
                    d["name"] = body.name
                    if body.groups is not None:
                        d["groups"] = body.groups
                    if body.type is not None:
                        d["type"] = body.type
                    return
            entry: dict[str, Any] = {"name": body.name, "address": address}
            if body.type is not None:
                entry["type"] = body.type
            if body.groups is not None:
                entry["groups"] = body.groups
            devs.append(entry)
            devs.sort(key=lambda d: d.get("address", 0))

        state.edit(change)
        return {"ok": True}

    @api.delete("/devices/{line}/{address}")
    def remove_device(line: int, address: int) -> dict:
        def change(raw: dict[str, Any]) -> None:
            devs = (raw.get("lines") or {}).get(line, {}).get("devices") or []
            keep = [d for d in devs if d.get("address") != address]
            if len(keep) == len(devs):
                raise lookup.NotFound(f"no device at line {line} A{address} in the site file")
            raw["lines"][line]["devices"] = keep

        state.edit(change)
        return {"ok": True}

    @api.post("/devices/{line}/{address}/blink")
    def blink(line: int, address: int) -> dict:
        c = state.make_client()
        d = lookup.device_at(c, format_ref(line, address))
        return {"restored": c.blink_device(d["id"])}

    # schedules: entries in the site file

    @api.get("/schedules")
    def schedules() -> dict:
        site = state.site()
        return {
            "schedules": [s.model_dump(exclude_none=True) for s in site.schedules],
            "zones": [z.name for z in site.zones],
            "devices": [
                {"ref": str(format_ref(line, d.address)), "name": d.name} for line, d in site.devices()
            ],
        }

    @api.post("/schedules")
    def add_schedule(body: ScheduleSpec) -> dict:
        def change(raw: dict[str, Any]) -> None:
            items = raw.setdefault("schedules", [])
            if any(s.get("name") == body.name for s in items):
                raise ValueError(f"schedule {body.name!r} already exists")
            items.append(_dump(body))

        state.edit(change)
        return {"ok": True}

    @api.put("/schedules/{name}")
    def edit_schedule(name: str, body: ScheduleSpec) -> dict:
        def change(raw: dict[str, Any]) -> None:
            items = raw.setdefault("schedules", [])
            items[_find(items, name, "schedule")] = _dump(body)

        state.edit(change)
        return {"ok": True}

    @api.delete("/schedules/{name}")
    def remove_schedule(name: str) -> dict:
        def change(raw: dict[str, Any]) -> None:
            items = raw.setdefault("schedules", [])
            del items[_find(items, name, "schedule")]

        state.edit(change)
        return {"ok": True}

    # plan / apply

    @api.get("/plan")
    def plan(prune: bool = False) -> dict:
        changes = planner.build(state.site(), state.make_client(), prune=prune)
        return {"changes": [_change(c) for c in changes]}

    @api.post("/apply")
    def apply(body: ApplyRequest) -> dict:
        with state.lock:
            changes = planner.build(state.site(), state.make_client(), prune=body.prune)
            applied = []
            for c in changes:
                if c.apply:
                    c.apply()
                    applied.append(_change(c))
        return {"applied": applied, "errors": [_change(c) for c in changes if c.op == "error"]}

    return api


def create_app(
    site_path: Path,
    gateway_url: str,
    make_client: Callable[[], Client] | None = None,
    timeout: float = 5.0,
    static_dir: Path | None = STATIC_DIR,
) -> FastAPI:
    """The ASGI app. ``make_client`` is injectable so tests run over a fake session."""
    state = State(
        site_path=site_path,
        gateway_url=gateway_url,
        make_client=make_client or (lambda: Client(gateway_url, timeout=timeout)),
    )
    app = FastAPI(title="dali-iot", docs_url="/api/docs", openapi_url="/api/openapi.json")
    app.include_router(_router(state))

    @app.exception_handler(lookup.NotFound)
    def _not_found(_: Request, e: lookup.NotFound) -> JSONResponse:
        return JSONResponse({"detail": str(e)}, status_code=404)

    @app.exception_handler(FileNotFoundError)
    def _no_site(_: Request, e: FileNotFoundError) -> JSONResponse:
        return JSONResponse(
            {"detail": f"{state.site_path} not found; create it with: dali-iot site init"}, status_code=404
        )

    @app.exception_handler(ValidationError)
    def _invalid(_: Request, e: ValidationError) -> JSONResponse:
        msgs = [f"{'.'.join(str(p) for p in err['loc'])}: {err['msg']}" for err in e.errors()]
        return JSONResponse({"detail": "; ".join(msgs)}, status_code=422)

    @app.exception_handler(ValueError)
    def _bad(_: Request, e: ValueError) -> JSONResponse:
        return JSONResponse({"detail": str(e)}, status_code=422)

    @app.exception_handler(requests.RequestException)
    def _gateway(_: Request, e: requests.RequestException) -> JSONResponse:
        return JSONResponse({"detail": f"gateway: {e}"}, status_code=502)

    if static_dir and (static_dir / "index.html").exists():
        app.mount("/assets", StaticFiles(directory=static_dir / "assets"), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        def spa(path: str) -> FileResponse:
            file = static_dir / path
            if path and file.is_file():
                return FileResponse(file)
            return FileResponse(static_dir / "index.html")

    return app
