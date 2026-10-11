"""``site check``: does the site file still describe what is on the gateway?

Compares the device inventory only (which addresses exist and what they are),
not names, zones or schedules; those are ``plan``'s job. Finds devices the
file has that the gateway no longer has (lost), records the gateway has that
the file does not (new), and pairs them up as moves when type and groups
match, since both live in the device itself and survive a readdress.
"""

from __future__ import annotations

import dataclasses

from .site import DeviceSpec, Site, format_ref, type_name


@dataclasses.dataclass
class Finding:
    kind: str  # lost | new | moved | type
    detail: str
    suggest: str

    def __str__(self) -> str:
        return f"{self.kind:<6} {self.detail}\n       {self.suggest}"


def _fingerprint(dtype: str, groups: list[int] | None) -> tuple[str, tuple[int, ...] | None]:
    return dtype, tuple(sorted(groups)) if groups is not None else None


def compare(site: Site, gw_devices: list[dict], scan: dict | None = None) -> list[Finding]:
    """``scan`` is a finished ``GET /dali/scan`` result; with it, stale records can be counted."""
    by_addr = {(int(d.get("line", 0)), int(d["address"])): d for d in gw_devices if "address" in d}
    lost: list[tuple[int, DeviceSpec]] = []
    findings: list[Finding] = []
    claimed: set[tuple[int, int]] = set()
    for line, spec in site.devices():
        key = (line, spec.address)
        d = by_addr.get(key)
        if d is None:
            lost.append((line, spec))
            continue
        claimed.add(key)
        gw_type = type_name(d.get("daliTypes") or [])
        if spec.type is not None and spec.type != gw_type:
            findings.append(
                Finding(
                    "type",
                    f"{spec.name!r} at line {line} A{spec.address}: file says {spec.type}, gateway has a {gw_type}",
                    "a different device answers at this address; fix the address or the type in the file",
                )
            )
    new = [d for k, d in sorted(by_addr.items()) if k not in claimed]
    # file devices with the same fingerprint as a new record: candidates for "it was readdressed"
    twins: dict[tuple[str, tuple[int, ...] | None], list[str]] = {}
    for line, spec in site.devices():
        if (line, spec.address) in claimed and spec.type is not None and spec.groups is not None:
            twins.setdefault(_fingerprint(spec.type, spec.groups), []).append(f"A{spec.address}")

    # pair lost with new by (type, groups); unmatched ones stay lost / new
    for line, spec in lost:
        fp = _fingerprint(spec.type or "", spec.groups)
        match = None
        for d in new:
            gfp = _fingerprint(type_name(d.get("daliTypes") or []), sorted(d.get("groups") or []))
            if spec.type is not None and spec.groups is not None and gfp == fp:
                match = d
                break
        where = f"line {line} A{spec.address}"
        if match is not None:
            new.remove(match)
            ref_old, ref_new = (
                format_ref(line, spec.address),
                format_ref(int(match.get("line", 0)), match["address"]),
            )
            findings.append(
                Finding(
                    "moved",
                    f"{spec.name!r} {where} -> A{match['address']} (same type {spec.type}, groups {list(fp[1] or [])})",
                    f"change address: {spec.address} to {match['address']} and any devices: [{ref_old}] to "
                    f"[{ref_new}] in the file, then: dali-iot apply --prune",
                )
            )
        else:
            findings.append(
                Finding(
                    "lost",
                    f"{spec.name!r} {where}: nothing at this address on the gateway",
                    "if it was readdressed, fix the address in the file; if it is gone, remove it "
                    "(apply --prune then deletes the gateway record)",
                )
            )
    for d in new:
        gw_type = type_name(d.get("daliTypes") or [])
        groups = sorted(d.get("groups") or [])
        same = twins.get(_fingerprint(gw_type, groups), [])
        detail = f"{d.get('name')!r} line {d.get('line', 0)} A{d['address']}: {gw_type}, groups {groups}, not in the file"
        if same:
            detail += f"; same type and groups as {', '.join(same)}"
        findings.append(
            Finding(
                "new",
                detail,
                "if it is one of those readdressed, change that entry's address in the file and run "
                "apply --prune to drop the stale record; if it is really new, add it under lines "
                "(dali-iot site init --path OTHER writes a full file to copy from)"
                if same
                else "add it under lines (dali-iot site init --path OTHER writes a full file to copy from), "
                "or apply --prune to delete the gateway record",
            )
        )
    if scan:
        findings += _stale(site, gw_devices, scan)
    return findings


def _stale(site: Site, gw_devices: list[dict], scan: dict) -> list[Finding]:
    """More records on a line than devices the bus answered for: some records are stale.

    The gateway never drops a record, and a stale one looks exactly like a live
    one that is switched off, so only the count gives it away. Records sharing
    a type and groups with another are the likely pairs.
    """
    out: list[Finding] = []
    for ln in scan.get("lines") or []:
        line = int(ln.get("line", 0))
        recs = [d for d in gw_devices if int(d.get("line", 0)) == line and "address" in d]
        found = ln.get("found")
        if found is None or len(recs) <= found:
            continue
        fps: dict[tuple, list[int]] = {}
        for d in recs:
            fps.setdefault(
                _fingerprint(type_name(d.get("daliTypes") or []), sorted(d.get("groups") or [])), []
            ).append(int(d["address"]))
        pairs = [sorted(a) for a in fps.values() if len(a) > 1]
        detail = f"line {line}: gateway holds {len(recs)} records but the bus answered for {found}"
        if pairs:
            detail += "; same type and groups: " + "; ".join("A" + ", A".join(map(str, p)) for p in pairs)
        out.append(
            Finding(
                "stale",
                detail,
                f"{len(recs) - found} record(s) belong to no device. If you readdressed one, drop its old "
                "address from the file and run apply --prune. To tell a pair apart, switch one on "
                "(dali-iot on --device ID) and see which record reports lampOn.",
            )
        )
    return out
