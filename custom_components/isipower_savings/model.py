"""Pure calculation and append-only history. No Home Assistant dependency."""
from __future__ import annotations

from bisect import bisect_right
from datetime import datetime, time, timedelta, timezone
import json
import math
import os
from pathlib import Path
import re
from zoneinfo import ZoneInfo

EXPORT_MODES = ("none", "unpaid", "paid")
MONEY_KEYS = ("without_cost", "import_cost", "export_revenue", "net_cost", "consumption_savings", "benefit")


def stamp(value: str) -> float:
    result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("missing_timezone")
    return result.timestamp()


def finite(value, *, nonnegative: bool = False) -> float:
    if isinstance(value, bool):
        raise ValueError("invalid_number")
    result = float(value)
    if not math.isfinite(result) or (nonnegative and result < 0):
        raise ValueError("invalid_number")
    return result


def watts(value, unit: str | None) -> float:
    result = finite(value)
    if unit == "W":
        return result
    if unit == "kW":
        return result * 1000
    raise ValueError("invalid_power_unit")


def parse_windows(value: str) -> list[list[int]]:
    """Daily windows; overnight ranges wrap; 24:00 is accepted as an end."""
    if not isinstance(value, str):
        raise ValueError("invalid_windows")
    if not value.strip():
        return []
    windows = set()
    for part in value.split(","):
        match = re.fullmatch(r"\s*(\d{2}):(\d{2})\s*-\s*(\d{2}):(\d{2})\s*", part)
        if not match:
            raise ValueError("invalid_windows")
        sh, sm, eh, em = map(int, match.groups())
        if sh > 23 or sm > 59 or eh > 24 or em > 59 or (eh == 24 and em != 0):
            raise ValueError("invalid_windows")
        start, end = sh * 60 + sm, eh * 60 + em
        if start == end:
            raise ValueError("invalid_windows")
        if start < end:
            windows.add((start, end))
        else:
            windows.add((start, 1440))
            if end:
                windows.add((0, end))
    return [list(pair) for pair in sorted(windows)]


def build_plan(config: dict) -> dict:
    """Normalize the UI choices; super off-peak overrides off-peak."""
    plan = {"base_rate": finite(config["base_rate"], nonnegative=True), "bands": []}
    for name in ("off_peak", "super_off_peak"):
        if config.get(f"{name}_enabled", False):
            windows = parse_windows(config.get(f"{name}_windows", ""))
            if not windows:
                raise ValueError("invalid_windows")
            plan["bands"].append({"name": name,
                "rate": finite(config[f"{name}_rate"], nonnegative=True), "windows": windows})
    mode = config.get("export_mode", "none")
    if mode not in EXPORT_MODES:
        raise ValueError("invalid_export_mode")
    plan["export_mode"] = mode
    plan["export_rate"] = finite(config.get("export_rate", 0), nonnegative=True) if mode == "paid" else 0.
    return plan


def validate_plan(plan: dict) -> dict:
    """Validate stored plans too, rather than trusting editable history files."""
    result = {"base_rate": finite(plan["base_rate"], nonnegative=True), "bands": []}
    names = []
    for band in plan["bands"]:
        if band["name"] not in ("off_peak", "super_off_peak"):
            raise ValueError("invalid_band")
        names.append(band["name"])
        windows = []
        for start, end in band["windows"]:
            if not isinstance(start, int) or not isinstance(end, int) or not 0 <= start < end <= 1440:
                raise ValueError("invalid_windows")
            windows.append([start, end])
        if not windows:
            raise ValueError("invalid_windows")
        result["bands"].append({"name": band["name"], "rate": finite(band["rate"], nonnegative=True), "windows": windows})
    if len(set(names)) != len(names):
        raise ValueError("invalid_band")
    result["bands"].sort(key=lambda band: band["name"] == "super_off_peak")
    mode = plan["export_mode"]
    if mode not in EXPORT_MODES:
        raise ValueError("invalid_export_mode")
    result["export_mode"] = mode
    result["export_rate"] = finite(plan["export_rate"], nonnegative=True) if mode == "paid" else 0.
    return result


def rate_at(plan: dict, at: float, tz: ZoneInfo) -> float:
    local = datetime.fromtimestamp(at, tz)
    minute = local.hour * 60 + local.minute + local.second / 60
    rate = plan["base_rate"]
    for band in plan["bands"]:
        if any(start <= minute < end for start, end in band["windows"]):
            rate = band["rate"]
    return rate


def positive_area(a: float, b: float, seconds: float) -> float:
    """Integral of the positive part of linearly interpolated W, in kWh."""
    if min(a, b) >= 0:
        return (a + b) * .5 * seconds / 3_600_000
    if max(a, b) <= 0:
        return 0.
    fraction = abs(a) / (abs(a) + abs(b))
    height_times_fraction = a * fraction if a > 0 else b * (1 - fraction)
    return height_times_fraction * .5 * seconds / 3_600_000


