# Roadmap

Last reviewed: 2026-10-10

## Current State

The project is a local Windows workflow for generating a Weekly Metals Rotation Watch report. The active path is:

1. Run `run_weekly_metals_rotation_watch.bat`
2. The batch file selects a local Python interpreter
3. `automation/metals_rotation_watch.py` fetches market data through `automation/yfinance_metrics.py`
4. The report prints to the terminal and writes a timestamped file under `output/`

Decision Layer conversion Phases 1-5 are complete: the taxonomy, structured rules engine, decision-first report surface, historical decision tracking, and validation and acceptance work are implemented and covered by unit tests.

`README.md` describes the local workflow, Decision Layer versus supporting evidence, entry points, dependencies, validation commands, scheduling guidance, and output behavior.

## Completion Checklist

### Required Before Project Is Complete

- [x] Add a pinned dependency file, such as `requirements.txt`, with `yfinance`, `pandas`, and `numpy`.
- [x] Add a quick setup command to the README for creating and installing into `.venv`.
- [x] Add a lightweight smoke test or validation script that confirms the report can run and create an output file.
- [x] Add expected-output checks for required report sections:
  - Date and run time
  - Key data
  - Signal type
  - AI bottleneck confirmation
  - Ticker detail table
  - Rotation summary
- [x] Decide whether this should remain manual-only or be scheduled with Windows Task Scheduler.
- [x] If scheduled, add setup instructions for the Windows scheduled task.
- [x] Add a troubleshooting section for common failures:
  - Missing Python
  - Missing packages
  - yfinance download failures
  - Ticker unavailable or partial data
- [x] Document how old files in `output/` should be retained, archived, or deleted.
- [x] Refresh `sample_output/fresh_local_sample_output.txt` after the final output format is accepted.

### Should Do

- [x] Add a `--no-write` or `--output-dir` option for easier testing and alternate report locations.
- [x] Add basic unit tests for scoring and classification helpers in `automation/metals_rotation_watch.py`.
- [x] Add basic unit tests for date/formatting helpers in `automation/sensor_common.py`.
- [x] Consider separating report rendering from live data fetching so logic can be tested without network access.
- [x] Add clear behavior for optional tickers `XME` and `SETM` when data is missing.
- [x] Review whether the legacy OpenClaw fallback path in `automation/sensor_common.py` is still needed.

### Nice To Have

- [x] Add CSV or JSON output alongside the text report.
- [x] Add a changelog for report logic changes.
- [x] Add a small historical summary that compares the latest report to the previous local output file.
- [x] Add an archive policy for `backups/`, `cron/`, and `run_history/` if the project is now permanently local-only.

## Decision Layer Conversion Plan

Goal: convert the Weekly Metals Rotation Watch from a descriptive report into a rules-based decision dashboard that answers what action the model recommends, why, what would change the recommendation, and when the thesis is wrong.

### Phase 1 - Decision Taxonomy

- [x] Define the allowed model decisions:
  - `Add / Increase`
  - `Hold / Maintain`
  - `Trim / Reduce`
  - `Avoid / Watchlist Only`
  - `De-risk`
- [x] Define exposure bias labels for each ticker or sleeve:
  - `Overweight`
  - `Neutral`
  - `Underweight`
  - `Avoid`
  - `Watch`
- [x] Map existing report states into decision states:
  - `Industrial metals rotation` + `Confirmed` -> risk-on decision candidate
  - `Improving but not confirmed` -> watch / hold candidate
  - `Gold-led defensive tape` -> trim / defensive candidate
  - `Broad metals weakness` or `Weak / risk-off` -> avoid / de-risk candidate
- [x] Fix wording consistency in the existing narrative so confirmed risk-on language uses deterioration as the downgrade condition, not improvement as the hold condition.
- [x] Add unit tests for the decision taxonomy mapping before changing the rendered report.

### Phase 2 - Rules Engine

- [x] Add a dedicated decision helper that returns structured output instead of only narrative text.
- [x] Include these fields in the helper output:
  - `model_decision`
  - `exposure_bias`
  - `primary_reason`
  - `upgrade_triggers`
  - `downgrade_triggers`
  - `invalidation_conditions`
  - `confidence`
- [x] Convert the current signal thresholds into explicit rule inputs:
  - `SLV/SPY > 0`
  - `COPX/SPY > 0`
  - `CPER/SPY > 0`
  - `GLD/SLV < 0`
  - `XME/SPY` or `SETM/SPY > 0`
  - 1w relative momentum improving or weakening
