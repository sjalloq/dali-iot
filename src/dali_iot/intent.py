"""Vocabulary shared by schedules, triggers and sequences: *to whom* and *what*.

``Targets`` names devices (by short address), zones (by name), DALI groups and
whole lines. ``Action`` is exactly one of ``switch``, ``level`` (with optional
``fade``), ``scene`` or a raw ``features`` dict, and converts to and from the
gateway's feature dict.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .refs import DeviceRef, format_ref, parse_ref


class Targets(BaseModel):
    model_config = ConfigDict(extra="forbid")
    devices: list[DeviceRef] = Field(default_factory=list)  # short addresses; see site.parse_ref
    zones: list[str] = Field(default_factory=list)  # zone names from this file
    groups: list[int] = Field(default_factory=list)  # DALI groups 0-15
    broadcast: list[int] = Field(default_factory=list)  # lines

    def empty(self) -> bool:
        return not (self.devices or self.zones or self.groups or self.broadcast)

    def resolve(self, ids: dict[tuple[int, int], int], zone_ids: dict[str, int]) -> list[dict]:
        """Gateway target list. Callers check that every device and zone resolves first."""
        t = [{"type": "device", "id": ids[parse_ref(r)]} for r in self.devices]
        t += [{"type": "zone", "id": zone_ids[n]} for n in self.zones]
        t += [{"type": "group", "id": g} for g in self.groups]
        t += [{"type": "broadcast", "id": line} for line in self.broadcast]
        return t

    def describe(self) -> str:
        parts = [f"A{r}" if isinstance(r, int) else str(r) for r in self.devices]
        parts += [f"zone {z}" for z in self.zones]
        parts += [f"group {g}" for g in self.groups] + [f"line {line}" for line in self.broadcast]
        return ", ".join(parts) or "-"

    @staticmethod
    def from_gateway(targets: list[dict], refs: dict[int, Any], zone_names: dict[int, str]) -> dict[str, Any]:
        """Gateway target list -> site-file keys. ``refs``: gateway device id -> address reference."""
        out: dict[str, Any] = {}
        for t in targets or []:
            kind, tid = t.get("type"), t.get("id")
            if kind == "device" and tid in refs:
                out.setdefault("devices", []).append(refs[tid])
            elif kind == "zone" and tid in zone_names:
                out.setdefault("zones", []).append(zone_names[tid])
            elif kind == "group":
                out.setdefault("groups", []).append(int(tid or 0))
            elif kind == "broadcast":
                out.setdefault("broadcast", []).append(int(tid or 0))
        return out


def target_key(t: dict) -> tuple[str, int]:
    return (str(t.get("type")), int(t.get("id") or 0))


class Action(BaseModel):
    model_config = ConfigDict(extra="forbid")
    switch: bool | None = None
    level: int | None = Field(None, ge=0, le=100)
    fade: float | None = Field(None, ge=0)
    scene: int | None = Field(None, ge=0, le=15)
    features: dict[str, Any] | None = None  # raw gateway features, for anything else

    @model_validator(mode="after")
    def _one_action(self) -> Action:
        given = [k for k in ("switch", "level", "scene", "features") if getattr(self, k) is not None]
        if len(given) != 1:
            raise ValueError("give exactly one of switch, level, scene, features")
        if self.fade is not None and self.level is None:
            raise ValueError("fade needs level")
        return self

    def action_features(self) -> dict[str, Any]:
        if self.switch is not None:
            return {"switchable": self.switch}
        if self.level is not None:
            if self.fade:
                return {"dimmableWithFade": {"dimValue": self.level, "fadeTime": self.fade}}
            return {"dimmable": self.level}
        if self.scene is not None:
            return {"scene": self.scene}
        assert self.features is not None
        return self.features

    @staticmethod
    def from_features(f: dict | None) -> dict[str, Any]:
        """Gateway feature dict -> the site-file action keys."""
        f = f or {}
        if set(f) == {"switchable"}:
            return {"switch": bool(f["switchable"])}
        if set(f) == {"dimmable"}:
            return {"level": int(f["dimmable"])}
        if set(f) == {"dimmableWithFade"} and set(f["dimmableWithFade"]) <= {"dimValue", "fadeTime"}:
            return {
                "level": int(f["dimmableWithFade"].get("dimValue", 0)),
                "fade": f["dimmableWithFade"].get("fadeTime", 0),
            }
        if set(f) == {"scene"}:
            return {"scene": int(f["scene"])}
        return {"features": f}


__all__ = ["Action", "Targets", "format_ref", "parse_ref", "target_key"]