def local_boundaries(day, minute: int, tz: ZoneInfo) -> set[float]:
    """Return both occurrences of an ambiguous wall time, none if nonexistent."""
    naive = datetime.combine(day, time()) + timedelta(minutes=minute)
    found = set()
    for fold in (0, 1):
        aware = naive.replace(tzinfo=tz, fold=fold)
        at = aware.timestamp()
        if datetime.fromtimestamp(at, tz).replace(tzinfo=None) == naive:
            found.add(at)
    return found


def transition_between(lo: float, hi: float, tz: ZoneInfo) -> float | None:
    """Find the UTC-offset change inside a short measurement interval."""
    before = datetime.fromtimestamp(lo, tz).utcoffset()
    if before == datetime.fromtimestamp(hi, tz).utcoffset():
        return None
    a, b = int(lo), math.ceil(hi)
    while b - a > 1:
        middle = (a + b) // 2
        if datetime.fromtimestamp(middle, tz).utcoffset() == before:
            a = middle
        else:
            b = middle
    return float(b)


class Engine:
    def __init__(self):
        self.start: float | None = None
        self.tz = ZoneInfo("UTC")
        self.currency = "EUR"
        self.max_gap = 900
        self.plans: list[tuple[float, dict]] = []
        self.last: dict | None = None
        self.source_key: str | None = None
        self.rows: dict[str, dict] = {}

    def plan_at(self, at: float) -> dict:
        index = bisect_right([item[0] for item in self.plans], at) - 1
        if index < 0:
            raise ValueError("missing_tariff")
        return self.plans[index][1]

    def apply(self, event: dict) -> set[str]:
        kind = event["type"]
        if kind == "start":
            if self.start is not None:
                raise ValueError("duplicate_start")
            self.start = stamp(event["at"])
            self.tz = ZoneInfo(event["timezone"])
            self.currency = event["currency"]
            self.max_gap = int(event["max_gap_seconds"])
            if self.max_gap < 1 or not re.fullmatch(r"[A-Z]{3}", self.currency):
                raise ValueError("invalid_configuration")
            self.plans.append((self.start, validate_plan(event["plan"])))
            return set()
        if self.start is None:
            raise ValueError("missing_start")
        if kind == "tariff":
            at = stamp(event["at"])
            if at < self.start or at < self.plans[-1][0]:
                raise ValueError("tariff_before_start")
            self.plans.append((at, validate_plan(event["plan"])))
            return set()
        if kind == "sources":
            self.source_key = event["key"]
            self.max_gap = int(event["max_gap_seconds"])
            if self.max_gap < 1:
                raise ValueError("invalid_configuration")
            self.last = None  # Do not interpolate between two different perimeters.
            return set()
        if kind != "sample":
            raise ValueError("invalid_record_type")
        current = dict(event, t=stamp(event["measured_at"]))
        if not event.get("error"):
            current["consumption_w"] = finite(event["consumption_w"], nonnegative=True)
            current["grid_w"] = finite(event["grid_w"])
            if event.get("export_w") is not None:
                current["export_w"] = finite(event["export_w"], nonnegative=True)
                finite(current["grid_w"], nonnegative=True)
        if self.last and current["t"] <= self.last["t"]:
            return set()
        previous, self.last = self.last, current
        if previous is None:
            return set()
        a, b = previous["t"], current["t"]
        if previous.get("error") or current.get("error") or b - a > self.max_gap:
            return set()
        if (previous.get("export_w") is None) != (current.get("export_w") is None):
            return set()
        lo, hi = max(a, self.start), b
        if hi <= lo:
            return set()
        boundaries = {lo, hi}
        applicable = [self.plan_at(lo)] + [plan for at, plan in self.plans if lo < at < hi]
        edges = {0, 1440}
        for plan in applicable:
            for band in plan["bands"]:
                for start, end in band["windows"]:
                    edges.update((start, end))
        day = datetime.fromtimestamp(lo, self.tz).date()
        last_day = datetime.fromtimestamp(hi, self.tz).date()
        while day <= last_day:
            for minute in edges:
                boundaries.update(at for at in local_boundaries(day, minute, self.tz) if lo < at < hi)
            day += timedelta(days=1)
        transition = transition_between(lo, hi, self.tz)
        if transition and lo < transition < hi:
            boundaries.add(transition)
        boundaries.update(at for at, _ in self.plans if lo < at < hi)
        ordered = sorted(boundaries)
        dirty = set()
        for left, right in zip(ordered, ordered[1:]):
            middle = (left + right) / 2
            plan = self.plan_at(middle)
            rate = rate_at(plan, middle, self.tz)
            def power(key, at):
                return previous[key] + (current[key] - previous[key]) * (at - a) / (b - a)
            seconds = right - left
            home = (power("consumption_w", left) + power("consumption_w", right)) * .5 * seconds / 3_600_000
            imported = positive_area(power("grid_w", left), power("grid_w", right), seconds)
            if current.get("export_w") is None:
                exported = positive_area(-power("grid_w", left), -power("grid_w", right), seconds)
            else:
                exported = positive_area(power("export_w", left), power("export_w", right), seconds)
            key = datetime.fromtimestamp(middle, self.tz).date().isoformat()
            row = self.rows.setdefault(key, {"day": key, **dict.fromkeys(MONEY_KEYS, 0.),
                "consumption_kwh": 0., "import_kwh": 0., "export_kwh": 0.,
                "seconds": 0., "begin": left, "end": right})
            row["without_cost"] += home * rate
            row["import_cost"] += imported * rate
            row["export_revenue"] += exported * plan["export_rate"] if plan["export_mode"] == "paid" else 0.
            row["net_cost"] = row["import_cost"] - row["export_revenue"]
            row["consumption_savings"] = row["without_cost"] - row["import_cost"]
            row["benefit"] = row["consumption_savings"] + row["export_revenue"]
            row["consumption_kwh"] += home
            row["import_kwh"] += imported
            row["export_kwh"] += exported
            row["seconds"] += seconds
            row["begin"], row["end"] = min(row["begin"], left), max(row["end"], right)
            dirty.add(key)
        return dirty

    def summary(self, period: str, now: datetime) -> dict:
        local = now.astimezone(self.tz)
        today = local.date().isoformat()
        start = today if period == "jour" else local.strftime("%Y-%m-01") if period == "mois" else local.strftime("%Y-01-01")
        selected = [row for day, row in sorted(self.rows.items()) if start <= day <= today]
        result = {key: sum(row[key] for row in selected) if selected else None for key in MONEY_KEYS}
        result.update(days=len(selected), measured_hours=round(sum(row["seconds"] for row in selected)/3600, 2),
            export_kwh=sum(row["export_kwh"] for row in selected) if selected else None,
            begin=datetime.fromtimestamp(selected[0]["begin"], self.tz).isoformat() if selected else None,
            end=datetime.fromtimestamp(selected[-1]["end"], self.tz).isoformat() if selected else None,
            started_at=datetime.fromtimestamp(self.start, self.tz).isoformat() if self.start is not None else None,
            currency=self.currency)
        return result

    def statistics(self, key: str, only: set[str] | None = None) -> list[dict]:
        total, result = 0., []
        for day, row in sorted(self.rows.items()):
            total += row[key]
            if only is not None and day not in only:
                continue
            end = datetime.combine(datetime.fromisoformat(day).date()+timedelta(days=1), time(), self.tz).timestamp()
            at = datetime.fromtimestamp(min(row["end"], end-1), timezone.utc).replace(minute=0, second=0, microsecond=0)
            result.append({"start": at, "sum": total, "state": total})
        return result


