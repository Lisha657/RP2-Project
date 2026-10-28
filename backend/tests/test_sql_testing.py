import unittest
import os
import tempfile
from sql_testing import test_sql_query, test_sql_file


class TestSQLTesting(unittest.TestCase):

    def test_valid_query(self):
        result = test_sql_query(
            "SELECT customer FROM orders"
        )
        self.assertTrue(result["syntax_valid"])
        self.assertEqual(result["status"], "success")

    def test_invalid_query(self):
        result = test_sql_query(
            "SELEC customer FROM orders"
        )
        self.assertEqual(result["status"], "failed")

    def test_empty_sql_file(self):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".sql", delete=False
        ) as file:
            file_path = file.name

        try:
            result = test_sql_file(file_path)
            self.assertEqual(result["status"], "failed")
            self.assertEqual(result["total_statements"], 0)
        finally:
            os.remove(file_path)

    def test_missing_sql_file(self):
        result = test_sql_file(
            "test_data/file_that_does_not_exist.sql"
        )
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["total_statements"], 0)


if __name__ == "__main__":
    unittest.main()