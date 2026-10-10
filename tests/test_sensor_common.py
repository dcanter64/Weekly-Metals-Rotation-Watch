import re
import unittest

from automation.sensor_common import (
    change_from_scores,
    confidence_from_ok,
    et_date_time,
    fmt_pct,
    fmt_ret_pair,
    rotation_summary_block,
    stance_from_score,
)


class SensorCommonTests(unittest.TestCase):
    def test_format_helpers(self) -> None:
        self.assertEqual(fmt_pct(1.234), "+1.23%")
        self.assertEqual(fmt_pct(None), "unavailable")
        self.assertEqual(fmt_ret_pair(1.2, -3.4), "+1.20%/-3.40%")
        self.assertEqual(fmt_ret_pair(None, -3.4), "unavailable/unavailable")

    def test_stance_and_change_helpers(self) -> None:
        self.assertEqual(stance_from_score(2), "risk-on")
        self.assertEqual(stance_from_score(-2), "risk-off")
        self.assertEqual(stance_from_score(0), "neutral")
        self.assertEqual(change_from_scores(3, 1), "improving")
        self.assertEqual(change_from_scores(0, 2), "weakening")
        self.assertEqual(change_from_scores(2, 1), "unchanged")

    def test_confidence_helper(self) -> None:
        self.assertEqual(confidence_from_ok(7, 7), "high")
        self.assertEqual(confidence_from_ok(5, 7), "medium")
        self.assertEqual(confidence_from_ok(2, 7), "low")

    def test_rotation_summary_block_contains_required_fields(self) -> None:
        text = rotation_summary_block(
            stance="neutral",
            change="unchanged",
            evidence=["a", "b", "c"],
            action="watch",
            confidence="medium",
            data_quality="high",
        )
        self.assertIn("## Rotation Summary", text)
        self.assertIn("Current stance: neutral", text)
        self.assertIn("Decision conviction: medium", text)
        self.assertIn("Data quality: high", text)

    def test_et_date_time_shape(self) -> None:
        d, t = et_date_time()
        self.assertRegex(d, r"^\d{4}-\d{2}-\d{2}$")
        self.assertRegex(t, r"^\d{1,2}:\d{2} [AP]M ET$")


if __name__ == "__main__":
    unittest.main()
