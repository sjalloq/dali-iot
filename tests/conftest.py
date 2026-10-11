from __future__ import annotations

import json
from typing import Any

import pytest
import requests

from dali_iot.client import Client


class FakeSession:
    """Records requests; answers from a {(method, path): body} table."""

    def __init__(self, answers: dict[tuple[str, str], Any] | None = None) -> None:
        self.calls: list[tuple[str, str, Any, dict | None]] = []
        self.answers = answers or {}

    def request(self, method, url, json=None, params=None, timeout=None):
        path = url.split("http://gw", 1)[1]
        self.calls.append((method, path, json, params))
        r = requests.Response()
        r.status_code = 200
        body = self.answers.get((method, path))
        r._content = b"" if body is None else globals()["json"].dumps(body).encode()
        return r


@pytest.fixture
def fake() -> FakeSession:
    return FakeSession()


@pytest.fixture
def client(fake: FakeSession) -> Client:
    return Client("http://gw", session=fake)  # type: ignore[arg-type]


_ = json  # keep the import for FakeSession
