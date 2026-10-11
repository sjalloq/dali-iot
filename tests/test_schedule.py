import pytest
import yaml

from dali_iot import schedule
from dali_iot.schedule import ScheduleSpec, canonical, format_at, from_gateway, parse_at
from dali_iot.site import Site
from dali_iot.site import from_gateway as site_from_gateway
from tests.test_plan import GW_SCHEDULES
from tests.test_site import GW_DEVICES, GW_ZONES


@pytest.mark.parametrize(
    ("at", "parsed"),
    [
        ("22:00", ("timeOfDay", 22, 0, 0)),
        ("7:05:30", ("timeOfDay", 7, 5, 30)),
        ("sunset", ("afterSunset", 0, 0, 0)),
        ("sunrise", ("afterSunrise", 0, 0, 0)),
        ("sunset-0:30", ("beforeSunset", 0, 30, 0)),
        ("sunrise + 1:00", ("afterSunrise", 1, 0, 0)),
    ],
)
def test_parse_at(at, parsed):
    assert parse_at(at) == parsed
    assert parse_at(format_at(*parsed)) == parsed


@pytest.mark.parametrize("bad", ["24:00", "10:60", "noon", "sunset-0:75", "sunset+1", 1320])
def test_parse_at_rejects(bad):
    with pytest.raises(ValueError):
        parse_at(bad)


def test_unquoted_time_gets_a_quoting_hint():
    with pytest.raises(ValueError, match="quote the time"):
        ScheduleSpec.model_validate({"name": "x", "at": 1320, "devices": [0], "switch": True})


def _spec(**kw):
    return ScheduleSpec.model_validate({"name": "x", "at": "sunset", "devices": [0], **kw})


@pytest.mark.parametrize(
    ("extra", "msg"),
    [
        ({}, "exactly one of"),
        ({"switch": True, "level": 50}, "exactly one of"),
        ({"switch": True, "fade": 2}, "fade needs level"),
        ({"level": 101}, "less than or equal to 100"),
        ({"scene": 16}, "less than or equal to 15"),
        ({"switch": True, "days": ["monday"]}, "unknown day"),
        ({"switch": True, "months": ["sept"]}, "unknown month"),
        ({"switch": True, "at": "later"}, "use 'HH:MM'"),
    ],
)
def test_spec_validation(extra, msg):
    with pytest.raises(ValueError, match=msg):
        _spec(**extra)


def test_spec_without_targets_is_rejected():
    with pytest.raises(ValueError, match="no targets"):
        ScheduleSpec.model_validate({"name": "x", "at": "sunset", "switch": True})


@pytest.mark.parametrize(
    ("extra", "features"),
    [
        ({"switch": True}, {"switchable": True}),
        ({"switch": False}, {"switchable": False}),
        ({"level": 40}, {"dimmable": 40}),
        ({"level": 40, "fade": 2.5}, {"dimmableWithFade": {"dimValue": 40, "fadeTime": 2.5}}),
        ({"level": 40, "fade": 0}, {"dimmable": 40}),
        ({"scene": 3}, {"scene": 3}),
        ({"features": {"colourTemperature": 2700}}, {"colourTemperature": 2700}),
    ],
)
def test_action_features(extra, features):
    assert _spec(**extra).action_features() == features


def test_body_defaults_to_every_day_and_month():
    body = _spec(switch=True).body([{"type": "device", "id": 1}])
    assert body["recallMode"] == "afterSunset"
    assert body["recallTime"] == {"hour": 0, "minute": 0, "second": 0}
    assert all(body["activeWeekdays"].values()) and len(body["activeWeekdays"]) == 7
    assert all(body["activeMonths"].values()) and len(body["activeMonths"]) == 12
    assert body["enabled"] is True
    assert body["action"] == {"type": "features", "data": {"features": {"switchable": True}}}


def test_canonical_treats_missing_as_default():
    sparse = {
        "name": "n",
        "targets": [],
        "recallMode": "timeOfDay",
        "recallTime": {"hour": 22},
        "activeMonths": {},
        "activeWeekdays": {},
        "action": {"type": "features", "data": {"features": {}}},
    }
    full = _spec(at="22:00", switch=True).body([])
    full["name"] = "n"
    full["action"] = {"type": "features", "data": {"features": {}}}
    assert canonical(sparse) == canonical(full)
    assert canonical(GW_SCHEDULES[0])["days"] == (True, False, False, False, False, False, True)


def test_from_gateway_record():
    rec = from_gateway(GW_SCHEDULES[0], {8: 7}, {})
    assert rec == {
        "name": "Outside Sunset On",
        "at": "sunset",
        "devices": [7],
        "switch": True,
        "days": ["mon", "sun"],
        "months": ["jan", "feb", "mar", "dec"],
    }
    odd = dict(
        GW_SCHEDULES[1], enabled=False, targets=[{"type": "zone", "id": 3}, {"type": "group", "id": 2}]
    )
    odd["action"] = {"type": "features", "data": {"features": {"switchable": True, "dimmable": 50}}}
    rec = from_gateway(odd, {}, {3: "lounge"})
    assert rec["zones"] == ["lounge"] and rec["groups"] == [2]
    assert rec["features"] == {"switchable": True, "dimmable": 50}
    assert rec["enabled"] is False and "days" not in rec and "months" not in rec


def test_site_round_trips_schedules():
    text = site_from_gateway(GW_DEVICES, GW_ZONES, GW_SCHEDULES)
    data = yaml.safe_load(text)
    assert data["schedules"][1] == {
        "name": "Outside 10pm Off",
        "at": "22:00",
        "devices": [7],
        "switch": False,
    }
    site = Site.model_validate(data)
    body = site.schedules[1].body([{"type": "device", "id": 8}])
    assert canonical(body) == canonical(GW_SCHEDULES[1])


def test_site_rejects_unknown_refs_and_duplicates():
    base = {
        "lines": {0: {"devices": [{"name": "a", "address": 0}]}},
        "zones": [{"name": "z", "devices": [0]}],
    }
    s = {"name": "s", "at": "sunset", "switch": True}
    with pytest.raises(ValueError, match="not under lines"):
        Site.model_validate({**base, "schedules": [{**s, "devices": [5]}]})
    with pytest.raises(ValueError, match="unknown zone"):
        Site.model_validate({**base, "schedules": [{**s, "zones": ["nope"]}]})
    with pytest.raises(ValueError, match="used twice"):
        Site.model_validate({**base, "schedules": [{**s, "zones": ["z"]}, {**s, "devices": [0]}]})
    assert schedule.DAYS[0] == "mon"
