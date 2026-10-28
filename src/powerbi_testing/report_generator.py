import json
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

ATTENTION_STATUSES = {"FAIL", "WARNING", "NOT_TESTED"}

STATUS_ORDER = [
    "FAIL",
    "WARNING",
    "NOT_TESTED",
    "NOT_APPLICABLE",
    "INFO",
    "PASS",
]


def load_report(path):
    """Load and validate the JSON testing report."""
    report_path = Path(path)

    if not report_path.is_file():
        raise FileNotFoundError(
            f"JSON report not found: {report_path}"
        )

    try:
        with report_path.open("r", encoding="utf-8") as file:
            report = json.load(file)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"Invalid JSON report: {exc}"
        ) from exc

    if not isinstance(report, dict):
        raise ValueError(
            "The JSON report must contain an object."
        )

    return report


def safe_text(value, default="N/A"):
    """Convert a value to readable text."""
    if value is None or value == "":
        return default

    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)

    return str(value)


def markdown_cell(value):
    """Escape characters that could break a Markdown table."""
    return (
        safe_text(value)
        .replace("|", "\\|")
        .replace("\n", " ")
        .replace("\r", " ")
    )


def get_findings(report):
    """Return normalized findings, excluding Member 1's KPI checks."""
    findings = report.get("findings", [])

    if not isinstance(findings, list):
        return []

    result = []

    for item in findings:
        if not isinstance(item, dict):
            continue

        finding = dict(item)
        finding["status"] = str(
            finding.get("status", "NOT_TESTED")
        ).upper()

        finding.setdefault("check", "Unnamed check")
        finding.setdefault("message", "No details provided.")

        source = str(finding.get("source", "")).lower()
        check = str(finding.get("check", "")).lower()
        category = str(finding.get("category", "")).lower()

        # KPI validation is handled by Member 1.
        if (
            source == "kpi_validation"
            or "kpi_validation" in source
            or "kpi_validation" in check
            or "kpi validation" in category
        ):
            continue

        result.append(finding)

    return result


def get_category(finding):
    """Determine the report category for a finding."""
    check = str(finding.get("check", "")).lower()
    category = str(finding.get("category", "")).strip()
    source = str(finding.get("source", "")).lower()

    if category:
        return category.replace("_", " ").title()

    if "visual" in check or "dashboard" in check:
        return "Dashboard Visuals"

    if "dax" in check or "measure" in check:
        return "DAX and Measures"

    if (
        "relationship" in check
        or "table" in check
        or "model" in check
    ):
        return "Semantic Model"

    if (
        "data_quality" in check
        or "dataset" in check
        or "data quality" in check
        or check in {
            "missing_values",
            "duplicate_rows",
            "empty_rows",
            "empty_columns",
            "invalid_numeric_values",
        }
        or source == "data_quality"
    ):
        return "Data Quality"

    if "requirement" in check:
        return "Requirements"

    if (
        "project" in check
        or "report" in check
        or "json" in check
    ):
        return "Project Files"

    return "Other Checks"


def get_filename(finding):
    """Get the dataset or file associated with a finding."""
    evidence = finding.get("evidence")

    filename = (
        finding.get("file")
        or finding.get("path")
        or finding.get("dataset")
    )

    if not filename and isinstance(evidence, dict):
        filename = (
            evidence.get("file")
            or evidence.get("path")
            or evidence.get("dataset")
        )

    return safe_text(filename, "Dataset not specified")


def is_data_quality_finding(finding):
    """Identify findings related to data quality."""
    check = str(finding.get("check", "")).lower()
    source = str(finding.get("source", "")).lower()
    category = str(finding.get("category", "")).lower()

    return (
        source == "data_quality"
        or "data_quality" in source
        or "data_quality" in check
        or "data quality" in category
        or check in {
            "missing_values",
            "duplicate_rows",
            "empty_rows",
            "empty_columns",
            "invalid_numeric_values",
        }
    )


def missing_value_recommendation(column):
    """Suggest a review based on a column name."""
    name = str(column).lower()

    if "closed_date" in name or "close_date" in name:
        return (
            "Check whether the record is still open; a closing date "
            "may be optional for open records."
        )

    if "due_date" in name:
        return (
            "Confirm whether a due date is required for every record."
        )

    if "owner" in name:
        return (
            "Review whether every record must have an assigned owner."
        )

    if "evidence" in name or "link" in name or "url" in name:
        return (
            "Confirm whether supporting evidence or a link is mandatory."
        )

    if "parent" in name:
        return (
            "Check whether parent references are optional for "
            "top-level records."
        )

    return (
        "Review the business rules to determine whether this value "
        "is allowed to be empty."
    )


