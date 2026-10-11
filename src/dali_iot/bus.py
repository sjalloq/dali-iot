"""Read device identity over the gateway's WebSocket.

The REST API never says *which* device sits at an address; only the device's own
memory bank 0 does. The gateway's WebSocket on port 80 (``ws://<gateway>/``, no
authentication) relays raw DALI frames: a ``daliFrame`` with ``waitForAnswer``
gets a ``daliAnswer`` whose ``result`` is 8 for a reply (``daliData`` the byte)
or 0 for none. This module sends only queries and the DTR writes they need; it
never programs a device.

Bank 0 (IEC 62386-102) holds GTIN, firmware version and the identification
(serial) number. Lunatone gear also carries a product block tagged
``"Lunatone"`` with the 8-digit article number and an ASCII suffix: in bank 0
at offset 0x84 on DALI-2 devices, in bank 2 at offset 3 on older gear.
"""

from __future__ import annotations

import dataclasses
import json
import re
from collections.abc import Callable, Iterator
from typing import Any, Protocol, Self
from urllib.parse import urlparse

ANSWER = 8  # daliAnswer.result for "a device replied"
_TAG = b"Lunatone"


class Socket(Protocol):
    def send(self, message: str) -> None: ...
    def recv(self, timeout: float | None = None) -> str | bytes: ...
    def close(self) -> None: ...


def ws_url(base_url: str) -> str:
    """REST base URL -> the gateway's WebSocket URL."""
    host = urlparse(base_url).netloc or base_url
    return f"ws://{host}/"


def connect(base_url: str, timeout: float = 5.0) -> Socket:
    from websockets.sync.client import connect as _connect  # imported here: optional, slow import

    return _connect(ws_url(base_url), open_timeout=timeout, max_size=1 << 20)


@dataclasses.dataclass
class Identity:
    line: int
    address: int
    bank0: bytes  # offsets 0..last accessible; unanswered locations read as 0; empty = no device
    product_block: bytes = b""

    @property
    def last_offset(self) -> int:
        return self.bank0[0] if self.bank0 else -1

    @property
    def dali2(self) -> bool:
        """IEC 62386-102 ed. 2 layout (8-byte serial) if the bank reaches offset 0x1A."""
        return self.last_offset >= 0x1A

    @property
    def gtin(self) -> int | None:
        return int.from_bytes(self.bank0[3:9], "big") if len(self.bank0) >= 9 else None

    @property
    def firmware(self) -> str | None:
        return f"{self.bank0[9]}.{self.bank0[10]}" if len(self.bank0) >= 11 else None

    @property
    def serial(self) -> int | None:
        """Identification number: 0x0B..0x12 (ed. 2) or 0x0B..0x0E (ed. 1)."""
        end = 0x13 if self.dali2 else 0x0F
        if len(self.bank0) < end:
            return None
        return int.from_bytes(self.bank0[0x0B:end], "big")

    @property
    def units(self) -> int | None:
        """Logical control gear units in this physical device (DALI-2 bank 0 offset 0x19)."""
        return self.bank0[0x19] if self.dali2 and len(self.bank0) > 0x1A else None

    @property
    def unit(self) -> int | None:
        """This unit's index within the device (offset 0x1A); None for single-unit devices."""
        if self.units is None or self.units <= 1:
            return None
        return self.bank0[0x1A]

    @property
    def key(self) -> tuple[int, int | None] | None:
        """What identifies this physical unit: (serial, unit index)."""
        return (self.serial, self.unit) if self.serial is not None else None

    @property
    def article(self) -> str | None:
        """Lunatone article number with suffix, e.g. ``86458619-300U-HS``."""
        return parse_article(self.product_block)


def parse_article(block: bytes) -> str | None:
    """The Lunatone product block: ``"Lunatone"``, a few bytes, then a big-endian u32
    article number followed by an ASCII suffix starting with ``-``."""
    i = block.find(_TAG)
    if i < 0:
        return None
    rest = block[i + len(_TAG) :]
    for j in range(len(rest) - 4):
        n = int.from_bytes(rest[j : j + 4], "big")
        if 10_000_000 <= n <= 99_999_999 and rest[j + 4 : j + 5] == b"-":
            m = re.match(rb"[\x21-\x7e]*", rest[j + 4 :])
            return f"{n}{(m[0] if m else b'').decode('ascii')}"
    return None


