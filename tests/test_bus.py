import json

import pytest

from dali_iot.bus import Bus, Identity, identities_by_address, parse_article, ws_url

# bank 0 of a pre-DALI-2 Lunatone dimmer and the Lunatone block in its bank 2 (real captures)
OLD_BANK0 = bytes([17, 155, 3, 0, 0, 0, 0, 0, 0, 4, 8, 0, 1, 153, 183, 1, 1, 3])
OLD_BANK2 = bytes(
    [50, 148, 255, *b"Lunatone", 108, 0, 49, 17, 3, 97, 0, 1, 153, 183, 0, 0, 0, 0, 0, 0, 0, 0, 0]
    + [5, 39, 64, 251, *b"-300U-HS", 0, 0, 0]
)
# bank 0 of one unit of a DALI-2 4-channel relay module (real capture): 4 units, this is unit 1
NEW_BANK0 = bytes([175, 0, 5, 0, 0, 0, 0, 0, 0, 1, 2, 0, 0, 0, 4, 0, 1, 75, 191, 3, 0, 8, 8, 255, 0, 4, 1])
NEW_RAW = [*NEW_BANK0]
NEW_RAW[1] = None  # DALI-2 bank 0 offset 1 is reserved and does not answer


class FakeSocket:
    """Answers READ MEMORY LOCATION from a {(address, bank): bytes} table, tracking DTR0/DTR1."""

    def __init__(self, banks):
        self.banks = banks
        self.sent = []
        self.queue = []
        self.dtr0 = self.dtr1 = 0
        self.closed = False

    def send(self, message):
        m = json.loads(message)
        self.sent.append(m)
        data = m["data"]["daliData"]
        # the gateway echoes the frame first; answers follow
        self.queue.append(json.dumps({"type": "daliFrame", "data": {"line": 0, "result": 0}}))
        if data[0] == 0xC3:
            self.dtr1 = data[1]
            self.queue.append(json.dumps({"type": "daliAnswer", "data": {"line": 0, "result": 0}}))
        elif data[0] == 0xA3:
            self.dtr0 = data[1]
            self.queue.append(json.dumps({"type": "daliAnswer", "data": {"line": 0, "result": 0}}))
        elif data[1] == 0x91:  # QUERY CONTROL GEAR PRESENT
            if any(a == data[0] >> 1 for a, _ in self.banks):
                self.queue.append(
                    json.dumps({"type": "daliAnswer", "data": {"line": 0, "result": 8, "daliData": 255}})
                )
            else:
                self.queue.append(json.dumps({"type": "daliAnswer", "data": {"line": 0, "result": 0}}))
        elif data[1] == 0xC5:
            bank = self.banks.get((data[0] >> 1, self.dtr1))
            if bank is not None and self.dtr0 < len(bank):
                v = bank[self.dtr0]
                self.dtr0 += 1
                self.queue.append(
                    json.dumps({"type": "daliAnswer", "data": {"line": 0, "result": 8, "daliData": v}})
                )
            else:
                self.queue.append(json.dumps({"type": "daliAnswer", "data": {"line": 0, "result": 0}}))

    def recv(self, timeout=None):
        return self.queue.pop(0)

    def close(self):
        self.closed = True


def test_ws_url():
    assert ws_url("http://10.0.0.239") == "ws://10.0.0.239/"
    assert ws_url("http://gw:8080/") == "ws://gw:8080/"


def test_parse_article():
    assert parse_article(OLD_BANK2) == "86458619-300U-HS"
    assert parse_article(b"nothing here") is None
    assert parse_article(b"Lunatone\x00\x00") is None


def test_identity_layouts():
    old = Identity(0, 0, OLD_BANK0, OLD_BANK2)
    assert not old.dali2 and old.serial == 104887 and old.firmware == "4.8" and old.gtin == 0
    assert old.article == "86458619-300U-HS"
    new = Identity(0, 7, NEW_BANK0)
    assert new.dali2 and new.serial == int.from_bytes(NEW_BANK0[0x0B:0x13], "big") and new.article is None
    assert new.units == 4 and new.unit == 1 and new.firmware == "1.2"
    assert old.units is None and old.unit is None
    assert Identity(0, 9, b"").serial is None


def test_query_frame_shape_and_answer():
    sock = FakeSocket({(0, 0): OLD_BANK0})
    with Bus(sock) as bus:
        assert bus.query(0, [0xC3, 0]) is None
        assert bus.read_bank(0, 0, 0, 0, 3) == [*OLD_BANK0[:3]]
    assert sock.closed
    first = sock.sent[0]
    assert first["type"] == "daliFrame"
    assert first["data"]["numberOfBits"] == 16 and first["data"]["mode"]["waitForAnswer"] is True
    assert [m["data"]["daliData"] for m in sock.sent[1:4]] == [[0xC3, 0], [0xA3, 0], [0x01, 0xC5]]


def test_identify_reads_the_product_block_from_the_right_bank():
    sock = FakeSocket(
        {(0, 0): OLD_BANK0, (0, 2): OLD_BANK2, (7, 0): NEW_BANK0 + bytes(0x84 - len(NEW_BANK0)) + OLD_BANK2}
    )
    with Bus(sock) as bus:
        idents = list(bus.identify_all([(0, 0), (0, 7), (0, 9)]))
    assert [i.serial for i in idents][:2] == [104887, int.from_bytes(NEW_BANK0[0x0B:0x13], "big")]
    assert idents[0].bank0 == OLD_BANK0  # only up to the last accessible offset
    assert idents[1].bank0[1] == 0 and idents[1].dali2
    assert idents[0].article == "86458619-300U-HS"
    assert idents[1].article == "86458619-300U-HS"  # read from bank 0 at 0x84
    assert idents[2].bank0 == b"" and idents[2].serial is None
    table = identities_by_address(idents)
    assert table[(0, 0)] == {"serial": 104887, "product": "86458619-300U-HS"}
    assert table[(0, 7)]["unit"] == 1
    assert (0, 9) not in table


@pytest.mark.parametrize("v", [[5], 5])
def test_answer_bytes_may_be_int_or_list(v):
    class S:
        def send(self, m):
            pass

        def recv(self, timeout=None):
            return json.dumps({"type": "daliAnswer", "data": {"result": 8, "daliData": v}})

        def close(self):
            pass

    assert Bus(S()).query(0, [1, 0xC5]) == 5


def test_sweep_finds_present_addresses():
    sock = FakeSocket({(0, 0): OLD_BANK0, (7, 0): NEW_BANK0})
    seen = []
    with Bus(sock) as bus:
        assert bus.sweep(0, seen.append) == [0, 7]
        assert bus.identify(0, 7, product=False).product_block == b""
    assert seen == list(range(64))
    assert sum(1 for m in sock.sent if m["data"]["daliData"][1] == 0x91) == 64
