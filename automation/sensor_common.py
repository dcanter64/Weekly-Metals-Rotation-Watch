#!/usr/bin/env python3
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, tzinfo
from pathlib import Path
from typing import Any

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover - Python < 3.9 fallback
    ZoneInfo = None


@dataclass(frozen=True)
class Metrics:
    payload: dict[str, Any]

    def ticker(self, symbol: str) -> dict[str, Any] | None:
        t = self.payload.get("tickers", {}).get(symbol)
        return t if isinstance(t, dict) and t.get("ok") is True else None

    def ratio_1m(self, spec: str) -> float | None:
        ratios = self.payload.get("ratios_1m", {})
        if not isinstance(ratios, dict):
            return None
        v = ratios.get(spec)
        return float(v) if isinstance(v, (int, float)) else None


class _EasternTimeFallback(tzinfo):
    def utcoffset(self, dt: datetime | None) -> timedelta:
        return timedelta(hours=-5) + self.dst(dt)

    def dst(self, dt: datetime | None) -> timedelta:
        if dt is None:
            return timedelta(0)
        naive = dt.replace(tzinfo=None)
        start = _nth_weekday(dt.year, 3, 6, 2).replace(hour=2)
        end = _nth_weekday(dt.year, 11, 6, 1).replace(hour=2)
        return timedelta(hours=1) if start <= naive < end else timedelta(0)

    def tzname(self, dt: datetime | None) -> str:
        return "EDT" if self.dst(dt) else "EST"


def _nth_weekday(year: int, month: int, weekday: int, n: int) -> datetime:
    d = datetime(year, month, 1)
    days_until = (weekday - d.weekday()) % 7
    return d + timedelta(days=days_until + (n - 1) * 7)


def _eastern_tz() -> tzinfo:
    if ZoneInfo is not None:
        try:
            return ZoneInfo("America/New_York")
        except Exception:
            pass
    return _EasternTimeFallback()


def et_date_time() -> tuple[str, str]:
    now = datetime.now(_eastern_tz())
    d = now.strftime("%Y-%m-%d")
    t = now.strftime("%I:%M %p ET").lstrip("0")
    return d, t


def run_yfinance_metrics(*, tickers: list[str], ratios: list[str]) -> Metrics:
    root = Path(__file__).resolve().parents[1]
    venv_candidates = [
        root / ".venv" / "Scripts" / "python.exe",
        root / "venv" / "Scripts" / "python.exe",
        root / ".venv" / "bin" / "python",
    ]
    py = next((str(p) for p in venv_candidates if p.exists()), sys.executable)
    cmd = [
        py,
        str(root / "automation" / "yfinance_metrics.py"),
        "--tickers",
        *tickers,
    ]
    if ratios:
        cmd += ["--ratios", *ratios]
    cp = subprocess.run(cmd, capture_output=True, text=True, cwd=str(root))
    if cp.returncode != 0:
        raise RuntimeError((cp.stderr or cp.stdout or "").strip() or f"yfinance_metrics failed rc={cp.returncode}")
    try:
        payload = json.loads(cp.stdout)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"yfinance_metrics returned non-JSON: {e}") from e
    if not isinstance(payload, dict):
        raise RuntimeError("yfinance_metrics returned unexpected JSON type")
    return Metrics(payload=payload)


def fmt_pct(v: float | None) -> str:
    if v is None:
        return "unavailable"
    return f"{v:+.2f}%"


def fmt_ret_pair(w: float | None, m: float | None) -> str:
    if w is None or m is None:
        return "unavailable/unavailable"
    return f"{w:+.2f}%/{m:+.2f}%"


def stance_from_score(score: int) -> str:
    if score >= 2:
        return "risk-on"
    if score <= -2:
        return "risk-off"
    return "neutral"


def change_from_scores(week_score: int, month_score: int) -> str:
    if week_score > month_score + 1:
        return "improving"
    if week_score < month_score - 1:
        return "weakening"
    return "unchanged"


def confidence_from_ok(ok_count: int, needed: int) -> str:
    if ok_count >= needed:
        return "high"
    if ok_count >= max(1, needed - 2):
        return "medium"
    return "low"


def action_from_stance_conf(stance: str, confidence: str) -> str:
    if confidence in ("medium", "high") and stance == "risk-on":
        return "cyclical leadership improving; monitor for confirmation"
    if confidence in ("medium", "high") and stance == "risk-off":
        return "tactically weak; wait for relative strength confirmation"
    return "watch"


def rotation_summary_block(
    *,
    stance: str,
    change: str,
    evidence: list[str],
    action: str,
    confidence: str,
    data_quality: str | None = None,
) -> str:
    ev = (evidence + ["unavailable", "unavailable", "unavailable"])[:3]
    return (
        "## Rotation Summary\n"
        f"Current stance: {stance}\n"
        f"Change from last week: {change}\n"
        "Evidence:\n"
        f"1. {ev[0]}\n"
        f"2. {ev[1]}\n"
        f"3. {ev[2]}\n"
        f"Action implication: {action}\n"
        f"Decision conviction: {confidence}\n"
        f"Data quality: {data_quality or 'unavailable'}\n"
    )
