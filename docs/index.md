# dali-iot

`dali-iot` configures and drives a Lunatone DALI-2 IoT gateway from the
command line, without the Lunatone cloud subscription.

The gateway's own web page exposes a handful of settings. Everything else,
naming lamps, grouping them into zones, scheduling, linking a wall switch to
more lights, lives behind its REST API, and the API speaks in gateway ids and
feature dicts. `dali-iot` puts a plain description of your installation in
front of that: one YAML file naming the devices by DALI address, the zones,
and the automations in words like `at: sunset` and `switch: off`. `plan`
shows how the gateway differs from the file, `apply` makes them match. A
set of short verbs controls lights directly for scripts and other tools.

What it covers is what the gateway's REST API covers: control gear, meaning
lamps, drivers and relays, on up to four DALI lines. Push-button couplers and
sensors are commissioned with other tools; the gateway only sees their
effect on the bus. One thing the REST API cannot tell you is *which* lamp
sits at an address, so `dali-iot` also reads each device's serial number over
the gateway's WebSocket, which is what makes readdressing survivable.

Status: the command-line tool is complete for one gateway. A small web page
for phone use is the next step.

```{toctree}
:maxdepth: 2

getting-started
commands
examples
bus
site-file
gateway-api
```
