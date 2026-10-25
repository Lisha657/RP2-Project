import unittest
import os
import tempfile
import pandas as pd
from data_quality import check_data_quality


class TestDataQuality(unittest.TestCase):

    def setUp(self):
        self.temp_file = tempfile.NamedTemporaryFile(
            suffix=".csv", delete=False
        )
        self.temp_file.close()

    def tearDown(self):
        if os.path.exists(self.temp_file.name):
            os.remove(self.temp_file.name)

    def test_clean_data(self):
        df = pd.DataFrame({
            "name": ["Alice", "Bob"],
            "sales": [100, 200]
        })
        df.to_csv(self.temp_file.name, index=False)

        result = check_data_quality(self.temp_file.name)

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["total_rows"], 2)
        self.assertEqual(result["duplicate_rows"], 0)
        self.assertEqual(result["missing_values"], {})

    def test_missing_values(self):
        df = pd.DataFrame({
            "name": ["Alice", None],
            "sales": [100, 200]
        })
        df.to_csv(self.temp_file.name, index=False)

        result = check_data_quality(self.temp_file.name)

        self.assertEqual(result["missing_values"], {"name": 1})

    def test_duplicate_rows(self):
        df = pd.DataFrame({
            "name": ["Alice", "Alice"],
            "sales": [100, 100]
        })
        df.to_csv(self.temp_file.name, index=False)

        result = check_data_quality(self.temp_file.name)

        self.assertEqual(result["duplicate_rows"], 1)

    def test_missing_file(self):
        result = check_data_quality(
            "test_data/file_that_does_not_exist.csv"
        )

        self.assertEqual(result["status"], "error")


if __name__ == "__main__":
    unittest.main()
