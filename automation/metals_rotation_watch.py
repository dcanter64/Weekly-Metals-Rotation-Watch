#!/usr/bin/env python3
import argparse
import csv
import json
from contextlib import redirect_stdout
from io import StringIO
import os
from pathlib import Path
import re
import sys
from typing import Any

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from automation.sensor_common import (
    change_from_scores,
    confidence_from_ok,
    et_date_time,
    fmt_pct,
    fmt_ret_pair,
    rotation_summary_block,
    run_yfinance_metrics,
    stance_from_score,
)


CORE_METALS = ["GLD", "SLV", "COPX", "CPER", "DBC"]
OPTIONAL_METALS = ["XME", "SETM"]
BENCHMARKS = ["SPY", "QQQ"]
REPORT_TICKERS = CORE_METALS + OPTIONAL_METALS

MODEL_DECISIONS = (
    "Add / Increase",
    "Hold / Maintain",
    "Trim / Reduce",
    "Avoid / Watchlist Only",
    "De-risk",
)
EXPOSURE_BIASES = (
    "Overweight",
    "Neutral",
    "Underweight",
    "Avoid",
    "Watch",
)
DECISION_CONFIDENCE_LEVELS = ("low", "medium", "high")


def _default_ratios() -> list[str]:
    return [
        "GLD/SPY",
        "SLV/SPY",
        "COPX/SPY",
        "CPER/SPY",
        "DBC/SPY",
        "XME/SPY",
        "SETM/SPY",
        "GLD/SLV",
        "COPX/CPER",
        "GLD/QQQ",
        "SLV/QQQ",
        "COPX/QQQ",
        "CPER/QQQ",
        "DBC/QQQ",
        "XME/QQQ",
        "SETM/QQQ",
    ]


def _score(
    *,
    copx_spy: float | None,
    slv_spy: float | None,
    gld_slv: float | None,
    gld_spy: float | None,
) -> int:
    score = 0

    # Copper and silver leadership tend to align with cyclical / risk appetite.
    for v in (copx_spy, slv_spy):
        if v is None:
            continue
        score += 1 if v > 0 else -1

    # Gold leading silver can lean defensive; silver leading gold leans cyclical.
    if gld_slv is not None:
        score += -1 if gld_slv > 0 else 1

    # If gold is strong vs SPY while copper is weak vs SPY, that's a defensive mix.
    if gld_spy is not None and copx_spy is not None:
        if gld_spy > 0 and copx_spy < 0:
            score -= 1

    return score


def _num(d: dict[str, Any] | None, key: str) -> float | None:
    if not d:
        return None
    v = d.get(key)
    return float(v) if isinstance(v, (int, float)) else None


def _w_ratio(a_w: float | None, b_w: float | None) -> float | None:
    if a_w is None or b_w is None:
        return None
    return a_w - b_w


def _gt(v: float | None, threshold: float = 0.0) -> bool:
    return v is not None and v > threshold


def _lt(v: float | None, threshold: float = 0.0) -> bool:
    return v is not None and v < threshold


def _mostly_negative(values: list[float | None]) -> bool:
    known = [v for v in values if v is not None]
    return bool(known) and sum(1 for v in known if v < 0) >= max(3, len(known) - 1)


def _fmt_price(v: float | None) -> str:
    if v is None:
        return "unavailable"
    return f"${v:,.2f}"


def _status(m_ret: float | None, vs_spy: float | None, week_vs_spy: float | None = None) -> str:
    if m_ret is None:
        return "UNAVAILABLE"
    if vs_spy is not None and m_ret <= -10.0 and vs_spy <= -5.0:
        return "VERY WEAK"
    if vs_spy is not None and m_ret > 0 and vs_spy > 0:
        return "STRONG"
    if vs_spy is not None and m_ret > 0 and vs_spy >= -1.0:
        return "CONFIRMED"
    improving = week_vs_spy is not None and vs_spy is not None and week_vs_spy > vs_spy
    if m_ret > -5.0 or (improving and (vs_spy is None or vs_spy > -7.5)):
        return "MIXED"
    if vs_spy is not None and m_ret < 0 and vs_spy < 0:
        return "WEAK"
    return "MIXED"


def _action_implication(decision_output: dict[str, Any]) -> str:
    return str(decision_output["positioning_action"])


def _decision_taxonomy(signal_type: str, ai_confirmation: str) -> tuple[str, str]:
    """Map the existing report state to a model decision and sleeve exposure bias."""
    if ai_confirmation == "Weak / risk-off":
        return "De-risk", "Avoid"
    if signal_type == "Broad metals weakness":
        return "Avoid / Watchlist Only", "Avoid"
    if signal_type == "Gold-led defensive tape":
        return "Trim / Reduce", "Underweight"
    if signal_type == "Industrial metals rotation" and ai_confirmation == "Confirmed":
        return "Add / Increase", "Overweight"
    if ai_confirmation == "Improving but not confirmed":
        return "Hold / Maintain", "Watch"
    return "Avoid / Watchlist Only", "Watch"


def _rule_above_zero(value: float | None) -> bool | None:
    return None if value is None else value > 0.0


def _rule_below_zero(value: float | None) -> bool | None:
    return None if value is None else value < 0.0


def _any_positive(values: list[float | None]) -> bool | None:
    known = [value for value in values if value is not None]
    return None if not known else any(value > 0.0 for value in known)


def _lower_confidence(confidence: str) -> str:
    if confidence == "high":
        return "medium"
    return "low"


def _positioning_action(model_decision: str, exposure_bias: str) -> str:
    if model_decision == "Add / Increase":
        return f"Increase toward {exposure_bias} if currently below target; otherwise maintain."
    if model_decision == "Hold / Maintain":
        return f"Maintain the current sleeve near a {exposure_bias} target."
    if model_decision == "Trim / Reduce":
        return f"Reduce to {exposure_bias} if currently Neutral/Overweight; otherwise maintain {exposure_bias}."
    if model_decision == "De-risk":
        return "Reduce toward Avoid; retain exposure only within predefined risk limits."
    return f"Do not add; maintain the {exposure_bias} target."


