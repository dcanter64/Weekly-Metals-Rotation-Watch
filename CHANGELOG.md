# Changelog

## 2026-10-08

- Added the model-decision and exposure-bias taxonomy for metals rotation states.
- Added a structured rules engine with explicit relative-strength thresholds, upgrade and downgrade triggers, invalidation conditions, confidence, and mixed-state conflict resolution.
- Added a decision-first report surface with a compact Decision Layer, measurable trigger matrix, and direct action language.
- Added tests for confirmed risk-on, improving, defensive, broad-weakness, mixed-momentum, and missing-optional-data cases.
- Extended JSON and CSV sidecars with structured decision fields and trigger thresholds.
- Extended report comparison with decision, conviction, data-quality, upgrade-driver, escalation-risk, and invalidation-condition changes plus offline fixtures.
- Chose per-report sidecars as the historical decision store instead of adding a separate history file.
- Extended report validation to require the Decision Layer and each of its core fields.
- Completed Decision Layer acceptance with 31 passing tests, latest-report validation, and historical comparison.
- Refined the report to separate target exposure from trade instructions, active bearish evidence from future escalation, data quality from decision conviction, and tactical from structural views.
- Added threshold gaps and pass/fail states, previous-report metric deltas, benchmark returns, position-aware actions, exact Boolean upgrade logic, and a separate DBC context section.
- Added two-observation persistence before a new `Add / Increase` decision can become actionable.
- Updated the roadmap, README, and sample report for the Phase 1-3 decision-layer implementation.

## 2026-07-20

- Added `ROADMAP.md` with completion criteria and remaining project tasks.
- Added pinned local dependencies in `requirements.txt`.
- Added `--no-write` and `--output-dir` options to `automation/metals_rotation_watch.py`.
- Split report rendering into `build_report_text()` so logic can be tested without live market data.
- Added `automation/validate_report.py` for fresh-run and latest-output validation.
- Added unit tests for report scoring, classification, optional ticker handling, and shared formatting helpers.
- Added README setup, validation, troubleshooting, output retention, and Windows Task Scheduler guidance.
- Removed the obsolete OpenClaw Python fallback path from the local yfinance helper.
- Added JSON and CSV summary sidecars next to each written text report.
- Added an executive read, numeric confirmation triggers, and contradiction notes to the report.
