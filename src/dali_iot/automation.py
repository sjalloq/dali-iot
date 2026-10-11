"""Trigger actions and sequences: the site file's ``triggers`` and ``sequences`` entries.

A **trigger** mirrors what happens to its sources onto its targets: when a source
(a device by address, or a DALI group as seen on the bus) receives a control
command, the gateway repeats it to the targets. Sources are written to the
gateway as ``d16gear``/``d16group`` with line and address, so the file needs no
gateway ids; ``device``/``group`` sources the gateway already holds are read
back as addresses and group numbers.

A **sequence** is an ordered list of steps, each a set of targets, an action and a
``delay`` in seconds that the gateway waits before running the step. ``repeat``
runs it that many times, ``loop`` runs it until stopped.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .intent import Action, Targets, target_key
from .refs import DeviceRef, format_ref, parse_ref


class Sources(BaseModel):
    model_config = ConfigDict(extra="forbid")
    devices: list[DeviceRef] = Field(default_factory=list)  # addresses whose commands are mirrored
    groups: list[int] = Field(default_factory=list)  # DALI groups as seen on the bus
    line: int = 0  # the line the groups are on

    def resolve(self) -> list[dict]:
        out = [{"type": "d16gear", "line": line, "address": a} for line, a in map(parse_ref, self.devices)]
        out += [{"type": "d16group", "line": self.line, "address": g} for g in self.groups]
        return out

    def describe(self) -> str:
        parts = [f"A{r}" if isinstance(r, int) else str(r) for r in self.devices]
        parts += [f"group {g}" for g in self.groups]
        return ", ".join(parts) or "-"


class TriggerSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1)
    sources: Sources
    targets: Targets
    enabled: bool = True

    @model_validator(mode="after")
    def _check(self) -> TriggerSpec:
        if not (self.sources.devices or self.sources.groups):
            raise ValueError(f"trigger {self.name!r} has no sources")
        if self.targets.empty():
            raise ValueError(f"trigger {self.name!r} has no targets")
        return self

    def body(self, targets: list[dict]) -> dict[str, Any]:
        return {
            "name": self.name,
            "enabled": self.enabled,
            "sources": self.sources.resolve(),
            "targets": targets,
        }

    def summary(self) -> str:
        return f"{self.sources.describe()} -> {self.targets.describe()}"


def source_key(src: dict, refs_by_id: dict[int, tuple[int, int]]) -> tuple[str, int, int]:
    """Normalise a gateway source to ("gear"|"group", line, address) whatever its type."""
    kind = src.get("type")
    if kind == "device":
        line, addr = refs_by_id.get(int(src.get("id") or -1), (-1, int(src.get("id") or -1)))
        return ("gear", line, addr)
    if kind == "group":
        return ("group", int(src.get("line") or 0), int(src.get("id") or 0))
    return ("gear" if kind == "d16gear" else "group", int(src.get("line") or 0), int(src.get("address") or 0))


def trigger_canonical(rec: dict, refs_by_id: dict[int, tuple[int, int]]) -> dict[str, Any]:
    return {
        "name": rec.get("name"),
        "enabled": rec.get("enabled", True),
        "sources": sorted(source_key(s, refs_by_id) for s in rec.get("sources") or []),
        "targets": sorted(map(target_key, rec.get("targets") or [])),
    }


def trigger_from_gateway(
    rec: dict, device_refs: dict[int, Any], zone_names: dict[int, str]
) -> dict[str, Any]:
    refs_by_id = {i: parse_ref(r) for i, r in device_refs.items()}
    sources: dict[str, Any] = {}
    lines: set[int] = set()
    for kind, line, addr in (source_key(s, refs_by_id) for s in rec.get("sources") or []):
        if kind == "gear" and line >= 0:
            sources.setdefault("devices", []).append(format_ref(line, addr))
        elif kind == "group":
            sources.setdefault("groups", []).append(addr)
            lines.add(line)
    if lines and lines != {0}:
        sources["line"] = min(lines)
    out: dict[str, Any] = {"name": rec.get("name") or f"trigger {rec.get('id')}", "sources": sources}
    out["targets"] = Targets.from_gateway(rec.get("targets") or [], device_refs, zone_names)
    if not rec.get("enabled", True):
        out["enabled"] = False
    return out


class StepSpec(Targets, Action):
    model_config = ConfigDict(extra="forbid")
    delay: float = Field(0.0, ge=0)  # seconds the gateway waits before this step
    enabled: bool = True

    @model_validator(mode="after")
    def _has_targets(self) -> StepSpec:
        if self.empty():
            raise ValueError("step has no targets")
        return self


class SequenceSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1)
    steps: list[StepSpec] = Field(min_length=1)
    repeat: int | None = Field(None, ge=1)
    loop: bool = False
    enabled: bool = True

    def body(self, step_targets: list[list[dict]]) -> dict[str, Any]:
        body: dict[str, Any] = {
            "name": self.name,
            "enabled": self.enabled,
            "loop": self.loop,
            "steps": [
                {
                    "type": "features",
                    "enabled": st.enabled,
                    "delay": st.delay,
                    "data": {"targets": t, "features": st.action_features()},
                }
                for st, t in zip(self.steps, step_targets, strict=True)
            ],
        }
        if self.repeat is not None:
            body["repeat"] = self.repeat
        return body

    def all_targets(self) -> Targets:
        """Every device and zone any step refers to, for reference checking."""
        t = Targets()
        for st in self.steps:
            t.devices += st.devices
            t.zones += st.zones
        return t

    def summary(self) -> str:
        return (
            f"{len(self.steps)} step(s)"
            + (f", repeat {self.repeat}" if self.repeat else "")
            + (", loop" if self.loop else "")
        )


def sequence_canonical(rec: dict) -> dict[str, Any]:
    return {
        "name": rec.get("name"),
        "enabled": rec.get("enabled", True),
        "loop": bool(rec.get("loop", False)),
        "repeat": rec.get("repeat"),
        "steps": [
            (
                bool(st.get("enabled", True)),
                float(st.get("delay") or 0),
                sorted(map(target_key, (st.get("data") or {}).get("targets") or [])),
                (st.get("data") or {}).get("features"),
            )
            for st in rec.get("steps") or []
        ],
    }


def sequence_from_gateway(
    rec: dict, device_refs: dict[int, Any], zone_names: dict[int, str]
) -> dict[str, Any]:
    out: dict[str, Any] = {"name": rec.get("name") or f"sequence {rec.get('id')}"}
    if rec.get("repeat") is not None and rec.get("repeat") != 1:
        out["repeat"] = rec["repeat"]
    if rec.get("loop"):
        out["loop"] = True
    if not rec.get("enabled", True):
        out["enabled"] = False
    steps = []
    for st in rec.get("steps") or []:
        data = st.get("data") or {}
        entry: dict[str, Any] = Targets.from_gateway(data.get("targets") or [], device_refs, zone_names)
        entry.update(Action.from_features(data.get("features")))
        if st.get("delay"):
            entry["delay"] = st["delay"]
        if not st.get("enabled", True):
            entry["enabled"] = False
        steps.append(entry)
    out["steps"] = steps
    return out
