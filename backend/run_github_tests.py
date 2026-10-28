import sys
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent
SRC_DIR = PROJECT_ROOT / "src"
DOWNLOAD_DIR = PROJECT_ROOT / "downloaded_repo"

for folder in [
    "github",
    "data_testing",
    "sql_testing",
]:
    sys.path.insert(0, str(SRC_DIR / folder))

from github_integration import fetch_dataset_url, fetch_sql_url
from data_quality import check_data_quality
from sql_testing import test_sql_file


def main():
    csv_url = input("Enter the CSV dataset URL: ").strip()
    sql_url = input("Enter the SQL file URL: ").strip()

    try:
        # Download the CSV and SQL files
        csv_file = fetch_dataset_url(
            csv_url,
            output_dir=str(DOWNLOAD_DIR),
        )

        sql_file = fetch_sql_url(
            sql_url,
            output_dir=str(DOWNLOAD_DIR),
        )

        # TEST 1: DATA QUALITY
        print("\n========== DATA QUALITY TEST ==========")

        quality_result = check_data_quality(csv_file)
        print(quality_result)

        # TEST 2: SQL TESTING
        print("\n========== SQL TEST ==========")

        sql_result = test_sql_file(sql_file)
        print(sql_result)

        # TEST 3: KPI CALCULATIONS
        print("\n========== KPI TEST ==========")

        df = pd.read_csv(csv_file)
        numeric_columns = df.select_dtypes(
            include="number"
        ).columns

        if len(numeric_columns) == 0:
            print("No numeric columns found for KPI calculations.")
        else:
            for column in numeric_columns:
                total = df[column].sum()
                average = df[column].mean()
                count = df[column].count()

                print(f"\nColumn: {column}")
                print(f"Total (Sum): {total:.2f}")
                print(f"Average (Mean): {average:.2f}")
                print(f"Count: {count}")

        print("\n========== TESTING COMPLETED ==========")

    except Exception as error:
        print(f"\nTesting failed: {error}")


if __name__ == "__main__":
    main()