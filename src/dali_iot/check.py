"""``site check``: does the site file still describe what is on the bus?

The bus is asked directly, over the gateway's WebSocket: which addresses answer,
and the serial and unit index in each device's memory bank 0. Serial plus unit
identifies a physical unit, so a readdressed device is seen as a move, not as
one device lost and another found. The gateway's own device records are then
compared with the bus as well, because the gateway never drops a record for a
device that has gone.
"""

from __future__ import annotations

import dataclasses

from .bus import Identity
from .site import DeviceSpec, Site, format_ref


@dataclasses.dataclass
class Finding:
    kind: str  # moved | lost | new | replaced | stale | unscanned | unknown
    detail: str
    suggest: str

    def __str__(self) -> str:
        return f"{self.kind:<9} {self.detail}\n          {self.suggest}"


def _ref(line: int, address: int) -> str:
    r = format_ref(line, address)
    return f"A{r}" if isinstance(r, int) else str(r)


def compare(site: Site, on_bus: list[Identity], gw_devices: list[dict] | None = None) -> list[Finding]:
    """``on_bus``: one Identity per address that answered. ``gw_devices``: the gateway's records."""
    findings: list[Finding] = []
    bus_at: dict[tuple[int, int], Identity] = {(i.line, i.address): i for i in on_bus if i.bank0}
    bus_by_key: dict[tuple, Identity] = {i.key: i for i in bus_at.values() if i.key is not None}
    file_at: dict[tuple[int, int], DeviceSpec] = {(line, d.address): d for line, d in site.devices()}
    file_by_key: dict[tuple, tuple[int, DeviceSpec]] = {
        (d.serial, d.unit): (line, d) for line, d in site.devices() if d.serial is not None
    }
    claimed: set[tuple[int, int]] = set()

    for (line, addr), spec in file_at.items():
        here = bus_at.get((line, addr))
        key = (spec.serial, spec.unit) if spec.serial is not None else None
        if key is None:
            if here is None:
                findings.append(
                    Finding(
                        "lost",
                        f"{spec.name!r} {_ref(line, addr)}: nothing answers on the bus",
                        "remove it from the file if it is gone; a serial (site init --identify) would show a move",
                    )
                )
            else:
                claimed.add((line, addr))
                findings.append(
                    Finding(
                        "unknown",
                        f"{spec.name!r} {_ref(line, addr)}: answers, but the file has no serial to compare",
                        "record serials with: dali-iot site init --identify (then copy them into your file)",
                    )
                )
            continue
        elsewhere = bus_by_key.get(key)
        if here is not None and here.key == key:
            claimed.add((line, addr))
        elif elsewhere is not None:
            claimed.add((elsewhere.line, elsewhere.address))
            findings.append(
                Finding(
                    "moved",
                    f"{spec.name!r} serial {spec.serial}{_unit(spec.unit)}: {_ref(line, addr)} -> {_ref(elsewhere.line, elsewhere.address)}",
                    f"change address: {addr} to {elsewhere.address} and any devices: [{format_ref(line, addr)}] to "
                    f"[{format_ref(elsewhere.line, elsewhere.address)}], then: dali-iot gateway rescan && dali-iot apply --prune",
                )
            )
        elif here is None:
            findings.append(
                Finding(
                    "lost",
                    f"{spec.name!r} serial {spec.serial}{_unit(spec.unit)} {_ref(line, addr)}: not on the bus",
                    "the device is gone or unpowered; remove it from the file if it is gone (apply --prune drops the record)",
                )
            )
        else:
            claimed.add((line, addr))  # something else sits there now; it is handled as replaced, not new
            findings.append(
                Finding(
                    "replaced",
                    f"{spec.name!r} {_ref(line, addr)}: file says serial {spec.serial}{_unit(spec.unit)}, "
                    f"bus has serial {here.serial}{_unit(here.unit)}",
                    "a different device answers here; update serial/unit (and type) in the file if that is intended",
                )
            )

    for (line, addr), ident in sorted(bus_at.items()):
        if (line, addr) in claimed:
            continue
        if ident.key is not None and ident.key in file_by_key:
            continue  # the move finding above covers it
        findings.append(
            Finding(
                "new",
                f"{_ref(line, addr)}: serial {ident.serial}{_unit(ident.unit)}"
                f"{', ' + ident.article if ident.article else ''}, not in the file",
                "add it under lines (dali-iot site init --identify --path OTHER writes a full file to copy from)",
            )
        )

    if gw_devices is not None:
        gw_at = {(int(d.get("line", 0)), int(d["address"])): d for d in gw_devices if "address" in d}
        for (line, addr), d in sorted(gw_at.items()):
            if (line, addr) not in bus_at:
                findings.append(
                    Finding(
                        "stale",
                        f"gateway record {d.get('name')!r} at {_ref(line, addr)}: nothing answers on the bus",
                        "dali-iot apply --prune deletes the record (the device itself is untouched)",
                    )
                )
        for line, addr in sorted(bus_at):
            if (line, addr) not in gw_at:
                findings.append(
                    Finding(
                        "unscanned",
                        f"{_ref(line, addr)} answers on the bus but the gateway has no record of it",
                        "dali-iot gateway rescan",
                    )
                )
    return findings


def _unit(unit: int | None) -> str:
    return f" unit {unit}" if unit is not None else ""
