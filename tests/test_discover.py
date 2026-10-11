from dali_iot.discover import parse_reply


def test_parse_gateway_reply():
    f = parse_reply("10.0.0.239", b'{"type": "dali-2-iot", "name": "DALI-2 IoT"}')
    assert f is not None
    assert (f.type, f.name, f.url) == ("dali-2-iot", "DALI-2 IoT", "http://10.0.0.239")


def test_parse_ignores_junk():
    assert parse_reply("1.2.3.4", b"not json") is None
    assert parse_reply("1.2.3.4", b'{"name": "x"}') is None


IP_JSON = """[
 {"ifname": "lo", "operstate": "UNKNOWN", "addr_info": [{"local": "127.0.0.1", "prefixlen": 8}]},
 {"ifname": "wlan0", "operstate": "UP", "addr_info": [{"local": "10.0.0.135", "prefixlen": 24}]},
 {"ifname": "eth0", "operstate": "UP", "addr_info": [{"local": "192.168.0.5", "prefixlen": 16}]},
 {"ifname": "tailscale0", "operstate": "UNKNOWN", "linkinfo": {"info_kind": "tun"},
  "addr_info": [{"local": "100.68.180.69", "prefixlen": 32}]},
 {"ifname": "docker0", "operstate": "DOWN", "linkinfo": {"info_kind": "bridge"},
  "addr_info": [{"local": "172.17.0.1", "prefixlen": 16}]},
 {"ifname": "br0", "operstate": "UP", "linkinfo": {"info_kind": "bridge"},
  "addr_info": [{"local": "172.18.0.1", "prefixlen": 16}]}
]"""


def test_local_lans_keeps_only_real_up_interfaces():
    import ipaddress

    from dali_iot.discover import Lan, local_lans

    assert local_lans(IP_JSON) == [
        Lan("wlan0", ipaddress.ip_network("10.0.0.0/24")),
        Lan("eth0", ipaddress.ip_network("192.168.0.0/16")),
    ]


def test_broadcast_targets():
    from dali_iot.discover import broadcast_targets, local_lans

    assert broadcast_targets(local_lans(IP_JSON)) == ["10.0.0.255", "192.168.255.255"]


def test_discover_sweeps_only_after_silence_and_consent(monkeypatch):
    from dali_iot import discover as d

    lans = d.local_lans(IP_JSON)
    monkeypatch.setattr(d, "local_lans", lambda: lans)
    gw = d.Found("10.0.0.239", "dali-2-iot", "x", "http://10.0.0.239")
    calls: list[list[str]] = []

    def silent_broadcast(targets, timeout=3.2, probes=3):
        calls.append(targets)
        return [gw] if len(targets) > 3 else []

    monkeypatch.setattr(d, "probe", silent_broadcast)
    log: list[str] = []
    questions: list[str] = []

    def confirm(q):
        questions.append(q)
        return True

    assert d.discover(progress=log.append, confirm=confirm) == [gw]
    assert calls[0] == ["10.0.0.255", "192.168.255.255"]
    assert len(calls[1]) == 254 + 65534
    assert "10.0.0.0/24 on wlan0 (254 hosts)" in questions[0]
    assert "192.168.0.0/16 on eth0 (65534 hosts)" in questions[0]

    calls.clear()
    assert d.discover(confirm=lambda q: False) == []
    assert len(calls) == 1  # declined: broadcast only

    calls.clear()
    assert d.discover() == []
    assert len(calls) == 1  # no confirm callback: never sweeps

    calls.clear()
    monkeypatch.setattr(d, "probe", lambda targets, timeout=3.2, probes=3: calls.append(targets) or [gw])
    assert d.discover(confirm=lambda q: True) == [gw]
    assert len(calls) == 1  # broadcast answered: no question, no sweep
