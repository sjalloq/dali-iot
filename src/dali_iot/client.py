"""Thin REST client for the DALI-2 IoT gateway.

One ``requests.Session``, one ``request`` method, and resource helpers that
know the gateway's naming quirks (``/automations/scheduler`` creates, but
``/automations/schedules`` lists under a ``schedulers`` key, and so on).
Every exchange can be traced to a callback for ``--trace``.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable
from typing import Any

import requests

Trace = Callable[[str, str, Any, int, Any], None]
"""``(method, url, request_body, status, response_body)``"""

# kind -> (singular path for create/get/update/delete/start/stop, list path, list key)
AUTOMATIONS: dict[str, tuple[str, str, str]] = {
    "schedule": ("/automations/scheduler", "/automations/schedules", "schedulers"),
    "sequence": ("/automations/sequence", "/automations/sequences", "sequences"),
    "trigger": ("/automations/triggerAction", "/automations/triggerActions", "triggerActions"),
    "circadian": ("/automations/circadian", "/automations/circadians", "circadians"),
}


@dataclasses.dataclass
class Client:
    base_url: str
    timeout: float = 5.0
    trace: Trace | None = None
    session: requests.Session = dataclasses.field(default_factory=requests.Session)

    # --- core ---
    def request(self, method: str, path: str, json: Any = None, params: dict | None = None) -> Any:
        url = f"{self.base_url}/{path.lstrip('/')}"
        r = self.session.request(method, url, json=json, params=params, timeout=self.timeout)
        body: Any = None
        if r.content:
            try:
                body = r.json()
            except ValueError:
                body = r.text
        if self.trace:
            self.trace(method, url, json, r.status_code, body)
        r.raise_for_status()
        return body

    def get(self, path: str, **params: Any) -> Any:
        return self.request("GET", path, params=params or None)

    def post(self, path: str, json: Any = None, **params: Any) -> Any:
        return self.request("POST", path, json=json, params=params or None)

    def put(self, path: str, json: Any = None) -> Any:
        return self.request("PUT", path, json=json)

    def delete(self, path: str) -> Any:
        return self.request("DELETE", path)

    # --- gateway ---
    def info(self) -> dict:
        return self.get("/info")

    # --- devices, groups, zones ---
    def devices(self) -> list[dict]:
        return self.get("/devices").get("devices", [])

    def device(self, device_id: int) -> dict:
        return self.get(f"/device/{device_id}")

    def zones(self) -> list[dict]:
        return self.get("/zones").get("zones", [])

    def zone(self, zone_id: int) -> dict:
        return self.get(f"/zone/{zone_id}")

    def sensors(self) -> Any:
        return self.get("/sensors")

    def control_device(self, device_id: int, features: dict) -> None:
        self.post(f"/device/{device_id}/control", json=features)

    def control_group(self, group_id: int, features: dict, line: int | None = None) -> None:
        self.post(
            f"/group/{group_id}/control", json=features, **({"_line": line} if line is not None else {})
        )

    def control_zone(self, zone_id: int, features: dict) -> None:
        self.post(f"/zone/{zone_id}/control", json=features)

    def control_broadcast(self, features: dict, line: int | None = None) -> None:
        self.post("/broadcast/control", json=features, **({"_line": line} if line is not None else {}))

    # --- automations, uniformly ---
    def automations(self, kind: str) -> list[dict]:
        _, list_path, key = AUTOMATIONS[kind]
        data = self.get(list_path)
        return data.get(key, []) if isinstance(data, dict) else data

    def automation(self, kind: str, item_id: int) -> dict:
        return self.get(f"{AUTOMATIONS[kind][0]}/{item_id}")

    def create_automation(self, kind: str, model: dict) -> dict:
        return self.post(AUTOMATIONS[kind][0], json=model) or {}

    def update_automation(self, kind: str, item_id: int, model: dict) -> dict:
        return self.put(f"{AUTOMATIONS[kind][0]}/{item_id}", json=model) or {}

    def delete_automation(self, kind: str, item_id: int) -> None:
        self.delete(f"{AUTOMATIONS[kind][0]}/{item_id}")

    def start_automation(self, kind: str, item_id: int) -> None:
        self.post(f"{AUTOMATIONS[kind][0]}/{item_id}/start")

    def stop_automation(self, kind: str, item_id: int) -> None:
        self.post(f"{AUTOMATIONS[kind][0]}/{item_id}/stop")


# --- payload helpers: the feature-dict shapes the gateway expects ---


def off_features(fade: float = 0.0) -> dict:
    """OFF for relays and dimmers alike."""
    if fade > 0:
        return {"switchable": False, "dimmableWithFade": {"dimValue": 0, "fadeTime": fade}}
    return {"switchable": False, "dimmable": 0}


def on_features(level: int = 100, fade: float = 0.0) -> dict:
    """ON for relays and dimmers alike."""
    if fade > 0:
        return {"switchable": True, "dimmableWithFade": {"dimValue": level, "fadeTime": fade}}
    return {"switchable": True, "dimmable": level}


def schedule_action(features: dict) -> dict:
    """The one shape a scheduler action accepts.

    The gateway silently accepts ``{"type": "features", "data": {"switchable": ...}}``
    and never fires it. The features must sit under ``data.features``
    (Lunatone API manual 4.2.1). The OpenAPI spec types ``data`` as a free dict,
    so generated models cannot catch this; this helper is the one place that knows.
    """
    return {"type": "features", "data": {"features": features}}