def render_missing_values_table(evidence, filename):
    """Render missing-value evidence with affected data-row numbers."""
    if not isinstance(evidence, dict) or not evidence:
        return None

    if not all(
        isinstance(value, dict)
        for value in evidence.values()
    ):
        return None

    if not any(
        "missing_count" in value
        or "missing_percentage" in value
        for value in evidence.values()
    ):
        return None

    lines = [
        "| Dataset | Column | Missing values | Missing % | "
        "Affected data rows | Recommended action |",
        "|---|---|---:|---:|---|---|",
    ]

    for column, details in evidence.items():
        count = details.get("missing_count", "N/A")
        percentage = details.get("missing_percentage")
        row_numbers = details.get("example_data_row_numbers", [])

        if isinstance(percentage, (int, float)):
            percentage_text = f"{percentage:.2f}%"
        else:
            percentage_text = "N/A"

        if isinstance(row_numbers, list) and row_numbers:
            rows_text = ", ".join(
                str(row) for row in row_numbers
            )
        else:
            rows_text = "Not provided"

        recommendation = missing_value_recommendation(column)

        lines.append(
            f"| {markdown_cell(filename)} "
            f"| {markdown_cell(column)} "
            f"| {markdown_cell(count)} "
            f"| {percentage_text} "
            f"| {markdown_cell(rows_text)} "
            f"| {markdown_cell(recommendation)} |"
        )

    return lines


def render_duplicate_rows_table(evidence, filename):
    """Render duplicate-row evidence in a readable table."""
    if not isinstance(evidence, list) or not evidence:
        return None

    if not any(isinstance(item, dict) for item in evidence):
        return None

    lines = [
        "| Dataset | Duplicate data row | Matching original data row(s) |",
        "|---|---:|---|",
    ]

    for item in evidence:
        if not isinstance(item, dict):
            continue

        duplicate_row = item.get(
            "duplicate_data_row_number", "N/A"
        )
        original_rows = item.get(
            "matching_original_data_row_numbers", []
        )

        if isinstance(original_rows, list):
            original_text = (
                ", ".join(str(row) for row in original_rows)
                if original_rows
                else "Not provided"
            )
        else:
            original_text = safe_text(original_rows)

        lines.append(
            f"| {markdown_cell(filename)} "
            f"| {markdown_cell(duplicate_row)} "
            f"| {markdown_cell(original_text)} |"
        )

    return lines if len(lines) > 2 else None


def render_finding(finding, number):
    """Render one finding, including structured evidence."""
    lines = [
        f"### {number}. {safe_text(finding.get('check'))}",
        "",
        f"- **Status:** `{safe_text(finding.get('status'))}`",
        f"- **Details:** {safe_text(finding.get('message'))}",
    ]

    recommendation = (
        finding.get("recommendation")
        or finding.get("recommended_fix")
        or finding.get("suggestion")
        or finding.get("fix")
    )

    if recommendation:
        lines.append(
            f"- **Recommended action:** {safe_text(recommendation)}"
        )

    evidence = finding.get("evidence")
    filename = get_filename(finding)
    check = str(finding.get("check", "")).lower()

    if check == "missing_values":
        table = render_missing_values_table(
            evidence, filename
        )

        if table:
            lines.extend([
                "",
                "**Missing-value evidence:**",
                "",
                *table,
                "",
                "*Confirm whether these values are allowed to be empty "
                "before modifying the dataset.*",
                "",
            ])
            return lines

    if check == "duplicate_rows":
        table = render_duplicate_rows_table(
            evidence, filename
        )

        if table:
            lines.extend([
                "",
                "**Duplicate-row evidence:**",
                "",
                *table,
                "",
                "*Review duplicate records before deleting them. "
                "Repeated records may represent valid transactions.*",
                "",
            ])
            return lines

    if evidence:
        lines.append("- **Evidence:**")

        if isinstance(evidence, list):
            for item in evidence:
                if isinstance(item, dict):
                    evidence_file = (
                        item.get("file") or item.get("path")
                    )
                    detail = (
                        item.get("error") or item.get("message")
                    )

                    if evidence_file and detail:
                        lines.append(
                            f"  - `{evidence_file}`: {detail}"
                        )
                    else:
                        lines.append(
                            f"  - {safe_text(item)}"
                        )
                else:
                    lines.append(
                        f"  - {safe_text(item)}"
                    )
        else:
            lines.append(
                f"  - {safe_text(evidence)}"
            )

    lines.append("")
    return lines


