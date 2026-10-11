# Site file

`dali-iot` keeps your names for the gateway's devices and zones, and your
schedules, triggers and sequences, in a YAML
site file, `site/site.yaml` by default. The `site/` directory is git-ignored
because the file describes one installation. `--site PATH` points elsewhere.

```
dali-iot site init     # starting file from what the gateway holds now (--identify adds serials)
dali-iot site check    # does the file still describe the bus? asks every device (read-only)
dali-iot plan          # what apply would change (read-only)
dali-iot apply         # make the gateway match the file
```

## Format

Devices are keyed by DALI line and short address, the only identifier the
gateway shares with the bus. The gateway's own device id is looked up at plan
time and never appears in the file.

```yaml
lines:
  0:
    devices:
      - name: lounge back
        address: 0
        type: dimmer          # checked against the gateway; omit to skip
        groups: [0, 1]        # managed if given; omit to leave alone
      - name: outside
        address: 7
        type: relay

zones:
  - name: lounge
    devices: [0, 4]                         # short addresses ("1/4" = line 1, address 4)
  - name: downstairs
    groups: [0]                             # DALI groups, and/or devices
  - name: everything
    broadcast: [0]                          # lines
```

Names must be unique across all devices, and across all zones.

`dali-iot site init` keeps the serials an existing file already has.
`dali-iot site init --identify` also reads each device's memory bank 0 over
the gateway's WebSocket and records `serial`, `product` (the Lunatone article
number with its suffix) and, for multi-channel devices that share one serial,
`unit`. These are informational: `plan` ignores them, but they say *which*
device an address was, which nothing in the REST API does.
`dali-iot bus identify` prints the same without writing a file.

To find out which light an address is, `dali-iot device identify 7` blinks
it off and on twice and restores it.

Zones and schedules refer to devices by short address, never by name: an
integer is an address on line 0, and `"line/address"` reaches other lines.
Names are labels you can change freely without breaking anything. Every
referenced address must appear under `lines`, so the type check covers it.

### Groups and zones

A DALI *group* (0–15) is membership stored in the device itself; every
device lists the groups it belongs to under `groups`, and changing that list
rewrites the device. A *zone* is a gateway object: a named set of targets
(devices, groups or a whole line) that the gateway controls together. A
group only appears in the file as a zone if someone created a zone for it,
so a group can have members and still have no zone. To control such a group
as a unit, add a zone that targets it.

### Schedules

```yaml
schedules:
  - name: outside on
    at: sunset                # when
    devices: [7]              # to whom
    switch: on                # what
  - name: outside off
    at: '22:00'
    devices: [7]
    switch: off
  - name: evening lounge
    at: sunset-0:30
    zones: [lounge]
    level: 40
    fade: 2.5
    days: [mon, tue, wed, thu, fri]
    months: [oct, nov, dec, jan, feb]
    enabled: false
```

- `at` is a time of day as `'HH:MM'` or `'HH:MM:SS'`, or `sunrise`/`sunset`
  with an optional `-H:MM`/`+H:MM` offset. Quote clock times: an unquoted
  `22:00` is a number to YAML and is rejected with a hint.
- Targets are any mix of `devices` (addresses), `zones` (names from this
  file), `groups` (DALI group numbers) and `broadcast` (line numbers).
- The action is exactly one of `switch: on|off`, `level: 0..100` (with an
  optional `fade` in seconds), `scene: 0..15`, or `features:` with a raw
  gateway feature dict for anything else.
- `days` (`mon`..`sun`) and `months` (`jan`..`dec`) default to all.
  `enabled` defaults to true.

A date range (`activePeriod`) or day-of-month list (`activeDays`) on the
gateway is not modelled: it is neither written nor compared.

### Triggers

A trigger mirrors what happens to its sources onto its targets. When a
source receives a control command on the bus, from a push-button coupler
say, the gateway repeats it to the targets. This is how a wall switch that
drives one DALI group also drives a zone, or a lamp on another line.

