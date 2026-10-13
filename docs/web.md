# Web UI

A phone-sized page for the household to control lights and for you to edit
the site file without a terminal. It runs wherever the gateway is reachable,
typically a container on the home server, and needs no account: it is for the
LAN only. Nothing in it is protected, so do not expose the port beyond the LAN.

On a phone-sized screen the page shows only the Control view, with no tab
bar: the household gets lights, not configuration. Add `?full=1` to the URL
to get the full page on a small screen. On a wider screen there are four
tabs:

- **Control.** Zones and devices by the names in the site file, with on/off,
  a level slider for dimmers, scene buttons where a device has scenes, an
  *All off*, and run/stop for stored sequences. Commands go straight to the
  gateway; this tab never touches the site file.
- **Devices.** The site file's `lines` table beside what the gateway holds.
  Edit a name, type or groups; *blink* a lamp to see which one it is. Edits
  are written to the site file, not to the gateway.
- **Schedules.** The `schedules` entries: when, what, to whom, days,
  enabled. Same vocabulary as the file (`sunset-0:30`, `22:00`).
- **Apply.** The plan as `dali-iot plan` prints it, a *prune* checkbox, one
  button to apply, and the result.

The page is a thin client of a JSON API that exposes the same operations as
the CLI; `/api/docs` lists it. The site file is the configuration source of
truth: the page edits the file and runs plan/apply, it does not bypass it, and
it never shows a gateway id.

## Run it locally

The page is built with Node once; the server needs only Python.

```
make web                              # npm ci && npm run build into the package
uv sync --extra web
dali-iot serve --site site/site.yaml  # http://127.0.0.1:8000
```

`--host 0.0.0.0` opens it to the LAN, `--port` picks the port. The gateway
URL resolves as for every command: `--url`, then `DALI_IOT_URL`, then the
saved config.

For frontend work, `cd frontend && npm run dev` serves the Vue app with hot
reload and proxies `/api` to a `dali-iot serve` on port 8000.

## Run it in Docker

The image builds the page in a Node stage and ships only Python. Put the
gateway URL in `.env` and the site file under `data/`:

```
echo DALI_IOT_URL=http://10.0.0.239 > .env
mkdir -p data && cp site/site.yaml data/site.yaml
docker compose up -d --build
```

The page is on port 8000. `data/site.yaml` is the live site file on that
machine: the page writes it, and `dali-iot plan --site data/site.yaml` from
the host reads the same file. Back it up like any config.

## Why the site file, not the gateway

The Devices and Schedules tabs edit the file and leave the gateway alone until
you press *Apply*, for the same reason the CLI does: the file is what you can
read, diff, and put back on a reset gateway. The page owns the file on the
machine it runs on; edit it by hand there too if you like, the page reloads it
on every request.
