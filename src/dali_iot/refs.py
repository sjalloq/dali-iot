"""Device references in the site file: a short address, never a name or a gateway id."""

from __future__ import annotations

import re

DeviceRef = int | str  # address on line 0, or "line/address"


def parse_ref(ref: DeviceRef) -> tuple[int, int]:
    """A device reference -> (line, address)."""
    if isinstance(ref, bool):
        raise ValueError(f"device reference {ref!r} is not an address")  # noqa: TRY004  (pydantic wants ValueError)
    if isinstance(ref, int):
        line, addr = 0, ref
    else:
        m = re.fullmatch(r"\s*(\d+)\s*/\s*(\d+)\s*", str(ref))
        if not m:
            raise ValueError(f"device reference {ref!r}; use an address like 7, or line/address like 1/7")
        line, addr = int(m[1]), int(m[2])
    if not 0 <= addr <= 63:
        raise ValueError(f"device reference {ref!r}: address must be 0..63")
    return line, addr


def format_ref(line: int, address: int) -> DeviceRef:
    return address if line == 0 else f"{line}/{address}"
