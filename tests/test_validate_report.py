from pathlib import Path
import unittest

from automation import validate_report


class ReportValidationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        root = Path(__file__).resolve().parents[1]
        cls.sample = (root / "sample_output" / "fresh_local_sample_output.txt").read_text(encoding="utf-8")

    def test_current_sample_passes_validation(self) -> None:
        self.assertEqual(validate_report.validate_text(self.sample), [])

    def test_decision_layer_is_required(self) -> None:
        without_decision_layer = self.sample.replace("## Decision Layer", "## Legacy Decision Summary", 1)
        self.assertIn("## Decision Layer", validate_report.validate_text(without_decision_layer))

    def test_each_decision_field_is_required(self) -> None:
        without_invalidation = self.sample.replace("- Invalidation:", "- Legacy invalidation:", 1)
        self.assertIn("- Invalidation:", validate_report.validate_text(without_invalidation))


if __name__ == "__main__":
    unittest.main()
