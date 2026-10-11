# Site file

`dali-iot` keeps your names for the gateway's devices and zones, and your
schedules, in a YAML
site file, `site/site.yaml` by default. The `site/` directory is git-ignored
because the file describes one installation. `--site PATH` points elsewhere.

```
dali-iot site init     # starting file from what the gateway holds now
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
  are listed as notes.
- **Zones** are matched by name: missing ones are created, differing targets
  are updated. Zones the file does not mention are notes and left alone;
  `--prune` deletes them.
- **Schedules** are matched by name the same way. An update sends the whole
  schedule. A schedule may target a zone the same plan creates; the zone id
  is looked up when the schedule change runs, so apply order works out.
- `plan` only reads. `apply` prints the plan, asks once, then runs each
  change in order; `--yes` skips the question. Errors never block the other
  changes.

The site file covers what the REST API covers: control gear, meaning lamps
and relays. Control devices such as push-button couplers are not visible to
the gateway's REST API and are not part of this file.
