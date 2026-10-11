"""``dali-iot``: a few scriptable verbs and a full dump of the gateway."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import click

from . import bus as dalibus
from . import config, discover
from . import plan as planner
from . import site as sitefile
from .client import AUTOMATIONS, Client, off_features, on_features


def _trace(method: str, url: str, req: Any, status: int, resp: Any) -> None:
    click.echo(f"> {method} {url}", err=True)
    if req is not None:
        click.echo("> " + json.dumps(req), err=True)
    click.echo(f"< {status}", err=True)
    if resp is not None:
        click.echo("< " + json.dumps(resp)[:2000], err=True)


@click.group(context_settings={"help_option_names": ["-h", "--help"]})
@click.option("--url", help="Gateway base URL, e.g. http://10.0.0.239 (else from config)")
@click.option("--trace", is_flag=True, help="Log every request and response to stderr")
@click.option("--timeout", default=5.0, show_default=True)
@click.pass_context
def main(ctx: click.Context, url: str | None, trace: bool, timeout: float) -> None:
    ctx.ensure_object(dict)
    ctx.obj["url"] = url
    ctx.obj["trace"] = trace
    ctx.obj["timeout"] = timeout


def _url(ctx: click.Context) -> tuple[str, str]:
    try:
        return config.resolve_url(ctx.obj["url"])
    except config.NoGatewayError as e:
        raise click.ClickException(str(e)) from None


def _client(ctx: click.Context) -> Client:
    url, _ = _url(ctx)
    return Client(url, timeout=ctx.obj["timeout"], trace=_trace if ctx.obj["trace"] else None)


# --- gateway ---


@main.group()
def gateway() -> None:
    """Which gateway to talk to."""


@gateway.command("set-url")
@click.argument("url")
def gateway_set_url(url: str) -> None:
    path = config.save_url(url.rstrip("/"))
    click.echo(f"saved {url} to {path}")


@gateway.command("get-url")
@click.pass_context
def gateway_get_url(ctx: click.Context) -> None:
    try:
        url, source = config.resolve_url(ctx.obj["url"])
    except config.NoGatewayError as e:
        raise click.ClickException(str(e)) from None
    click.echo(f"{url} ({source})")


@gateway.command("scan")
@click.option("--timeout", "scan_timeout", default=3.2, show_default=True, help="Seconds to listen")
@click.option(
    "--yes", "-y", is_flag=True, help="Sweep the LAN host by host without asking if broadcast is silent"
)
@click.option("--save", is_flag=True, help="Save the URL to config if exactly one gateway answers")
def gateway_scan(scan_timeout: float, yes: bool, save: bool) -> None:
    """Find gateways on the LAN (UDP broadcast on port 5555)."""

    def confirm(question: str) -> bool:
        if yes:
            return True
        if not sys.stdin.isatty():
            click.echo("not a terminal; pass --yes to sweep the LAN host by host", err=True)
            return False
        return click.confirm(question, err=True)

    found = discover.discover(
        timeout=scan_timeout, progress=lambda m: click.echo(m, err=True), confirm=confirm
    )
    if not found:
        raise click.ClickException("no gateway answered; use gateway set-url if you know its address")
    for f in found:
        click.echo(f"{f.ip:<15} {f.type:<14} {f.name}")
    if save:
        if len(found) != 1:
            raise click.ClickException("more than one gateway answered; use gateway set-url")
        click.echo(f"saved {found[0].url} to {config.save_url(found[0].url)}")


@gateway.command("spec")
@click.option("--out", type=click.Path(path_type=Path), default="spec", show_default=True, help="Directory")
@click.pass_context
def gateway_spec(ctx: click.Context, out: Path) -> None:
    """Download the gateway's OpenAPI spec, named after its firmware version."""
    c = _client(ctx)
    spec = c.get("/openapi.json")
    version = str(spec.get("info", {}).get("version", "unknown")).replace("/", "-")
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"openapi-{version}.json"
    path.write_text(json.dumps(spec, indent=2, sort_keys=True) + "\n")
    click.echo(f"wrote {path}")


