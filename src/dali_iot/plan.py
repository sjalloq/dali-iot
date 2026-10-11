"""Diff a site file against the gateway, and apply the difference.

A plan is a list of changes, each of which knows how to apply itself. Nothing
touches the gateway until ``Change.apply`` is called, so ``plan`` is read-only.
Devices are matched by line and short address; the gateway id is looked up.
Zones and schedules are matched by name.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable
from typing import Any

from .automation import sequence_canonical, trigger_canonical
from .client import Client
from .intent import Targets
from .schedule import canonical as schedule_canonical
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

    # automations: by name. Zone targets may be zones this plan creates, so they
    # are resolved again at apply time.
    zone_ids = {name: gz["id"] for name, gz in gw_by_name.items()}
    refs_by_id = {i: key for key, i in ids.items()}

    def fresh_zone_ids() -> dict[str, int]:
        return {str(z.get("name")): z["id"] for z in client.zones()}

    def unresolved(t: Targets) -> list[str]:
        return [str(r) for r in t.devices if parse_ref(r) not in ids]

    def pending_zones(t: Targets) -> list[str]:
        return [n for n in t.zones if n not in zone_ids]

    # schedules
    changes += _sync(
        "schedule",
        site.schedules,
        client.automations("schedule"),
        client,
        unresolved=unresolved,
        pending=pending_zones,
        body=lambda sc, z: sc.body(sc.resolve(ids, z)),
        same=lambda sc, rec: (
            schedule_canonical(rec) == schedule_canonical(sc.body(sc.resolve(ids, zone_ids)))
        ),
        summary=lambda sc: f"{sc.at} -> {sc.action_features()} on {sc.describe()}",
        fresh_zone_ids=fresh_zone_ids,
        prune=prune,
    )
    # triggers
    changes += _sync(
        "trigger",
        site.triggers,
        client.automations("trigger"),
        client,
        unresolved=lambda tr: (
            unresolved(tr.targets) + [str(r) for r in tr.sources.devices if parse_ref(r) not in ids]
        ),
        pending=lambda tr: pending_zones(tr.targets),
        body=lambda tr, z: tr.body(tr.targets.resolve(ids, z)),
        same=lambda tr, rec: (
            trigger_canonical(rec, refs_by_id)
            == trigger_canonical(tr.body(tr.targets.resolve(ids, zone_ids)), refs_by_id)
        ),
        summary=lambda tr: tr.summary(),
        fresh_zone_ids=fresh_zone_ids,
        prune=prune,
    )
    # sequences
    changes += _sync(
        "sequence",
        site.sequences,
        client.automations("sequence"),
        client,
        unresolved=lambda sq: unresolved(sq.all_targets()),
        pending=lambda sq: pending_zones(sq.all_targets()),
        body=lambda sq, z: sq.body([st.resolve(ids, z) for st in sq.steps]),
        same=lambda sq, rec: (
            sequence_canonical(rec)
            == sequence_canonical(sq.body([st.resolve(ids, zone_ids) for st in sq.steps]))
        ),
        summary=lambda sq: sq.summary(),
        fresh_zone_ids=fresh_zone_ids,
        prune=prune,
    )
    return changes


def _refs(refs) -> str:
    return ", ".join(f"A{r}" if isinstance(r, int) else str(r) for r in refs)


def _sync(
    kind: str,
    items: list,
    gw_items: list[dict],
    client: Client,
    *,
    unresolved: Callable[[Any], list[str]],
    pending: Callable[[Any], list[str]],
    body: Callable[[Any, dict[str, int]], dict],
    same: Callable[[Any, dict], bool],
    summary: Callable[[Any], str],
    fresh_zone_ids: Callable[[], dict[str, int]],
    prune: bool,
) -> list[Change]:
    """Create, update, note or delete one kind of named automation."""
    changes: list[Change] = []
    gw_by_name: dict[str, dict] = {}
    for r in gw_items:
        gw_by_name.setdefault(str(r.get("name")), r)
    site_names = {it.name for it in items}
    for it in items:
        name = it.name
        missing = unresolved(it)
        if missing:
            changes.append(
                Change("error", f"{kind} {name}", f"skipped: device(s) {', '.join(missing)} unresolved")
            )
            continue
        rec = gw_by_name.get(name)
        if rec is None:
            changes.append(
                Change(
                    "create",
                    f"{kind} {name}",
                    summary(it),
                    lambda i=it: client.create_automation(kind, body(i, fresh_zone_ids())),
                )
            )
        elif pending(it) or not same(it, rec):
            changes.append(
                Change(
                    "update",
                    f"{kind} {name}",
                    summary(it),
                    lambda i=it, rid=rec["id"]: client.update_automation(
                        kind, rid, body(i, fresh_zone_ids())
                    ),
                )
            )
    for name, rec in gw_by_name.items():
        if name not in site_names:
            if prune:
                changes.append(
                    Change(
                        "delete",
                        f"{kind} {name}",
                        f"id {rec['id']}",
                        lambda rid=rec["id"]: client.delete_automation(kind, rid),
                    )
                )
            else:
                changes.append(
                    Change(
                        "note", f"{kind} {name}", f"id {rec['id']} is not in the site file (--prune deletes)"
                    )
                )
    return changes
