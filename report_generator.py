import json
from datetime import datetime


def generate_report(
    data_quality,
    sql_testing,
    kpi_validation,
    output_file="test_report.json"
):
    """Generate a consolidated report from all testing modules."""

    # Count data quality issues
    missing_values = data_quality.get("missing_values", {})
    duplicate_rows = data_quality.get("duplicate_rows", 0)
    data_quality_issue_count = (
        sum(missing_values.values()) + duplicate_rows
    )

    # Summarize SQL test results
    sql_total = sql_testing.get("total_statements", 0)
    sql_passed = sql_testing.get("passed_statements", 0)
    sql_failed = sql_testing.get("failed_statements", 0)

    # Determine individual module outcomes
    data_status = (
        "passed"
        if data_quality.get("status") == "success"
        and data_quality_issue_count == 0
        else "issues_found"
    )

    sql_status = (
        "passed"
        if sql_testing.get("status") == "success"
        and sql_failed == 0
        else "failed"
    )

    kpi_status = (
        "passed"
        if kpi_validation.get("status") == "passed"
        else "failed"
    )

    # Determine overall result
    if "failed" in (sql_status, kpi_status):
        overall_status = "FAILED"
    elif data_status == "issues_found":
        overall_status = "COMPLETED WITH ISSUES"
    else:
        overall_status = "PASSED"

    report = {
        "project": "AI-Powered Power BI Dashboard Testing Agent",
        "generated_at": datetime.now().astimezone().isoformat(
            timespec="seconds"
        ),
        "overall_status": overall_status,
        "summary": {
            "data_quality_status": data_status,
            "data_quality_issue_count": data_quality_issue_count,
            "missing_value_count": sum(missing_values.values()),
            "duplicate_row_count": duplicate_rows,
            "sql_testing_status": sql_status,
            "sql_total_statements": sql_total,
            "sql_passed_statements": sql_passed,
            "sql_failed_statements": sql_failed,
            "kpi_validation_status": kpi_status,
            "kpi_expected_value": kpi_validation.get("expected_value"),
            "kpi_actual_value": kpi_validation.get("actual_value")
        },
        "results": {
            "data_quality": data_quality,
            "sql_testing": sql_testing,
            "kpi_validation": kpi_validation
        }
    }

    with open(output_file, "w", encoding="utf-8") as file:
        json.dump(report, file, indent=4, default=str)

    return report
