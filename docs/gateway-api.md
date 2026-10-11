# Gateway API notes

Things the gateway's OpenAPI spec (`/openapi.json`, firmware 1.12.1) does not tell you.
Download it with `dali-iot gateway spec`.

## Scheduler actions

A scheduler's `action` must be

```json
{"type": "features", "data": {"features": {"switchable": true}}}
```

The gateway accepts `{"type": "features", "data": {"switchable": true}}` with
no error and never fires it (Lunatone API manual 4.2.1). The spec types
`data` as a free-form object, so schema validation cannot catch this.
`dali_iot.client.schedule_action` is the one place that builds the shape.

## Discovery

Send the 9 ASCII bytes `discovery` to UDP port 5555. The gateway answers from
port 5555 with `{"type": "dali-2-iot", "name": "DALI-2 IoT"}`. It answers
unicast and broadcast probes alike. Other Lunatone products answer the same
probe with their own `type` (`dali-2-iot4`, `dali4net`, `dali-2-display`).

A stateful host firewall (ufw, firewalld, Windows Firewall) drops the reply to
a **broadcast** probe: the outgoing packet's conntrack entry is for the
broadcast address, the reply comes from the gateway's own address, so it is
treated as new inbound traffic and denied. Unicast replies match the entry
and pass. Seen on Arch with ufw as `[UFW BLOCK] ... SRC=<gateway> ...
PROTO=UDP SPT=5555` in the kernel log. `dali-iot gateway scan` looks only at
real LAN interfaces that are up (no loopback, Docker bridges or VPN tunnels),
broadcasts on each first and, only if nothing answers, offers to send one
unicast probe to every host of each LAN (254 packets for a /24), which works
through any firewall. The question names each subnet and its host count;
`--yes` answers it for scripts, and without a terminal there is no sweep.
Each phase is reported on stderr. To make broadcast work too, allow inbound UDP from
source port 5555 on the LAN, e.g. for ufw:

```
sudo ufw allow in proto udp from 10.0.0.0/24 port 5555
```

## Naming

Automations are created and addressed by a singular path and listed by a
plural one with a wrapper key:

| kind | create / item | list | list key |
|---|---|---|---|
| schedule | `/automations/scheduler` | `/automations/schedules` | `schedulers` |
| sequence | `/automations/sequence` | `/automations/sequences` | `sequences` |
| trigger | `/automations/triggerAction` | `/automations/triggerActions` | `triggerActions` |
| circadian | `/automations/circadian` | `/automations/circadians` | `circadians` |

## Ids

Gateway device id = DALI short address + 1.

## WebSocket

Port 80 also serves a WebSocket at `ws://<gateway>/` that relays raw DALI
frames. No authentication is needed on the LAN. Messages are JSON:

```json
{"type": "daliFrame", "data": {"line": 0, "numberOfBits": 16, "daliData": [1, 197],
 "mode": {"sendTwice": false, "waitForAnswer": true, "priority": 4}}}
```

The gateway echoes `{"type": "daliFrame", "data": {"line": 0, "result": 0}}`,
then, when `waitForAnswer` was set, sends `daliAnswer` with `data.result` 8
and `data.daliData` the answer byte as an integer, or `result` 0 for no
answer. `daliMonitor` events carry every frame seen on the bus. One query
round trip takes about 75 ms.

`dali_iot.bus` uses this for memory bank reads only (SET DTR1 `C3 bb`, SET
DTR0 `A3 oo`, then READ MEMORY LOCATION `C5` per byte with DTR0
auto-incrementing, also past locations that give no answer). Bank 0 layout:
offset 0 is the last accessible offset, 3–8 GTIN, 9–10 firmware, 0x0B–0x12
the identification number on IEC 62386-102 ed. 2 gear (0x0B–0x0E on ed. 1
gear, whose bank ends at 0x11), 0x19 the number of logical units in the
device and 0x1A this unit's index. Lunatone devices add a block tagged
`Lunatone`, in bank 0 at 0x84 on DALI-2 gear and in bank 2 at offset 3 on
older gear, holding a big-endian u32 article number and an ASCII suffix,
e.g. `86458619-300U-HS`. GTIN was zero on every Lunatone device seen.