def render_data_quality_summary(findings):
    """Summarize data-quality results by dataset and status."""
    data_findings = [
        finding
        for finding in findings
        if is_data_quality_finding(finding)
    ]

    lines = [
        "## Data Quality Summary by Dataset",
        "",
        "This section groups data-quality findings by file. A warning "
        "for one dataset does not imply that every dataset has the same issue.",
        "",
    ]

    if not data_findings:
        lines.extend([
            "No data-quality findings were included in the report.",
            "",
        ])
        return lines

    grouped = defaultdict(list)

    for finding in data_findings:
        grouped[get_filename(finding)].append(finding)

    lines.extend([
        "| Dataset | Failures | Warnings | Not tested | Passed | Info |",
        "|---|---:|---:|---:|---:|---:|",
    ])

    for filename, dataset_findings in sorted(grouped.items()):
        counts = Counter(
            finding["status"]
            for finding in dataset_findings
        )

        lines.append(
            f"| {markdown_cell(filename)} "
            f"| {counts.get('FAIL', 0)} "
            f"| {counts.get('WARNING', 0)} "
            f"| {counts.get('NOT_TESTED', 0)} "
            f"| {counts.get('PASS', 0)} "
            f"| {counts.get('INFO', 0)} |"
        )

    lines.extend([
        "",
        "### Data Quality Findings",
        "",
    ])

    for filename, dataset_findings in sorted(grouped.items()):
        lines.extend([
            f"#### `{markdown_cell(filename)}`",
            "",
        ])

        for finding in dataset_findings:
            lines.append(
                f"- **{safe_text(finding.get('status'))} — "
                f"{safe_text(finding.get('check'))}:** "
                f"{safe_text(finding.get('message'))}"
            )

        lines.append("")

    lines.extend([
        "Review each warning against the dataset's business rules. "
        "Do not automatically delete duplicate rows or fill missing "
        "values without confirming the intended behavior.",
        "",
    ])

    return lines