- [x] Add conflict-resolution rules for mixed states, such as confirmed 1m leadership but weakening 1w tape.
- [x] Add tests for representative cases:
  - confirmed risk-on
  - improving but not confirmed
  - defensive gold-led tape
  - broad metals weakness
  - missing optional ticker data

### Phase 3 - Report Surface

- [x] Add a new top-level `## Decision Layer` section above `## Executive Read`.
- [x] Render the structured decision output in a compact format:
  - `Model decision`
  - `Target bias`
  - `Positioning action`
  - `Tactical view`
  - `Structural view`
  - `Primary reason`
  - `Nearest upgrade gate`
  - `Escalation trigger`
  - `Invalidation`
  - `Decision conviction`
  - `Data quality`
- [x] Replace vague action implications with direct decision language.
- [x] Convert `What Would Improve the Signal` into a trigger matrix showing condition, current value, threshold, and decision impact.
- [x] Convert `What Would Keep the Signal Weak` into current bearish conditions plus escalation and invalidation rules.
- [x] Keep the descriptive sections, but make them supporting evidence under the decision output.

### Phase 4 - Historical Decision Tracking

- [x] Extend CSV and JSON sidecars to include decision-layer fields.
- [x] Update `automation/compare_reports.py` to compare decision changes between the two newest reports.
- [x] Surface changes such as:
  - `Decision changed`
  - `Confidence changed`
  - `Main upgrade driver`
  - `Main escalation risk`
  - `New invalidation risk`
- [x] Add tests or fixtures for report comparison so decision changes are repeatable without live market data.
- [x] Keep historical decision state in per-report JSON and CSV sidecars rather than duplicating it in a separate history file.

### Phase 5 - Validation And Acceptance

- [x] Update `automation/validate_report.py` required-section checks to include `Decision Layer`.
- [x] Refresh `sample_output/fresh_local_sample_output.txt` after the new format is accepted.
- [x] Update `README.md` to explain the difference between descriptive sections and decision-layer sections.
- [x] Add a short disclaimer that decisions are rules-based model outputs, not personalized financial advice.
- [x] Run the full local verification set:
  - `python -m unittest discover -s tests`
  - `python automation\validate_report.py --latest`
  - `python automation\compare_reports.py`

### Decision Layer Definition Of Done

- [x] The first screen of the report answers what the model would do now.
- [x] Every decision has a primary reason and at least one escalation or invalidation condition.
- [x] Trigger thresholds are visible, testable, and stored in structured sidecar output.
- [x] Week-to-week comparison identifies whether the model decision changed and why.
- [x] Existing descriptive analysis remains available as evidence, not as the main output.

## Definition Of Done

This project can be considered complete when:

- A new user can set it up from the README without prior context.
- A local run reliably produces a timestamped report in `output/`.
- The project has at least one repeatable validation command.
- The expected report sections are checked automatically or documented clearly.
- The scheduling decision is documented.
- Legacy files are clearly labeled as reference-only or removed by explicit choice.

## Notes From 2026-07-20 Review

- `README.md` exists at the project root.
- No `roadmap.md` or `ROADMAP.md` existed before this file was created.
- A report file exists for 2026-07-20 under `output/`, indicating the local report path has recently run.
- `git status` could not be used from this folder because Git did not recognize it as a repository, despite a `.git` folder being present.

## Next Cleanup

- [x] Keep `.json` sidecars by default as the canonical structured decision-history record.

## Status Note

As of 2026-10-08, Decision Layer Phases 1-5 and every Decision Layer definition-of-done item are complete. The refined report separates target exposure, positioning action, current evidence, future escalation, tactical and structural views, decision conviction, and data quality. Documentation and the tracked sample are current, per-report sidecars provide structured history, all 31 tests pass, the latest report validates, and previous-report comparison runs successfully.

## Status Note 2026-10-10

Re-verified after the escalation-trigger reporting fix (PR #1, branch `muse/fix-breadth-downgrade-trigger`): 37/37 unit tests pass, a fresh live report run validates end-to-end, the tracked sample validates, and previous-report comparison runs successfully. Escalation triggers now list future deterioration only, per the section's documented intent; no thresholds, decisions, or scoring logic changed. All Definition of Done items above remain satisfied.
