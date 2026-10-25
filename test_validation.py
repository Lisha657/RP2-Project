import unittest
from data_validation import validate_kpi


class TestKPIValidation(unittest.TestCase):

    def test_correct_kpi(self):
        result = validate_kpi(
            "test_data/sales.csv", "sales", 1700
        )
        self.assertEqual(result["status"], "passed")

    def test_incorrect_kpi(self):
        result = validate_kpi(
            "test_data/sales.csv", "sales", 1600
        )
        self.assertEqual(result["status"], "failed")

    def test_missing_column(self):
        result = validate_kpi(
            "test_data/sales.csv", "revenue", 1000
        )
        self.assertEqual(result["status"], "error")

    def test_unsupported_operation(self):
        result = validate_kpi(
            "test_data/sales.csv",
            "sales",
            1700,
            operation="median"
        )
        self.assertEqual(result["status"], "error")


if __name__ == "__main__":
    unittest.main()