def _nearest_upgrade_gate(
    *,
    slv_spy: float | None,
    copx_spy: float | None,
    cper_spy: float | None,
    gld_slv: float | None,
    xme_spy: float | None,
    setm_spy: float | None,
) -> str:
    gaps: list[tuple[float, str]] = []
    if slv_spy is not None and slv_spy <= 0:
        gaps.append((-slv_spy, "SLV/SPY"))
    copper_values = [value for value in (copx_spy, cper_spy) if value is not None]
    if copper_values and max(copper_values) <= 0:
        gaps.append((-max(copper_values), "COPX/SPY or CPER/SPY"))
    if gld_slv is not None and gld_slv >= 0:
        gaps.append((gld_slv, "GLD/SLV"))
    breadth_values = [value for value in (xme_spy, setm_spy) if value is not None]
    if breadth_values and max(breadth_values) <= 0:
        gaps.append((-max(breadth_values), "XME/SPY or SETM/SPY"))
    if not gaps:
        return "All available core gates pass; monitor persistence and breadth."
    gap, condition = min(gaps)
    return f"{condition}, {gap:.2f} percentage points from confirmation."


def _decision_output(
    *,
    signal_type: str,
    ai_confirmation: str,
    confidence: str,
    slv_spy: float | None,
    copx_spy: float | None,
    cper_spy: float | None,
    gld_slv: float | None,
    xme_spy: float | None,
    setm_spy: float | None,
    relative_momentum: str,
) -> dict[str, Any]:
    """Return the structured decision produced by the explicit rotation rules."""
    rules: dict[str, bool | str | None] = {
        "slv_spy_above_zero": _rule_above_zero(slv_spy),
        "copx_spy_above_zero": _rule_above_zero(copx_spy),
        "cper_spy_above_zero": _rule_above_zero(cper_spy),
        "copper_confirmation": _any_positive([copx_spy, cper_spy]),
        "gld_slv_below_zero": _rule_below_zero(gld_slv),
        "materials_breadth_above_zero": _any_positive([xme_spy, setm_spy]),
        "relative_momentum": (
            relative_momentum
            if relative_momentum in ("improving", "unchanged", "weakening")
            else "unavailable"
        ),
    }

    model_decision, exposure_bias = _decision_taxonomy(signal_type, ai_confirmation)
    data_quality = confidence if confidence in DECISION_CONFIDENCE_LEVELS else "low"
    core_rules = (
        rules["slv_spy_above_zero"],
        rules["copper_confirmation"],
        rules["gld_slv_below_zero"],
    )
    missing_core_input = any(value is None for value in core_rules)
    one_month_confirmed = all(value is True for value in core_rules) and rules[
        "materials_breadth_above_zero"
    ] is not False

    if ai_confirmation == "Weak / risk-off":
        primary_reason = "Weak / risk-off confirmation overrides any isolated positive metals signal."
    elif signal_type == "Broad metals weakness":
        primary_reason = "Broad metals weakness does not support cyclical metals exposure."
    elif signal_type == "Gold-led defensive tape":
        primary_reason = (
            "Gold is the relative defensive leader within a broadly weak metals complex; "
            "silver, copper, and materials breadth lag SPY."
        )
    elif model_decision == "Add / Increase" and rules["relative_momentum"] == "weakening":
        model_decision, exposure_bias = "Hold / Maintain", "Neutral"
        primary_reason = "One-month leadership is confirmed, but 1w relative momentum is weakening."
    elif model_decision == "Add / Increase" and not one_month_confirmed:
        model_decision, exposure_bias = "Hold / Maintain", "Watch" if missing_core_input else "Neutral"
        primary_reason = "The report state is confirmed, but the explicit 1m leadership rules are not aligned."
    elif model_decision == "Add / Increase":
        primary_reason = "Silver and copper leadership meet the explicit 1m confirmation rules."
    elif ai_confirmation == "Improving but not confirmed":
        primary_reason = "Relative momentum is improving, but the full 1m leadership rules are not confirmed."
    else:
        primary_reason = "The available metals signals do not meet the risk-on confirmation rules."

    if missing_core_input:
        data_quality = _lower_confidence(data_quality)

    current_conditions: list[str] = []
    if rules["slv_spy_above_zero"] is False:
        current_conditions.append("SLV/SPY is at or below 0.00%.")
    if rules["copper_confirmation"] is False:
        current_conditions.append("Both COPX/SPY and CPER/SPY are at or below 0.00%.")
    if rules["gld_slv_below_zero"] is False:
        current_conditions.append("GLD/SLV is at or above 0.00%; gold leads silver.")
    if rules["materials_breadth_above_zero"] is False:
        current_conditions.append("No available materials breadth proxy is above 0.00% versus SPY.")
    if rules["relative_momentum"] == "weakening":
        current_conditions.append("1w relative momentum is weakening.")

    upgrade_triggers: list[str] = []
    if rules["slv_spy_above_zero"] is not True:
        upgrade_triggers.append("SLV/SPY moves above 0.00%.")
    if rules["copper_confirmation"] is not True:
        upgrade_triggers.append("COPX/SPY or CPER/SPY moves above 0.00%.")
    if rules["gld_slv_below_zero"] is not True:
        upgrade_triggers.append("GLD/SLV moves below 0.00% to confirm silver leadership.")
    if rules["materials_breadth_above_zero"] is False:
        upgrade_triggers.append("XME/SPY or SETM/SPY moves above 0.00%.")
    if rules["relative_momentum"] != "improving":
        upgrade_triggers.append("1w relative momentum improves.")
    if not upgrade_triggers:
        upgrade_triggers.append("Leadership broadens while all confirmation rules remain satisfied.")

    if model_decision in ("Trim / Reduce", "Avoid / Watchlist Only", "De-risk"):
        downgrade_triggers = [
            "Escalate to De-risk if 1w relative momentum weakens while silver and both copper proxies remain below SPY.",
            "Escalate if the signal becomes Broad metals weakness or Weak / risk-off.",
        ]
    else:
        # Escalation names future deterioration only: each trigger is listed
        # while its condition has not already tripped, so the list never
        # contradicts the upgrade triggers or the current bearish conditions.
        downgrade_triggers = []
        if rules["slv_spy_above_zero"] is not False:
            downgrade_triggers.append("SLV/SPY falls to 0.00% or below.")
        if rules["copper_confirmation"] is not False:
            downgrade_triggers.append("Both COPX/SPY and CPER/SPY fall to 0.00% or below.")
        if rules["gld_slv_below_zero"] is not False:
            downgrade_triggers.append("GLD/SLV rises to 0.00% or above.")
        if rules["materials_breadth_above_zero"] is True:
            downgrade_triggers.append("No available materials breadth proxy remains above 0.00%.")
        if rules["relative_momentum"] != "weakening":
            downgrade_triggers.append("1w relative momentum weakens.")
    if not downgrade_triggers:
        # The Decision Layer header prints the first trigger, so the list is
        # never empty; this mirrors the upgrade-trigger fallback above.
        downgrade_triggers.append(
            "No escalation triggers currently active; all watched conditions have already tripped."
        )

    if model_decision in ("Add / Increase", "Hold / Maintain"):
        invalidation_conditions = [
            "SLV/SPY is at or below 0.00% while both copper proxies are at or below 0.00%.",
            "Gold regains leadership over silver while 1w relative momentum weakens.",
        ]
    else:
        invalidation_conditions = [
            "The full bullish confirmation rule passes for two consecutive weekly observations.",
        ]

    bullish_gates = [
        rules["slv_spy_above_zero"],
        rules["copper_confirmation"],
        rules["gld_slv_below_zero"],
        rules["materials_breadth_above_zero"],
    ]
    bullish_gates_passed = sum(value is True for value in bullish_gates)
    bearish_conditions = sum(value is False for value in bullish_gates)
    if data_quality == "low":
        decision_conviction = "low"
    elif model_decision == "Add / Increase":
        decision_conviction = "high" if one_month_confirmed else "medium"
    elif model_decision in ("Trim / Reduce", "Avoid / Watchlist Only", "De-risk"):
        decision_conviction = "high" if bearish_conditions >= 4 else "medium" if bearish_conditions >= 3 else "low"
    else:
        decision_conviction = "medium"

    upgrade_rule = (
        "SLV/SPY > 0 AND (COPX/SPY > 0 OR CPER/SPY > 0) AND GLD/SLV < 0 "
        "AND (XME/SPY > 0 OR SETM/SPY > 0, when available), with 1w momentum not weakening."
    )

    return {
        "model_decision": model_decision,
        "exposure_bias": exposure_bias,
        "positioning_action": _positioning_action(model_decision, exposure_bias),
        "primary_reason": primary_reason,
        "upgrade_rule": upgrade_rule,
        "upgrade_triggers": upgrade_triggers,
        "downgrade_triggers": downgrade_triggers,
        "invalidation_conditions": invalidation_conditions,
        "current_conditions": current_conditions,
        "bullish_gates_passed": bullish_gates_passed,
        "bullish_gates_total": len(bullish_gates),
        "nearest_upgrade_gate": _nearest_upgrade_gate(
            slv_spy=slv_spy,
            copx_spy=copx_spy,
            cper_spy=cper_spy,
            gld_slv=gld_slv,
            xme_spy=xme_spy,
            setm_spy=setm_spy,
        ),
        "decision_conviction": decision_conviction,
        "data_quality": data_quality,
        "confidence": decision_conviction,
        "rule_inputs": rules,
    }


