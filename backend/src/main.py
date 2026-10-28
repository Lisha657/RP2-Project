from data_quality import check_data_quality
from sql_testing import test_sql_file
from data_validation import validate_kpi
from report_generator import generate_report


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

    kpi_results = validate_kpi(
        file_path="test_data/sales.csv",
        column="sales",
        expected_value=1700,
        operation="sum"
    )
    print_report("KPI VALIDATION REPORT", kpi_results)

    generate_report(
        data_quality=data_results,
        sql_testing=sql_results,
        kpi_validation=kpi_results
    )

    print("\nConsolidated report saved to test_report.json")


if __name__ == "__main__":
    main()