```yaml
triggers:
  - name: hall switch also lights the landing
    sources:
      groups: [3]           # DALI groups as seen on the bus (line 0; set line: for another)
      devices: [5]          # addresses whose commands are mirrored
    targets:
      zones: [landing]
      devices: [7]
    enabled: true
```

Sources are written to the gateway as bus addresses (`d16gear`/`d16group`),
so the file never needs gateway ids. Targets take the same keys as a zone or
schedule: `devices`, `zones`, `groups`, `broadcast`.

### Sequences

A sequence is an ordered list of steps. Each step has targets, an action in
the same vocabulary as a schedule, and a `delay` in seconds that the gateway
waits before running it.

```yaml
sequences:
  - name: evening
    repeat: 2               # optional; loop: true runs until stopped
    steps:
      - devices: [7]
        switch: on
      - groups: [1]
        level: 30
        fade: 2
        delay: 1.5
      - zones: [lounge]
        scene: 2
        delay: 0.5
        enabled: false      # a step can be parked without deleting it
```

Sequences are stored, not run, by `apply`. `dali-iot sequence run NAME`
starts one and `sequence stop NAME` stops a looping one.

The gateway's two other automation kinds, circadian curves and status
queries, are not modelled. They are left alone on the gateway and never
appear in the file.

### Types

`type` names what the gateway reports in `daliTypes`:

| type | DALI device type |
|---|---|
| `relay` | 7 |
| `dimmer` | 4 (incandescent, phase-cut) |
| `led` | 6 |
| `colour` | 8 |
| `fluorescent` | 0 |
| `emergency` | 1 |

A device reporting several types gets the most specific name, so `colour`
over `led`. Anything else is written as the raw number.

## What plan and apply do

- **Devices** are matched by line and address. If the gateway reports a
  different type than the file says, that device is an error and `apply`
  does not touch it, since the address probably no longer means what the
  file thinks. Otherwise a different name is a `rename` and, when `groups`
  is given and differs, a `groups` change. Devices the file does not mention
  are listed as notes; `--prune` deletes their gateway records, which never
  touches the device itself.
- **Zones** are matched by name: missing ones are created, differing targets
  are updated. Zones the file does not mention are notes and left alone;
  `--prune` deletes them.
- **Schedules, triggers and sequences** are matched by name the same way. An
  update sends the whole record. They may target a zone the same plan
  creates; the zone id is looked up when the change runs, so apply order
  works out. `--prune` deletes ones the file does not mention.
- `plan` only reads. `apply` prints the plan, asks once, then runs each
  change in order; `--yes` skips the question. Errors never block the other
  changes.

## Changing addresses with another tool

The gateway only learns about the bus when it scans, and it keys its device
records by line and address without ever reconciling them. Readdress a
device with a commissioning tool and the gateway is left with stale data: the
old record stays, and the next scan adds a fresh record at the new address
with a factory name and no zone or schedule memberships. Nothing in the REST
API tells a stale record from a live device that is switched off.

`dali-iot site check` asks the bus instead. It sweeps every short address on
each line, reads the serial and unit index from each device that answers,
and compares with the file and with the gateway's records:

- `moved`: a serial from the file answers at another address. The finding
  gives the exact edit.
- `lost`: the file's device is not on the bus at all.
- `replaced`: the address answers, but with a different serial.
- `new`: a device on the bus that the file does not know.
- `unknown`: the file entry has no serial to compare, so only presence was
  checked; `site init --identify` records serials.
- `stale`: a gateway record at an address where nothing answers;
  `apply --prune` deletes it.
- `unscanned`: a device on the bus the gateway has no record of;
  `gateway rescan` adds it.

It exits 1 when anything differs. It takes about half a minute for a line:
one query per address, then a bank read per device. `--no-sweep` skips the
sweep and reads only the gateway's addresses.

The readdress workflow is therefore: change the address, `site check`, make
the edit it names, `gateway rescan`, then `plan` and `apply --prune`. Zone and
schedule targets follow, because they are resolved from addresses when the
change runs. The file is what restores names and memberships, since the
gateway does not carry them over.

The site file covers what the REST API covers: control gear, meaning lamps
and relays. Control devices such as push-button couplers are not visible to
the gateway's REST API and are not part of this file.