def generate_markdown_report(json_report_path, output_path):
    """Generate a Markdown report from the combined JSON results."""
    report = load_report(json_report_path)
    output_path = Path(output_path)

    summary = report.get("summary", {})

    if not isinstance(summary, dict):
        summary = {}

    findings = get_findings(report)
    counts = Counter(
        item["status"] for item in findings
    )

    statuses = STATUS_ORDER + sorted(
        status
        for status in counts
        if status not in STATUS_ORDER
    )

    overall_status = report.get(
        "overall_status",
        summary.get("overall_status", "UNKNOWN"),
    )

    total_findings = len(findings)

    visual_count = summary.get(
        "dashboard_visuals_checked",
        summary.get(
            "visuals_checked",
            summary.get("visual_files_found", "N/A"),
        ),
    )

    lines = [
        "# Power BI Dashboard Testing Report",
        "",
        f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        f"**Project path:** `{safe_text(report.get('project_path'))}`",
        "",
        f"**Overall status:** **{safe_text(overall_status)}**",
        "",
        "## Executive Summary",
        "",
        f"- Total findings: **{total_findings}**",
        f"- Failures: **{counts.get('FAIL', 0)}**",
        f"- Warnings: **{counts.get('WARNING', 0)}**",
        f"- Not tested: **{counts.get('NOT_TESTED', 0)}**",
        f"- Informational: **{counts.get('INFO', 0)}**",
        f"- Passed findings: **{counts.get('PASS', 0)}**",
        "",
        "> A PASS applies only to the specific check that was performed. "
        "It does not establish that the entire dashboard is defect-free.",
        "",
        "## Project Scan Summary",
        "",
        "| Metric | Value |",
        "|---|---:|",
        f"| Project format | {safe_text(summary.get('project_format'))} |",
        f"| JSON files checked | {safe_text(summary.get('json_files_checked'))} |",
        f"| Visual definition files | {safe_text(summary.get('visual_files_found'))} |",
        f"| Report pages | {safe_text(summary.get('page_count'))} |",
        f"| Visuals checked | {safe_text(visual_count)} |",
        f"| TMDL files checked | {safe_text(summary.get('tmdl_files_checked'))} |",
        f"| Tables detected | {safe_text(summary.get('tables_detected'))} |",
        f"| Measures detected | {safe_text(summary.get('measures_detected'))} |",
        f"| Columns detected | {safe_text(summary.get('columns_detected'))} |",
        f"| Relationships parsed | {safe_text(summary.get('relationships_parsed'))} |",
        "",
        "## Finding Counts",
        "",
        "| Status | Count |",
        "|---|---:|",
    ]

    for status in statuses:
        lines.append(
            f"| {status} | {counts.get(status, 0)} |"
        )

    # Dedicated dataset-level summary before detailed attention findings.
    lines.extend([
        "",
        *render_data_quality_summary(findings),
    ])

    lines.extend([
        "## Findings Requiring Attention",
        "",
        "Warnings indicate potential issues that should be reviewed "
        "against the dataset rules and intended dashboard design.",
        "",
    ])

    attention = [
        item
        for item in findings
        if item["status"] in ATTENTION_STATUSES
    ]

    if attention:
        grouped_attention = defaultdict(list)

        for finding in attention:
            grouped_attention[get_category(finding)].append(finding)

        number = 1

        for category, category_findings in sorted(
            grouped_attention.items()
        ):
            lines.extend([
                f"### {category}",
                "",
            ])

            for finding in category_findings:
                lines.extend(
                    render_finding(finding, number)
                )
                number += 1
    else:
        lines.extend([
            "No attention-required findings were reported.",
            "",
        ])

    informational = [
        item
        for item in findings
        if item["status"] == "INFO"
    ]

    lines.extend([
        "## Informational Findings",
        "",
        f"Total informational findings: **{len(informational)}**",
        "",
        "These findings provide context or indicate areas for review. "
        "They are not necessarily defects.",
        "",
        "| Category | Check | Count |",
        "|---|---|---:|",
    ])

    info_groups = Counter(
        (
            get_category(item),
            safe_text(item.get("check")),
        )
        for item in informational
    )

    for (category, check), count in sorted(
        info_groups.items()
    ):
        lines.append(
            f"| {markdown_cell(category)} "
            f"| {markdown_cell(check)} | {count} |"
        )

    lines.extend([
        "",
        "<details>",
        "<summary>Show all informational findings</summary>",
        "",
    ])

    for number, finding in enumerate(
        informational, start=1
    ):
        lines.extend(
            render_finding(finding, number)
        )

    lines.extend([
        "</details>",
        "",
    ])

    passed = [
        item for item in findings if item["status"] == "PASS"
    ]

    unique_passed = []
    seen_passed = set()

    for item in passed:
        key = (
            item.get("check"),
            item.get("message"),
            item.get("file") or item.get("path"),
        )

        if key not in seen_passed:
            seen_passed.add(key)
            unique_passed.append(item)

    passed = unique_passed

    passed_groups = defaultdict(list)

    for finding in passed:
        passed_groups[get_category(finding)].append(finding)

    lines.extend([
        "## Passed Checks",
        "",
        f"Total: **{len(passed)}**",
        "",
        "These entries represent individual checks that passed; "
        "they should not be interpreted as a guarantee of overall quality.",
        "",
    ])

    for category, category_findings in sorted(
        passed_groups.items()
    ):
        lines.extend([
            f"### {category}",
            "",
        ])

        for finding in category_findings:
            lines.append(
                f"- **{safe_text(finding.get('check'))}** — "
                f"{safe_text(finding.get('message'))}"
            )

        lines.append("")

    lines.extend([
        "## Testing Limitations",
        "",
        "- Static DAX checks inspect expressions but do not establish "
        "that every measure executes correctly in the Power BI engine.",
        "- A successful connection or simple DAX query does not prove "
        "that all report measures have been executed.",
        "- Numerical measure validation requires expected results, "
        "suitable data, and the relevant filter context.",
        "- Metadata checks cannot guarantee that visuals render correctly.",
        "- Data-quality checks require supported dataset files.",
        "- Data refresh and interactive filters may not have been tested.",
        "- Requirement checks cover only requirements supplied to the agent.",
        "- PASS means the specific implemented check passed, not that the "
        "entire dashboard is defect-free.",
        "",
    ])

    output_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    output_path.write_text(
        "\n".join(lines),
        encoding="utf-8",
    )

    print(
        f"Markdown report saved to: {output_path.resolve()}"
    )


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Generate the Power BI testing Markdown report."
    )

    parser.add_argument(
        "--json-report",
        default="reports/pbip_check_results.json",
    )

    parser.add_argument(
        "--output",
        default="reports/testing_summary.md",
    )

    args = parser.parse_args()

    try:
        generate_markdown_report(
            args.json_report,
            args.output,
        )
    except (OSError, ValueError) as exc:
        raise SystemExit(
            f"Report generation failed: {exc}"
        ) from exc


if __name__ == "__main__":
    main()