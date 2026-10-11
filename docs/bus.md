# The bus and the gateway's two interfaces

Background for understanding what `dali-iot` can and cannot see. It is short
on purpose; the DALI standard is IEC 62386.

## DALI in two sentences

A DALI line is a two-wire bus with up to 64 *control gear* (lamp drivers,
relays, each with a short address 0 to 63, membership of up to 16 groups,
and 16 stored scenes) and any number of *control devices* (push-button
couplers, sensors) that send commands onto it. Commands are 16-bit frames
addressed to a short address, a group or everyone; a few are queries, which
the addressed device answers with one byte.

Group membership and scenes are stored in each lamp, not in any controller.
That is why a wall switch can run a group with no gateway present, and why
the gateway's groups are just what it last read from the lamps.

## What the gateway's REST API sees

The gateway keeps a database of the control gear it found at its last scan:
one record per line and short address, holding the name you give it, the
device type, groups and scenes read from the lamp, and a status byte. On top
of that it stores its own objects: zones, schedules, trigger actions,
sequences. The REST API reads and writes that database and sends control
commands. It is what `plan`, `apply` and the control verbs use.

Three consequences shape the tool:

- The REST API has no notion of control devices. Switches and sensors do not
  appear, and cannot be configured through it.
- A record is keyed by address, not by device. The gateway does not notice
  when a lamp is readdressed elsewhere: the old record stays, a new one
  appears at the next scan, and the two look alike. See
  [Changing addresses](site-file.md#changing-addresses-with-another-tool).
- Records carry no serial number, so nothing in the REST API says *which*
  lamp an address is.

## What the WebSocket sees

The same gateway serves a WebSocket on port 80 that relays raw DALI frames
in both directions: send a 16-bit frame, optionally wait for the one-byte
answer, and receive every frame seen on the bus. This is the interface
commissioning tools use. It needs no authentication on the LAN.

`dali-iot` uses it for one thing: reading a device's memory bank 0, which
every DALI lamp carries and which holds its serial number, firmware version,
and on multi-channel devices the number of units and this unit's index.
Lunatone gear also stores its article number there. That read is what gives
`site init` its `serial` and `product` fields, `bus identify` its table, and
`site check` its certainty about moves. It sends only queries and the two
data-register writes a memory read needs; it never programs a device.

Protocol details for both interfaces are in the
[gateway API notes](gateway-api.md).

## What this leaves to other tools

Addressing lamps, programming push-button couplers, reading sensors and
watching bus traffic are commissioning jobs on the bus side. `dali-iot`
assumes they have been done, and keeps the gateway's picture of the result
true to the bus.
