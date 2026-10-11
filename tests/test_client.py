from dali_iot.client import off_features, on_features, schedule_action


def test_all_off_broadcasts_switch_and_dim(client, fake):
    client.control_broadcast(off_features())
    assert fake.calls == [("POST", "/broadcast/control", {"switchable": False, "dimmable": 0}, None)]


def test_broadcast_line_is_a_query_param(client, fake):
    client.control_broadcast(off_features(), line=1)
    assert fake.calls[0][3] == {"_line": 1}


def test_on_with_fade_uses_dimmable_with_fade():
    assert on_features(50, 2.5) == {"switchable": True, "dimmableWithFade": {"dimValue": 50, "fadeTime": 2.5}}


def test_automations_list_unwraps_key(client, fake):
    fake.answers[("GET", "/automations/schedules")] = {"schedulers": [{"id": 1}]}
    assert client.automations("schedule") == [{"id": 1}]


def test_automation_create_uses_singular_path(client, fake):
    client.create_automation("schedule", {"name": "x"})
    assert fake.calls[0][:2] == ("POST", "/automations/scheduler")


def test_schedule_action_nests_features():
    assert schedule_action({"switchable": True}) == {
        "type": "features",
        "data": {"features": {"switchable": True}},
    }
