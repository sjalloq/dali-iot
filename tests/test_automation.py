import pytest
import yaml

from dali_iot import plan
from dali_iot.automation import (
    SequenceSpec,
    TriggerSpec,
    sequence_canonical,
    sequence_from_gateway,
    trigger_canonical,
    trigger_from_gateway,
)
from dali_iot.site import Site, from_gateway
from tests.test_plan import _gw
from tests.test_site import GW_DEVICES, GW_ZONES

GW_TRIGGER = {
    "id": 1,
    "enabled": True,
    "name": "hall",
    "sources": [
        {"type": "d16group", "id": None, "address": 3, "line": 0},
        {"type": "device", "id": 8, "address": None, "line": None},
    ],
    "targets": [{"type": "zone", "id": 2}, {"type": "group", "id": 1}],
}
GW_SEQUENCE = {
    "id": 1,
    "active": False,
    "name": "evening",
    "enabled": False,
    "loop": False,
    "repeat": 3,
    "isMacro": False,
    "steps": [
        {
            "enabled": True,
            "type": "features",
            "delay": 0.0,
            "data": {"targets": [{"type": "device", "id": 8}], "features": {"switchable": True}},
        },
        {
            "enabled": True,
            "type": "features",
            "delay": 1.5,
            "data": {
                "targets": [{"type": "group", "id": 1}],
                "features": {"dimmableWithFade": {"dimValue": 30, "fadeTime": 2}},
            },
        },
        {
            "enabled": False,
            "type": "features",
            "delay": 0.5,
            "data": {"targets": [{"type": "zone", "id": 2}], "features": {"scene": 2}},
        },
    ],
}
REFS = {8: 7, 9: 8}  # gateway id -> address reference
ZONES = {1: "broadcast", 2: "group 0", 3: "wet"}


def test_trigger_round_trip():
    entry = trigger_from_gateway(GW_TRIGGER, REFS, ZONES)
    assert entry == {
        "name": "hall",
        "sources": {"groups": [3], "devices": [7]},
        "targets": {"zones": ["group 0"], "groups": [1]},
    }
    spec = TriggerSpec.model_validate(entry)
    body = spec.body([{"type": "zone", "id": 2}, {"type": "group", "id": 1}])
    assert body["sources"] == [
        {"type": "d16gear", "line": 0, "address": 7},
        {"type": "d16group", "line": 0, "address": 3},
    ]
    refs_by_id = {8: (0, 7)}
    assert trigger_canonical(body, refs_by_id) == trigger_canonical(GW_TRIGGER, refs_by_id)


def test_trigger_validation():
    with pytest.raises(ValueError, match="no sources"):
        TriggerSpec.model_validate({"name": "t", "sources": {}, "targets": {"groups": [1]}})
    with pytest.raises(ValueError, match="no targets"):
        TriggerSpec.model_validate({"name": "t", "sources": {"groups": [1]}, "targets": {}})


def test_sequence_round_trip():
    entry = sequence_from_gateway(GW_SEQUENCE, REFS, ZONES)
    assert entry == {
        "name": "evening",
        "repeat": 3,
        "enabled": False,
        "steps": [
            {"devices": [7], "switch": True},
            {"groups": [1], "level": 30, "fade": 2, "delay": 1.5},
            {"zones": ["group 0"], "scene": 2, "delay": 0.5, "enabled": False},
        ],
    }
    spec = SequenceSpec.model_validate(entry)
    body = spec.body(
        [[{"type": "device", "id": 8}], [{"type": "group", "id": 1}], [{"type": "zone", "id": 2}]]
    )
    assert sequence_canonical(body) == sequence_canonical(GW_SEQUENCE)
    assert body["steps"][1]["data"]["features"] == {"dimmableWithFade": {"dimValue": 30, "fadeTime": 2}}
    assert spec.summary() == "3 step(s), repeat 3"


