# Site file

`dali-iot` keeps your names for the gateway's devices and zones in a YAML
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
    devices: [lounge back, lounge front]    # device names
  - name: downstairs
    groups: [0]                             # DALI groups, and/or devices
  - name: everything
    broadcast: [0]                          # lines
```

Names must be unique across all devices, and across all zones.

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
- `plan` only reads. `apply` prints the plan, asks once, then runs each
  change in order; `--yes` skips the question. Errors never block the other
  changes.

The site file covers what the REST API covers: control gear, meaning lamps
and relays. Control devices such as push-button couplers are not visible to
the gateway's REST API and are not part of this file.
