# dali-iot

Configure and drive a Lunatone DALI-2 IoT gateway over its REST API: an
intent model for house-level automations, YAML config with `dump`/`plan`/`apply`,
and a small web UI. No cloud subscription needed.

```
source sourceme
dali-iot gateway scan --save   # or: dali-iot gateway set-url http://<gateway-ip>
dali-iot dump                  # everything the gateway holds -> dump/*.json
dali-iot all-off               # broadcast off
dali-iot on --zone 2 --level 60
dali-iot --trace off --device 8
dali-iot gateway spec          # download the gateway's OpenAPI spec (then: make models)
```

Docs: `make docs` → `docs/build/html/`.
