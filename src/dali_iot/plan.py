"""Diff a site file against the gateway, and apply the difference.

A plan is a list of changes, each of which knows how to apply itself. Nothing
touches the gateway until ``Change.apply`` is called, so ``plan`` is read-only.
Devices are matched by line and short address; the gateway id is looked up.
Zones and schedules are matched by name.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable

from .client import Client
from .schedule import canonical
from .site import Site, parse_ref, type_name


@dataclasses.dataclass
class Change:
    op: str  # rename | groups | create | update | delete | note | error
    what: str  # e.g. "device outside" or "zone lounge"
    detail: str
    apply: Callable[[], None] | None = None  # None for notes and errors

    def __str__(self) -> str:
        return f"{self.op:<7} {self.what}: {self.detail}"


def _where(d: dict) -> str:
    return f"line {d.get('line', '?')} A{d.get('address', '?')}"


def _target_key(t: dict) -> tuple[str, int]:
    return (str(t.get("type")), int(t.get("id") or 0))


def _fmt(targets: list[dict]) -> str:
    return ", ".join(f"{t.get('type')}:{t.get('id')}" for t in targets) or "-"


def build(site: Site, client: Client, prune: bool = False) -> list[Change]:
    changes: list[Change] = []
    gw_devices = client.devices()
    by_addr = {(int(d.get("line", 0)), int(d["address"])): d for d in gw_devices if "address" in d}
    gw_zones = client.zones()

    # devices: matched by (line, address); name and, when given, groups
    ids: dict[tuple[int, int], int] = {}  # (line, address) -> gateway id, for targets
    claimed: set[int] = set()
    for line, spec in site.devices():
        name = spec.name
        d = by_addr.get((line, spec.address))
        if d is None:
            changes.append(
                Change(
                    "error",
                    f"device {name}",
                    f"nothing at line {line} A{spec.address} on the gateway",
                )
            )
            continue
        gw_type = type_name(d.get("daliTypes") or [])
        if spec.type is not None and spec.type != gw_type:
            changes.append(
                Change(
                    "error",
                    f"device {name}",
                    f"{_where(d)} is a {gw_type}, site says {spec.type}; not touching it",
                )
            )
            continue
        ids[(line, spec.address)] = d["id"]
        claimed.add(d["id"])
        if d.get("name") != name:
            changes.append(
                Change(
                    "rename",
                    f"device {name}",
                    f"{_where(d)} {d.get('name')!r} -> {name!r}",
                    lambda i=d["id"], n=name: client.put(f"/device/{i}", json={"name": n}),
                )
            )
        if spec.groups is not None:
            have, want = sorted(d.get("groups") or []), sorted(spec.groups)
            if have != want:
                changes.append(
                    Change(
                        "groups",
                        f"device {name}",
                        f"{_where(d)} {have} -> {want}",
                        lambda i=d["id"], g=want: client.put(f"/device/{i}", json={"groups": g}),
                    )
                )
    for d in sorted(gw_devices, key=lambda d: (d.get("line", 0), d.get("address", 0))):
        if d["id"] not in claimed:
            kind = type_name(d.get("daliTypes") or [])
            if prune:
                changes.append(
                    Change(
                        "delete",
                        f"device {d.get('name')!r}",
                        f"{_where(d)} {kind}: gateway record id {d['id']} (the device itself is untouched)",
                        lambda i=d["id"]: client.delete(f"/device/{i}"),
                    )
                )
            else:
                changes.append(
                    Change(
                        "note",
                        f"device {d.get('name')!r}",
                        f"{_where(d)} {kind}: not in the site file (--prune deletes the record)",
                    )
                )

    # zones: by name
    gw_by_name: dict[str, dict] = {}
    for z in gw_zones:
        gw_by_name.setdefault(str(z.get("name")), z)
    site_zone_names = {z.name for z in site.zones}
    for z in site.zones:
        name = z.name
        missing = [r for r in z.devices if parse_ref(r) not in ids]
        if missing:
            changes.append(Change("error", f"zone {name}", f"skipped: device(s) {_refs(missing)} unresolved"))
            continue
        want = [{"type": "device", "id": ids[parse_ref(r)]} for r in z.devices]
        want += [{"type": "group", "id": g} for g in z.groups]
        want += [{"type": "broadcast", "id": line} for line in z.broadcast]
        gz = gw_by_name.get(name)
        if gz is None:
            changes.append(
                Change(
                    "create",
                    f"zone {name}",
                    _fmt(want),
                    lambda n=name, t=want: client.post("/zone", json={"name": n, "targets": t}),
                )
            )
        elif sorted(map(_target_key, gz.get("targets") or [])) != sorted(map(_target_key, want)):
            changes.append(
                Change(
                    "update",
                    f"zone {name}",
                    f"{_fmt(gz.get('targets') or [])} -> {_fmt(want)}",
                    lambda i=gz["id"], n=name, t=want: client.put(
                        f"/zone/{i}", json={"name": n, "targets": t}
                    ),
                )
            )
    for name, gz in gw_by_name.items():
        if name not in site_zone_names:
            if prune:
                changes.append(
                    Change(
                        "delete",
                        f"zone {name}",
                        f"id {gz['id']}",
                        lambda i=gz["id"]: client.delete(f"/zone/{i}"),
                    )
                )
            else:
                changes.append(
                    Change("note", f"zone {name}", f"id {gz['id']} is not in the site file (--prune deletes)")
                )

    # schedules: by name. Zone targets may be zones this plan creates, so they
    # are resolved again at apply time.
    zone_ids = {name: gz["id"] for name, gz in gw_by_name.items()}

    def targets_for(sc, zone_ids: dict[str, int]) -> list[dict]:
        t = [{"type": "device", "id": ids[parse_ref(r)]} for r in sc.devices]
        t += [{"type": "zone", "id": zone_ids[n]} for n in sc.zones]
        t += [{"type": "group", "id": g} for g in sc.groups]
        t += [{"type": "broadcast", "id": line} for line in sc.broadcast]
        return t

    def body_now(sc) -> dict:
        fresh = {str(z.get("name")): z["id"] for z in client.zones()}
        return sc.body(targets_for(sc, fresh))

    gw_sched: dict[str, dict] = {}
    for r in client.automations("schedule"):
        gw_sched.setdefault(str(r.get("name")), r)
    site_sched_names = {sc.name for sc in site.schedules}
    for sc in site.schedules:
        name = sc.name
        missing = [r for r in sc.devices if parse_ref(r) not in ids]
        if missing:
            changes.append(
                Change("error", f"schedule {name}", f"skipped: device(s) {_refs(missing)} unresolved")
            )
            continue
        pending = [n for n in sc.zones if n not in zone_ids]
        summary = f"{sc.at} -> {sc.action_features()} on " + _names(sc)
        gr = gw_sched.get(name)
        if gr is None:
            changes.append(
                Change(
                    "create",
                    f"schedule {name}",
                    summary,
                    lambda s=sc: client.create_automation("schedule", body_now(s)),
                )
            )
        elif pending or canonical(gr) != canonical(sc.body(targets_for(sc, zone_ids))):
            changes.append(
                Change(
                    "update",
                    f"schedule {name}",
                    summary,
                    lambda i=gr["id"], s=sc: client.update_automation("schedule", i, body_now(s)),
                )
            )
    for name, gr in gw_sched.items():
        if name not in site_sched_names:
            if prune:
                changes.append(
                    Change(
                        "delete",
                        f"schedule {name}",
                        f"id {gr['id']}",
                        lambda i=gr["id"]: client.delete_automation("schedule", i),
                    )
                )
            else:
                changes.append(
                    Change(
                        "note", f"schedule {name}", f"id {gr['id']} is not in the site file (--prune deletes)"
                    )
                )
    return changes


def _refs(refs) -> str:
    return ", ".join(f"A{r}" if isinstance(r, int) else str(r) for r in refs)


def _names(sc) -> str:
    parts = [f"A{r}" if isinstance(r, int) else str(r) for r in sc.devices] + [f"zone {z}" for z in sc.zones]
    parts += [f"group {g}" for g in sc.groups] + [f"line {line}" for line in sc.broadcast]
    return ", ".join(parts)