def _apply_decision_persistence(
    decision_output: dict[str, Any],
    previous_state: dict[str, Any] | None,
) -> dict[str, Any]:
    if decision_output["model_decision"] != "Add / Increase":
        return decision_output
    previous_decision = previous_state.get("model_decision") if previous_state else None
    if previous_decision == "Add / Increase":
        return decision_output

    resolved = dict(decision_output)
    resolved["model_decision"] = "Hold / Maintain"
    resolved["exposure_bias"] = "Neutral"
    resolved["positioning_action"] = _positioning_action("Hold / Maintain", "Neutral")
    resolved["primary_reason"] = (
        "The bullish confirmation rule passes now, but Add / Increase requires a second consecutive weekly observation."
    )
    resolved["upgrade_triggers"] = ["The full bullish confirmation rule remains satisfied at the next weekly review."]
    resolved["decision_conviction"] = "medium"
    resolved["confidence"] = "medium"
    return resolved


def _executive_read(
    *,
    change: str,
    signal_type: str,
    slv_spy: float | None,
    copx_spy: float | None,
    gld_slv: float | None,
    dbc_spy: float | None,
) -> list[str]:
    if signal_type == "Gold-led defensive tape":
        read = "Risk-off metals read: gold is still winning inside metals while silver and copper miners lag SPY."
    elif signal_type == "Industrial metals rotation":
        read = "Risk-on metals read: silver and copper-linked exposure are confirming cyclical leadership."
    elif signal_type == "Broad metals weakness":
        read = "Weak metals read: the group is broadly underperforming and does not confirm an industrial rotation."
    else:
        read = "Mixed metals read: leadership is not clean enough to upgrade or abandon the rotation."

    if change == "improving":
        tape = "Short-term tape is improving, but the 1m confirmation bar still matters most."
    elif change == "weakening":
        tape = "Short-term tape is weakening, so confirmation needs to be rebuilt before upgrading exposure."
    else:
        tape = "Short-term tape is broadly unchanged from the 1m signal."

    key = (
        f"Key tells: SLV/SPY {fmt_pct(slv_spy)}, COPX/SPY {fmt_pct(copx_spy)}, "
        f"GLD/SLV {fmt_pct(gld_slv)}, DBC/SPY {fmt_pct(dbc_spy)}."
    )
    return [read, tape, key]


def _threshold_gap(value: float | None, *, above: bool) -> str:
    if value is None:
        return "unavailable"
    passed = value > 0.0 if above else value < 0.0
    if passed:
        return f"Passed by {abs(value):.2f} pp"
    return f"{abs(value):.2f} pp needed"


def _threshold_status(value: float | None, *, above: bool) -> str:
    if value is None:
        return "Unavailable"
    return "Pass" if (value > 0.0 if above else value < 0.0) else "Fail"


