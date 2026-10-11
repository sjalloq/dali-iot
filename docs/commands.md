# Commands

`dali-iot [--url URL] [--trace] [--timeout S] COMMAND`. `-h` on any command
prints its options. Global options:

| option | meaning |
|---|---|
| `--url URL` | gateway base URL, else the saved one from `gateway set-url` or `scan --save` |
| `--trace` | print every HTTP request and reply to stderr |
| `--timeout S` | seconds to wait for the gateway (default 5) |

Commands never print gateway ids. Devices are DALI short addresses, `7` for
line 0 or `1/7` for line 1; zones and sequences are names from the site
file; groups are DALI group numbers 0 to 15.

## gateway

Which gateway to talk to.

| command | does |
|---|---|
| `gateway scan [--timeout S] [--yes] [--save]` | find gateways on the LAN by UDP broadcast; `--yes` allows the host-by-host fallback without asking; `--save` stores the URL if exactly one answers |
| `gateway set-url URL` | remember the gateway URL in `~/.config/dali-iot/config.toml` |
| `gateway get-url` | print the URL in use and where it came from |
| `gateway info` | the gateway's name, firmware, lines and serial |
| `gateway rescan` | ask the gateway to reload its device list from the bus; changes no address |
| `gateway spec [--out DIR]` | download the gateway's OpenAPI spec as `openapi-<firmware>.json` |

## site, plan, apply

The site file and the loop that keeps the gateway matching it. All take
`--site PATH` or `--path PATH`, default `site/site.yaml`.

| command | does |
|---|---|
| `site init [--force]` | write a starting file from the gateway's devices, zones and automations, with serials read from the devices over the bus; `--force` overwrites |
| `site check [--no-sweep]` | compare the file with the bus by serial, and the gateway's records with the bus; exits 1 when anything differs; `--no-sweep` reads only the gateway's addresses instead of all 64 per line |
| `plan [--prune]` | list what `apply` would change; read-only |
| `apply [--prune] [--yes]` | print the plan, ask once, make the changes; `--yes` skips the question |

`--prune` adds deletion of device records, zones and automations the file
does not mention. Without it they are reported as notes and left alone.

## device, zone, group, broadcast

Direct control. Each noun has `on [--level N] [--fade S]`, `off [--fade S]`
and `recall SCENE [--fade S]`.

| command | target |
|---|---|
| `device on\|off\|recall ADDRESS` | one device by short address |
| `device identify ADDRESS [--times N] [--pause S]` | blink the device off and on so you can see which it is, then restore it |
| `zone on\|off\|recall ZONE` | a zone by name |
| `group on\|off\|recall GROUP` | a DALI group, 0 to 15 |
| `broadcast [--line N] on\|off\|recall` | every device, or every device on one line |

## sequence

| command | does |
|---|---|
| `sequence run NAME` | start a stored sequence |
| `sequence stop NAME` | stop a running one |

Sequences are defined in the site file and stored by `apply`.

## bus

Raw queries over the gateway's WebSocket; read-only.

| command | does |
|---|---|
| `bus identify` | serial, unit, firmware and product of every device the gateway lists, from memory bank 0 |

## dump

| command | does |
|---|---|
| `dump [--out DIR]` | write everything the gateway holds to `dump/*.json`: info, devices, zones, sensors, each automation kind |

## Exit codes

0 on success. 1 for a gateway or file error, and for `site check` when the
file and the bus differ. 2 for a usage error.
