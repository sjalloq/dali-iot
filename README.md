# dali-iot

Configure and drive a Lunatone DALI-2 IoT gateway over its REST API: an
intent model for house-level automations, YAML config with `dump`/`plan`/`apply`,
and a small web UI. No cloud subscription needed.

```
source sourceme
dali-iot gateway scan --save   # or: dali-iot gateway set-url http://<gateway-ip>
dali-iot dump                  # everything the gateway holds -> dump/*.json
dali-iot site init --identify  # site/site.yaml from the gateway, with serials read over the bus
dali-iot bus identify          # serial, unit and product of every device (memory bank 0)
dali-iot site check            # does the file still describe the bus? (serials, ~30 s)
dali-iot device identify 7     # blink the light at A7 so you can see which one it is
dali-iot plan && dali-iot apply
dali-iot broadcast off         # everything off
dali-iot zone on lounge --level 60
dali-iot device off 7          # by DALI address; --trace logs the requests
dali-iot group recall 2 3      # scene 3 on group 2
dali-iot sequence run evening  # start a stored sequence
dali-iot gateway spec          # download the gateway's OpenAPI spec (then: make models)
```

Docs: https://sjalloq.github.io/dali-iot/ (built with `make docs` → `docs/build/html/`).