def _trigger_matrix(
    *,
    slv_spy: float | None,
    copx_spy: float | None,
    cper_spy: float | None,
    gld_slv: float | None,
    xme_spy: float | None,
    setm_spy: float | None,
    relative_momentum: str,
) -> list[str]:
    breadth_values = [value for value in (xme_spy, setm_spy) if value is not None]
    best_breadth = max(breadth_values) if breadth_values else None
    momentum_status = (
        "Pass"
        if relative_momentum in ("improving", "unchanged")
        else "Fail" if relative_momentum == "weakening" else "Unavailable"
    )
    return [
        "| Condition | Current | Threshold | Gap | Status | Rule role |",
        "|---|---:|---:|---:|---|---|",
        (
            f"| SLV/SPY | {fmt_pct(slv_spy)} | > 0.00% | {_threshold_gap(slv_spy, above=True)} | "
            f"{_threshold_status(slv_spy, above=True)} | Required |"
        ),
        (
            f"| COPX/SPY | {fmt_pct(copx_spy)} | > 0.00% | {_threshold_gap(copx_spy, above=True)} | "
            f"{_threshold_status(copx_spy, above=True)} | Either copper proxy |"
        ),
        (
            f"| CPER/SPY | {fmt_pct(cper_spy)} | > 0.00% | {_threshold_gap(cper_spy, above=True)} | "
            f"{_threshold_status(cper_spy, above=True)} | Either copper proxy |"
        ),
        (
            f"| GLD/SLV | {fmt_pct(gld_slv)} | < 0.00% | {_threshold_gap(gld_slv, above=False)} | "
            f"{_threshold_status(gld_slv, above=False)} | Required |"
        ),
        (
            f"| Materials breadth | XME {fmt_pct(xme_spy)}; SETM {fmt_pct(setm_spy)} | "
            f"Either > 0.00% | {_threshold_gap(best_breadth, above=True)} | "
            f"{_threshold_status(best_breadth, above=True)} | Required when available |"
        ),
        (
            f"| 1w relative momentum | {relative_momentum} | Not weakening | n/a | "
            f"{momentum_status} | Weakening blocks Add / Increase |"
        ),
    ]


def _contradiction_notes(
    *,
    dbc_m: float | None,
    dbc_spy: float | None,
    cper_m: float | None,
    cper_spy: float | None,
    slv_spy: float | None,
    copx_spy: float | None,
) -> list[str]:
    notes = ["ETF proxies can diverge from spot; treat this as a directional signal, not precise pricing."]
    if _gt(dbc_m) and _gt(dbc_spy) and (_lt(slv_spy) or _lt(copx_spy)):
        notes.append(
            f"DBC is strong ({fmt_pct(dbc_m)} 1m, {fmt_pct(dbc_spy)} vs SPY), but that is broad commodities strength rather than clean industrial metals leadership."
        )
    if cper_m is not None and cper_spy is not None and cper_m > -2.0 and cper_spy > -1.0 and _lt(copx_spy):
        notes.append(
            f"CPER is stabilizing ({fmt_pct(cper_m)} 1m, {fmt_pct(cper_spy)} vs SPY), while COPX remains weak; miners have not confirmed copper itself."
        )
    return notes


def _signal_type(
    *,
    gld_m: float | None,
    slv_m: float | None,
    copx_m: float | None,
    cper_m: float | None,
    dbc_m: float | None,
    xme_m: float | None,
    setm_m: float | None,
    slv_spy: float | None,
    copx_spy: float | None,
    cper_spy: float | None,
    dbc_spy: float | None,
    gld_slv: float | None,
) -> str:
    broad_weak = (
        _mostly_negative([gld_m, slv_m, copx_m, cper_m, dbc_m])
        and _lt(slv_spy)
        and _lt(copx_spy)
        and _lt(dbc_spy)
    )
    if broad_weak:
        return "Broad metals weakness"

    industrial_count = sum(1 for v in [slv_m, copx_m, cper_m, xme_m, setm_m] if _gt(v))
    industrial = (
        slv_m is not None
        and gld_m is not None
        and slv_m > gld_m
        and (_gt(copx_spy) or _gt(cper_spy))
        and (_gt(slv_spy) or (slv_spy is not None and slv_spy > -2.0))
        and industrial_count >= 2
    )
    if industrial:
        return "Industrial metals rotation"

    gold_led = (
        _gt(gld_slv, 5.0)
        and gld_m is not None
        and slv_m is not None
        and copx_m is not None
        and gld_m > slv_m
        and gld_m > copx_m
        and _lt(slv_spy)
        and _lt(copx_spy)
    )
    if gold_led:
        return "Gold-led defensive tape"

    return "Mixed / no clear signal"


def _ai_confirmation(
    *,
    gld_m: float | None,
    slv_m: float | None,
    copx_m: float | None,
    cper_m: float | None,
    dbc_m: float | None,
    slv_spy: float | None,
    copx_spy: float | None,
    cper_spy: float | None,
    xme_spy: float | None,
    setm_spy: float | None,
    gld_slv: float | None,
    copx_cper: float | None,
    week_slv_spy: float | None,
    week_copx_spy: float | None,
) -> str:
    materials_breadth = [v for v in [xme_spy, setm_spy] if v is not None]
    breadth_ok = not materials_breadth or sum(1 for v in materials_breadth if v > 0) >= 1

    weak_risk_off = (
        _lt(slv_m, -10.0)
        and _lt(copx_m, -10.0)
        and _gt(gld_slv, 5.0)
        and _lt(dbc_m)
        and (copx_cper is None or copx_cper < 0)
    )
    if weak_risk_off:
        return "Weak / risk-off"

    confirmed = (
        _gt(slv_spy)
        and (_gt(copx_spy) or _gt(cper_spy))
        and slv_m is not None
        and gld_m is not None
        and slv_m > gld_m
        and breadth_ok
    )
    if confirmed:
        return "Confirmed"

    improving = (
        (slv_spy is not None and week_slv_spy is not None and week_slv_spy > slv_spy)
        or (copx_spy is not None and week_copx_spy is not None and week_copx_spy > copx_spy)
        or (cper_m is not None and cper_m > -2.0)
    ) and (gld_slv is None or gld_slv < 5.0)
    if improving:
        return "Improving but not confirmed"

    not_confirmed = (
        _lt(slv_spy)
        and _lt(copx_spy)
        and gld_m is not None
        and slv_m is not None
        and gld_m > slv_m
    )
    if not_confirmed:
        return "Not confirmed"

    return "Not confirmed"