def test_sequence_validation():
    with pytest.raises(ValueError, match="at least 1"):
        SequenceSpec.model_validate({"name": "s", "steps": []})
    with pytest.raises(ValueError, match="no targets"):
        SequenceSpec.model_validate({"name": "s", "steps": [{"switch": True}]})
    with pytest.raises(ValueError, match="exactly one"):
        SequenceSpec.model_validate({"name": "s", "steps": [{"devices": [1], "switch": True, "scene": 1}]})


def test_site_checks_automation_references():
    base = {
        "lines": {0: {"devices": [{"name": "a", "address": 7}]}},
        "zones": [{"name": "z", "devices": [7]}],
    }
    Site.model_validate(
        {**base, "triggers": [{"name": "t", "sources": {"devices": [7]}, "targets": {"zones": ["z"]}}]}
    )
    with pytest.raises(ValueError, match="trigger 't' sources refers to 9"):
        Site.model_validate(
            {**base, "triggers": [{"name": "t", "sources": {"devices": [9]}, "targets": {"zones": ["z"]}}]}
        )
    with pytest.raises(ValueError, match="sequence 's' refers to unknown zone"):
        Site.model_validate(
            {**base, "sequences": [{"name": "s", "steps": [{"zones": ["nope"], "switch": True}]}]}
        )
    with pytest.raises(ValueError, match="sequence name 's' is used twice"):
        Site.model_validate(
            {**base, "sequences": [{"name": "s", "steps": [{"devices": [7], "switch": True}]}] * 2}
        )


def test_site_init_includes_triggers_and_sequences():
    text = from_gateway(GW_DEVICES, GW_ZONES, [], None, [GW_TRIGGER], [GW_SEQUENCE])
    data = yaml.safe_load(text)
    assert data["triggers"][0]["name"] == "hall" and data["sequences"][0]["steps"][0] == {
        "devices": [7],
        "switch": True,
    }
    Site.model_validate(data)


def test_plan_syncs_triggers_and_sequences(client, fake):
    _gw(fake, schedules=[])
    fake.answers[("GET", "/automations/triggerActions")] = {"triggerActions": [GW_TRIGGER]}
    fake.answers[("GET", "/automations/sequences")] = {"sequences": [GW_SEQUENCE]}
    site = Site.model_validate(
        {
            "lines": {0: {"devices": [{"name": "outside", "address": 7}]}},
            "zones": [{"name": "group 0", "groups": [0]}, {"name": "new", "groups": [5]}],
            "triggers": [
                {
                    "name": "hall",
                    "sources": {"groups": [3], "devices": [7]},
                    "targets": {"zones": ["group 0"], "groups": [1]},
                },
                {"name": "porch", "sources": {"groups": [4]}, "targets": {"zones": ["new"]}},
            ],
            "sequences": [
                {"name": "evening", "repeat": 2, "steps": [{"devices": [7], "switch": True}]},
            ],
        },
    )
    changes = plan.build(site, client, prune=True)
    auto = [(c.op, c.what) for c in changes if c.what.split()[0] in ("trigger", "sequence")]
    assert auto == [("create", "trigger porch"), ("update", "sequence evening")]
    create = next(c for c in changes if c.what == "trigger porch")
    fake.answers[("GET", "/zones")] = {"zones": [*GW_ZONES, {"id": 9, "name": "new", "targets": []}]}
    create.apply()
    m, path, body, _ = fake.calls[-1]
    assert (m, path) == ("POST", "/automations/triggerAction")
    assert body["sources"] == [{"type": "d16group", "line": 0, "address": 4}]
    assert body["targets"] == [{"type": "zone", "id": 9}]
    next(c for c in changes if c.what == "sequence evening").apply()
    m, path, body, _ = fake.calls[-1]
    assert (m, path) == ("PUT", "/automations/sequence/1")
    assert body["repeat"] == 2 and body["steps"][0]["data"]["targets"] == [{"type": "device", "id": 8}]
