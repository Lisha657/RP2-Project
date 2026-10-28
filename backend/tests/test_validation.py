import unittest
from pathlib import Path

from data_validation import validate_kpi

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SALES_FILE = PROJECT_ROOT / "test_data" / "sales.csv"


class TestKPIValidation(unittest.TestCase):

    def test_correct_kpi(self):
        result = validate_kpi(
            str(SALES_FILE), "sales", 1700
        )
        self.assertEqual(result["status"], "passed")

    def test_incorrect_kpi(self):
        result = validate_kpi(
            str(SALES_FILE), "sales", 1600
        )
        self.assertEqual(result["status"], "failed")

    def test_missing_column(self):
        result = validate_kpi(
            str(SALES_FILE), "revenue", 1000
        )
        self.assertEqual(result["status"], "error")

    def test_unsupported_operation(self):
        result = validate_kpi(
            str(SALES_FILE),
            "sales",
            1700,
            operation="median"
        )
        self.assertEqual(result["status"], "error")


if __name__ == "__main__":
    unittest.main()