# Examples

Each example is an edit to `site/site.yaml` followed by `dali-iot plan` and
`dali-iot apply`, unless it says otherwise. Device references are DALI short
addresses; the device must be listed under `lines`.

## Name the lights in a room

Blink each address until you know what it is, then name it:

```
dali-iot device identify 0
dali-iot device identify 4
```

```yaml
lines:
  0:
    devices:
      - name: lounge back
        address: 0
        type: dimmer
        groups: [0, 1]
      - name: lounge front
        address: 4
        type: dimmer
        groups: [0, 1]
```

`plan` shows one `rename` per changed name. Renames are safe: nothing else
in the file refers to a device by its name.

## A zone for the room

```yaml
zones:
  - name: lounge
    devices: [0, 4]
```

Then `dali-iot zone on lounge --level 40`. A zone can also be built from
groups, which is cheaper on the bus when the lamps already share one:

```yaml
  - name: downstairs
    groups: [1]
```

## Outside light on at dusk, off at bedtime

```yaml
schedules:
  - name: outside on
    at: sunset
    devices: [7]
    switch: on
  - name: outside off
    at: '22:00'
    devices: [7]
    switch: off
```

Clock times are quoted; `sunset-0:30` and `sunrise+1:00` are offsets.

## Dim the lounge on winter weekday evenings

```yaml
  - name: lounge evening
    at: sunset-0:30
    zones: [lounge]
    level: 40
    fade: 5
    days: [mon, tue, wed, thu, fri]
    months: [nov, dec, jan, feb]
```

## Make a wall switch control more lights

The hall switch is a push-button coupler sending DALI commands to group 3 on
the bus. The gateway never programs the switch, but it can repeat what the
switch does to other targets:

```yaml
triggers:
  - name: hall switch also lights the landing
    sources:
      groups: [3]
    targets:
      zones: [landing]
```

## A lighting sequence

```yaml
sequences:
  - name: welcome home
    steps:
      - devices: [7]           # porch on at once
        switch: on
      - zones: [hall]          # then the hall, two seconds later, fading up
        level: 60
        fade: 2
        delay: 2
      - zones: [lounge]
        scene: 1
        delay: 3
```

`apply` stores it; `dali-iot sequence run "welcome home"` plays it. A
sequence can be a schedule's or another tool's action.

## After readdressing with a commissioning tool

You moved the lamp at A5 to A31 and the gateway still shows both. Ask the
bus:

```
dali-iot site check
moved     'bed' serial 108054: A5 -> A31
          change address: 5 to 31 and any devices: [5] to [31], then: dali-iot gateway rescan && dali-iot apply --prune
```

Make that edit, then:

```
dali-iot gateway rescan
dali-iot plan --prune
dali-iot apply --prune
```

`rescan` lets the gateway see A31; `apply --prune` renames the new record,
repoints zones and schedules at it, and deletes the stale record at A5. The
device itself is never touched by a record delete.

## Scripts and other systems

The verbs are made for shells, cron and home-automation systems:

```
dali-iot broadcast off                     # last one out
dali-iot zone on landing --level 20 --fade 10
dali-iot --url http://10.0.0.239 --trace device on 7
```

Exit code 1 means the gateway refused or was unreachable. `site check`
exits 1 when the installation has drifted from the file, so it can run from
cron as a drift alarm.

## Keep the file in git

`site/` is git-ignored in this repository because the file describes one
house. Keep your own copy in a private repository, or point every command at
it with `--site PATH`. The file plus the gateway's firmware is everything
needed to rebuild the configuration: `apply` on an empty gateway after a
rescan recreates the names, zones and automations.
