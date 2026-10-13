"""The web API: every route reaches the right request, and edits land in the site file."""

from __future__ import annotations

import pytest
import yaml
from fastapi.testclient import TestClient

from dali_iot.client import Client, off_features, on_features
from dali_iot.web.app import create_app
from tests.test_plan import _gw

SITE = {
    "lines": {0: {"devices": [{"name": "outside", "address": 7, "type": "relay", "groups": [0, 1]}]}},
    "zones": [{"name": "wet", "devices": [7]}],
    "schedules": [{"name": "dusk", "at": "sunset", "devices": [7], "switch": True}],
}


@pytest.fixture
def web(fake, tmp_path):
    _gw(fake)
    fake.answers[("GET", "/automations/sequences")] = {
        "sequences": [{"id": 4, "name": "evening", "steps": []}]
    }
    fake.answers[("GET", "/info")] = {"name": "gw"}
    path = tmp_path / "site.yaml"
    path.write_text(yaml.safe_dump(SITE))
    app = create_app(
        path, "http://gw", make_client=lambda: Client("http://gw", session=fake), static_dir=None
    )
    tc = TestClient(app)
    tc.fake = fake
    tc.site_path = path
    return tc


def _writes(fake):
    return [(m, p, j) for m, p, j, _ in fake.calls if m != "GET"]


def test_info(web):
    r = web.get("/api/info")
    assert r.status_code == 200 and r.json()["info"] == {"name": "gw"}


def test_control_state_uses_site_names(web):
    body = web.get("/api/control").json()
    by_ref = {d["ref"]: d for d in body["devices"]}
    assert by_ref["7"]["name"] == "outside" and by_ref["7"]["type"] == "relay"
    assert "ref" in by_ref["8"] and "id" not in by_ref["8"]
    assert [z["name"] for z in body["zones"]] and body["sequences"] == ["evening"]


def test_control_commands(web):
    assert web.post("/api/control", json={"kind": "device", "target": "7", "switch": True}).status_code == 200
    assert (
        web.post("/api/control", json={"kind": "device", "target": 8, "level": 40, "fade": 2}).status_code
        == 200
    )
    assert web.post("/api/control", json={"kind": "device", "target": "7", "scene": 3}).status_code == 200
    assert (
        web.post("/api/control", json={"kind": "zone", "target": "wet", "switch": False}).status_code == 200
    )
    assert web.post("/api/control", json={"kind": "group", "target": 3, "switch": True}).status_code == 200
    assert web.post("/api/control", json={"kind": "broadcast", "switch": False}).status_code == 200
    assert _writes(web.fake) == [
        ("POST", "/device/8/control", on_features(100)),
        ("POST", "/device/9/control", on_features(40, 2.0)),
        ("POST", "/device/8/control", {"scene": 3}),
        ("POST", "/zone/3/control", off_features()),
        ("POST", "/group/3/control", on_features(100)),
        ("POST", "/broadcast/control", off_features()),
    ]


def test_control_errors(web):
    r = web.post("/api/control", json={"kind": "device", "target": "40", "switch": True})
    assert r.status_code == 404 and "nothing at line 0 A40" in r.json()["detail"]
    r = web.post("/api/control", json={"kind": "zone", "target": "nope", "switch": True})
    assert r.status_code == 404
    r = web.post("/api/control", json={"kind": "device", "target": "7"})
    assert r.status_code == 422 and "exactly one" in r.json()["detail"]
    assert _writes(web.fake) == []


def test_sequence_run(web):
    assert web.post("/api/sequences/evening/run").status_code == 200
    assert web.post("/api/sequences/missing/run").status_code == 404
    assert _writes(web.fake) == [("POST", "/automations/sequence/4/start", None)]


def test_devices_table_merges_site_and_gateway(web):
    rows = web.get("/api/devices").json()["devices"]
    assert [(r["ref"], r["in_site"], r["on_gateway"]) for r in rows] == [
        ("7", True, True),
        ("8", False, True),
    ]
    assert rows[0]["gateway_name"] != "outside" and rows[0]["type"] == "relay"