def _ticker_table(rows: list[dict[str, Any]], include_qqq: bool) -> list[str]:
    header = "| Ticker | Last price | 1w return | 1m return | 3m return | vs SPY 1m |"
    sep = "|---|---:|---:|---:|---:|---:|"
    if include_qqq:
        header += " vs QQQ 1m |"
        sep += "---:|"
    header += " Status |"
    sep += "---|"

    out = [header, sep]
    for row in rows:
        line = (
            f"| {row['symbol']} | {_fmt_price(row['last'])} | {fmt_pct(row['w'])} | "
            f"{fmt_pct(row['m'])} | {fmt_pct(row['q'])} | {fmt_pct(row['vs_spy'])} |"
        )
        if include_qqq:
            line += f" {fmt_pct(row['vs_qqq'])} |"
        line += f" {row['status']} |"
        out.append(line)
    return out


def _leadership_note(symbol: str, status: str, gld_slv: float | None) -> str:
    if symbol == "GLD" and _gt(gld_slv):
        return "defensive relative leader"
    if symbol == "SLV":
        return "high-beta metal"
    if symbol == "COPX":
        return "cyclical copper miners"
    if symbol == "CPER":
        return "copper proxy"
    if symbol == "DBC":
        return "broad commodities proxy"
    if status == "STRONG":
        return "relative strength leader"
    if status == "VERY WEAK":
        return "very weak"
    if status == "WEAK":
        return "weak"
    return "mixed / stabilizing"


def _report_output_path(report_date: str, report_time: str, output_dir: Path | None = None) -> Path:
    root = Path(__file__).resolve().parents[1]
    target_dir = output_dir if output_dir is not None else root / "output"
    target_dir.mkdir(parents=True, exist_ok=True)
    safe_time = report_time.replace(":", "").replace(" ", "_")
    return target_dir / f"weekly_metals_rotation_watch_{report_date}_{safe_time}.txt"


def _structural_view(values: list[float | None]) -> str:
    known = [value for value in values if value is not None]
    if not known:
        return "Unavailable"
    positive = sum(value > 0 for value in known)
    if positive > len(known) / 2:
        return "Constructive; a majority of metals proxies remain positive over 3m."
    if positive < len(known) / 3:
        return "Weak; fewer than one-third of metals proxies are positive over 3m."
    return "Mixed; the 3m metals trend is not broad enough for a structural signal."


def _parse_pct_value(value: Any) -> float | None:
    if not isinstance(value, str):
        return None
    match = re.search(r"([+-]?\d+(?:\.\d+)?)%", value)
    return float(match.group(1)) if match else None


