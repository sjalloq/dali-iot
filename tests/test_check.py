from dali_iot.check import compare
from dali_iot.site import Site

GW = [
    {"id": 1, "name": "a", "line": 0, "address": 0, "daliTypes": [4], "groups": [0, 1]},
    {"id": 6, "name": "e", "line": 0, "address": 5, "daliTypes": [4], "groups": [0, 2, 3]},
    {"id": 8, "name": "out", "line": 0, "address": 7, "daliTypes": [7], "groups": [0]},
    {"id": 13, "name": "new", "line": 0, "address": 31, "daliTypes": [4], "groups": [0, 2, 3]},
]


def _site(*devs):
    return Site.model_validate({"lines": {0: {"devices": list(devs)}}})


A0 = {"name": "a", "address": 0, "type": "dimmer", "groups": [0, 1]}
A5 = {"name": "e", "address": 5, "type": "dimmer", "groups": [0, 2, 3]}
A7 = {"name": "out", "address": 7, "type": "relay", "groups": [0]}
A31 = {"name": "new", "address": 31, "type": "dimmer", "groups": [0, 2, 3]}


def test_matching_file_has_no_findings():
    assert compare(_site(A0, A5, A7, A31), GW) == []


def test_move_is_paired_when_old_record_is_gone():
    gw = [d for d in GW if d["address"] != 5]
    (f,) = compare(_site(A0, A5, A7), gw)
    assert f.kind == "moved"
    assert "A5 -> A31" in f.detail
    assert "address: 5 to 31" in f.suggest and "[5] to [31]" in f.suggest


def test_ghost_record_makes_new_with_candidates():
    (f,) = compare(_site(A0, A5, A7), GW)
    assert f.kind == "new"
    assert "A31" in f.detail and "same type and groups as A5" in f.detail
    assert "readdressed" in f.suggest


def test_lost_without_a_twin_and_type_change():
    gw = [d for d in GW if d["address"] not in (7, 31)]
    gw.append({"id": 9, "name": "x", "line": 0, "address": 7, "daliTypes": [4], "groups": []})
    findings = compare(_site(A0, A5, A7, {"name": "gone", "address": 20, "type": "led", "groups": [9]}), gw)
    assert [f.kind for f in findings] == ["type", "lost"]
    assert "file says relay, gateway has a dimmer" in findings[0].detail
    assert "A20" in findings[1].detail


def test_untyped_entries_never_pair_as_moves():
    gw = [d for d in GW if d["address"] != 5]
    kinds = sorted(f.kind for f in compare(_site(A0, {"name": "e", "address": 5}, A7), gw))
    assert kinds == ["lost", "new"]


SCAN = {"status": "done", "found": 3, "lines": [{"line": 0, "found": 3}]}


def test_more_records_than_found_is_stale_with_pairs():
    (f,) = compare(_site(A0, A5, A7, A31), GW, SCAN)
    assert f.kind == "stale"
    assert "holds 4 records but the bus answered for 3" in f.detail
    assert "A5, A31" in f.detail
    assert "1 record(s)" in f.suggest


def test_counts_that_agree_are_quiet():
    assert compare(_site(A0, A5, A7, A31), GW, {"lines": [{"line": 0, "found": 4}]}) == []
    assert compare(_site(A0, A5, A7, A31), GW, {"lines": []}) == []
