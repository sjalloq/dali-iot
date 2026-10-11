"""The site file: your names for the gateway's devices and zones.

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
        devices: [lounge back, lounge front]     # device names
      - name: downstairs
        groups: [0]
      - name: everything
        broadcast: [0]                           # lines
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

DEFAULT_PATH = Path("site/site.yaml")

# our type names <-> DALI device type numbers the gateway reports in ``daliTypes``
TYPES = {"fluorescent": 0, "emergency": 1, "dimmer": 4, "led": 6, "relay": 7, "colour": 8}
_BY_NUMBER = {n: name for name, n in TYPES.items()}
_PRIORITY = ["colour", "led", "dimmer", "fluorescent", "emergency", "relay"]  # most specific first


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
    devices: list[str] = Field(default_factory=list)
    groups: list[int] = Field(default_factory=list)
    broadcast: list[int] = Field(default_factory=list)  # lines


class Site(BaseModel):
    model_config = ConfigDict(extra="forbid")
    lines: dict[int, LineSpec] = Field(default_factory=dict)
    zones: list[ZoneSpec] = Field(default_factory=list)

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
        zone_names: set[str] = set()
        for z in self.zones:
            if z.name in zone_names:
                raise ValueError(f"zone name {z.name!r} is used twice")
            zone_names.add(z.name)
            for dname in z.devices:
                if dname not in seen_names:
                    raise ValueError(f"zone {z.name!r} refers to unknown device {dname!r}")
            if not (z.devices or z.groups or z.broadcast):
                raise ValueError(f"zone {z.name!r} has no targets")
        return self

    def devices(self) -> list[tuple[int, DeviceSpec]]:
        """(line, spec) for every device, in file order."""
        return [(line, d) for line, spec in self.lines.items() for d in spec.devices]


def load(path: Path = DEFAULT_PATH) -> Site:
    with path.open() as f:
        return Site.model_validate(yaml.safe_load(f) or {})


def from_gateway(devices: list[dict], zones: list[dict]) -> str:
    """A starting site file from what the gateway holds now, as YAML text.

    Names are kept exactly as the gateway has them, so a fresh file plans no changes.
    """
    names = {d["id"]: (d.get("name") or f"device {d['id']}") for d in devices}
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
    for z in zones:
        spec: dict[str, Any] = {"name": z.get("name") or f"zone {z['id']}"}
        for t in z.get("targets") or []:
            if t.get("type") == "device" and t.get("id") in names:
                spec.setdefault("devices", []).append(names[t["id"]])
            elif t.get("type") == "group":
                spec.setdefault("groups", []).append(t["id"])
            elif t.get("type") == "broadcast":
                spec.setdefault("broadcast", []).append(t.get("id") or 0)
        out["zones"].append(spec)
    header = "# Names for this installation. Edit freely; check with: dali-iot plan\n"
    return header + yaml.safe_dump(out, sort_keys=False, default_flow_style=None, width=100)
