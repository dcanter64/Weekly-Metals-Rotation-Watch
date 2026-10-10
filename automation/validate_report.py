#!/usr/bin/env python3
import argparse
import subprocess
import sys
import tempfile
from pathlib import Path


REQUIRED_SECTIONS = [
    "Date:",
    "Run Time:",
    "## Decision Layer",
    "## Executive Read",
    "## Key Data",
    "## Change Since Previous Report",
    "## Signal Type",
    "## Cyclical Metals / AI Bottleneck Proxy Confirmation",
    "## Ticker Detail",
    "## Commodity Context",
    "## Decision Trigger Matrix",
    "## Current Bearish Conditions",
    "## Escalation And Invalidation Rules",
    "## Rotation Summary",
]

REQUIRED_DECISION_FIELDS = [
    "- Model decision:",
    "- Target bias:",
    "- Positioning action:",
    "- Tactical view:",
    "- Structural view:",
    "- Primary reason:",
    "- Core bullish rules:",
    "- Nearest upgrade gate:",
    "- Escalation trigger:",
    "- Invalidation:",
    "- Decision conviction:",
    "- Data quality:",
    "- Review frequency:",
]


def validate_text(text: str) -> list[str]:
    missing = [section for section in REQUIRED_SECTIONS if section not in text]
    missing.extend(field for field in REQUIRED_DECISION_FIELDS if field not in text)
    if "| Ticker | Last price | 1w return | 1m return | 3m return | vs SPY 1m |" not in text:
        missing.append("ticker table header")
    return missing


def _latest_output(root: Path) -> Path | None:
    output_dir = root / "output"
    if not output_dir.exists():
        return None
    files = sorted(output_dir.glob("weekly_metals_rotation_watch_*.txt"), key=lambda p: p.stat().st_mtime)
    return files[-1] if files else None


def _run_report(root: Path) -> tuple[str, list[Path], int]:
    with tempfile.TemporaryDirectory(prefix="metals_rotation_watch_") as tmp:
        tmp_path = Path(tmp)
        cmd = [
            sys.executable,
            str(root / "automation" / "metals_rotation_watch.py"),
            "--output-dir",
            str(tmp_path),
        ]
        cp = subprocess.run(cmd, capture_output=True, text=True, cwd=str(root))
        created = sorted(tmp_path.glob("weekly_metals_rotation_watch_*.txt"))
        text = created[-1].read_text(encoding="utf-8") if created else cp.stdout
        return text, created, cp.returncode


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate Weekly Metals Rotation Watch report and Decision Layer output."
    )
    parser.add_argument(
        "--latest",
        action="store_true",
        help="Validate the newest file in ./output instead of running a fresh live report.",
    )
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[1]
    if args.latest:
        latest = _latest_output(root)
        if latest is None:
            print("No output files found under output/.")
            return 1
        text = latest.read_text(encoding="utf-8")
        source = str(latest)
        created = [latest]
        returncode = 0
    else:
        text, created, returncode = _run_report(root)
        source = "fresh report run"
        if returncode != 0:
            print("Report command failed before validation completed.")
            return returncode
        if not created:
            print("Report command did not create an output file.")
            return 1

    missing = validate_text(text)
    if missing:
        print(f"Validation failed for {source}. Missing: {', '.join(missing)}")
        return 1

    print(f"Validation passed for {source}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
