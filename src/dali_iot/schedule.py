"""Schedule intents: the site file's ``schedules`` entries and the gateway's scheduler records.

A schedule says *when* (``at``), *what* (``switch``/``level``/``scene``/``features``) and
*to whom* (``devices``/``zones``/``groups``/``broadcast``), plus optional ``days``,
``months`` and ``enabled``. This module turns that into the scheduler body the gateway
takes, and a gateway record back into an intent, so ``site init`` round-trips.

Not modelled: ``activePeriod`` and ``activeDays`` (a date range or a day-of-month list).
They are left as the gateway has them and never written.
"""

from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .client import schedule_action

DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
_DAY_KEYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
MONTHS = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]
_MONTH_KEYS = [
    "january", "february", "march", "april", "may", "june",
    "july", "august", "september", "october", "november", "december",
]  # fmt: skip

_CLOCK = re.compile(r"^(\d{1,2}):(\d{2})(?::(\d{2}))?$")
_SUN = re.compile(r"^(sunrise|sunset)\s*(?:([+-])\s*(\d{1,2}):(\d{2}))?$")


def parse_at(at: Any) -> tuple[str, int, int, int]:
    """``at`` -> (recallMode, hour, minute, second)."""
    if isinstance(at, int):
        # ValueError so pydantic reports it as a validation error, not a crash
        raise ValueError(f"at: {at} is a number; quote the time, e.g. '22:00'")  # noqa: TRY004
    s = str(at).strip()
    m = _CLOCK.match(s)
    if m:
        h, mi, se = int(m[1]), int(m[2]), int(m[3] or 0)
        if h > 23 or mi > 59 or se > 59:
            raise ValueError(f"at: {s!r} is not a valid time of day")
        return "timeOfDay", h, mi, se
    m = _SUN.match(s)
    if m:
        event = m[1].capitalize()
        if m[2] is None:
            return f"after{event}", 0, 0, 0
        h, mi = int(m[3]), int(m[4])
        if mi > 59:
            raise ValueError(f"at: {s!r} offset minutes must be below 60")
        return ("before" if m[2] == "-" else "after") + event, h, mi, 0
    raise ValueError(f"at: {s!r}; use 'HH:MM', 'sunrise', 'sunset', 'sunset-0:30' or 'sunrise+1:00'")


def format_at(mode: str, hour: int, minute: int, second: int) -> str:
    if mode == "timeOfDay":
        return f"{hour:02d}:{minute:02d}" + (f":{second:02d}" if second else "")
    sign = "-" if mode.startswith("before") else "+"
    event = mode.removeprefix("before").removeprefix("after").lower()
    if hour == 0 and minute == 0:
        return event
    return f"{event}{sign}{hour}:{minute:02d}"


class ScheduleSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1)
    at: str
    devices: list[str] = Field(default_factory=list)
    zones: list[str] = Field(default_factory=list)
    groups: list[int] = Field(default_factory=list)
    broadcast: list[int] = Field(default_factory=list)  # lines
    switch: bool | None = None
    level: int | None = Field(None, ge=0, le=100)
    fade: float | None = Field(None, ge=0)
    scene: int | None = Field(None, ge=0, le=15)
    features: dict[str, Any] | None = None  # raw gateway features, for anything else
    days: list[str] | None = None  # mon..sun; None = every day
    months: list[str] | None = None  # jan..dec; None = every month
    enabled: bool = True

    @model_validator(mode="before")
    @classmethod
    def _at_is_text(cls, data: Any) -> Any:
        if isinstance(data, dict) and isinstance(data.get("at"), int):
            parse_at(data["at"])  # raises with the quoting hint
        return data

    @model_validator(mode="after")
    def _check(self) -> ScheduleSpec:
        parse_at(self.at)
        actions = [k for k in ("switch", "level", "scene", "features") if getattr(self, k) is not None]
        if len(actions) != 1:
            raise ValueError(f"schedule {self.name!r}: give exactly one of switch, level, scene, features")
        if self.fade is not None and self.level is None:
            raise ValueError(f"schedule {self.name!r}: fade needs level")
        if not (self.devices or self.zones or self.groups or self.broadcast):
            raise ValueError(f"schedule {self.name!r} has no targets")
        for d in self.days or []:
            if d not in DAYS:
                raise ValueError(f"schedule {self.name!r}: unknown day {d!r} (use {', '.join(DAYS)})")
        for m in self.months or []:
            if m not in MONTHS:
                raise ValueError(f"schedule {self.name!r}: unknown month {m!r} (use {', '.join(MONTHS)})")
        return self

    def action_features(self) -> dict[str, Any]:
        if self.switch is not None:
            return {"switchable": self.switch}
        if self.level is not None:
            if self.fade:
                return {"dimmableWithFade": {"dimValue": self.level, "fadeTime": self.fade}}
            return {"dimmable": self.level}
        if self.scene is not None:
            return {"scene": self.scene}
        assert self.features is not None
        return self.features

    def body(self, targets: list[dict]) -> dict[str, Any]:
        """The full scheduler model for POST or PUT, given resolved targets."""
        mode, h, m, s = parse_at(self.at)
        days = set(self.days if self.days is not None else DAYS)
        months = set(self.months if self.months is not None else MONTHS)
        return {
            "name": self.name,
            "enabled": self.enabled,
            "targets": targets,
            "recallMode": mode,
            "recallTime": {"hour": h, "minute": m, "second": s},
            "activeWeekdays": {k: d in days for d, k in zip(DAYS, _DAY_KEYS, strict=True)},
            "activeMonths": {k: mo in months for mo, k in zip(MONTHS, _MONTH_KEYS, strict=True)},
            "action": schedule_action(self.action_features()),
        }


def canonical(rec: dict) -> dict[str, Any]:
    """What matters of a scheduler record (ours or the gateway's), for comparing."""
    t = rec.get("recallTime") or {}
    wd = rec.get("activeWeekdays") or {}
    mo = rec.get("activeMonths") or {}
    return {
        "name": rec.get("name"),
        "enabled": rec.get("enabled", True),
        "targets": sorted((str(x.get("type")), int(x.get("id") or 0)) for x in rec.get("targets") or []),
        "mode": rec.get("recallMode"),
        "time": (int(t.get("hour") or 0), int(t.get("minute") or 0), int(t.get("second") or 0)),
        "days": tuple(wd.get(k, True) is not False for k in _DAY_KEYS),
        "months": tuple(mo.get(k, True) is not False for k in _MONTH_KEYS),
        "features": ((rec.get("action") or {}).get("data") or {}).get("features"),
    }


def from_gateway(rec: dict, device_names: dict[int, str], zone_names: dict[int, str]) -> dict[str, Any]:
    """A gateway scheduler record as a site-file entry (plain dict, in file order)."""
    c = canonical(rec)
    out: dict[str, Any] = {"name": rec.get("name") or f"schedule {rec.get('id')}"}
    out["at"] = format_at(c["mode"], *c["time"])
    for kind, tid in c["targets"]:
        if kind == "device" and tid in device_names:
            out.setdefault("devices", []).append(device_names[tid])
        elif kind == "zone" and tid in zone_names:
            out.setdefault("zones", []).append(zone_names[tid])
        elif kind == "group":
            out.setdefault("groups", []).append(tid)
        elif kind == "broadcast":
            out.setdefault("broadcast", []).append(tid)
    f = c["features"] or {}
    if set(f) == {"switchable"}:
        out["switch"] = bool(f["switchable"])
    elif set(f) == {"dimmable"}:
        out["level"] = int(f["dimmable"])
    elif set(f) == {"dimmableWithFade"} and set(f["dimmableWithFade"]) <= {"dimValue", "fadeTime"}:
        out["level"] = int(f["dimmableWithFade"].get("dimValue", 0))
        out["fade"] = f["dimmableWithFade"].get("fadeTime", 0)
    elif set(f) == {"scene"}:
        out["scene"] = int(f["scene"])
    else:
        out["features"] = f
    if not all(c["days"]):
        out["days"] = [d for d, on in zip(DAYS, c["days"], strict=True) if on]
    if not all(c["months"]):
        out["months"] = [m for m, on in zip(MONTHS, c["months"], strict=True) if on]
    if not c["enabled"]:
        out["enabled"] = False
    return out
