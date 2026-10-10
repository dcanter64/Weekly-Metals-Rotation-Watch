import json
import os
from pathlib import Path
import tempfile
import unittest

from automation import compare_reports


class ReportComparisonTests(unittest.TestCase):
    def test_compare_latest_surfaces_decision_changes_from_sidecars(self) -> None:
        previous = {
            "date": "2026-10-01",
            "run_time": "11:00 AM ET",
            "model_decision": "Hold / Maintain",
            "exposure_bias": "Watch",
            "positioning_action": "Maintain the current sleeve near a Watch target.",
            "tactical_view": "Watch over 1-4 weeks.",
            "structural_view": "Mixed.",
            "primary_reason": "Leadership is improving but incomplete.",
            "upgrade_triggers": ["SLV/SPY moves above 0.00%."],
            "downgrade_triggers": ["1w relative momentum weakens."],
            "invalidation_conditions": ["Gold regains leadership over silver."],
            "signal_type": "Mixed / no clear signal",
            "ai_confirmation": "Improving but not confirmed",
            "stance": "neutral",
            "change": "improving",
            "decision_conviction": "medium",
            "data_quality": "high",
            "confidence": "medium",
        }
        latest = {
            "date": "2026-10-08",
            "run_time": "11:00 AM ET",
            "model_decision": "Add / Increase",
            "exposure_bias": "Overweight",
            "positioning_action": "Increase toward Overweight if currently below target; otherwise maintain.",
            "tactical_view": "Overweight over 1-4 weeks.",
            "structural_view": "Constructive.",
            "primary_reason": "Silver and copper leadership are confirmed.",
            "upgrade_triggers": ["Leadership broadens."],
            "downgrade_triggers": ["SLV/SPY falls to 0.00% or below."],
            "invalidation_conditions": [
                "Gold regains leadership over silver.",
                "Both copper proxies lose relative strength.",
            ],
            "signal_type": "Industrial metals rotation",
            "ai_confirmation": "Confirmed",
            "stance": "risk-on",
            "change": "improving",
            "decision_conviction": "high",
            "data_quality": "high",
            "confidence": "high",
        }

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output_dir = root / "output"
            output_dir.mkdir()
            previous_path = output_dir / "weekly_metals_rotation_watch_2026-10-01_1100_AM_ET.txt"
            latest_path = output_dir / "weekly_metals_rotation_watch_2026-10-08_1100_AM_ET.txt"
            previous_path.write_text("legacy-compatible report text", encoding="utf-8")
            latest_path.write_text("legacy-compatible report text", encoding="utf-8")
            previous_path.with_suffix(".json").write_text(json.dumps(previous), encoding="utf-8")
            latest_path.with_suffix(".json").write_text(json.dumps(latest), encoding="utf-8")
            os.utime(previous_path, (1_000, 1_000))
            os.utime(latest_path, (2_000, 2_000))

            comparison = compare_reports.compare_latest(root)

        self.assertIn("| Model Decision | Hold / Maintain | Add / Increase |", comparison)
        self.assertIn("- Decision changed: Yes - Hold / Maintain -> Add / Increase", comparison)
        self.assertIn("- Decision conviction changed: Yes - medium -> high", comparison)
        self.assertIn("- Data quality changed: No - high", comparison)
        self.assertIn("- Main upgrade driver: Leadership broadens. (previously: SLV/SPY", comparison)
        self.assertIn("- Main escalation risk: SLV/SPY falls to 0.00% or below.", comparison)
        self.assertIn("- New invalidation condition: Both copper proxies lose relative strength.", comparison)

    def test_load_report_falls_back_to_decision_layer_text(self) -> None:
        text = """Date: 2026-10-08
Run Time: 11:00 AM ET

## Decision Layer
- Model decision: Hold / Maintain
- Target bias: Neutral
- Positioning action: Maintain the current sleeve near a Neutral target.
- Primary reason: Weekly momentum is weakening.
- Invalidation: Both copper proxies lose relative strength.
- Decision conviction: medium
- Data quality: high

## Upgrade Conditions
- Exact rule: Full confirmation.
- 1w relative momentum improves.

## Escalation And Invalidation Rules
### Escalation
- SLV/SPY falls to 0.00% or below.
### Invalidation
- Both copper proxies lose relative strength.
"""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "report.txt"
            path.write_text(text, encoding="utf-8")
            report = compare_reports._load_report(path)

        self.assertEqual(report["model_decision"], "Hold / Maintain")
        self.assertEqual(report["upgrade_triggers"], ["1w relative momentum improves."])


if __name__ == "__main__":
    unittest.main()
