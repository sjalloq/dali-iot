from dali_iot.bus import Identity
from dali_iot.check import compare
from dali_iot.site import Site
from tests.test_bus import NEW_BANK0, OLD_BANK0


def _ident(address, serial, unit=None, line=0):
    """An Identity with the given serial (ed. 1 layout) or unit (ed. 2 layout)."""
    if unit is None:
        b = bytearray(OLD_BANK0)
        b[0x0B:0x0F] = serial.to_bytes(4, "big")
    else:
        b = bytearray(NEW_BANK0)
        b[0x0B:0x13] = serial.to_bytes(8, "big")
        b[0x1A] = unit
    return Identity(line, address, bytes(b))


def _site(*devs, zones=()):
    return Site.model_validate({"lines": {0: {"devices": list(devs)}}, "zones": list(zones)})


D0 = {"name": "lounge", "address": 0, "type": "dimmer", "serial": 1000}
D5 = {"name": "bed", "address": 5, "type": "dimmer", "serial": 1005}
R7 = {"name": "out", "address": 7, "type": "relay", "serial": 77, "unit": 0}
R8 = {"name": "bath", "address": 8, "type": "relay", "serial": 77, "unit": 1}
BUS = [_ident(0, 1000), _ident(5, 1005), _ident(7, 77, 0), _ident(8, 77, 1)]
GW = [{"id": a + 1, "name": f"d{a}", "line": 0, "address": a} for a in (0, 5, 7, 8)]


def test_matching_bus_and_gateway_are_quiet():
    assert compare(_site(D0, D5, R7, R8), BUS, GW) == []


def test_move_is_exact_by_serial():
    bus = [_ident(0, 1000), _ident(31, 1005), _ident(7, 77, 0), _ident(8, 77, 1)]
    findings = compare(_site(D0, D5, R7, R8), bus)
    assert [f.kind for f in findings] == ["moved"]
    assert "A5 -> A31" in findings[0].detail
    assert "address: 5 to 31" in findings[0].suggest and "[5] to [31]" in findings[0].suggest


def test_units_sharing_a_serial_are_told_apart():
    swapped = [_ident(0, 1000), _ident(5, 1005), _ident(7, 77, 1), _ident(8, 77, 0)]
    kinds = sorted(f.kind for f in compare(_site(D0, D5, R7, R8), swapped))
    assert kinds == ["moved", "moved"]


def test_lost_replaced_and_new():
    bus = [_ident(0, 2000), _ident(7, 77, 0), _ident(8, 77, 1), _ident(9, 3000)]
    findings = {f.kind: f for f in compare(_site(D0, D5, R7, R8), bus)}
    assert set(findings) == {"replaced", "lost", "new"}
    assert (
        "file says serial 1000" in findings["replaced"].detail
        and "serial 2000" in findings["replaced"].detail
    )
    assert "'bed'" in findings["lost"].detail
    assert "A9: serial 3000" in findings["new"].detail


def test_entries_without_serial_fall_back_to_presence():
    findings = compare(_site({"name": "x", "address": 0}, {"name": "y", "address": 1}), [_ident(0, 1)])
    assert [(f.kind, f.detail.split(":")[0]) for f in findings] == [("unknown", "'x' A0"), ("lost", "'y' A1")]
    assert "site init" in findings[0].suggest


def test_gateway_records_against_the_bus():
    gw = [*GW, {"id": 13, "name": "ghost", "line": 0, "address": 31}]
    bus = [*BUS, _ident(40, 4040)]
    findings = compare(_site(D0, D5, R7, R8), bus, gw)
    by_kind = {f.kind: f for f in findings}
    assert set(by_kind) == {"new", "stale", "unscanned"}
    assert "'ghost' at A31" in by_kind["stale"].detail and "apply --prune" in by_kind["stale"].suggest
    assert "A40" in by_kind["unscanned"].detail and by_kind["unscanned"].suggest == "dali-iot gateway rescan"
