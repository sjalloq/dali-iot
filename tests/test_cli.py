"""Command wiring: arguments reach the right request. The HTTP layer is the fake session."""

import pytest
from click.testing import CliRunner

from dali_iot import cli
from dali_iot.client import Client, off_features, on_features
from tests.test_plan import _gw

STEP = {
    "type": "features",
    "delay": 0,
    "data": {"targets": [{"type": "device", "id": 8}], "features": {"switchable": True}},
}


@pytest.fixture
def run(fake, monkeypatch):
    _gw(fake)
    fake.answers[("GET", "/automations/sequences")] = {
        "sequences": [{"id": 4, "name": "evening", "steps": [STEP]}]
    }
    monkeypatch.setattr(cli, "_url", lambda ctx: ("http://gw", "test"))
    monkeypatch.setattr(cli, "_client", lambda ctx: Client("http://gw", session=fake))

    def _run(*args):
        return CliRunner().invoke(cli.main, args, catch_exceptions=False)

    _run.fake = fake
    return _run


def _writes(fake):
    return [(m, p, j) for m, p, j, _ in fake.calls if m != "GET"]


def test_device_verbs_resolve_the_address(run):
    assert run("device", "on", "7", "--level", "40").exit_code == 0
    assert run("device", "off", "8", "--fade", "2").exit_code == 0
    assert run("device", "recall", "7", "3").exit_code == 0
    assert _writes(run.fake) == [
        ("POST", "/device/8/control", on_features(40)),
        ("POST", "/device/9/control", off_features(2.0)),
        ("POST", "/device/8/control", {"scene": 3}),
    ]


def test_device_errors(run):
    r = run("device", "on", "40")
    assert r.exit_code == 1 and "nothing at line 0 A40" in r.output
    r = run("device", "on", "x")
    assert r.exit_code == 2 and "use an address like 7" in r.output
    assert _writes(run.fake) == []


def test_zone_group_broadcast(run):
    assert run("zone", "off", "wet").exit_code == 0
    assert run("group", "on", "2", "--level", "10").exit_code == 0
    assert run("broadcast", "--line", "0", "off").exit_code == 0
    assert run("group", "on", "16").exit_code == 2
    r = run("zone", "on", "nope")
    assert "no zone named 'nope'" in r.output
    writes = _writes(run.fake)
    assert writes[0] == ("POST", "/zone/3/control", off_features())
    assert writes[1] == ("POST", "/group/2/control", on_features(10))
    assert writes[2][:2] == ("POST", "/broadcast/control")
    assert len(writes) == 3


def test_sequence_run_and_stop(run):
    assert run("sequence", "run", "evening").exit_code == 0
    assert run("sequence", "stop", "evening").exit_code == 0
    assert [p for _, p, _ in _writes(run.fake)] == [
        "/automations/sequence/4/start",
        "/automations/sequence/4/stop",
    ]
    r = run("sequence", "run", "nope")
    assert r.exit_code == 1 and "no sequence named 'nope' (have: evening)" in r.output


def test_device_identify_blinks_and_restores(run, monkeypatch):
    monkeypatch.setattr("dali_iot.client.time.sleep", lambda s: None)
    run.fake.answers[("GET", "/device/8")] = {"id": 8, "features": {"switchable": {"status": True}}}
    r = run("device", "identify", "7", "--times", "1")
    assert r.exit_code == 0 and "blinking line 0 A7" in r.output
    assert _writes(run.fake) == [
        ("POST", "/device/8/control", off_features()),
        ("POST", "/device/8/control", on_features()),
        ("POST", "/device/8/control", on_features()),
    ]


def test_site_init_plan_and_apply_round_trip(run, tmp_path):
    path = tmp_path / "site.yaml"
    assert run("site", "init", "--path", str(path)).exit_code == 0
    assert run("site", "init", "--path", str(path)).exit_code == 1  # exists; needs --force
    r = run("plan", "--site", str(path))
    assert r.exit_code == 0 and "no changes" in r.output
    text = path.read_text().replace("name: Line 0 - DALI#07", "name: outside")
    text = text.replace("address: 7\n", "address: 7\n      serial: 4242\n", 1)
    path.write_text(text)
    r = run("plan", "--site", str(path))
    assert "rename  device outside" in r.output and "1 change(s)" in r.output
    assert _writes(run.fake) == []  # plan is read-only
    assert run("apply", "--yes", "--site", str(path)).exit_code == 0
    assert _writes(run.fake) == [("PUT", "/device/8", {"name": "outside"})]
    # a plain re-init keeps the serial the file had
    assert run("site", "init", "--force", "--path", str(path)).exit_code == 0
    assert "serial: 4242" in path.read_text()


def test_help_short_option(run):
    r = run("-h")
    assert r.exit_code == 0 and "Usage: " in r.output