def test_device_edit_writes_the_site_file(web):
    assert web.put("/api/devices/0/7", json={"name": "porch", "groups": [2]}).status_code == 200
    assert web.put("/api/devices/0/8", json={"name": "bath", "type": "relay"}).status_code == 200
    raw = yaml.safe_load(web.site_path.read_text())
    assert raw["lines"][0]["devices"] == [
        {"name": "porch", "address": 7, "type": "relay", "groups": [2]},
        {"name": "bath", "address": 8, "type": "relay"},
    ]
    assert raw["zones"] == [{"name": "wet", "devices": [7]}]
    assert raw["schedules"] == [{"name": "dusk", "at": "sunset", "devices": [7], "switch": True}]
    # a duplicate name is refused and the file is left alone
    r = web.put("/api/devices/0/8", json={"name": "porch"})
    assert r.status_code == 422 and "used twice" in r.json()["detail"]
    assert yaml.safe_load(web.site_path.read_text())["lines"][0]["devices"][1]["name"] == "bath"
    assert web.delete("/api/devices/0/8").status_code == 200
    assert web.delete("/api/devices/0/8").status_code == 404
    assert _writes(web.fake) == []


def test_device_blink(web):
    web.fake.answers[("GET", "/device/8")] = {"id": 8, "features": {"switchable": {"status": True}}}
    assert web.post("/api/devices/0/7/blink").status_code == 200
    assert _writes(web.fake)[-1] == ("POST", "/device/8/control", on_features())


def test_schedules_crud(web):
    body = web.get("/api/schedules").json()
    assert body["zones"] == ["wet"] and body["devices"] == [{"ref": "7", "name": "outside"}]
    assert body["schedules"][0]["name"] == "dusk" and body["schedules"][0]["enabled"] is True
    new = {"name": "late", "at": "23:00", "zones": ["wet"], "switch": False, "days": ["fri", "sat"]}
    assert web.post("/api/schedules", json=new).status_code == 200
    assert web.post("/api/schedules", json=new).status_code == 422
    assert (
        web.put("/api/schedules/dusk", json={**new, "name": "dusk2", "at": "sunset-0:30"}).status_code == 200
    )
    r = web.put("/api/schedules/dusk2", json={"name": "x", "at": "25:00", "devices": [7], "switch": True})
    assert r.status_code == 422
    r = web.put("/api/schedules/dusk2", json={"name": "x", "at": "22:00", "zones": ["nope"], "switch": True})
    assert r.status_code == 422 and "unknown zone" in r.json()["detail"]
    assert web.delete("/api/schedules/late").status_code == 200
    raw = yaml.safe_load(web.site_path.read_text())
    assert raw["schedules"] == [
        {"name": "dusk2", "at": "sunset-0:30", "zones": ["wet"], "switch": False, "days": ["fri", "sat"]}
    ]
    assert web.delete("/api/schedules/late").status_code == 404


def test_plan_and_apply(web):
    changes = web.get("/api/plan").json()["changes"]
    real = [(c["op"], c["what"]) for c in changes if c["applies"]]
    assert real[:3] == [("rename", "device outside"), ("groups", "device outside"), ("update", "zone wet")]
    assert ("note", "device 'Bathroom'") in [(c["op"], c["what"]) for c in changes]
    assert _writes(web.fake) == []
    out = web.post("/api/apply", json={"prune": False}).json()
    assert [c["what"] for c in out["applied"]][:3] == ["device outside", "device outside", "zone wet"]
    assert ("PUT", "/device/8", {"name": "outside"}) in _writes(web.fake)


def test_missing_site_file(web):
    web.site_path.unlink()
    r = web.get("/api/schedules")
    assert r.status_code == 404 and "site init" in r.json()["detail"]
