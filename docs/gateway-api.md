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

The gateway also serves a WebSocket on port 80 that carries raw DALI frames
and a bus monitor stream. dali-iot does not use it.

## Scans and device records

`POST /dali/scan` takes `newInstallation` and `noAddressing`:

| newInstallation | noAddressing | effect |
|---|---|---|
| true | false | deletes every device record, readdresses the whole bus |
| false | false | adds unaddressed devices with new addresses |
| false | true | reloads the device list; nothing is readdressed |

Only the last is safe to run casually, and it is what `dali-iot gateway
rescan` runs. Poll `GET /dali/scan` until `status` is `done`;
the reply carries the scan `id`, so a stale `done` from an earlier scan can
be told apart from the new one.

Device records are keyed by line and address. After a device is readdressed
elsewhere and the bus rescanned, the gateway keeps the old record (its
`available` flag stays `true`) and creates a new one with a new id, a
factory name and no zone or schedule memberships. Records expose no serial
number, GTIN or firmware version. `DELETE /device/{id}` removes only the
record, never anything in the device.