def _load_previous_decision_state(root: Path) -> dict[str, Any] | None:
    output_dir = root / "output"
    if not output_dir.exists():
        return None
    reports = sorted(
        output_dir.glob("weekly_metals_rotation_watch_*.txt"),
        key=lambda path: (path.stat().st_mtime, path.name),
    )
    if not reports:
        return None

    report_path = reports[-1]
    text = report_path.read_text(encoding="utf-8")
    state: dict[str, Any] = {
        "date": _extract_field(text, r"^Date: (.+)$"),
        "run_time": _extract_field(text, r"^Run Time: (.+)$"),
        "model_decision": _extract_field(text, r"^- Model decision: (.+)$"),
        "rule_values": {},
    }
    sidecar_path = report_path.with_suffix(".json")
    if sidecar_path.exists():
        try:
            sidecar = json.loads(sidecar_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            sidecar = {}
        if isinstance(sidecar, dict):
            state["date"] = sidecar.get("date", state["date"])
            state["run_time"] = sidecar.get("run_time", state["run_time"])
            state["model_decision"] = sidecar.get("model_decision", state["model_decision"])
            decision_rules = sidecar.get("decision_rules", [])
            if isinstance(decision_rules, list):
                for rule in decision_rules:
                    if isinstance(rule, dict):
                        condition = rule.get("condition")
                        if condition in ("SLV/SPY", "COPX/SPY", "GLD/SLV"):
                            state["rule_values"][condition] = _parse_pct_value(rule.get("current_value"))

    for condition in ("SLV/SPY", "COPX/SPY", "GLD/SLV"):
        if condition not in state["rule_values"]:
            match = re.search(rf"^\| {re.escape(condition)} \| ([^|]+) \|", text, flags=re.MULTILINE)
            state["rule_values"][condition] = _parse_pct_value(match.group(1)) if match else None
    return state


def _week_over_week_table(
    current_values: dict[str, float | None],
    current_decision: str,
    previous_state: dict[str, Any] | None,
) -> list[str]:
    if previous_state:
        basis = f"{previous_state.get('date', 'unavailable')} at {previous_state.get('run_time', 'unavailable')}"
    else:
        basis = "unavailable"
    rows = [
        f"- Comparison basis: previous report from {basis}; the normal review cadence is weekly.",
        "",
        "| Metric | Previous | Current | Change |",
        "|---|---:|---:|---:|",
    ]
    previous_values = previous_state.get("rule_values", {}) if previous_state else {}
    for condition in ("SLV/SPY", "COPX/SPY", "GLD/SLV"):
        previous = previous_values.get(condition) if isinstance(previous_values, dict) else None
        current = current_values.get(condition)
        change = current - previous if current is not None and previous is not None else None
        rows.append(f"| {condition} | {fmt_pct(previous)} | {fmt_pct(current)} | {fmt_pct(change)} |")
    previous_decision = previous_state.get("model_decision", "unavailable") if previous_state else "unavailable"
    decision_change = "unchanged" if previous_decision == current_decision else f"{previous_decision} -> {current_decision}"
    rows.append(f"| Model decision | {previous_decision} | {current_decision} | {decision_change} |")
    return rows


def _extract_field(text: str, pattern: str) -> str:
    match = re.search(pattern, text, flags=re.MULTILINE)
    return match.group(1).strip() if match else "unavailable"


def _extract_list_field(text: str, pattern: str) -> list[str]:
    value = _extract_field(text, pattern)
    if value == "unavailable":
        return []
    return [item.strip() for item in value.split("; ") if item.strip()]


def _extract_bullets(text: str, pattern: str) -> list[str]:
    match = re.search(pattern, text, flags=re.MULTILINE | re.DOTALL)
    if not match:
        return []
    return [line[2:].strip() for line in match.group(1).splitlines() if line.startswith("- ")]


def _extract_decision_rules(report_text: str) -> list[dict[str, str]]:
    match = re.search(
        r"^## Decision Trigger Matrix\n(.+?)(?=\n## |\Z)",
        report_text,
        flags=re.MULTILINE | re.DOTALL,
    )
    if not match:
        return []

    rules: list[dict[str, str]] = []
    for line in match.group(1).splitlines():
        if not line.startswith("|") or line.startswith("|---") or "| Condition |" in line:
            continue
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if len(cells) == 6:
            rules.append(
                {
                    "condition": cells[0],
                    "current_value": cells[1],
                    "threshold": cells[2],
                    "gap": cells[3],
                    "status": cells[4],
                    "rule_role": cells[5],
                }
            )
        elif len(cells) == 4:
            rules.append(
                {
                    "condition": cells[0],
                    "current_value": cells[1],
                    "threshold": cells[2],
                    "decision_impact": cells[3],
                }
            )
    return rules


def _report_summary(report_text: str, report_date: str, report_time: str) -> dict[str, Any]:
    return {
        "date": report_date,
        "run_time": report_time,
        "model_decision": _extract_field(report_text, r"^- Model decision: (.+)$"),
        "exposure_bias": _extract_field(report_text, r"^- Target bias: (.+)$"),
        "positioning_action": _extract_field(report_text, r"^- Positioning action: (.+)$"),
        "tactical_view": _extract_field(report_text, r"^- Tactical view: (.+)$"),
        "structural_view": _extract_field(report_text, r"^- Structural view: (.+)$"),
        "primary_reason": _extract_field(report_text, r"^- Primary reason: (.+)$"),
        "upgrade_rule": _extract_field(report_text, r"^- Exact rule: (.+)$"),
        "upgrade_triggers": _extract_bullets(
            report_text,
            r"^## Upgrade Conditions\n(.+?)(?=\n## |\Z)",
        )[1:],
        "downgrade_triggers": _extract_bullets(
            report_text,
            r"^### Escalation\n(.+?)(?=\n### Invalidation|\n## |\Z)",
        ),
        "invalidation_conditions": _extract_bullets(
            report_text,
            r"^### Invalidation\n(.+?)(?=\n## |\Z)",
        ),
        "current_conditions": _extract_bullets(
            report_text,
            r"^## Current Bearish Conditions\n(.+?)(?=\n## |\Z)",
        ),
        "decision_rules": _extract_decision_rules(report_text),
        "signal_type": _extract_field(report_text, r"^## Signal Type\n- (.+)$"),
        "ai_confirmation": _extract_field(
            report_text,
            r"^## (?:Cyclical Metals / AI Bottleneck Proxy Confirmation|AI Bottleneck Confirmation)\n- Answer: (.+)$",
        ),
        "stance": _extract_field(report_text, r"^Current stance: (.+)$"),
        "change": _extract_field(report_text, r"^Change from last week: (.+)$"),
        "decision_conviction": _extract_field(report_text, r"^- Decision conviction: (.+)$"),
        "data_quality": _extract_field(report_text, r"^- Data quality: (.+)$"),
        "review_frequency": _extract_field(report_text, r"^- Review frequency: (.+)$"),
        "confidence": _extract_field(report_text, r"^- Decision conviction: (.+)$"),
    }


def _write_sidecars(output_path: Path, report_text: str, report_date: str, report_time: str) -> None:
    summary = _report_summary(report_text, report_date, report_time)
    json_path = output_path.with_suffix(".json")
    csv_path = output_path.with_suffix(".csv")

    json_payload = dict(summary)
    json_payload["report_text"] = report_text
    json_path.write_text(json.dumps(json_payload, indent=2), encoding="utf-8")

    csv_payload = {
        key: json.dumps(value, separators=(",", ":")) if isinstance(value, (list, dict)) else value
        for key, value in summary.items()
    }
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(summary.keys()))
        writer.writeheader()
        writer.writerow(csv_payload)


