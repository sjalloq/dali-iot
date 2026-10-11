# Getting started

## Install

Python 3.13 or newer. From a clone:

```
git clone https://github.com/sjalloq/dali-iot
cd dali-iot
source sourceme          # creates .venv with uv and activates it
dali-iot -h
```

Or into any environment with `pip install git+https://github.com/sjalloq/dali-iot`.

## Find the gateway

The gateway must be on a LAN you are connected to.

```
dali-iot gateway scan --save
```

This broadcasts a discovery probe on each real network interface and saves
the URL of the one gateway that answers to `~/.config/dali-iot/config.toml`.
If broadcast is silent, usually because of a host firewall, it offers to
probe every host of the subnet instead; see
[gateway API notes](gateway-api.md#discovery). If you know the address:

```
dali-iot gateway set-url http://10.0.0.239
dali-iot gateway info
```

Every command also takes `--url` to override the saved gateway.

## Describe the installation

```
dali-iot site init
```

This writes `site/site.yaml`: every device the gateway knows with its DALI
address, type, group memberships, and the serial number read from the device
itself; every zone; every schedule, trigger and sequence. The `site/`
directory is git-ignored because the file describes one house. Reading the
serials takes about a minute for a dozen devices.

Right after `init`, `dali-iot plan` reports no changes: the file and the
gateway agree.

## Name the lights

The gateway's factory names are `Line 0 - DALI#07` and so on. To find out
which lamp an address is, blink it:

```
dali-iot device identify 7
```

Then edit the name in the file, add zones for the rooms, and check:

```
dali-iot plan
rename  device outside: line 0 A7 'Line 0 - DALI#07' -> 'outside'
create  zone lounge: device:1, device:5
2 change(s)
dali-iot apply
```

`apply` prints the same plan, asks once, and sends the changes. Names and
zones live in the gateway from then on, so anything else that talks to the
gateway sees them too.

## Control lights

```
dali-iot zone on lounge --level 60
dali-iot device off 7
dali-iot group recall 2 3        # scene 3 on DALI group 2
dali-iot broadcast off
```

Devices are addressed by DALI short address, zones by the names in your
file. `--trace` on any command prints the HTTP requests and replies.

## Keep the file true

After wiring changes or readdressing with a commissioning tool:

```
dali-iot site check
```

It asks every device on the bus for its serial and reports what moved, went
missing or appeared, with the edit to make. The [examples](examples.md)
walk through that and other common tasks.