@gateway.command("info")
@click.pass_context
def gateway_info(ctx: click.Context) -> None:
    click.echo(json.dumps(_client(ctx).info(), indent=2))


def _rescan(c: Client) -> dict:
    """Run a no-addressing scan with a progress line on stderr; returns the result."""
    last = [-1.0]

    def progress(st: dict) -> None:
        pct = st.get("progress") or 0.0
        if pct != last[0]:
            click.echo(f"\rscanning the bus... {pct:3.0f}%", nl=False, err=True)
            last[0] = pct

    try:
        st = c.rescan(progress)
    except RuntimeError as e:
        raise click.ClickException(str(e)) from None
    click.echo(f"\rscanning the bus... {st.get('status')}, {st.get('found')} device(s)", err=True)
    return st


@gateway.command("rescan")
@click.pass_context
def gateway_rescan(ctx: click.Context) -> None:
    """Reload the gateway's device list from the bus. Changes no address."""
    _rescan(_client(ctx))


# --- dump ---


@main.command()
@click.option("--out", type=click.Path(path_type=Path), default="dump", show_default=True)
@click.pass_context
def dump(ctx: click.Context, out: Path) -> None:
    """Write everything the gateway holds to a directory of JSON files."""
    c = _client(ctx)
    out.mkdir(parents=True, exist_ok=True)
    files: dict[str, Any] = {
        "info.json": c.info(),
        "devices.json": c.devices(),
        "zones.json": c.zones(),
        "sensors.json": c.sensors(),
    }
    for kind in AUTOMATIONS:
        files[f"{kind}s.json"] = c.automations(kind)
    for name, data in files.items():
        (out / name).write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
        click.echo(f"wrote {out / name}")


# --- site file: names, zones; plan and apply ---


@main.group()
def site() -> None:
    """The site file: your names for devices and zones, and your schedules."""


@site.command("init")
@click.option("--path", type=click.Path(path_type=Path), default=sitefile.DEFAULT_PATH, show_default=True)
@click.option("--force", is_flag=True, help="Overwrite an existing file")
@click.option("--identify", is_flag=True, help="Also read each device's serial and product over the bus")
@click.pass_context
def site_init(ctx: click.Context, path: Path, force: bool, identify: bool) -> None:
    """Write a starting site file from what the gateway holds now."""
    if path.exists() and not force:
        raise click.ClickException(f"{path} exists; pass --force to overwrite")
    c = _client(ctx)
    devices = c.devices()
    identities = None
    if identify:
        identities = dalibus.identities_by_address(_identify(ctx, devices))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(sitefile.from_gateway(devices, c.zones(), c.automations("schedule"), identities))
    click.echo(f"wrote {path}; edit the names, then: dali-iot plan")


def _identify(ctx: click.Context, devices: list[dict]) -> list[dalibus.Identity]:
    """Read bank 0 of every gateway device over the WebSocket, with progress on stderr."""
    addrs = sorted((int(d.get("line", 0)), int(d["address"])) for d in devices if "address" in d)
    url, _ = _url(ctx)
    try:
        sock = dalibus.connect(url, timeout=ctx.obj["timeout"])
    except OSError as e:
        raise click.ClickException(f"cannot open {dalibus.ws_url(url)}: {e}") from None
    out: list[dalibus.Identity] = []
    with dalibus.Bus(sock, timeout=ctx.obj["timeout"]) as bus:
        for n, ident in enumerate(bus.identify_all(addrs), 1):
            click.echo(f"\ridentifying... {n}/{len(addrs)}", nl=False, err=True)
            out.append(ident)
    click.echo("", err=True)
    return out


@main.group()
def bus() -> None:
    """Raw DALI queries over the gateway's WebSocket (read-only)."""