class Journal:
    """Full normalized measurements and every effective tariff in local JSONL."""
    def __init__(self, directory):
        self.root = Path(directory)
        self.engine = Engine()

    def load(self, now: datetime, config: dict):
        self.root.mkdir(parents=True, exist_ok=True)
        engine = Engine()
        for path in sorted(self.root.glob("history-????-??.jsonl")):
            with path.open(encoding="utf-8") as stream:
                for line in stream:
                    if not line.endswith("\n"):
                        raise ValueError("incomplete_journal_write")
                    engine.apply(json.loads(line))
        self.engine = engine
        if engine.start is None:
            self.append({"type": "start", "at": now.isoformat(), "schema": 1,
                "timezone": config["timezone"], "currency": config["currency"],
                "max_gap_seconds": config["max_gap_seconds"], "plan": build_plan(config)})
        elif engine.currency != config["currency"] or str(engine.tz) != config["timezone"]:
            raise ValueError("history_currency_or_timezone_mismatch")
        plan = build_plan(config)
        if engine.plans[-1][1] != plan:
            self.append({"type": "tariff", "at": now.isoformat(), "plan": plan})

    def append(self, event: dict) -> set[str]:
        # Validate in isolation before committing a malformed record. Samples
        # only need the tiny validation below; no copy of the accumulated days.
        kind = event["type"]
        if kind in ("start", "tariff"):
            stamp(event["at"])
            validate_plan(event["plan"])
            if kind == "start":
                if self.engine.start is not None:
                    raise ValueError("duplicate_start")
                Engine().apply(event)
            elif stamp(event["at"]) < self.engine.plans[-1][0]:
                raise ValueError("tariff_before_start")
        elif kind == "sources":
            stamp(event["at"])
            if int(event["max_gap_seconds"]) < 1:
                raise ValueError("invalid_configuration")
        elif kind == "sample":
            stamp(event["measured_at"])
            if not event.get("error"):
                finite(event["consumption_w"], nonnegative=True)
                finite(event["grid_w"], nonnegative=event.get("export_w") is not None)
                if event.get("export_w") is not None:
                    finite(event["export_w"], nonnegative=True)
        else:
            raise ValueError("invalid_record_type")
        tz = ZoneInfo(event["timezone"]) if kind == "start" else self.engine.tz
        when = datetime.fromtimestamp(stamp(event.get("received_at", event.get("at"))), tz)
        path = self.root / f"history-{when:%Y-%m}.jsonl"
        data = json.dumps(event, ensure_ascii=False, allow_nan=False) + "\n"
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        return self.engine.apply(event)
