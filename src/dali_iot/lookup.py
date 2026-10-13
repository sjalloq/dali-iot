"""Find gateway records by the names people use: an address, a zone name, a sequence name.

Shared by the CLI and the web UI so neither shows a gateway id to anyone.
"""

from __future__ import annotations

from .client import Client
from .refs import parse_ref


class NotFound(LookupError):
    """The gateway has nothing by that address or name."""


def device_at(c: Client, address: str | int) -> dict:
    """The gateway record for an address reference like ``7`` or ``1/7``.

    Raises ``ValueError`` for a malformed reference and ``NotFound`` for an
    address the gateway has no record for.
    """
    ref = int(address) if isinstance(address, str) and address.isdigit() else address
    line, addr = parse_ref(ref)
    for d in c.devices():
        if int(d.get("line", 0)) == line and d.get("address") == addr:
            return d
    raise NotFound(f"nothing at line {line} A{addr} on the gateway")


def zone_named(c: Client, name: str) -> dict:
    zones = c.zones()
    for z in zones:
        if z.get("name") == name:
            return z
    raise NotFound(f"no zone named {name!r} (have: {', '.join(str(z.get('name')) for z in zones)})")


def sequence_named(c: Client, name: str) -> dict:
    seqs = c.automations("sequence")
    for sq in seqs:
        if sq.get("name") == name:
            return sq
    raise NotFound(f"no sequence named {name!r} (have: {', '.join(str(x.get('name')) for x in seqs)})")