@bus.command("identify")
@click.pass_context
def bus_identify(ctx: click.Context) -> None:
    """Serial and product of every device, read from memory bank 0."""
    for i in _identify(ctx, _client(ctx).devices()):
        if not i.bank0:
            click.echo(f"line {i.line} A{i.address:<3} no answer")
            continue
        unit = f" unit {i.unit}/{i.units}" if i.unit is not None else ""
        click.echo(
            f"line {i.line} A{i.address:<3} serial {i.serial!s:<12}{unit:<10} fw {i.firmware!s:<6} "
            f"{i.article or ''}{'' if i.dali2 else '  (pre-DALI-2 bank layout)'}"
        )


def _load_site(path: Path) -> sitefile.Site:
    try:
        return sitefile.load(path)
    except FileNotFoundError:
        raise click.ClickException(f"{path} not found; create one with: dali-iot site init") from None
    except ValueError as e:
        raise click.ClickException(f"{path}: {e}") from None


def _print_plan(changes: list[planner.Change]) -> int:
    real = [c for c in changes if c.apply]
    errors = [c for c in changes if c.op == "error"]
    for c in changes:
        click.echo(str(c))
    summary = f"{len(real)} change(s)" if real else "no changes"
    if errors:
        summary += f", {len(errors)} error(s)"
    click.echo(summary, err=True)
    return len(real)


@main.command("plan")
@click.option(
    "--site", "path", type=click.Path(path_type=Path), default=sitefile.DEFAULT_PATH, show_default=True
)
@click.option(
    "--prune",
    is_flag=True,
    help="Also delete device records, zones and schedules that are not in the site file",
)
@click.pass_context
def plan_cmd(ctx: click.Context, path: Path, prune: bool) -> None:
    """Show what apply would change on the gateway. Read-only."""
    _print_plan(planner.build(_load_site(path), _client(ctx), prune=prune))


@main.command("apply")
@click.option(
    "--site", "path", type=click.Path(path_type=Path), default=sitefile.DEFAULT_PATH, show_default=True
)
@click.option(
    "--prune",
    is_flag=True,
    help="Also delete device records, zones and schedules that are not in the site file",
)
@click.option("--yes", "-y", is_flag=True, help="Apply without asking")
@click.pass_context
def apply_cmd(ctx: click.Context, path: Path, prune: bool, yes: bool) -> None:
    """Make the gateway match the site file."""
    changes = planner.build(_load_site(path), _client(ctx), prune=prune)
    if not _print_plan(changes):
        return
    if not yes and not click.confirm("apply?", err=True):
        raise click.Abort()
    for c in changes:
        if c.apply:
            c.apply()
            click.echo(f"applied {c.op} {c.what}", err=True)


# --- control, by noun: device ADDRESS | zone NAME | group N | broadcast ---


def _device_at(c: Client, address: str) -> dict:
    """The gateway record for an address reference like ``7`` or ``1/7``."""
    try:
        line, addr = sitefile.parse_ref(int(address) if address.isdigit() else address)
    except ValueError as e:
        raise click.UsageError(str(e)) from None
    for d in c.devices():
        if int(d.get("line", 0)) == line and d.get("address") == addr:
            return d
    raise click.ClickException(f"nothing at line {line} A{addr} on the gateway")


def _zone_named(c: Client, zone: str) -> dict:
    zones = c.zones()
    for z in zones:
        if z.get("name") == zone:
            return z
    raise click.ClickException(
        f"no zone named {zone!r} (have: {', '.join(str(z.get('name')) for z in zones)})"
    )


def _fade_option(f):
    return click.option("--fade", default=0.0, help="Fade seconds for dimmers")(f)


def _level_option(f):
    return click.option("--level", default=100, show_default=True, help="Dim level 0-100")(f)


