# Weekly Metals Rotation Watch

Created UTC: 20260618T131735Z

## Current Status

This project is a local Windows automation for generating a weekly metals rotation report. It does not depend on a remote scheduler or OpenClaw runtime.

Recent updates as of 2026-10-08:

- Project docs now describe this as a local-only laptop workflow.
- Each local run now prints to the terminal and writes a timestamped report file under `output/`.
- The project now includes pinned dependencies, validation commands, unit tests, and Windows Task Scheduler guidance.
- The report now opens with a rules-based Decision Layer that states the model decision, exposure bias, rationale, triggers, invalidation conditions, and confidence.
- The original descriptive analysis remains in the report as supporting evidence.

The active entry points are:

- `run_weekly_metals_rotation_watch.bat`
- `automation/metals_rotation_watch.py`

`automation/metals_rotation_watch.py` imports shared helpers from `automation/sensor_common.py`, which locates this folder dynamically and calls the local yfinance helper for market data.

Each local run prints the report to the CMD/PowerShell window and also writes a timestamped text file under `output/`.

## Repository Contents

- `ROADMAP.md`: remaining completion tasks and definition of done
- `CHANGELOG.md`: report logic and project maintenance changes
- `requirements.txt`: pinned local Python dependencies
- `automation/compare_reports.py`: decision and signal comparison for the two newest local report files
- `automation/metals_rotation_watch.py`: active local report script
- `automation/validate_report.py`: smoke validation for fresh or existing report output
- `automation/sensor_common.py`: shared helper module used by the local script
- `automation/yfinance_metrics.py`: local yfinance metrics helper
- `run_weekly_metals_rotation_watch.bat`: Windows launcher for local runs
- `tests/`: focused unit tests for report classification and formatting helpers
- `sample_output/fresh_local_sample_output.txt`: sample output from a local run
- `output/`: generated local reports (not tracked in Git)

## Setup

From PowerShell in this folder:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

If `py -3` is unavailable, use:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

## Local Usage

Double-click `run_weekly_metals_rotation_watch.bat`, or run it from Command Prompt/PowerShell.

The launcher uses `.venv\Scripts\python.exe` or `venv\Scripts\python.exe` if present. Otherwise it falls back to the Windows `py -3` launcher or `python` on PATH.

Direct command:

```powershell
python automation\metals_rotation_watch.py
```

Print without writing a file:

```powershell
python automation\metals_rotation_watch.py --no-write
```

Write to an alternate output directory:

```powershell
python automation\metals_rotation_watch.py --output-dir output_test
```

## Report Structure

The report is decision-first:

- `Decision Layer` separates the model state from the portfolio action. It gives the target bias, a position-aware action, tactical and structural views, the primary reason, nearest upgrade gate, escalation and invalidation conditions, decision conviction, and data quality.
- `Change Since Previous Report` shows prior and current decision metrics with numerical deltas. The normal cadence is weekly, but the label remains accurate when multiple reports run on the same day.
- `Decision Trigger Matrix` shows each rule's current value, threshold, distance to threshold, pass/fail status, and role in the exact Boolean confirmation rule.
- `Current Bearish Conditions` records conditions that are already active. `Escalation And Invalidation Rules` separately defines future deterioration and thesis-reversal conditions.
- `Commodity Context` keeps DBC outside the metals leadership ranking, while `Executive Read`, `Key Data`, signal interpretation, ticker detail, risks, and rotation summary remain supporting evidence.

The decisions are rules-based model outputs for research and monitoring. They are not personalized financial advice and do not account for an individual's objectives, risk tolerance, or financial circumstances.

## Validation

Run unit tests:

```powershell
python -m unittest discover -s tests
```

Run a fresh smoke validation. This fetches live yfinance data, writes to a temporary output directory, and checks required report sections and Decision Layer fields:

```powershell
python automation\validate_report.py
```

Validate the newest existing report under `output/` without fetching live data:

```powershell
python automation\validate_report.py --latest
```

Compare the two newest local report files:

```powershell
python automation\compare_reports.py
```

The comparison reads structured JSON sidecars when available and falls back to parsing the text reports. It reports model-decision, decision-conviction, data-quality, upgrade-driver, escalation-risk, and invalidation-condition changes.

Local output:

- The report is printed to the CMD/PowerShell window during the run.
- A new timestamped text file is also created in `output/`, for example `output/weekly_metals_rotation_watch_2026-07-10_1058_AM_ET.txt`.
- Matching `.csv` and `.json` summary sidecars are written next to the text report. They include Decision Layer fields and structured trigger rules.
- The `.txt` report is the primary human-readable artifact. The `.json` sidecar is the canonical structured history record used by comparison tooling, while `.csv` provides a portable one-row summary.
- Historical decision state remains in each report's sidecars; there is no separate history database or ledger to maintain.

Output retention:

- Keep recent reports in `output/` for quick comparison.
- Archive or delete older reports manually when the folder becomes noisy.
- Retain at least the latest successful report so `python automation\validate_report.py --latest` has a local file to check.
- Retain at least two successful reports if you want `python automation\compare_reports.py` to show changes since the previous report.
- Retain each `.json` sidecar with its matching text report so decision history and previous-report drivers remain available.

## Windows Task Scheduler

Manual runs are the default and safest operating mode for this project. To automate it locally, create a Windows Task Scheduler task that runs the batch file.

Suggested task settings:

- Name: `Weekly Metals Rotation Watch`
- Trigger: Weekly, Thursday, 11:00 AM Eastern
- Action: Start a program
- Program/script: full path to `run_weekly_metals_rotation_watch.bat`
- Start in: this project folder

After creating the task, use Task Scheduler's Run command once and confirm a new file appears under `output/`.

## Troubleshooting

Python not found:

- Install Python 3 for Windows, or create `.venv` in this folder.
- Re-run the setup command above.

Missing packages:

- Run `.\.venv\Scripts\python.exe -m pip install -r requirements.txt`.
- If running without `.venv`, run `python -m pip install -r requirements.txt`.

yfinance download failures:

- Confirm the laptop has internet access.
- Try again after a few minutes; yfinance can fail when Yahoo Finance throttles or returns partial data.
- Run `python automation\validate_report.py --latest` to validate the latest local report without a fresh download.

Ticker unavailable or partial data:

- Optional tickers `XME` and `SETM` are omitted from the ticker table when yfinance does not return usable data.
- Required ticker gaps reduce report confidence and may show as `unavailable`.
