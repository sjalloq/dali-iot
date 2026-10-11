"""Thin REST client for the DALI-2 IoT gateway.

One ``requests.Session``, one ``request`` method, and resource helpers that
know the gateway's naming quirks (``/automations/scheduler`` creates, but
``/automations/schedules`` lists under a ``schedulers`` key, and so on).
Every exchange can be traced to a callback for ``--trace``.
"""

from __future__ import annotations

import dataclasses
import time
from collections.abc import Callable
from typing import Any

import requests

Trace = Callable[[str, str, Any, int, Any], None]
"""``(method, url, request_body, status, response_body)``"""

# kind -> (singular path for create/get/update/delete/start/stop, list path, list key)
AUTOMATIONS: dict[str, tuple[str, str, str]] = {
    "schedule": ("/automations/scheduler", "/automations/schedules", "schedulers"),
    "sequence": ("/automations/sequence", "/automations/sequences", "sequences"),
    "trigger": ("/automations/triggerAction", "/automations/triggerActions", "triggerActions"),
    "circadian": ("/automations/circadian", "/automations/circadians", "circadians"),
}


@dataclasses.dataclass
class Client:
    base_url: str
    timeout: float = 5.0
    trace: Trace | None = None
    session: requests.Session = dataclasses.field(default_factory=requests.Session)

    # --- core ---
    def request(self, method: str, path: str, json: Any = None, params: dict | None = None) -> Any:
        url = f"{self.base_url}/{path.lstrip('/')}"
        r = self.session.request(method, url, json=json, params=params, timeout=self.timeout)
        body: Any = None
        if r.content:
            try:
                body = r.json()
            except ValueError:
                body = r.text
        if self.trace:
            self.trace(method, url, json, r.status_code, body)
        r.raise_for_status()
        return body

    def get(self, path: str, **params: Any) -> Any:
        return self.request("GET", path, params=params or None)

    def post(self, path: str, json: Any = None, **params: Any) -> Any:
        return self.request("POST", path, json=json, params=params or None)

    def put(self, path: str, json: Any = None) -> Any:
        return self.request("PUT", path, json=json)

    def delete(self, path: str) -> Any:
        return self.request("DELETE", path)

    # --- gateway ---
    def info(self) -> dict:
        return self.get("/info")

    def scan_status(self) -> dict:
        return self.get("/dali/scan")

    def rescan(self, progress: Callable[[dict], None] | None = None, poll: float = 1.0) -> dict:
        """Reload the gateway's device list from the bus without changing any address.

        Starts a "current device list" scan (``noAddressing``), the only scan type
        that leaves addresses alone, and waits for it. ``progress`` is called with
        each status poll. Returns the final status. Refuses to start while another
        scan is running.
        """
        before = self.scan_status()
        if before.get("status") in ("in progress", "running", "started", "addressing", "scanning"):
            raise RuntimeError(f"a scan is already running ({before.get('progress')}%)")
        started = self.post("/dali/scan", json={"newInstallation": False, "noAddressing": True})
        scan_id = started.get("id")
        while True:
            time.sleep(poll)
            st = self.scan_status()
            if progress:
                progress(st)
            if st.get("id") == scan_id and st.get("status") in ("done", "cancelled", "error", "failed"):
                return st

    # --- devices, groups, zones ---
    def devices(self) -> list[dict]:
        return self.get("/devices").get("devices", [])

    def device(self, device_id: int) -> dict:
        return self.get(f"/device/{device_id}")

    def zones(self) -> list[dict]:
        return self.get("/zones").get("zones", [])

    def zone(self, zone_id: int) -> dict:
        return self.get(f"/zone/{zone_id}")

    def sensors(self) -> Any:
        return self.get("/sensors")

    def control_device(self, device_id: int, features: dict) -> None:
        self.post(f"/device/{device_id}/control", json=features)

    def blink_device(self, device_id: int, times: int = 2, pause: float = 0.7) -> dict:
        """Switch a device off and on ``times`` times, then put it back as it was.

        The state to restore comes from the device record's feature status
        (``dimmable.status`` 0-100 for dimmers, ``switchable.status`` for relays).
        Returns the features sent to restore it.
        """
        d = self.device(device_id)
        feats = d.get("features") or {}
        level = (feats.get("dimmable") or {}).get("status")
        was_on = bool((feats.get("switchable") or {}).get("status")) or bool(level)
        for _ in range(times):
            self.control_device(device_id, off_features() if was_on else on_features())
            time.sleep(pause)
            self.control_device(device_id, on_features() if was_on else off_features())
            time.sleep(pause)
        restore = (
            on_features(round(level)) if was_on and level else (on_features() if was_on else off_features())
        )
        self.control_device(device_id, restore)
        return restore

    def control_group(self, group_id: int, features: dict, line: int | None = None) -> None:
        self.post(
            f"/group/{group_id}/control", json=features, **({"_line": line} if line is not None else {})
        )

    def control_zone(self, zone_id: int, features: dict) -> None:
        self.post(f"/zone/{zone_id}/control", json=features)

    def control_broadcast(self, features: dict, line: int | None = None) -> None:
        self.post("/broadcast/control", json=features, **({"_line": line} if line is not None else {}))

    # --- automations, uniformly ---
    def automations(self, kind: str) -> list[dict]:
        _, list_path, key = AUTOMATIONS[kind]
        data = self.get(list_path)
        return data.get(key, []) if isinstance(data, dict) else data

    def automation(self, kind: str, item_id: int) -> dict:
        return self.get(f"{AUTOMATIONS[kind][0]}/{item_id}")

    def create_automation(self, kind: str, model: dict) -> dict:
        return self.post(AUTOMATIONS[kind][0], json=model) or {}

    def update_automation(self, kind: str, item_id: int, model: dict) -> dict:
        return self.put(f"{AUTOMATIONS[kind][0]}/{item_id}", json=model) or {}

    def delete_automation(self, kind: str, item_id: int) -> None:
        self.delete(f"{AUTOMATIONS[kind][0]}/{item_id}")

    def start_automation(self, kind: str, item_id: int) -> None:
        self.post(f"{AUTOMATIONS[kind][0]}/{item_id}/start")

    def stop_automation(self, kind: str, item_id: int) -> None:
        self.post(f"{AUTOMATIONS[kind][0]}/{item_id}/stop")


# --- payload helpers: the feature-dict shapes the gateway expects ---


def off_features(fade: float = 0.0) -> dict:
    """OFF for relays and dimmers alike."""
    if fade > 0:
        return {"switchable": False, "dimmableWithFade": {"dimValue": 0, "fadeTime": fade}}
    return {"switchable": False, "dimmable": 0}


def on_features(level: int = 100, fade: float = 0.0) -> dict:
    """ON for relays and dimmers alike."""
    if fade > 0:
        return {"switchable": True, "dimmableWithFade": {"dimValue": level, "fadeTime": fade}}
    return {"switchable": True, "dimmable": level}


def schedule_action(features: dict) -> dict:
    """The one shape a scheduler action accepts.

    The gateway silently accepts ``{"type": "features", "data": {"switchable": ...}}``
    and never fires it. The features must sit under ``data.features``
    (Lunatone API manual 4.2.1). The OpenAPI spec types ``data`` as a free dict,
    so generated models cannot catch this; this helper is the one place that knows.
    """
    return {"type": "features", "data": {"features": features}}
