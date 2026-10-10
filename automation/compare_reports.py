#!/usr/bin/env python3
import json
import re
from pathlib import Path
from typing import Any


TEXT_FIELDS = {
    "date": r"^Date: (.+)$",
    "run_time": r"^Run Time: (.+)$",
    "model_decision": r"^- Model decision: (.+)$",
    "exposure_bias": r"^- (?:Target bias|Exposure bias): (.+)$",
    "positioning_action": r"^- Positioning action: (.+)$",
    "tactical_view": r"^- Tactical view: (.+)$",
    "structural_view": r"^- Structural view: (.+)$",
    "primary_reason": r"^- Primary reason: (.+)$",
    "signal_type": r"^## Signal Type\n- (.+)$",
    "ai_confirmation": r"^## (?:Cyclical Metals / AI Bottleneck Proxy Confirmation|AI Bottleneck Confirmation)\n- Answer: (.+)$",
    "stance": r"^Current stance: (.+)$",
    "change": r"^Change from last week: (.+)$",
    "decision_conviction": r"^- Decision conviction: (.+)$",
    "data_quality": r"^- Data quality: (.+)$",
    "confidence": r"^(?:- Decision conviction|Confidence): (.+)$",
}

LIST_FIELDS = {
    "upgrade_triggers": r"^- Upgrade trigger: (.+)$",
    "downgrade_triggers": r"^- Downgrade trigger: (.+)$",
    "invalidation_conditions": r"^- Invalidation: (.+)$",
}

LABELS = {
    "model_decision": "Model Decision",
    "exposure_bias": "Target Bias",
    "ai_confirmation": "AI Confirmation",
}


def _extract(text: str) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, pattern in TEXT_FIELDS.items():
        match = re.search(pattern, text, flags=re.MULTILINE)
        out[key] = match.group(1).strip() if match else "unavailable"
    for key, pattern in LIST_FIELDS.items():
        match = re.search(pattern, text, flags=re.MULTILINE)
        out[key] = [item.strip() for item in match.group(1).split("; ")] if match else []
    section_patterns = {
        "upgrade_triggers": r"^## Upgrade Conditions\n(.+?)(?=\n## |\Z)",
        "downgrade_triggers": r"^### Escalation\n(.+?)(?=\n### Invalidation|\n## |\Z)",
        "invalidation_conditions": r"^### Invalidation\n(.+?)(?=\n## |\Z)",
    }
    for key, pattern in section_patterns.items():
        match = re.search(pattern, text, flags=re.MULTILINE | re.DOTALL)
        if match:
            bullets = [line[2:].strip() for line in match.group(1).splitlines() if line.startswith("- ")]
            out[key] = bullets[1:] if key == "upgrade_triggers" and bullets[:1] else bullets
    return out


def _report_files(root: Path) -> list[Path]:
    output_dir = root / "output"
    if not output_dir.exists():
        return []
    return sorted(
        output_dir.glob("weekly_metals_rotation_watch_*.txt"),
        key=lambda path: (path.stat().st_mtime, path.name),
    )


def _load_report(report_path: Path) -> dict[str, Any]:
    text = report_path.read_text(encoding="utf-8")
    report = _extract(text)
    sidecar_path = report_path.with_suffix(".json")
    if not sidecar_path.exists():
        return report

    try:
        sidecar = json.loads(sidecar_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return report
    if isinstance(sidecar, dict):
        report.update({key: value for key, value in sidecar.items() if key != "report_text"})
    if report.get("decision_conviction") in (None, "unavailable"):
        report["decision_conviction"] = report.get("confidence", "unavailable")
    return report


def _first(items: Any) -> str:
    if isinstance(items, list) and items:
        return str(items[0])
    if isinstance(items, str) and items not in ("", "unavailable"):
        return items
    return "unavailable"


def _changed(previous: Any, latest: Any) -> str:
    if previous == latest:
        return f"No - {latest}"
    return f"Yes - {previous} -> {latest}"


def _driver_change(previous: Any, latest: Any) -> str:
    previous_driver = _first(previous)
    latest_driver = _first(latest)
    if previous_driver == latest_driver:
        return latest_driver
    return f"{latest_driver} (previously: {previous_driver})"


def _new_invalidation(previous: Any, latest: Any) -> str:
    previous_items = set(previous) if isinstance(previous, list) else set()
    latest_items = latest if isinstance(latest, list) else []
    new_items = [str(item) for item in latest_items if item not in previous_items]
    return "; ".join(new_items) if new_items else "None"


def _render_comparison(
    previous_path: Path,
    latest_path: Path,
    previous: dict[str, Any],
    latest: dict[str, Any],
) -> str:
    lines = [
        "# Weekly Metals Rotation Watch Comparison",
        "",
        f"Previous: {previous_path.name}",
        f"Latest: {latest_path.name}",
        "",
        "| Field | Previous | Latest |",
        "|---|---|---|",
    ]
    fields = [
        "date",
        "run_time",
        "model_decision",
        "exposure_bias",
        "positioning_action",
        "tactical_view",
        "structural_view",
        "primary_reason",
        "signal_type",
        "ai_confirmation",
        "stance",
        "change",
        "decision_conviction",
        "data_quality",
    ]
    for field in fields:
        label = LABELS.get(field, field.replace("_", " ").title())
        lines.append(f"| {label} | {previous.get(field, 'unavailable')} | {latest.get(field, 'unavailable')} |")

    lines.extend(
        [
            "",
            "## Decision Changes",
            f"- Decision changed: {_changed(previous.get('model_decision'), latest.get('model_decision'))}",
            (
                "- Decision conviction changed: "
                f"{_changed(previous.get('decision_conviction'), latest.get('decision_conviction'))}"
            ),
            f"- Data quality changed: {_changed(previous.get('data_quality'), latest.get('data_quality'))}",
            (
                "- Main upgrade driver: "
                f"{_driver_change(previous.get('upgrade_triggers'), latest.get('upgrade_triggers'))}"
            ),
            (
                "- Main escalation risk: "
                f"{_driver_change(previous.get('downgrade_triggers'), latest.get('downgrade_triggers'))}"
            ),
            (
                "- New invalidation condition: "
                f"{_new_invalidation(previous.get('invalidation_conditions'), latest.get('invalidation_conditions'))}"
            ),
        ]
    )
    return "\n".join(lines) + "\n"


def compare_latest(root: Path) -> str:
    files = _report_files(root)
    if len(files) < 2:
        raise ValueError("Need at least two report files under output/ to compare.")
    previous_path, latest_path = files[-2], files[-1]
    return _render_comparison(
        previous_path,
        latest_path,
        _load_report(previous_path),
        _load_report(latest_path),
    )


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    try:
        comparison = compare_latest(root)
    except ValueError as error:
        print(error)
        return 1
    print(comparison, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
