#!/usr/bin/env python3
import argparse
import json
from datetime import timezone
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf

try:
    yf.set_tz_cache_location(str(Path(__file__).resolve().parents[1] / ".cache" / "yfinance"))
except AttributeError:
    pass


def _nearest_date(dti: pd.DatetimeIndex, target: pd.Timestamp) -> pd.Timestamp | None:
    if len(dti) == 0:
        return None
    # yfinance sometimes returns datetime64[s] indices; normalize to ns to avoid unit mismatch.
    dti_ns = pd.DatetimeIndex(dti).astype("datetime64[ns]")
    target_ns = np.datetime64(pd.Timestamp(target).to_datetime64(), "ns")
    diffs = np.abs(dti_ns.view("i8") - target_ns.view("i8"))
    return dti_ns[int(diffs.argmin())]


def _pct(now: float, then: float) -> float | None:
    if then == 0:
        return None
    return (now / then - 1.0) * 100.0


def _parse_ratio_spec(spec: str) -> tuple[str, str]:
    if "/" not in spec:
        raise ValueError(f"Invalid ratio spec (expected A/B): {spec}")
    a, b = spec.split("/", 1)
    a = a.strip()
    b = b.strip()
    if not a or not b:
        raise ValueError(f"Invalid ratio spec (empty ticker): {spec}")
    return a, b


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Compute 1w/1m returns and optional 1m ratio changes via yfinance."
    )
    parser.add_argument(
        "--tickers",
        nargs="+",
        required=True,
        help="Tickers to fetch (e.g. SPY QQQ BTC-USD).",
    )
    parser.add_argument(
        "--ratios",
        nargs="*",
        default=[],
        help="Optional ratio specs like BTC-USD/SPY; outputs 1m percent change in ratio.",
    )
    parser.add_argument(
        "--lookback-days",
        type=int,
        default=75,
        help="History window (days) to download (default: 75).",
    )
    parser.add_argument(
        "--week-days",
        type=int,
        default=7,
        help="Calendar days for 1w target (default: 7).",
    )
    parser.add_argument(
        "--month-days",
        type=int,
        default=30,
        help="Calendar days for 1m target (default: 30).",
    )
    parser.add_argument(
        "--quarter-days",
        type=int,
        default=90,
        help="Calendar days for 3m target (default: 90).",
    )
    args = parser.parse_args()

    tickers = [t.strip() for t in args.tickers if t.strip()]
    if not tickers:
        raise SystemExit("No tickers provided.")

    ratio_specs: list[tuple[str, str]] = []
    for r in args.ratios:
        ratio_specs.append(_parse_ratio_spec(r))

    end = pd.Timestamp.now(tz=timezone.utc).tz_convert(None)
    lookback_days = max(int(args.lookback_days), int(args.quarter_days) + 15)
    start = end - pd.Timedelta(days=lookback_days)

    raw = yf.download(
        tickers,
        start=start.date().isoformat(),
        end=(end + pd.Timedelta(days=1)).date().isoformat(),
        interval="1d",
        auto_adjust=False,
        progress=False,
        group_by="column",
        threads=True,
    )

    if raw is None or len(raw) == 0:
        print(
            json.dumps(
                {"error": "no_data", "tickers": tickers, "meta": {"start": str(start), "end": str(end)}}
            )
        )
        return 2

    if isinstance(raw.columns, pd.MultiIndex):
        close = raw.xs("Close", level=0, axis=1)
    else:
        close = raw["Close"]

    close = close.sort_index().dropna(how="all")
    if close.empty:
        print(
            json.dumps(
                {"error": "no_close_data", "tickers": tickers, "meta": {"start": str(start), "end": str(end)}}
            )
        )
        return 2

    out: dict[str, dict[str, object]] = {}
    for t in tickers:
        s = close[t].dropna() if t in close.columns else pd.Series(dtype=float)
        if s.empty:
            out[t] = {"ok": False}
            continue

        idx = s.index
        last_date = idx[-1]
        last = float(s.loc[last_date])

        w_target = last_date - pd.Timedelta(days=int(args.week_days))
        m_target = last_date - pd.Timedelta(days=int(args.month_days))
        q_target = last_date - pd.Timedelta(days=int(args.quarter_days))
        w_date = _nearest_date(idx, w_target)
        m_date = _nearest_date(idx, m_target)
        q_date = _nearest_date(idx, q_target)

        if w_date is None or m_date is None:
            out[t] = {"ok": False}
            continue

        w_close = float(s.loc[w_date])
        m_close = float(s.loc[m_date])
        q_close = float(s.loc[q_date]) if q_date is not None else None

        out[t] = {
            "ok": True,
            "last_date": str(pd.Timestamp(last_date).date()),
            "last": last,
            "w_date": str(pd.Timestamp(w_date).date()),
            "m_date": str(pd.Timestamp(m_date).date()),
            "q_date": str(pd.Timestamp(q_date).date()) if q_date is not None else None,
            "w": _pct(last, w_close),
            "m": _pct(last, m_close),
            "q": _pct(last, q_close) if q_close is not None else None,
        }

    ratios_out: dict[str, object] = {}
    for a, b in ratio_specs:
        key = f"{a}/{b}"
        if a not in close.columns or b not in close.columns:
            ratios_out[key] = None
            continue

        ab = close[[a, b]].dropna(how="any")
        if ab.empty:
            ratios_out[key] = None
            continue

        idx = ab.index
        anchor = idx[-1]
        m_target = anchor - pd.Timedelta(days=int(args.month_days))
        m_date = _nearest_date(idx, m_target)
        if m_date is None:
            ratios_out[key] = None
            continue

        a_now = float(ab.loc[anchor, a])
        b_now = float(ab.loc[anchor, b])
        a_then = float(ab.loc[m_date, a])
        b_then = float(ab.loc[m_date, b])
        if b_now == 0 or b_then == 0:
            ratios_out[key] = None
            continue
        ratios_out[key] = _pct(a_now / b_now, a_then / b_then)

    payload = {
        "meta": {
            "asof_utc": str(end),
            "lookback_days": lookback_days,
            "week_days": int(args.week_days),
            "month_days": int(args.month_days),
        },
        "tickers": out,
        "ratios_1m": ratios_out,
    }
    print(json.dumps(payload, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
