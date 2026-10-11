from dali_iot import plan
from dali_iot.site import Site
from tests.test_site import GW_DEVICES, GW_ZONES


def _gw(fake):
    fake.answers[("GET", "/devices")] = {"devices": GW_DEVICES}
    fake.answers[("GET", "/zones")] = {"zones": GW_ZONES}


def _site(devices, zones):
    return Site.model_validate({"lines": {0: {"devices": devices}}, "zones": zones})


def test_plan_is_read_only_and_lists_changes(client, fake):
    _gw(fake)
    site = _site(
        [
            {"name": "outside", "address": 7, "type": "relay", "groups": [0, 1]},
            {"name": "Bathroom", "address": 8},
        ],
        [
            {"name": "wet", "devices": ["outside"]},
            {"name": "all", "broadcast": [0]},
            {"name": "broadcast", "broadcast": [0]},
        ],
    )
    changes = plan.build(site, client)
    assert [m for m, *_ in fake.calls] == ["GET", "GET"]
    assert [(c.op, c.what) for c in changes] == [
        ("rename", "device outside"),
        ("groups", "device outside"),
        ("update", "zone wet"),
        ("create", "zone all"),
        ("note", "zone group 0"),
    ]


def test_type_mismatch_and_missing_address_are_errors_and_block(client, fake):
    _gw(fake)
    site = _site(
        [{"name": "outside", "address": 7, "type": "dimmer"}, {"name": "ghost", "address": 20}],
        [{"name": "z", "devices": ["outside"]}],
    )
    changes = plan.build(site, client)
    errors = [c for c in changes if c.op == "error"]
    assert [c.what for c in errors] == ["device outside", "device ghost", "zone z"]
    assert "is a relay, site says dimmer" in errors[0].detail
    assert all(c.apply is None for c in errors)
    assert not [c for c in changes if c.op in ("rename", "create", "update")]


def test_apply_sends_the_right_requests(client, fake):
    _gw(fake)
    site = _site(
        [{"name": "outside", "address": 7}],
        [{"name": "wet", "devices": ["outside"]}, {"name": "all", "groups": [0]}],
    )
    for c in plan.build(site, client, prune=True):
        if c.apply:
            c.apply()
    writes = [(m, p, j) for m, p, j, _ in fake.calls if m != "GET"]
    assert writes == [
        ("PUT", "/device/8", {"name": "outside"}),
        ("PUT", "/zone/3", {"name": "wet", "targets": [{"type": "device", "id": 8}]}),
        ("POST", "/zone", {"name": "all", "targets": [{"type": "group", "id": 0}]}),
        ("DELETE", "/zone/1", None),
        ("DELETE", "/zone/2", None),
    ]


def test_unmanaged_are_notes_without_prune(client, fake):
    _gw(fake)
    changes = plan.build(Site(), client)
    assert all(c.op == "note" and c.apply is None for c in changes)
    assert len(changes) == 5  # two devices, three zones
