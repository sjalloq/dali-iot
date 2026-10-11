from dali_iot import plan
from dali_iot.site import Site
from tests.test_site import GW_DEVICES, GW_ZONES

GW_SCHEDULES = [
    {
        "id": 1,
        "name": "Outside Sunset On",
        "targets": [{"type": "device", "id": 8}],
        "enabled": True,
        "activePeriod": {"startMonth": None, "endMonth": None, "startDay": None, "endDay": None},
        "activeMonths": {
            m: m in ("january", "february", "march", "december")
            for m in (
                "january",
                "february",
                "march",
                "april",
                "may",
                "june",
                "july",
                "august",
                "september",
                "october",
                "november",
                "december",
            )
        },
        "activeWeekdays": {
            d: d in ("monday", "sunday")
            for d in ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
        },
        "activeDays": {},
        "recallMode": "afterSunset",
        "recallTime": {"hour": 0, "minute": 0, "second": 0},
        "action": {"type": "features", "data": {"features": {"switchable": True}}},
    },
    {
        "id": 2,
        "name": "Outside 10pm Off",
        "targets": [{"type": "device", "id": 8}],
        "enabled": True,
        "activeMonths": {},
        "activeWeekdays": {},
        "recallMode": "timeOfDay",
        "recallTime": {"hour": 22, "minute": 0},
        "action": {"type": "features", "data": {"features": {"switchable": False}}},
    },
]


def _gw(fake, schedules=GW_SCHEDULES):
    fake.answers[("GET", "/devices")] = {"devices": GW_DEVICES}
    fake.answers[("GET", "/zones")] = {"zones": GW_ZONES}
    fake.answers[("GET", "/automations/schedules")] = {"schedulers": schedules}


def _site(devices, zones, schedules=()):
    return Site.model_validate(
        {"lines": {0: {"devices": devices}}, "zones": zones, "schedules": list(schedules)}
    )


def test_plan_is_read_only_and_lists_changes(client, fake):
    _gw(fake)
    site = _site(
        [
            {"name": "outside", "address": 7, "type": "relay", "groups": [0, 1]},
            {"name": "Bathroom", "address": 8},
        ],
        [
            {"name": "wet", "devices": [7]},
            {"name": "all", "broadcast": [0]},
            {"name": "broadcast", "broadcast": [0]},
        ],
    )
    changes = plan.build(site, client)
    assert [m for m, *_ in fake.calls] == ["GET", "GET", "GET"]  # devices, zones, schedules
    assert [(c.op, c.what) for c in changes] == [
        ("rename", "device outside"),
        ("groups", "device outside"),
        ("update", "zone wet"),
        ("create", "zone all"),
        ("note", "zone group 0"),
        ("note", "schedule Outside Sunset On"),
        ("note", "schedule Outside 10pm Off"),
    ]


def test_type_mismatch_and_missing_address_are_errors_and_block(client, fake):
    _gw(fake)
    site = _site(
        [{"name": "outside", "address": 7, "type": "dimmer"}, {"name": "ghost", "address": 20}],
        [{"name": "z", "devices": [7]}],
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
        [{"name": "wet", "devices": [7]}, {"name": "all", "groups": [0]}],
    )
    for c in plan.build(site, client, prune=True):
        if c.apply:
            c.apply()
    writes = [(m, p, j) for m, p, j, _ in fake.calls if m != "GET"]
    assert writes == [
        ("PUT", "/device/8", {"name": "outside"}),
        ("DELETE", "/device/9", None),
        ("PUT", "/zone/3", {"name": "wet", "targets": [{"type": "device", "id": 8}]}),
        ("POST", "/zone", {"name": "all", "targets": [{"type": "group", "id": 0}]}),
        ("DELETE", "/zone/1", None),
        ("DELETE", "/zone/2", None),
        ("DELETE", "/automations/scheduler/1", None),
        ("DELETE", "/automations/scheduler/2", None),
    ]


def test_unmanaged_are_notes_without_prune(client, fake):
    _gw(fake)
    changes = plan.build(Site(), client)
    assert all(c.op == "note" and c.apply is None for c in changes)
    assert len(changes) == 7  # two devices, three zones, two schedules


def _sched(**kw):
    return {"name": "Outside 10pm Off", "at": "22:00", "devices": [7], "switch": False, **kw}


def test_schedules_matching_the_gateway_plan_nothing(client, fake):
    _gw(fake)
    site = _site(
        [{"name": "outside", "address": 7}],
        [],
        [
            _sched(),
            _sched(
                name="Outside Sunset On",
                at="sunset",
                switch=True,
                days=["mon", "sun"],
                months=["jan", "feb", "mar", "dec"],
            ),
        ],
    )
    kinds = [c.op for c in plan.build(site, client) if c.what.startswith("schedule")]
    assert kinds == []


def test_schedule_update_sends_full_body(client, fake):
    _gw(fake)
    site = _site(
        [{"name": "outside", "address": 7}],
        [],
        [_sched(at="22:30", days=["mon", "fri"], enabled=False)],
    )
    changes = [c for c in plan.build(site, client) if c.what.startswith("schedule")]
    assert [(c.op, c.what) for c in changes] == [
        ("update", "schedule Outside 10pm Off"),
        ("note", "schedule Outside Sunset On"),
    ]
    changes[0].apply()
    m, path, body, _ = fake.calls[-1]
    assert (m, path) == ("PUT", "/automations/scheduler/2")
    assert body["recallMode"] == "timeOfDay"
    assert body["recallTime"] == {"hour": 22, "minute": 30, "second": 0}
    assert body["enabled"] is False
    assert body["targets"] == [{"type": "device", "id": 8}]
    assert body["activeWeekdays"] == {
        "monday": True,
        "tuesday": False,
        "wednesday": False,
        "thursday": False,
        "friday": True,
        "saturday": False,
        "sunday": False,
    }
    assert all(body["activeMonths"].values()) and len(body["activeMonths"]) == 12
    assert body["action"] == {"type": "features", "data": {"features": {"switchable": False}}}


def test_schedule_create_resolves_new_zone_at_apply_time(client, fake):
    _gw(fake, schedules=[])
    site = _site(
        [{"name": "outside", "address": 7}],
        [{"name": "wet", "devices": [7]}, {"name": "new", "groups": [3]}],
        [{"name": "dusk", "at": "sunset-0:30", "zones": ["new", "wet"], "level": 40, "fade": 2.5}],
    )
    changes = plan.build(site, client)
    create = next(c for c in changes if c.op == "create" and c.what == "schedule dusk")
    assert "sunset-0:30" in create.detail and "zone new" in create.detail
    # pretend the zone create has happened and the gateway now lists it
    fake.answers[("GET", "/zones")] = {"zones": [*GW_ZONES, {"id": 9, "name": "new", "targets": []}]}
    create.apply()
    m, path, body, _ = fake.calls[-1]
    assert (m, path) == ("POST", "/automations/scheduler")
    assert body["targets"] == [{"type": "zone", "id": 9}, {"type": "zone", "id": 3}]
    assert body["recallMode"] == "beforeSunset"
    assert body["recallTime"] == {"hour": 0, "minute": 30, "second": 0}
    assert body["action"]["data"]["features"] == {"dimmableWithFade": {"dimValue": 40, "fadeTime": 2.5}}
