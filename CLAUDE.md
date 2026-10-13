# dali-iot

Configure and drive a Lunatone DALI-2 IoT gateway over its REST API, without the
Lunatone cloud subscription. The gateway's web UI exposes only a few settings;
zones and automations exist only through the API, and the API's objects are
gateway-shaped (schedulers, triggers, sequences, circadians, feature dicts).
dali-iot puts a house-shaped intent model in front of them and compiles it down.

Project note: `~/Obsidian/Notes/projects/dali-iot.md` — where work stands.
This file is how to work here.

## Brief

- **Goal:** author and apply lighting automations for the house in house terms
  (rooms, buttons, sunset, clock times) and drive lights from scripts.
- **Scope (v1):** REST client; `dump`; scriptable verbs by noun (device ADDRESS | zone NAME | group N | broadcast: on/off/recall);
  intent model + compiler to gateway objects; YAML config with `plan`/`apply`.
  Then a small web UI (phone-usable, runs on Proxmox) over the same intent model.
- **Non-goals:** the DALI bus plane (raw frames, bus monitor, control device
  programming). Mirroring every REST endpoint as a command.
- **Constraints:** Python ≥3.13, uv, pydantic v2, click, requests; FastAPI + Vue/PrimeVue for the web UI (Node only at build time). One gateway
  (firmware 1.12.1 at time of writing; HA integration needs ≥1.14.1).
- **Done when:** the house's automations live in YAML in git, `apply` reproduces
  them on a reset gateway, and the web UI can switch zones and edit intents.

## Layout

- `src/dali_iot/client.py` — REST client: `Client.request` + resource helpers;
  payload helpers (`off_features`, `on_features`, `schedule_action`)
- `src/dali_iot/discover.py` — LAN scan on real up interfaces: UDP `discovery` to 5555; broadcast first, confirmed unicast sweep as fallback
- `src/dali_iot/config.py` — gateway URL: `--url` > `~/.config/dali-iot/config.toml`
- `src/dali_iot/site.py` — site file model: devices by line + short address with checked `type`, zones, schedules; device references are addresses (`parse_ref`), never names or gateway ids; `site init` generator
- `src/dali_iot/refs.py` — device references: short address (`7`, `"1/7"`) <-> (line, address)
- `src/dali_iot/intent.py` — shared vocabulary: `Targets` (devices/zones/groups/broadcast) and `Action` (switch/level/fade/scene/features) <-> gateway dicts
- `src/dali_iot/automation.py` — trigger (sources mirrored to targets, written as d16gear/d16group) and sequence (steps with delay) intents <-> gateway bodies
- `src/dali_iot/schedule.py` — schedule intent (`at`, targets, switch/level/scene/features, days, months) <-> gateway scheduler body; `canonical()` for diffing
- `src/dali_iot/bus.py` — WebSocket queries: memory bank reads -> `Identity` (serial, unit, article); read-only, never programs a device
- `src/dali_iot/check.py` — `site check`: bus sweep + serials vs the file and vs gateway records (moved/lost/replaced/new/stale/unscanned)
- `src/dali_iot/plan.py` — diff site vs gateway (devices, zones; schedules/triggers/sequences via one `_sync` by name) into `Change`s (incl. `error` for type/address mismatch); `plan` reads only, `apply` runs them
- `src/dali_iot/lookup.py` — gateway records by address / zone name / sequence name (`NotFound`); shared by CLI and web
- `src/dali_iot/cli.py` — `dali-iot` click CLI, including `serve`
- `src/dali_iot/web/app.py` — FastAPI JSON API (`create_app`) over the site file + gateway, serves the built SPA from `web/static/` (git-ignored, built by `make web` or the Dockerfile)
- `frontend/` — Vue 3 + Vite + PrimeVue SPA (screens ≤640px get Control only, `?full=1` overrides): `src/views/{Control,Devices,Schedules,Apply}.vue`, one `api.js`; builds into `src/dali_iot/web/static/`
- `Dockerfile`, `docker-compose.yml` — Node build stage + Python image; site file at `/data/site.yaml`, gateway from `DALI_IOT_URL`
- `src/dali_iot/api_models.py` — GENERATED (`make models`) from a downloaded spec; never edit.
  Its header names the spec file, and so the firmware version, it came from
- `spec/` — git-ignored; `dali-iot gateway spec` downloads `openapi-<firmware>.json` here
- `tests/` — pytest (test_cli.py drives the commands with click's runner over the fake session); `conftest.py` has a fake session, no gateway needed
- `docs/` — Sphinx (MyST, furo): index (what it is), getting-started, commands (reference), examples, bus (background), site-file (format reference), gateway-api (protocol facts)
- `site/` — git-ignored; the user's own site file lives here

## Commands

```
source sourceme                # uv sync --all-groups, activate
uv run pytest -q
uv run ruff check src tests && uv run ruff format --check src tests
make docs                      # Sphinx -> docs/build/html, warnings are errors
make web                       # npm ci && vite build -> src/dali_iot/web/static
uv sync --extra web && dali-iot serve [--site PATH] [--host 0.0.0.0] [--port 8000]
docker compose up -d --build   # needs .env with DALI_IOT_URL and data/site.yaml
dali-iot gateway spec          # download the gateway's OpenAPI spec into spec/
make models                    # regenerate api_models.py from the newest spec/openapi-*.json
dali-iot gateway scan [--yes] [--save]   # find gateways on the LAN
dali-iot gateway set-url http://<gw>
dali-iot site init | plan | apply [--prune] [--yes]
dali-iot [--trace] dump | device on|off|recall|identify ADDR | zone on|off NAME | group on N | broadcast off
```

## Rules

- Tests and lint pass before finishing.
- Official docs live in `docs/`. Never in the vault.
- `make docs` is the publishing contract: HTML into `docs/build/html/`,
  warnings as errors, installing only what the docs need.
  `.github/workflows/docs.yml` runs exactly that and publishes the result to
  GitHub Pages on every push to main (public repo, so no private docs server).
- Never commit a secret, a gateway dump, or the house's device map
  (`dump/` and `*.local.yaml` are ignored).
- Commit messages short and to the point; no co-auth attribution.
- Every gateway quirk learned goes into `docs/gateway-api.md` and into code
  in exactly one place.

## Invariants

- The site file never contains the gateway's device id. Devices are keyed by
  line + short address, and a `type` mismatch blocks changes to that device.
- The REST API sees control gear only. Control devices (buttons, sensors as
  inputs) are not modelled here and must not be added to the site file.

- Scheduler actions are built only by `schedule_action()`: the gateway accepts
  `data: {switchable: …}` silently and never fires it; it must be
  `data: {features: {…}}`. The OpenAPI spec types `data` as a free dict, so
  generated models cannot catch this.
- `api_models.py` is generated; knowledge the spec lacks lives in `client.py`
  helpers and, later, the intent compiler, never in the generated file.
- Readdressing with another tool leaves the gateway with stale records. REST
  cannot detect that; `site check` does it over the bus by serial. `bus.py` is the only module that talks
  to the WebSocket and it sends queries and DTR writes only. The recovery is documented in `docs/site-file.md`.
- Circadians and status queries are out of scope: never written, never compared.
- The web UI owns the site file on its machine: Devices/Schedules tabs write the file
  (`site.save`, atomic) and only Apply touches the gateway's configuration. Control
  goes to the gateway live. No gateway id crosses the API: addresses and names only.
- Web routes reuse the CLI's paths: `lookup.*` for names, `plan.build` for plan/apply,
  `ScheduleSpec` as the request body. Never a second implementation of either.
