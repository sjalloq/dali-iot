"""The site file: your names for the gateway's devices and zones, and your schedules.

Kept outside git by default (``site/`` is ignored) because it describes one
installation. Devices are keyed by DALI line and short address, the only
identifier the gateway shares with the bus::

    lines:
      0:
        devices:
          - name: outside
            address: 7
            type: relay          # checked against the gateway; omit to skip
            groups: [0]          # managed if given; omit to leave alone
    zones:
      - name: lounge
        devices: [0, 4]                          # short addresses on line 0 ("1/4" = line 1)
      - name: downstairs
        groups: [0]
      - name: everything
        broadcast: [0]                           # lines
    schedules:
      - name: outside on
        at: sunset                               # or '22:00', sunset-0:30, sunrise+1:00
        devices: [7]
        switch: on
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from . import schedule

DEFAULT_PATH = Path("site/site.yaml")

# our type names <-> DALI device type numbers the gateway reports in ``daliTypes``
TYPES = {"fluorescent": 0, "emergency": 1, "dimmer": 4, "led": 6, "relay": 7, "colour": 8}
_BY_NUMBER = {n: name for name, n in TYPES.items()}
_PRIORITY = ["colour", "led", "dimmer", "fluorescent", "emergency", "relay"]  # most specific first


DeviceRef = int | str  # address on line 0, or "line/address"


def parse_ref(ref: DeviceRef) -> tuple[int, int]:
    """A device reference -> (line, address)."""
    if isinstance(ref, bool):
        raise ValueError(f"device reference {ref!r} is not an address")  # noqa: TRY004  (pydantic wants ValueError)
    if isinstance(ref, int):
        line, addr = 0, ref
    else:
        m = re.fullmatch(r"\s*(\d+)\s*/\s*(\d+)\s*", str(ref))
        if not m:
            raise ValueError(f"device reference {ref!r}; use an address like 7, or line/address like 1/7")
        line, addr = int(m[1]), int(m[2])
    if not 0 <= addr <= 63:
        raise ValueError(f"device reference {ref!r}: address must be 0..63")
    return line, addr


def format_ref(line: int, address: int) -> DeviceRef:
    return address if line == 0 else f"{line}/{address}"


def type_name(dali_types: list[int]) -> str:
    """Our name for a device reporting these DALI types; the raw number if unknown."""
    names = [_BY_NUMBER[t] for t in dali_types if t in _BY_NUMBER]
    for p in _PRIORITY:
        if p in names:
            return p
    return str(dali_types[0]) if dali_types else "unknown"


class DeviceSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1)
    address: int = Field(ge=0, le=63)
    type: str | None = None
    groups: list[int] | None = None  # None = leave the gateway's groups alone


class LineSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    devices: list[DeviceSpec] = Field(default_factory=list)


class ZoneSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1)
    devices: list[DeviceRef] = Field(default_factory=list)  # see parse_ref
    groups: list[int] = Field(default_factory=list)
    broadcast: list[int] = Field(default_factory=list)  # lines


class Site(BaseModel):
    model_config = ConfigDict(extra="forbid")
    lines: dict[int, LineSpec] = Field(default_factory=dict)
    zones: list[ZoneSpec] = Field(default_factory=list)
    schedules: list[schedule.ScheduleSpec] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check(self) -> Site:
        seen_names: dict[str, int] = {}
        seen_addr: dict[tuple[int, int], str] = {}
        for line, spec in self.lines.items():
            for d in spec.devices:
                if d.name in seen_names:
                    raise ValueError(
                        f"device name {d.name!r} is used twice (lines {seen_names[d.name]} and {line})"
                    )
                seen_names[d.name] = line
                if (line, d.address) in seen_addr:
                    raise ValueError(
                        f"{seen_addr[(line, d.address)]!r} and {d.name!r} both have address {d.address} on line {line}"
                    )
                seen_addr[(line, d.address)] = d.name
                if d.type is not None and d.type not in TYPES and not d.type.isdigit():
                    raise ValueError(
                        f"device {d.name!r}: unknown type {d.type!r} (one of {', '.join(TYPES)}, or a number)"
                    )

        def check_refs(what: str, refs: list[DeviceRef]) -> None:
            for ref in refs:
                try:
                    key = parse_ref(ref)
                except ValueError as e:
                    raise ValueError(f"{what}: {e}") from None
                if key not in seen_addr:
                    raise ValueError(f"{what} refers to {ref!r}, which is not under lines")

        zone_names: set[str] = set()
        for z in self.zones:
            if z.name in zone_names:
                raise ValueError(f"zone name {z.name!r} is used twice")
            zone_names.add(z.name)
            check_refs(f"zone {z.name!r}", z.devices)
            if not (z.devices or z.groups or z.broadcast):
                raise ValueError(f"zone {z.name!r} has no targets")
        sched_names: set[str] = set()
        for sc in self.schedules:
            if sc.name in sched_names:
                raise ValueError(f"schedule name {sc.name!r} is used twice")
            sched_names.add(sc.name)
            check_refs(f"schedule {sc.name!r}", sc.devices)
            for zname in sc.zones:
                if zname not in zone_names:
                    raise ValueError(f"schedule {sc.name!r} refers to unknown zone {zname!r}")
        return self

    def devices(self) -> list[tuple[int, DeviceSpec]]:
        """(line, spec) for every device, in file order."""
        return [(line, d) for line, spec in self.lines.items() for d in spec.devices]


def load(path: Path = DEFAULT_PATH) -> Site:
    with path.open() as f:
        return Site.model_validate(yaml.safe_load(f) or {})


def from_gateway(devices: list[dict], zones: list[dict], schedules: list[dict] = ()) -> str:
    """A starting site file from what the gateway holds now, as YAML text.

    Names are kept exactly as the gateway has them, so a fresh file plans no changes.
    """
    names = {d["id"]: (d.get("name") or f"device {d['id']}") for d in devices}
    refs = {d["id"]: format_ref(int(d.get("line", 0)), int(d["address"])) for d in devices if "address" in d}
    lines: dict[int, dict[str, Any]] = {}
    for d in sorted(devices, key=lambda d: (d.get("line", 0), d.get("address", 0))):
        lines.setdefault(int(d.get("line", 0)), {"devices": []})["devices"].append(
            {
                "name": names[d["id"]],
                "address": d.get("address"),
                "type": type_name(d.get("daliTypes") or []),
                "groups": sorted(d.get("groups") or []),
            }
        )
    out: dict[str, Any] = {"lines": lines, "zones": []}
    zone_names = {z["id"]: (z.get("name") or f"zone {z['id']}") for z in zones}
    for z in zones:
        spec: dict[str, Any] = {"name": zone_names[z["id"]]}
        for t in z.get("targets") or []:
            if t.get("type") == "device" and t.get("id") in refs:
                spec.setdefault("devices", []).append(refs[t["id"]])
            elif t.get("type") == "group":
                spec.setdefault("groups", []).append(t["id"])
            elif t.get("type") == "broadcast":
                spec.setdefault("broadcast", []).append(t.get("id") or 0)
        out["zones"].append(spec)
    if schedules:
        out["schedules"] = [schedule.from_gateway(r, refs, zone_names) for r in schedules]
    header = "# Names for this installation. Edit freely; check with: dali-iot plan\n"
    return header + yaml.safe_dump(out, sort_keys=False, default_flow_style=None, width=100)
