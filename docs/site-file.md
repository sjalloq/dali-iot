# Site file

`dali-iot` keeps your names for the gateway's devices and zones, and your
schedules, in a YAML
site file, `site/site.yaml` by default. The `site/` directory is git-ignored
because the file describes one installation. `--site PATH` points elsewhere.

```
dali-iot site init     # starting file from what the gateway holds now
dali-iot site check    # rescan the bus; do the file's devices still match?
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
  are listed as notes; `--prune` deletes their gateway records, which never
  touches the device itself.
- **Zones** are matched by name: missing ones are created, differing targets
  are updated. Zones the file does not mention are notes and left alone;
  `--prune` deletes them.
- **Schedules** are matched by name the same way. An update sends the whole
  schedule. A schedule may target a zone the same plan creates; the zone id
  is looked up when the schedule change runs, so apply order works out.
- `plan` only reads. `apply` prints the plan, asks once, then runs each
  change in order; `--yes` skips the question. Errors never block the other
  changes.

## When addresses change

The gateway keys its device records by line and address and never
reconciles them: readdress a lamp with another tool and rescan, and the
gateway keeps a stale record at the old address and adds a fresh one, with a
factory name and no zone or schedule memberships, at the new. The REST API
exposes no serial number and no reliable liveness flag, so nothing can tell
a stale record from a real device automatically.

`dali-iot site check` first asks the gateway to reload its device list from
the bus (a "current device list" scan, which changes no address; skip it
with `--no-scan`, or run it alone with `dali-iot gateway rescan`), then
compares the file's device inventory with the gateway's and reports:

- `lost`: the file has a device at an address the gateway has nothing at.
- `new`: the gateway has a record the file does not mention. When file
  devices share its type and groups, they are listed as candidates, since
  both live in the device and survive a readdress.
- `moved`: a `lost` and a `new` with the same type and groups, paired.
- `type`: the file and the gateway disagree about what is at an address.
- `stale`: a line holds more records than the scan found devices, so some
  records belong to nothing. A stale record is indistinguishable from a live
  device that is switched off, so the count is the only evidence; records
  sharing a type and groups are listed as the likely pairs. Switching one on
  and reading which record reports `lampOn` settles it.

Each finding comes with the edit to make. The usual readdress workflow is:
change the address, run `site check`, change `address:` and any
`devices: [...]` references in the file, then `apply --prune` to drop the
stale record. Zone and schedule targets follow, because they are resolved
from addresses when the change runs. `check` exits 1 when anything differs,
so it can gate a script.

The site file covers what the REST API covers: control gear, meaning lamps
and relays. Control devices such as push-button couplers are not visible to
the gateway's REST API and are not part of this file.
