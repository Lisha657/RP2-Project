from data_quality import check_data_quality
from sql_testing import test_sql_file


def print_report(title, results):
    print(f"\n{title}")
    print("=" * 40)

    for key, value in results.items():
        print(f"{key}: {value}")


def main():
    data_results = check_data_quality("test_data/sales.csv")
    print_report("DATA QUALITY TEST REPORT", data_results)

    sql_results = test_sql_file("test_data/sample_queries.sql")
    print_report("SQL TEST REPORT", sql_results)


if __name__ == "__main__":
    main()
