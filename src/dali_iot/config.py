"""Where the gateway lives: ``--url`` beats ``~/.config/dali-iot/config.toml``."""

from __future__ import annotations

import os
import tomllib
from pathlib import Path

CONFIG_DIR = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "dali-iot"
CONFIG_PATH = CONFIG_DIR / "config.toml"


class NoGatewayError(RuntimeError):
    """No gateway URL was given and none is configured."""


def load() -> dict:
    try:
        with CONFIG_PATH.open("rb") as f:
            return tomllib.load(f)
    except FileNotFoundError:
        return {}


def save_url(url: str) -> Path:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(f'[gateway]\nurl = "{url}"\n', encoding="utf-8")
    return CONFIG_PATH


def resolve_url(arg_url: str | None) -> tuple[str, str]:
    """Return ``(url, source)`` where source is ``arg`` or ``config``."""
    if arg_url:
        return arg_url.rstrip("/"), "arg"
    url = load().get("gateway", {}).get("url")
    if isinstance(url, str) and url:
        return url.rstrip("/"), "config"
    raise NoGatewayError(
        "No gateway URL. Pass --url or run: dali-iot gateway set-url http://<gateway-ip>\n"
        f"Config file: {CONFIG_PATH}"
    )