def build_report_text(
    m: Any,
    report_date: str,
    report_time: str,
    previous_state: dict[str, Any] | None = None,
) -> str:
    tickers = CORE_METALS + OPTIONAL_METALS + BENCHMARKS
    ticker_data = {sym: m.ticker(sym) for sym in tickers}

    def wt(sym: str) -> tuple[float | None, float | None]:
        tt = ticker_data.get(sym)
        return (_num(tt, "w"), _num(tt, "m")) if tt else (None, None)

    def q(sym: str) -> float | None:
        return _num(ticker_data.get(sym), "q")

    gld_w, gld_m = wt("GLD")
    slv_w, slv_m = wt("SLV")
    copx_w, copx_m = wt("COPX")
    cper_w, cper_m = wt("CPER")
    dbc_w, dbc_m = wt("DBC")
    spy_w, spy_m = wt("SPY")
    qqq_w, qqq_m = wt("QQQ")
    xme_w, xme_m = wt("XME")
    setm_w, setm_m = wt("SETM")

    gld_spy = m.ratio_1m("GLD/SPY")
    slv_spy = m.ratio_1m("SLV/SPY")
    copx_spy = m.ratio_1m("COPX/SPY")
    cper_spy = m.ratio_1m("CPER/SPY")
    dbc_spy = m.ratio_1m("DBC/SPY")
    xme_spy = m.ratio_1m("XME/SPY")
    setm_spy = m.ratio_1m("SETM/SPY")
    gld_slv = m.ratio_1m("GLD/SLV")
    copx_cper = m.ratio_1m("COPX/CPER")

    week_slv_spy = _w_ratio(slv_w, spy_w)
    week_copx_spy = _w_ratio(copx_w, spy_w)

    month_score = _score(copx_spy=copx_spy, slv_spy=slv_spy, gld_slv=gld_slv, gld_spy=gld_spy)
    week_score = _score(
        copx_spy=week_copx_spy,
        slv_spy=week_slv_spy,
        gld_slv=_w_ratio(gld_w, slv_w),
        gld_spy=_w_ratio(gld_w, spy_w),
    )

    stance = stance_from_score(month_score)
    change = change_from_scores(week_score, month_score)

    signal_type = _signal_type(
        gld_m=gld_m,
        slv_m=slv_m,
        copx_m=copx_m,
        cper_m=cper_m,
        dbc_m=dbc_m,
        xme_m=xme_m,
        setm_m=setm_m,
        slv_spy=slv_spy,
        copx_spy=copx_spy,
        cper_spy=cper_spy,
        dbc_spy=dbc_spy,
        gld_slv=gld_slv,
    )
    ai_confirmation = _ai_confirmation(
        gld_m=gld_m,
        slv_m=slv_m,
        copx_m=copx_m,
        cper_m=cper_m,
        dbc_m=dbc_m,
        slv_spy=slv_spy,
        copx_spy=copx_spy,
        cper_spy=cper_spy,
        xme_spy=xme_spy,
        setm_spy=setm_spy,
        gld_slv=gld_slv,
        copx_cper=copx_cper,
        week_slv_spy=week_slv_spy,
        week_copx_spy=week_copx_spy,
    )

    ok_count = len(
        [
            x
            for x in [gld_m, slv_m, copx_m, cper_m, spy_w, gld_spy, copx_spy, slv_spy, gld_slv]
            if x is not None
        ]
    )
    confidence = confidence_from_ok(ok_count, needed=7)
    decision_output = _decision_output(
        signal_type=signal_type,
        ai_confirmation=ai_confirmation,
        confidence=confidence,
        slv_spy=slv_spy,
        copx_spy=copx_spy,
        cper_spy=cper_spy,
        gld_slv=gld_slv,
        xme_spy=xme_spy,
        setm_spy=setm_spy,
        relative_momentum=change,
    )
    decision_output = _apply_decision_persistence(decision_output, previous_state)
    decision_output["tactical_view"] = f"{decision_output['exposure_bias']} over 1-4 weeks."
    decision_output["structural_view"] = _structural_view(
        [q("GLD"), q("SLV"), q("COPX"), q("CPER"), q("XME"), q("SETM")]
    )
    decision_output["review_frequency"] = "Weekly"
    action = _action_implication(decision_output)
    executive_read = _executive_read(
        change=change,
        signal_type=signal_type,
        slv_spy=slv_spy,
        copx_spy=copx_spy,
        gld_slv=gld_slv,
        dbc_spy=dbc_spy,
    )
    trigger_matrix = _trigger_matrix(
        slv_spy=slv_spy,
        copx_spy=copx_spy,
        cper_spy=cper_spy,
        gld_slv=gld_slv,
        xme_spy=xme_spy,
        setm_spy=setm_spy,
        relative_momentum=change,
    )
    contradiction_notes = _contradiction_notes(
        dbc_m=dbc_m,
        dbc_spy=dbc_spy,
        cper_m=cper_m,
        cper_spy=cper_spy,
        slv_spy=slv_spy,
        copx_spy=copx_spy,
    )

    rows: list[dict[str, Any]] = []
    for sym in REPORT_TICKERS:
        tt = ticker_data.get(sym)
        if tt is None and sym in OPTIONAL_METALS:
            continue
        week_vs_spy = _w_ratio(_num(tt, "w"), spy_w)
        vs_spy = m.ratio_1m(f"{sym}/SPY")
        rows.append(
            {
                "symbol": sym,
                "last": _num(tt, "last"),
                "w": _num(tt, "w"),
                "m": _num(tt, "m"),
                "q": q(sym),
                "vs_spy": vs_spy,
                "vs_qqq": m.ratio_1m(f"{sym}/QQQ"),
                "status": _status(_num(tt, "m"), vs_spy, week_vs_spy),
            }
        )

    include_qqq = ticker_data.get("QQQ") is not None
    leadership = sorted(
        [r for r in rows if r["m"] is not None and r["symbol"] != "DBC"],
        key=lambda r: (r["m"], r["vs_spy"] if r["vs_spy"] is not None else -999.0),
        reverse=True,
    )
    dbc_context = next((row for row in rows if row["symbol"] == "DBC"), None)
    week_over_week = _week_over_week_table(
        {"SLV/SPY": slv_spy, "COPX/SPY": copx_spy, "GLD/SLV": gld_slv},
        str(decision_output["model_decision"]),
        previous_state,
    )

    evidence = [
        f"COPX/SPY (1m) {fmt_pct(copx_spy)}",
        f"GLD/SLV (1m) {fmt_pct(gld_slv)}",
        f"SLV/SPY (1m) {fmt_pct(slv_spy)}",
    ]

    buffer = StringIO()
    with redirect_stdout(buffer):
        print(f"Date: {report_date}")
        print(f"Run Time: {report_time}")
        print()
        print("# Weekly Metals Rotation Watch")
        print()
        print("## Decision Layer")
        print(f"- Model decision: {decision_output['model_decision']}")
        print(f"- Target bias: {decision_output['exposure_bias']}")
        print(f"- Positioning action: {decision_output['positioning_action']}")
        print(f"- Tactical view: {decision_output['tactical_view']}")
        print(f"- Structural view: {decision_output['structural_view']}")
        print(f"- Regime: {signal_type}")
        print(f"- Primary reason: {decision_output['primary_reason']}")
        print(
            f"- Core bullish rules: {decision_output['bullish_gates_passed']} of "
            f"{decision_output['bullish_gates_total']} passed"
        )
        print(f"- Nearest upgrade gate: {decision_output['nearest_upgrade_gate']}")
        print(f"- Escalation trigger: {decision_output['downgrade_triggers'][0]}")
        print(f"- Invalidation: {decision_output['invalidation_conditions'][0]}")
        print(f"- Decision conviction: {decision_output['decision_conviction']}")
        print(f"- Data quality: {decision_output['data_quality']}")
        print(f"- Review frequency: {decision_output['review_frequency']}")
        print()
        print("## Executive Read")
        for line in executive_read:
            print(f"- {line}")
        print()
        print("## Key Data")
        print(
            "- Returns (1w/1m): "
            f"GLD {fmt_ret_pair(gld_w, gld_m)} | "
            f"SLV {fmt_ret_pair(slv_w, slv_m)} | "
            f"COPX {fmt_ret_pair(copx_w, copx_m)} | "
            f"CPER {fmt_ret_pair(cper_w, cper_m)} | "
            f"DBC {fmt_ret_pair(dbc_w, dbc_m)}"
        )
        print(
            "- RS vs SPY (1m): "
            f"GLD {fmt_pct(gld_spy)} | "
            f"SLV {fmt_pct(slv_spy)} | "
            f"COPX {fmt_pct(copx_spy)} | "
            f"CPER {fmt_pct(cper_spy)} | "
            f"DBC {fmt_pct(dbc_spy)}"
        )
        print(f"- Gold vs Silver (1m): GLD/SLV {fmt_pct(gld_slv)}")
        print(f"- Benchmarks (1w/1m): SPY {fmt_ret_pair(spy_w, spy_m)} | QQQ {fmt_ret_pair(qqq_w, qqq_m)}")
        print()
        print("## Change Since Previous Report")
        for line in week_over_week:
            print(line)
        print()
        print("## Signal Type")
        print(f"- {signal_type}")
        print()
        print("## Interpretation")
        if signal_type == "Industrial metals rotation":
            print(
                "- Confirmation is relative and breadth-based: silver and copper-linked exposure lead defensive gold and SPY."
            )
        elif signal_type == "Gold-led defensive tape":
            print(
                "- This is relative, not absolute, gold leadership: GLD is less weak than SLV and COPX but may still lag SPY."
            )
        elif signal_type == "Broad metals weakness":
            print(
                "- Metals are not confirming an AI bottleneck rotation. Gold is outperforming silver, silver is underperforming SPY, and copper miners are weak."
            )
            print("- This is a risk-off metals tape, not an industrial metals leadership tape.")
        else:
            print("- Metals signals are mixed; no clear leadership pattern is confirmed.")
        print("- Anchor on copper/silver leadership vs gold dominance as the primary rotation lens.")
        print()
        print("## Cyclical Metals / AI Bottleneck Proxy Confirmation")
        print(f"- Answer: {ai_confirmation}")
        if ai_confirmation == "Confirmed":
            print("- SLV and copper-linked exposure are leading versus SPY, with silver outperforming gold.")
        elif ai_confirmation == "Improving but not confirmed":
            print("- Some relative trends are stabilizing, but the signal still needs SLV/COPX confirmation.")
        elif ai_confirmation == "Weak / risk-off":
            print("- SLV and COPX are sharply weak, gold is leading silver, and broad commodities are negative.")
        else:
            print("- SLV/SPY and COPX/SPY have not confirmed; gold remains ahead of silver.")
        print()
        print("## Ticker Detail")
        for line in _ticker_table(rows, include_qqq):
            print(line)
        print()
        print("## Metals Leadership Hierarchy")
        if leadership:
            for i, row in enumerate(leadership, start=1):
                note = _leadership_note(row["symbol"], row["status"], gld_slv)
                print(f"{i}. {row['symbol']} - {note} ({fmt_pct(row['m'])} 1m, {fmt_pct(row['vs_spy'])} vs SPY)")
        else:
            print("- Leadership unavailable; no valid ticker data returned.")
        print()
        print("## Commodity Context")
        if dbc_context:
            print(
                f"- DBC is a broad-commodity context indicator, not a metals-hierarchy constituent: "
                f"{fmt_pct(dbc_context['m'])} 1m and {fmt_pct(dbc_context['vs_spy'])} versus SPY."
            )
        else:
            print("- DBC context is unavailable.")
        if signal_type == "Gold-led defensive tape":
            print(
                "- Gold-led means GLD leads silver and copper miners defensively; it does not imply that GLD is rising or beating SPY."
            )
        print()
        print("## Decision Trigger Matrix")
        for line in trigger_matrix:
            print(line)
        print()
        print("## Upgrade Conditions")
        print(f"- Exact rule: {decision_output['upgrade_rule']}")
        for line in decision_output["upgrade_triggers"]:
            print(f"- {line}")
        print()
        print("## Current Bearish Conditions")
        if decision_output["current_conditions"]:
            for line in decision_output["current_conditions"]:
                print(f"- {line}")
        else:
            print("- No bearish confirmation condition is currently active.")
        print()
        print("## Escalation And Invalidation Rules")
        print("### Escalation")
        for line in decision_output["downgrade_triggers"]:
            print(f"- {line}")
        print("### Invalidation")
        for line in decision_output["invalidation_conditions"]:
            print(f"- {line}")
        print()
        print("## Risks / Contradictions")
        for line in contradiction_notes:
            print(f"- {line}")
        if ok_count < 7:
            print("- Some tickers were unavailable; confidence is reduced.")
        print()
        print(
            rotation_summary_block(
                stance=stance,
                change=change,
                evidence=evidence,
                action=action,
                confidence=str(decision_output["decision_conviction"]),
                data_quality=str(decision_output["data_quality"]),
            ),
            end="",
        )

    return buffer.getvalue()


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate the Weekly Metals Rotation Watch report.")
    parser.add_argument(
        "--no-write",
        action="store_true",
        help="Print the report without writing a timestamped output file.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Directory for timestamped report files. Defaults to ./output.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    root = Path(__file__).resolve().parents[1]
    previous_state = _load_previous_decision_state(root)
    tickers = CORE_METALS + OPTIONAL_METALS + BENCHMARKS
    m = run_yfinance_metrics(tickers=tickers, ratios=_default_ratios())

    d, t = et_date_time()
    report_text = build_report_text(m, d, t, previous_state=previous_state)
    print(report_text, end="")
    if not args.no_write:
        output_path = _report_output_path(d, t, args.output_dir)
        output_path.write_text(report_text, encoding="utf-8")
        _write_sidecars(output_path, report_text, d, t)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
