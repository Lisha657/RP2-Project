import json
from pathlib import Path

from github_integration import fetch_repository_files
from data_quality import check_data_quality
from sql_testing import test_sql_file
from data_validation import validate_kpi
from report_generator import generate_report


def run_github_tests(repo_url):
    """Download repository files, test them, and generate a report."""

    downloaded_files = fetch_repository_files(repo_url)

    csv_files = [
        file_path for file_path in downloaded_files
        if Path(file_path).suffix.lower() == ".csv"
    ]

    sql_files = [
        file_path for file_path in downloaded_files
        if Path(file_path).suffix.lower() == ".sql"
    ]

    # Run data-quality checks on downloaded CSV files.
    data_results = [
        check_data_quality(file_path)
        for file_path in csv_files
    ]

    # Run SQL validation on downloaded SQL files.
    sql_results = [
        test_sql_file(file_path)
        for file_path in sql_files
    ]

    # Combine the results from multiple CSV and SQL files.
    combined_data = {
        "status": (
            "success"
            if data_results
            and all(r.get("status") == "success" for r in data_results)
            else "error"
        ),
        "files_tested": len(data_results),
        "file_results": data_results,
        "missing_values": {},
        "duplicate_rows": 0,
    }

    for result in data_results:
        for column, count in result.get("missing_values", {}).items():
            combined_data["missing_values"][column] = (
                combined_data["missing_values"].get(column, 0) + count
            )

        combined_data["duplicate_rows"] += result.get("duplicate_rows", 0)

    combined_sql = {
    "status": (
        "success"
        if sql_results
        and all(
            r.get("status") == "success"
            or (
                r.get("status") == "failed"
                and r.get("total_statements", 0) == 0
                and r.get("message") == "The SQL file is empty."
            )
            for r in sql_results
        )
        else "failed"
    ),
        "files_tested": len(sql_results),
        "total_statements": sum(
            r.get("total_statements", 0) for r in sql_results
        ),
        "passed_statements": sum(
            r.get("passed_statements", 0) for r in sql_results
        ),
        "failed_statements": sum(
            r.get("failed_statements", 0) for r in sql_results
        ),
        "file_results": sql_results,
    }

    # Find a downloaded CSV with a numeric sales column.
    sales_file = next(
        (
            file_path for file_path in csv_files
            if "sales" in Path(file_path).name.lower()
        ),
        None,
    )

    if sales_file:
        kpi_result = validate_kpi(
            file_path=sales_file,
            column="sales",
            expected_value=1700,
            operation="sum",
        )
    else:
        kpi_result = {
            "status": "error",
            "message": "No sales CSV file was found for KPI validation.",
        }

    # Generate the consolidated report using the existing report generator.
    report = generate_report(
        data_quality=combined_data,
        sql_testing=combined_sql,
        kpi_validation=kpi_result,
        output_file="github_test_report.json",
    )

    report["repository_url"] = repo_url
    report["downloaded_file_count"] = len(downloaded_files)
    report["downloaded_files"] = [
        str(Path(file_path)) for file_path in downloaded_files
    ]

    # Save the report with repository details.
    Path("github_test_report.json").write_text(
        json.dumps(report, indent=4, default=str),
        encoding="utf-8",
    )

    return report


if __name__ == "__main__":
    repository_url = input(
        "Enter the public GitHub repository URL: "
    ).strip()

    try:
        report = run_github_tests(repository_url)

        print("\nTesting completed.")
        print("Overall status:", report["overall_status"])
        print("Report saved to github_test_report.json")
        print(json.dumps(report["summary"], indent=4))

    except Exception as error:
        print(f"\nTesting failed: {error}")