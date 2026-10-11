import pytest
import yaml

from dali_iot.site import Site, from_gateway, type_name

SITE = {
    "lines": {
        0: {
            "devices": [
                {"name": "a", "address": 0},
                {"name": "b", "address": 1, "type": "relay", "groups": [3]},
            ]
        }
    },
    "zones": [
        {"name": "z", "devices": [0, "0/1"]},
        {"name": "g", "groups": [0]},
        {"name": "all", "broadcast": [0]},
    ],
}


def test_layout():
    s = Site.model_validate(SITE)
    assert [(line, d.name) for line, d in s.devices()] == [(0, "a"), (0, "b")]
    a = s.lines[0].devices[0]
    assert a.groups is None and a.type is None
    assert s.zones[0].devices == [0, "0/1"]
    assert s.zones[2].broadcast == [0]


def test_type_names():
    assert type_name([7]) == "relay"
    assert type_name([4]) == "dimmer"
    assert type_name([6, 8]) == "colour"
    assert type_name([5]) == "5"
    assert type_name([]) == "unknown"


def _line(*devs):
    return {"lines": {0: {"devices": list(devs)}}}


@pytest.mark.parametrize(
    "data, msg",
    [
        (_line({"name": "a", "address": 1}, {"name": "b", "address": 1}), "both have address 1"),
        (_line({"name": "a", "address": 1}, {"name": "a", "address": 2}), "used twice"),
        (_line({"name": "a", "address": 1, "type": "lamp"}), "unknown type"),
        (_line({"name": "a", "address": 64}), "less than or equal to 63"),
        (_line({"name": "", "address": 1}), "at least 1 character"),
        (_line({"address": 1}), "name"),
        (_line({"name": "a", "address": 1, "typo": 2}), "extra"),
        ({"zones": [{"name": "z", "devices": [9]}]}, "not under lines"),
        ({"zones": [{"name": "z", "devices": ["x"]}]}, "use an address"),
        ({"zones": [{"name": "z", "devices": [64]}]}, "0..63"),
        ({"zones": [{"name": "z"}]}, "no targets"),
        ({"zones": [{"name": "z", "groups": [0]}, {"name": "z", "groups": [1]}]}, "used twice"),
    ],
)
def test_validation(data, msg):
    with pytest.raises(ValueError, match=msg):
        Site.model_validate(data)


GW_DEVICES = [
    {"id": 8, "name": "Line 0 - DALI#07", "groups": [0], "line": 0, "address": 7, "daliTypes": [7]},
    {"id": 9, "name": "Bathroom", "groups": [], "line": 0, "address": 8, "daliTypes": [4]},
]
GW_ZONES = [
    {"id": 1, "name": "broadcast", "targets": [{"id": None, "type": "broadcast"}]},
    {"id": 2, "name": "group 0", "targets": [{"id": 0, "type": "group"}]},
    {"id": 3, "name": "wet", "targets": [{"id": 9, "type": "device"}]},
]


def test_from_gateway_round_trips():
    text = from_gateway(GW_DEVICES, GW_ZONES)
    data = yaml.safe_load(text)
    assert data["lines"][0]["devices"][0] == {
        "name": "Line 0 - DALI#07",
        "address": 7,
        "type": "relay",
        "groups": [0],
    }
    s = Site.model_validate(data)
    assert s.zones[0].name == "broadcast" and s.zones[0].broadcast == [0]
    assert s.zones[2].devices == [8]
    assert not any(" # " in line for line in text.splitlines()[1:])  # no comments: types are keys
