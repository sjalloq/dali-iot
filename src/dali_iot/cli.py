"""``dali-iot``: a few scriptable verbs and a full dump of the gateway."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import click

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


@click.group()
@click.option("--url", help="Gateway base URL, e.g. http://10.0.0.239 (else from config)")
@click.option("--trace", is_flag=True, help="Log every request and response to stderr")
@click.option("--timeout", default=5.0, show_default=True)
@click.pass_context
def main(ctx: click.Context, url: str | None, trace: bool, timeout: float) -> None:
    ctx.ensure_object(dict)
    ctx.obj["url"] = url
    ctx.obj["trace"] = trace
    ctx.obj["timeout"] = timeout


def _client(ctx: click.Context) -> Client:
    try:
        url, _ = config.resolve_url(ctx.obj["url"])
    except config.NoGatewayError as e:
        raise click.ClickException(str(e)) from None
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
    """The site file: your names for devices and zones."""


@site.command("init")
@click.option("--path", type=click.Path(path_type=Path), default=sitefile.DEFAULT_PATH, show_default=True)
@click.option("--force", is_flag=True, help="Overwrite an existing file")
@click.pass_context
def site_init(ctx: click.Context, path: Path, force: bool) -> None:
    """Write a starting site file from what the gateway holds now."""
    if path.exists() and not force:
        raise click.ClickException(f"{path} exists; pass --force to overwrite")
    c = _client(ctx)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(sitefile.from_gateway(c.devices(), c.zones()))
    click.echo(f"wrote {path}; edit the names, then: dali-iot plan")


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
@click.option("--prune", is_flag=True, help="Also delete zones that are not in the site file")
@click.pass_context
def plan_cmd(ctx: click.Context, path: Path, prune: bool) -> None:
    """Show what apply would change on the gateway. Read-only."""
    _print_plan(planner.build(_load_site(path), _client(ctx), prune=prune))


@main.command("apply")
@click.option(
    "--site", "path", type=click.Path(path_type=Path), default=sitefile.DEFAULT_PATH, show_default=True
)
@click.option("--prune", is_flag=True, help="Also delete zones that are not in the site file")
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


# --- scriptable verbs ---


@main.command("all-off")
@click.option("--fade", default=0.0, help="Fade seconds for dimmers")
@click.option("--line", type=int, help="Restrict to one DALI line")
@click.pass_context
def all_off(ctx: click.Context, fade: float, line: int | None) -> None:
    """Broadcast OFF to every device."""
    _client(ctx).control_broadcast(off_features(fade), line=line)


def _target_option(f):
    f = click.option("--device", type=int, help="Device id")(f)
    f = click.option("--zone", type=int, help="Zone id")(f)
    f = click.option("--group", type=int, help="DALI group")(f)
    return f


def _control(
    ctx: click.Context, device: int | None, zone: int | None, group: int | None, feats: dict
) -> None:
    c = _client(ctx)
    if sum(x is not None for x in (device, zone, group)) != 1:
        raise click.UsageError("give exactly one of --device, --zone, --group")
    if device is not None:
        c.control_device(device, feats)
    elif zone is not None:
        c.control_zone(zone, feats)
    else:
        c.control_group(group, feats)  # type: ignore[arg-type]


@main.command()
@_target_option
@click.option("--level", default=100, show_default=True, help="Dim level 0-100")
@click.option("--fade", default=0.0)
@click.pass_context
def on(
    ctx: click.Context, device: int | None, zone: int | None, group: int | None, level: int, fade: float
) -> None:
    """Switch a device, zone or group on."""
    _control(ctx, device, zone, group, on_features(level, fade))


@main.command()
@_target_option
@click.option("--fade", default=0.0)
@click.pass_context
def off(ctx: click.Context, device: int | None, zone: int | None, group: int | None, fade: float) -> None:
    """Switch a device, zone or group off."""
    _control(ctx, device, zone, group, off_features(fade))


@main.command()
@_target_option
@click.argument("scene", type=int)
@click.option("--fade", default=0.0)
@click.pass_context
def recall(
    ctx: click.Context, device: int | None, zone: int | None, group: int | None, scene: int, fade: float
) -> None:
    """Recall a scene on a device, zone or group."""
    feats = {"sceneWithFade": {"scene": scene, "fadeTime": fade}} if fade > 0 else {"scene": scene}
    _control(ctx, device, zone, group, feats)


if __name__ == "__main__":
    sys.exit(main())
