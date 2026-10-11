"""Find gateways on the LAN.

The gateway answers the 9 ASCII bytes ``discovery`` on UDP port 5555. The
probe goes to every LAN's directed broadcast address, three times about a
second apart, with a 3.2 s listen. Each reply is JSON with ``type`` (``dali-2-iot``,
``dali-2-iot4``, ``dali4net``, ``dali-2-display``, ...) and ``name``.

A stateful host firewall drops the reply to a broadcast probe (it comes from
the gateway's address, not the broadcast address the conntrack entry was made
for), and the gateway answers a unicast probe just as happily, so when the
broadcast is silent the caller is offered a unicast sweep of every host.
"""

from __future__ import annotations

import dataclasses
import ipaddress
import json
import socket
import subprocess
import time
from collections.abc import Callable

PORT = 5555
PROBE = b"discovery"


@dataclasses.dataclass(frozen=True)
class Found:
    ip: str
    type: str
    name: str
    url: str


def parse_reply(ip: str, payload: bytes) -> Found | None:
    try:
        data = json.loads(payload.decode("utf-8", errors="replace"))
    except ValueError:
        return None
    if not isinstance(data, dict) or "type" not in data:
        return None
    return Found(ip=ip, type=str(data["type"]), name=str(data.get("name", "")), url=f"http://{ip}")


VIRTUAL_KINDS = {"bridge", "veth", "tun", "tap", "wireguard", "dummy", "vrf", "bond", "team"}


@dataclasses.dataclass(frozen=True)
class Lan:
    ifname: str
    network: ipaddress.IPv4Network


def local_lans(ip_json: str | None = None) -> list[Lan]:
    """Real LAN interfaces: up, IPv4, not loopback and not virtual (``ip -d -j -4 addr``).

    Docker bridges, VPN tunnels and the like are skipped: a gateway cannot be on them.
    """
    if ip_json is None:
        try:
            ip_json = subprocess.run(
                ["ip", "-d", "-j", "-4", "addr"], capture_output=True, text=True, check=True
            ).stdout
        except (OSError, subprocess.CalledProcessError):
            return []
    lans: list[Lan] = []
    for iface in json.loads(ip_json):
        if iface.get("operstate") != "UP":
            continue
        if iface.get("linkinfo", {}).get("info_kind") in VIRTUAL_KINDS:
            continue
        for a in iface.get("addr_info", []):
            net = ipaddress.ip_network(f"{a['local']}/{a['prefixlen']}", strict=False)
            if net.is_loopback or net.prefixlen >= 32:
                continue
            lan = Lan(iface["ifname"], net)
            if lan not in lans:
                lans.append(lan)
    return lans


def broadcast_targets(lans: list[Lan]) -> list[str]:
    """Directed broadcast address of each LAN."""
    return [str(lan.network.broadcast_address) for lan in lans]


Progress = Callable[[str], None]
Confirm = Callable[[str], bool]


def probe(targets: list[str], timeout: float = 3.2, probes: int = 3) -> list[Found]:
    """Send ``probes`` rounds of the discovery datagram to ``targets`` and collect replies for ``timeout`` s."""
    results: dict[str, Found] = {}
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        s.settimeout(0.2)
        deadline = time.monotonic() + timeout
        next_probe = 0.0
        sent = 0
        while time.monotonic() < deadline:
            if sent < probes and time.monotonic() >= next_probe:
                for t in targets:
                    try:
                        s.sendto(PROBE, (t, PORT))
                    except OSError:
                        pass
                sent += 1
                next_probe = time.monotonic() + 1.07
            try:
                payload, (ip, _) = s.recvfrom(10000)
            except TimeoutError:
                continue
            if (f := parse_reply(ip, payload)) and ip not in results:
                results[ip] = f
    return sorted(results.values(), key=lambda f: f.ip)


def discover(
    timeout: float = 3.2, progress: Progress | None = None, confirm: Confirm | None = None
) -> list[Found]:
    """Broadcast on each LAN; if nothing answers, offer to sweep each LAN host by host.

    ``progress`` receives one line per phase for the user. ``confirm`` is asked
    before the sweep, with a question naming the subnets and host counts; with
    no ``confirm`` there is no sweep.
    """
    say = progress or (lambda _msg: None)
    lans = local_lans()
    if not lans:
        say("no LAN interface is up")
        return []
    say("scanning " + ", ".join(f"{lan.ifname} ({lan.network})" for lan in lans))
    say(f"broadcasting discovery to {', '.join(broadcast_targets(lans))} on UDP {PORT} ({timeout:.1f} s)")
    found = probe(broadcast_targets(lans), timeout)
    if found:
        return found

    say("no reply (a host firewall may be dropping broadcast replies; see docs)")
    if confirm is None:
        return []
    hosts = [str(h) for lan in lans for h in lan.network.hosts()]
    what = ", ".join(f"{lan.network} on {lan.ifname} ({lan.network.num_addresses - 2} hosts)" for lan in lans)
    if not confirm(f"send a unicast probe to every host of {what}?"):
        return []
    say(f"sweeping {len(hosts)} addresses ({timeout:.1f} s)")
    return probe(hosts, timeout, probes=1)
