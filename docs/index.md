# dali-iot

Configure and drive a Lunatone DALI-2 IoT gateway over its REST API, without
the Lunatone cloud subscription. The gateway's own web UI only exposes a few
settings; zones and automations can only be created through the API, and the
API's objects are gateway-shaped. dali-iot puts a house-shaped intent model
in front of them: name your devices and zones once, describe automations in
terms of rooms, buttons, clock times and sun offsets, and let the tool compile
that into the gateway's schedulers, triggers, sequences and circadians.

Front ends, in order of arrival: a CLI with `dump`, `plan` and `apply` over
YAML files kept in git, then a small web UI for use from a phone.

```{toctree}
:maxdepth: 2

gateway-api
```
