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
- **Scope (v1):** REST client; `dump`; scriptable verbs (all-off, on, off, recall);
  intent model + compiler to gateway objects; YAML config with `plan`/`apply`.
  Then a small web UI (phone-usable, runs on Proxmox) over the same intent model.
- **Non-goals:** the DALI bus plane (raw frames, bus monitor, control device
  programming). Mirroring every REST endpoint as a command.
- **Constraints:** Python ≥3.13, uv, pydantic v2, click, requests. One gateway
  (firmware 1.12.1 at time of writing; HA integration needs ≥1.14.1).
- **Done when:** the house's automations live in YAML in git, `apply` reproduces
  them on a reset gateway, and the web UI can switch zones and edit intents.

## Layout

- `src/dali_iot/client.py` — REST client: `Client.request` + resource helpers;
  payload helpers (`off_features`, `on_features`, `schedule_action`)
- `src/dali_iot/discover.py` — LAN scan on real up interfaces: UDP `discovery` to 5555; broadcast first, confirmed unicast sweep as fallback
- `src/dali_iot/config.py` — gateway URL: `--url` > `~/.config/dali-iot/config.toml`
- `src/dali_iot/cli.py` — `dali-iot` click CLI
- `src/dali_iot/api_models.py` — GENERATED (`make models`) from a downloaded spec; never edit.
  Its header names the spec file, and so the firmware version, it came from
- `spec/` — git-ignored; `dali-iot gateway spec` downloads `openapi-<firmware>.json` here
- `tests/` — pytest; `conftest.py` has a fake session, no gateway needed
- `docs/` — Sphinx (MyST, furo); `docs/gateway-api.md` collects API gotchas

## Commands

```
source sourceme                # uv sync --all-groups, activate
uv run pytest -q
uv run ruff check src tests && uv run ruff format --check src tests
make docs                      # Sphinx -> docs/build/html, warnings are errors
dali-iot gateway spec          # download the gateway's OpenAPI spec into spec/
make models                    # regenerate api_models.py from the newest spec/openapi-*.json
dali-iot gateway scan [--yes] [--save]   # find gateways on the LAN
dali-iot gateway set-url http://<gw>
dali-iot [--trace] dump | all-off | on|off --device N|--zone N|--group N | recall N --zone N
```

## Rules

- Tests and lint pass before finishing.
- Official docs live in `docs/`. Never in the vault.
- `make docs` is the publishing contract: HTML into `docs/build/html/`,
  warnings as errors, installing only what the docs need. The docs server
  runs exactly that via `.github/workflows/docs.yml`, which is identical in
  every repo — never edit it; the flow is defined in `pve`. Procedure for
  publishing a new repo: pve docs, *vms/docs → Adding a repo*.
- Never commit a secret, a gateway dump, or the house's device map
  (`dump/` and `*.local.yaml` are ignored).
- Commit messages short and to the point; no co-auth attribution.
- Every gateway quirk learned goes into `docs/gateway-api.md` and into code
  in exactly one place.

## Invariants

- Scheduler actions are built only by `schedule_action()`: the gateway accepts
  `data: {switchable: …}` silently and never fires it; it must be
  `data: {features: {…}}`. The OpenAPI spec types `data` as a free dict, so
  generated models cannot catch this.
- `api_models.py` is generated; knowledge the spec lacks lives in `client.py`
  helpers and, later, the intent compiler, never in the generated file.