def _verbs(group: click.Group, target_help: str, send) -> None:
    """Add on/off/recall to a noun group. ``send(ctx, target, features)`` does the request."""

    @group.command("on")
    @click.argument("target", metavar=target_help)
    @_level_option
    @_fade_option
    @click.pass_context
    def _on(ctx: click.Context, target: str, level: int, fade: float) -> None:
        """Switch on."""
        send(ctx, target, on_features(level, fade))

    @group.command("off")
    @click.argument("target", metavar=target_help)
    @_fade_option
    @click.pass_context
    def _off(ctx: click.Context, target: str, fade: float) -> None:
        """Switch off."""
        send(ctx, target, off_features(fade))

    @group.command("recall")
    @click.argument("target", metavar=target_help)
    @click.argument("scene", type=int)
    @_fade_option
    @click.pass_context
    def _recall(ctx: click.Context, target: str, scene: int, fade: float) -> None:
        """Recall a scene (0-15)."""
        feats = {"sceneWithFade": {"scene": scene, "fadeTime": fade}} if fade > 0 else {"scene": scene}
        send(ctx, target, feats)


@main.group()
def device() -> None:
    """One device, by DALI address (7, or 1/7 for line 1)."""


_verbs(device, "ADDRESS", lambda ctx, t, f: (c := _client(ctx)).control_device(_device_at(c, t)["id"], f))


@device.command("identify")
@click.argument("address")
@click.option("--times", default=2, show_default=True, help="How many off/on cycles")
@click.option("--pause", default=0.7, show_default=True, help="Seconds between steps")
@click.pass_context
def device_identify(ctx: click.Context, address: str, times: int, pause: float) -> None:
    """Blink the light at ADDRESS so you can see which one it is.

    Switches it off and on a couple of times, then restores its previous state.
    """
    c = _client(ctx)
    d = _device_at(c, address)
    click.echo(
        f"blinking line {d.get('line', 0)} A{d['address']} {d.get('name')!r} "
        f"({sitefile.type_name(d.get('daliTypes') or [])})...",
        err=True,
    )
    c.blink_device(d["id"], times=times, pause=pause)
    click.echo("restored", err=True)


@main.group()
def zone() -> None:
    """A gateway zone, by name."""


_verbs(zone, "ZONE", lambda ctx, t, f: (c := _client(ctx)).control_zone(_zone_named(c, t)["id"], f))


@main.group()
def group() -> None:
    """A DALI group (0-15)."""


def _send_group(ctx: click.Context, target: str, feats: dict) -> None:
    if not target.isdigit() or not 0 <= int(target) <= 15:
        raise click.UsageError("group must be 0-15")
    _client(ctx).control_group(int(target), feats, line=ctx.obj.get("line"))


_verbs(group, "GROUP", _send_group)


@main.group()
@click.option("--line", type=int, help="Restrict to one DALI line")
@click.pass_context
def broadcast(ctx: click.Context, line: int | None) -> None:
    """Every device on the bus."""
    ctx.obj["line"] = line


@broadcast.command("on")
@_level_option
@_fade_option
@click.pass_context
def broadcast_on(ctx: click.Context, level: int, fade: float) -> None:
    """Switch everything on."""
    _client(ctx).control_broadcast(on_features(level, fade), line=ctx.obj.get("line"))


@broadcast.command("off")
@_fade_option
@click.pass_context
def broadcast_off(ctx: click.Context, fade: float) -> None:
    """Switch everything off."""
    _client(ctx).control_broadcast(off_features(fade), line=ctx.obj.get("line"))


@broadcast.command("recall")
@click.argument("scene", type=int)
@_fade_option
@click.pass_context
def broadcast_recall(ctx: click.Context, scene: int, fade: float) -> None:
    """Recall a scene everywhere."""
    feats = {"sceneWithFade": {"scene": scene, "fadeTime": fade}} if fade > 0 else {"scene": scene}
    _client(ctx).control_broadcast(feats, line=ctx.obj.get("line"))
