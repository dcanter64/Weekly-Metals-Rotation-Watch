import csv
import json
from pathlib import Path
import tempfile
import unittest

from automation import metals_rotation_watch as watch
from automation.sensor_common import Metrics


class ReportLogicTests(unittest.TestCase):
    def _structured_decision(self, **overrides: object) -> dict[str, object]:
        inputs: dict[str, object] = {
            "signal_type": "Industrial metals rotation",
            "ai_confirmation": "Confirmed",
            "confidence": "high",
            "slv_spy": 2.0,
            "copx_spy": 1.0,
            "cper_spy": 0.5,
            "gld_slv": -1.0,
            "xme_spy": 0.5,
            "setm_spy": -0.5,
            "relative_momentum": "improving",
        }
        inputs.update(overrides)
        return watch._decision_output(**inputs)

    def test_structured_decision_confirmed_risk_on(self) -> None:
        decision = self._structured_decision()
        self.assertTrue(
            {
                "model_decision",
                "exposure_bias",
                "positioning_action",
                "primary_reason",
                "upgrade_rule",
                "upgrade_triggers",
                "downgrade_triggers",
                "invalidation_conditions",
                "current_conditions",
                "bullish_gates_passed",
                "nearest_upgrade_gate",
                "decision_conviction",
                "data_quality",
                "confidence",
                "rule_inputs",
            }.issubset(decision),
        )
        self.assertEqual(decision["model_decision"], "Add / Increase")
        self.assertEqual(decision["exposure_bias"], "Overweight")
        self.assertEqual(decision["confidence"], "high")
        self.assertEqual(decision["decision_conviction"], "high")
        self.assertEqual(decision["data_quality"], "high")
        self.assertIn("Increase toward Overweight", decision["positioning_action"])
        self.assertTrue(decision["rule_inputs"]["slv_spy_above_zero"])
        self.assertTrue(decision["rule_inputs"]["copper_confirmation"])
        self.assertTrue(decision["rule_inputs"]["gld_slv_below_zero"])

    def test_structured_decision_resolves_weakening_weekly_conflict(self) -> None:
        decision = self._structured_decision(relative_momentum="weakening")
        self.assertEqual(decision["model_decision"], "Hold / Maintain")
        self.assertEqual(decision["exposure_bias"], "Neutral")
        self.assertEqual(decision["confidence"], "medium")
        self.assertIn("1w relative momentum is weakening", decision["primary_reason"])

    def test_add_decision_requires_two_consecutive_observations(self) -> None:
        raw_decision = self._structured_decision()
        first_observation = watch._apply_decision_persistence(raw_decision, None)
        second_observation = watch._apply_decision_persistence(
            raw_decision,
            {"model_decision": "Add / Increase"},
        )
        self.assertEqual(first_observation["model_decision"], "Hold / Maintain")
        self.assertEqual(first_observation["exposure_bias"], "Neutral")
        self.assertIn("second consecutive weekly observation", first_observation["primary_reason"])
        self.assertEqual(second_observation["model_decision"], "Add / Increase")

    def test_structured_decision_improving_but_not_confirmed(self) -> None:
        decision = self._structured_decision(
            signal_type="Mixed / no clear signal",
            ai_confirmation="Improving but not confirmed",
            slv_spy=-0.5,
            copx_spy=-0.2,
            gld_slv=0.5,
        )
        self.assertEqual(decision["model_decision"], "Hold / Maintain")
        self.assertEqual(decision["exposure_bias"], "Watch")
        self.assertIn("SLV/SPY moves above 0.00%.", decision["upgrade_triggers"])

    def test_breadth_triggers_are_complementary_when_breadth_fails(self) -> None:
        # Breadth currently failing: the upgrade list names the breadth fix,
        # so the escalation list must not also name breadth as a future
        # trigger -- it describes the current state, not a deterioration.
        decision = self._structured_decision(
            signal_type="Mixed / no clear signal",
            ai_confirmation="Improving but not confirmed",
            slv_spy=-0.5,
            copx_spy=-0.2,
            cper_spy=None,
            gld_slv=0.5,
            xme_spy=-1.0,
            setm_spy=None,
            relative_momentum="improving",
        )
        self.assertEqual(decision["model_decision"], "Hold / Maintain")
        self.assertIs(decision["rule_inputs"]["materials_breadth_above_zero"], False)
        self.assertIn(
            "XME/SPY or SETM/SPY moves above 0.00%.",
            decision["upgrade_triggers"],
        )
        self.assertFalse(
            any(
                "materials breadth proxy remains above" in item
                for item in decision["downgrade_triggers"]
            ),
            "breadth escalation trigger must not appear while breadth is failing",
        )

    def test_breadth_downgrade_trigger_listed_when_breadth_passes(self) -> None:
        # Breadth currently passing: the escalation list watches for its loss.
        decision = self._structured_decision()
        self.assertEqual(decision["model_decision"], "Add / Increase")
        self.assertTrue(decision["rule_inputs"]["materials_breadth_above_zero"])
        self.assertIn(
            "No available materials breadth proxy remains above 0.00%.",
            decision["downgrade_triggers"],
        )

    def test_downgrade_triggers_hide_already_tripped_conditions(self) -> None:
        # Hold with every rule failing: only genuinely future deterioration
        # may appear as an escalation trigger.
        decision = self._structured_decision(
            signal_type="Mixed / no clear signal",
            ai_confirmation="Improving but not confirmed",
            slv_spy=-0.5,
            copx_spy=-0.2,
            cper_spy=None,
            gld_slv=0.5,
            xme_spy=-1.0,
            setm_spy=None,
            relative_momentum="improving",
        )
        self.assertEqual(decision["model_decision"], "Hold / Maintain")
        self.assertEqual(
            decision["downgrade_triggers"], ["1w relative momentum weakens."]
        )
        self.assertEqual(
            decision["upgrade_triggers"],
            [
                "SLV/SPY moves above 0.00%.",
                "COPX/SPY or CPER/SPY moves above 0.00%.",
                "GLD/SLV moves below 0.00% to confirm silver leadership.",
                "XME/SPY or SETM/SPY moves above 0.00%.",
            ],
        )

    def test_downgrade_triggers_fallback_when_everything_tripped(self) -> None:
        # Hold with every rule failing and momentum already weakening: the
        # list must not be empty (the report header prints the first trigger).
        decision = self._structured_decision(
            signal_type="Mixed / no clear signal",
            ai_confirmation="Improving but not confirmed",
            slv_spy=-0.5,
            copx_spy=-0.2,
            cper_spy=None,
            gld_slv=0.5,
            xme_spy=-1.0,
            setm_spy=None,
            relative_momentum="weakening",
        )
        self.assertEqual(decision["model_decision"], "Hold / Maintain")
        self.assertEqual(
            decision["downgrade_triggers"],
            [
                "No escalation triggers currently active; "
                "all watched conditions have already tripped."
            ],
        )

    def test_downgrade_triggers_show_all_when_rules_pass(self) -> None:
        # Add / Increase: every rule passes, so every escalation trigger is a
        # genuine future risk and the list is unchanged from before.
        decision = self._structured_decision()
        self.assertEqual(decision["model_decision"], "Add / Increase")
        self.assertEqual(
            decision["downgrade_triggers"],
            [
                "SLV/SPY falls to 0.00% or below.",
                "Both COPX/SPY and CPER/SPY fall to 0.00% or below.",
                "GLD/SLV rises to 0.00% or above.",
                "No available materials breadth proxy remains above 0.00%.",
                "1w relative momentum weakens.",
            ],
        )

    def test_missing_data_keeps_both_trigger_lists(self) -> None:
        # Missing data is not "already tripped": both directions stay listed.
        decision = self._structured_decision(
            signal_type="Mixed / no clear signal",
            ai_confirmation="Improving but not confirmed",
            slv_spy=None,
            copx_spy=-0.2,
            cper_spy=None,
            gld_slv=0.5,
            xme_spy=-1.0,
            setm_spy=None,
            relative_momentum="improving",
        )
        self.assertIsNone(decision["rule_inputs"]["slv_spy_above_zero"])
        self.assertIn("SLV/SPY moves above 0.00%.", decision["upgrade_triggers"])
        self.assertIn(
            "SLV/SPY falls to 0.00% or below.", decision["downgrade_triggers"]
        )

    def test_structured_decision_defensive_gold_led_tape(self) -> None:
        decision = self._structured_decision(
            signal_type="Gold-led defensive tape",
            ai_confirmation="Not confirmed",
            slv_spy=-2.0,
            copx_spy=-3.0,
            cper_spy=-1.0,
            gld_slv=5.0,
            relative_momentum="weakening",
        )
        self.assertEqual(decision["model_decision"], "Trim / Reduce")
        self.assertEqual(decision["exposure_bias"], "Underweight")
        self.assertIn("Reduce to Underweight if currently Neutral/Overweight", decision["positioning_action"])
        self.assertTrue(any("SLV/SPY is at or below" in item for item in decision["current_conditions"]))
        self.assertTrue(decision["downgrade_triggers"][0].startswith("Escalate to De-risk"))
        self.assertIn("relative defensive leader", decision["primary_reason"])

    def test_structured_decision_broad_metals_weakness(self) -> None:
        decision = self._structured_decision(
            signal_type="Broad metals weakness",
            ai_confirmation="Not confirmed",
            slv_spy=-4.0,
            copx_spy=-5.0,
            cper_spy=-3.0,
            gld_slv=2.0,
            xme_spy=-4.0,
            setm_spy=-2.0,
            relative_momentum="weakening",
        )
        self.assertEqual(decision["model_decision"], "Avoid / Watchlist Only")
        self.assertEqual(decision["exposure_bias"], "Avoid")

    def test_structured_decision_allows_missing_optional_tickers(self) -> None:
        decision = self._structured_decision(xme_spy=None, setm_spy=None)
        self.assertEqual(decision["model_decision"], "Add / Increase")
        self.assertEqual(decision["confidence"], "high")
        self.assertIsNone(decision["rule_inputs"]["materials_breadth_above_zero"])

    def test_decision_taxonomy_defines_allowed_values(self) -> None:
        self.assertEqual(
            watch.MODEL_DECISIONS,
            (
                "Add / Increase",
                "Hold / Maintain",
                "Trim / Reduce",
                "Avoid / Watchlist Only",
                "De-risk",
            ),
        )
        self.assertEqual(
            watch.EXPOSURE_BIASES,
            ("Overweight", "Neutral", "Underweight", "Avoid", "Watch"),
        )

    def test_decision_taxonomy_maps_confirmed_industrial_rotation(self) -> None:
        decision = watch._decision_taxonomy("Industrial metals rotation", "Confirmed")
        self.assertEqual(decision, ("Add / Increase", "Overweight"))

    def test_decision_taxonomy_maps_improving_state(self) -> None:
        decision = watch._decision_taxonomy("Mixed / no clear signal", "Improving but not confirmed")
        self.assertEqual(decision, ("Hold / Maintain", "Watch"))

    def test_decision_taxonomy_maps_gold_led_tape(self) -> None:
        decision = watch._decision_taxonomy("Gold-led defensive tape", "Not confirmed")
        self.assertEqual(decision, ("Trim / Reduce", "Underweight"))

    def test_decision_taxonomy_maps_broad_weakness(self) -> None:
        decision = watch._decision_taxonomy("Broad metals weakness", "Not confirmed")
        self.assertEqual(decision, ("Avoid / Watchlist Only", "Avoid"))

    def test_decision_taxonomy_gives_risk_off_precedence(self) -> None:
        decision = watch._decision_taxonomy("Industrial metals rotation", "Weak / risk-off")
        self.assertEqual(decision, ("De-risk", "Avoid"))

    def test_executive_read_leaves_action_in_decision_layer(self) -> None:
        lines = watch._executive_read(
            change="unchanged",
            signal_type="Industrial metals rotation",
            slv_spy=2.0,
            copx_spy=1.0,
            gld_slv=-1.0,
            dbc_spy=0.5,
        )
        self.assertEqual(len(lines), 3)
        self.assertFalse(any("Action:" in line for line in lines))

    def test_score_favors_cyclical_leadership(self) -> None:
        score = watch._score(copx_spy=2.0, slv_spy=1.0, gld_slv=-3.0, gld_spy=-1.0)
        self.assertEqual(score, 3)

    def test_score_penalizes_gold_led_defensive_mix(self) -> None:
        score = watch._score(copx_spy=-2.0, slv_spy=-1.0, gld_slv=4.0, gld_spy=1.0)
        self.assertEqual(score, -4)

    def test_signal_type_detects_gold_led_tape(self) -> None:
        signal = watch._signal_type(
            gld_m=2.0,
            slv_m=-5.0,
            copx_m=-6.0,
            cper_m=-1.0,
            dbc_m=1.0,
            xme_m=None,
            setm_m=None,
            slv_spy=-4.0,
            copx_spy=-5.0,
            cper_spy=-1.0,
            dbc_spy=1.0,
            gld_slv=7.0,
        )
        self.assertEqual(signal, "Gold-led defensive tape")

    def test_report_omits_missing_optional_tickers(self) -> None:
        payload = {
            "tickers": {
                "GLD": {"ok": True, "last": 100.0, "w": 1.0, "m": 2.0, "q": 3.0},
                "SLV": {"ok": True, "last": 20.0, "w": 2.0, "m": 3.0, "q": 4.0},
                "COPX": {"ok": True, "last": 40.0, "w": 1.0, "m": 1.0, "q": 2.0},
                "CPER": {"ok": True, "last": 30.0, "w": 1.0, "m": 2.0, "q": 3.0},
                "DBC": {"ok": True, "last": 25.0, "w": 1.0, "m": 2.0, "q": 3.0},
                "SPY": {"ok": True, "last": 500.0, "w": 0.5, "m": 1.0, "q": 2.0},
                "QQQ": {"ok": True, "last": 450.0, "w": 0.4, "m": 1.2, "q": 2.2},
            },
            "ratios_1m": {
                "GLD/SPY": 1.0,
                "SLV/SPY": 2.0,
                "COPX/SPY": 1.0,
                "CPER/SPY": 1.0,
                "DBC/SPY": 1.0,
                "GLD/SLV": -1.0,
                "COPX/CPER": 0.0,
                "GLD/QQQ": 0.5,
                "SLV/QQQ": 0.5,
                "COPX/QQQ": 0.5,
                "CPER/QQQ": 0.5,
                "DBC/QQQ": 0.5,
            },
        }
        previous_state = {
            "date": "2026-07-13",
            "run_time": "4:18 PM ET",
            "model_decision": "Add / Increase",
            "rule_values": {"SLV/SPY": 1.0, "COPX/SPY": 0.5, "GLD/SLV": -0.5},
        }
        text = watch.build_report_text(
            Metrics(payload),
            "2026-07-20",
            "4:18 PM ET",
            previous_state=previous_state,
        )
        self.assertLess(text.index("## Decision Layer"), text.index("## Executive Read"))
        self.assertIn("- Model decision: Add / Increase", text)
        self.assertIn("- Target bias: Overweight", text)
        self.assertIn("- Positioning action: Increase toward Overweight", text)
        self.assertIn("- Tactical view: Overweight over 1-4 weeks.", text)
        self.assertIn("- Structural view: Constructive", text)
        self.assertIn("- Primary reason:", text)
        self.assertIn("- Core bullish rules: 3 of 4 passed", text)
        self.assertIn("- Exact rule:", text)
        self.assertIn("- Escalation trigger:", text)
        self.assertIn("- Invalidation:", text)
        self.assertIn("- Decision conviction: high", text)
        self.assertIn("- Data quality: high", text)
        self.assertIn("## Executive Read", text)
        self.assertIn("## Ticker Detail", text)
        self.assertIn("## Change Since Previous Report", text)
        self.assertIn("previous report from 2026-07-13 at 4:18 PM ET", text)
        self.assertIn("| SLV/SPY | +1.00% | +2.00% | +1.00% |", text)
        self.assertIn("| Model decision | Add / Increase | Add / Increase | unchanged |", text)
        self.assertIn("## Decision Trigger Matrix", text)
        self.assertIn("| Condition | Current | Threshold | Gap | Status | Rule role |", text)
        self.assertIn("## Current Bearish Conditions", text)
        self.assertIn("## Escalation And Invalidation Rules", text)
        self.assertIn("Action implication: Increase toward Overweight", text)
        self.assertIn("## Commodity Context", text)
        leadership_section = text.split("## Metals Leadership Hierarchy", 1)[1].split("## Commodity Context", 1)[0]
        self.assertNotIn("DBC -", leadership_section)
        self.assertNotIn("## What Would Improve the Signal", text)
        self.assertNotIn("## What Would Keep the Signal Weak", text)
        self.assertIn("| GLD |", text)
        self.assertNotIn("| XME |", text)
        self.assertNotIn("| SETM |", text)

    def test_trigger_matrix_includes_current_levels_and_thresholds(self) -> None:
        matrix = watch._trigger_matrix(
            slv_spy=-1.2,
            copx_spy=-2.3,
            cper_spy=0.4,
            gld_slv=3.5,
            xme_spy=None,
            setm_spy=-4.0,
            relative_momentum="improving",
        )
        self.assertIn("| SLV/SPY | -1.20% | > 0.00% | 1.20 pp needed | Fail | Required |", matrix)
        self.assertTrue(any("CPER/SPY | +0.40%" in line and "| Pass |" in line for line in matrix))
        self.assertTrue(any("XME unavailable; SETM -4.00%" in line for line in matrix))
        self.assertTrue(any("1w relative momentum | improving" in line for line in matrix))

    def test_sidecars_include_structured_decision_history(self) -> None:
        root = Path(__file__).resolve().parents[1]
        report_text = (root / "sample_output" / "fresh_local_sample_output.txt").read_text(encoding="utf-8")
        with tempfile.TemporaryDirectory() as tmp:
            output_path = Path(tmp) / "weekly_metals_rotation_watch_2026-07-20_435_PM_ET.txt"
            watch._write_sidecars(output_path, report_text, "2026-07-20", "4:35 PM ET")

            json_payload = json.loads(output_path.with_suffix(".json").read_text(encoding="utf-8"))
            self.assertEqual(json_payload["model_decision"], "Trim / Reduce")
            self.assertEqual(json_payload["exposure_bias"], "Underweight")
            self.assertIsInstance(json_payload["upgrade_triggers"], list)
            self.assertEqual(json_payload["decision_rules"][0]["condition"], "SLV/SPY")
            self.assertEqual(json_payload["decision_rules"][0]["threshold"], "> 0.00%")

            with output_path.with_suffix(".csv").open(newline="", encoding="utf-8") as csv_file:
                csv_payload = next(csv.DictReader(csv_file))
            self.assertEqual(csv_payload["model_decision"], "Trim / Reduce")
            self.assertIsInstance(json.loads(csv_payload["downgrade_triggers"]), list)
            self.assertEqual(json.loads(csv_payload["decision_rules"])[0]["condition"], "SLV/SPY")

    def test_contradiction_notes_call_out_dbc_strength(self) -> None:
        notes = watch._contradiction_notes(
            dbc_m=5.0,
            dbc_spy=6.0,
            cper_m=-1.0,
            cper_spy=-0.5,
            slv_spy=-3.0,
            copx_spy=-4.0,
        )
        self.assertTrue(any("DBC is strong" in note for note in notes))


if __name__ == "__main__":
    unittest.main()
