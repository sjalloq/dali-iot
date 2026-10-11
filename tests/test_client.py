import pytest

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


def test_rescan_starts_a_no_addressing_scan_and_waits(client, fake, monkeypatch):
    monkeypatch.setattr("dali_iot.client.time.sleep", lambda s: None)
    states = iter(
        [
            {"id": "", "status": "not started"},  # pre-check
            {"id": "old", "status": "done", "progress": 100.0},  # stale result from an earlier scan
            {"id": "new", "status": "in progress", "progress": 40.0},
            {"id": "new", "status": "done", "progress": 100.0, "found": 12},
        ]
    )
    fake.answers[("POST", "/dali/scan")] = {"id": "new", "status": "not started"}
    orig = fake.request

    def request(method, url, json=None, params=None, timeout=None):
        if method == "GET" and url.endswith("/dali/scan"):
            fake.answers[("GET", "/dali/scan")] = next(states)
        return orig(method, url, json, params, timeout)

    fake.request = request
    seen = []
    st = client.rescan(seen.append)
    assert st["found"] == 12
    assert [s["id"] for s in seen] == ["old", "new", "new"]
    post = [(m, p, j) for m, p, j, _ in fake.calls if m == "POST"]
    assert post == [("POST", "/dali/scan", {"newInstallation": False, "noAddressing": True})]


def test_rescan_refuses_while_a_scan_runs(client, fake):
    fake.answers[("GET", "/dali/scan")] = {"id": "x", "status": "in progress", "progress": 10.0}
    with pytest.raises(RuntimeError, match="already running"):
        client.rescan()


def test_blink_restores_a_dimmer_that_was_on(client, fake, monkeypatch):
    monkeypatch.setattr("dali_iot.client.time.sleep", lambda s: None)
    fake.answers[("GET", "/device/3")] = {
        "id": 3,
        "features": {"switchable": {"status": True}, "dimmable": {"status": 60.0}},
    }
    restore = client.blink_device(3, times=2)
    posts = [j for m, p, j, _ in fake.calls if m == "POST" and p == "/device/3/control"]
    assert posts[:4] == [off_features(), on_features(), off_features(), on_features()]
    assert posts[4] == restore == on_features(60)
    assert len(posts) == 5


def test_blink_restores_a_relay_that_was_off(client, fake, monkeypatch):
    monkeypatch.setattr("dali_iot.client.time.sleep", lambda s: None)
    fake.answers[("GET", "/device/8")] = {"id": 8, "features": {"switchable": {"status": False}}}
    client.blink_device(8, times=1)
    posts = [j for m, p, j, _ in fake.calls if m == "POST"]
    assert posts == [on_features(), off_features(), off_features()]