class Bus:
    """Raw 16-bit queries over the gateway's WebSocket. Use as a context manager."""

    def __init__(self, sock: Socket, timeout: float = 3.0) -> None:
        self.sock = sock
        self.timeout = timeout

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc: object) -> None:
        self.sock.close()

    def query(self, line: int, data: list[int]) -> int | None:
        """Send a 16-bit frame and return the answer byte, or None for no answer."""
        self.sock.send(
            json.dumps(
                {
                    "type": "daliFrame",
                    "data": {
                        "line": line,
                        "numberOfBits": 16,
                        "daliData": data,
                        "mode": {"sendTwice": False, "waitForAnswer": True, "priority": 4},
                    },
                }
            )
        )
        while True:
            msg = json.loads(self.sock.recv(self.timeout))
            if msg.get("type") == "daliAnswer":
                d = msg.get("data") or {}
                if d.get("result") != ANSWER:
                    return None
                v = d.get("daliData")
                return v[0] if isinstance(v, list) else v
            # daliFrame echoes, daliMonitor and daliStatus events are not answers

    def present(self, line: int, address: int) -> bool:
        """QUERY CONTROL GEAR PRESENT: does anything answer at this short address?"""
        return self.query(line, [(address << 1) | 1, 0x91]) is not None

    def sweep(self, line: int, progress: Callable[[int], None] | None = None) -> list[int]:
        """Every short address on ``line`` that has control gear, one query each."""
        found = []
        for address in range(64):
            if self.present(line, address):
                found.append(address)
            if progress:
                progress(address)
        return found

    def read_bank(self, line: int, address: int, bank: int, start: int, count: int) -> list[int | None]:
        """READ MEMORY LOCATION ``count`` bytes from ``bank`` at ``start``.

        A location the device does not implement (bank 0 offset 1 on DALI-2 gear) gets
        no answer but DTR0 still advances, so gaps are ``None`` and the read goes on.
        """
        self.query(line, [0xC3, bank])  # SET DTR1 = bank
        self.query(line, [0xA3, start])  # SET DTR0 = offset
        return [self.query(line, [(address << 1) | 1, 0xC5]) for _ in range(count)]  # DTR0 auto-increments

    def identify(self, line: int, address: int, product: bool = True) -> Identity:
        """Bank 0 identity; ``product=False`` skips the Lunatone block (serial and unit only)."""
        raw = self.read_bank(line, address, 0, 0, 0x1B)
        if raw[0] is None:  # nothing answers at this address
            return Identity(line, address, b"")
        bank0 = _bytes(raw[: raw[0] + 1])
        ident = Identity(line, address, bank0)
        if not product:
            return ident
        if ident.dali2 and ident.last_offset >= 0x84:
            ident.product_block = _bytes(
                self.read_bank(line, address, 0, 0x84, min(0x30, ident.last_offset - 0x84 + 1))
            )
        elif not ident.dali2 and bank0[2] >= 2:  # bank0[2] = last accessible bank
            ident.product_block = _bytes(self.read_bank(line, address, 2, 0, 0x30))
        return ident

    def identify_all(
        self,
        devices: list[tuple[int, int]],
        progress: Callable[[Identity], None] | None = None,
        product: bool = True,
    ) -> Iterator[Identity]:
        for line, address in devices:
            ident = self.identify(line, address, product=product)
            if progress:
                progress(ident)
            yield ident


def _bytes(raw: list[int | None]) -> bytes:
    """Unanswered locations read as 0."""
    return bytes(v if v is not None else 0 for v in raw)


def identities_by_address(idents: list[Identity]) -> dict[tuple[int, int], dict[str, Any]]:
    """(line, address) -> {"serial", "unit", "product"} for devices that answered, for the site file.

    A multi-channel device (one relay module with four short addresses, say) shares one
    serial across its units, so ``unit`` is what tells them apart.
    """
    out: dict[tuple[int, int], dict[str, Any]] = {}
    for i in idents:
        if i.serial is None:
            continue
        entry: dict[str, Any] = {"serial": i.serial}
        if i.unit is not None:
            entry["unit"] = i.unit
        if i.article:
            entry["product"] = i.article
        out[(i.line, i.address)] = entry
    return out
