
import argparse
import json
import math
from pathlib import Path

import pandas as pd


SUPPORTED_EXTENSIONS = {".csv", ".xlsx", ".xls"}

# Directories that should not normally be treated as source-data folders.
EXCLUDED_DIRECTORIES = {
    ".git",
    ".venv",
    "venv",
    "__pycache__",
    "node_modules",
    "reports",
    "examples",
    "logs",
    "log",
    "output",
    "outputs",
    "artifacts",
    "rejected_rows",
}


def make_finding(status, check, message, file=None, evidence=None):
    """Create a standardized finding."""
    result = {
        "status": status,
        "check": check,
        "message": message,
    }

    if file:
        result["file"] = str(file)

    if evidence is not None:
        result["evidence"] = evidence

    return result


def discover_datasets(data_path):
    """Discover CSV and Excel datasets, excluding generated-output folders."""
    root = Path(data_path).expanduser().resolve()

    if not root.exists():
        return []

    # An explicitly supplied file can be tested directly.
    if root.is_file():
        if root.suffix.lower() in SUPPORTED_EXTENSIONS:
            return [root]
        return []

    files = []

    for path in root.rglob("*"):
        if not path.is_file():
            continue

        if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
            continue

        try:
            relative_parts = path.relative_to(root).parts
        except ValueError:
            relative_parts = path.parts

        # Exclude directories, not files whose names happen to match.
        if any(
            part.lower() in EXCLUDED_DIRECTORIES
            for part in relative_parts[:-1]
        ):
            continue

        files.append(path)

    return sorted(files, key=lambda path: str(path).lower())


def load_dataset(path):
    """Read a supported CSV or Excel file."""
    suffix = path.suffix.lower()

    if suffix == ".csv":
        last_error = None

        for encoding in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
            try:
                return pd.read_csv(
                    path,
                    encoding=encoding,
                    low_memory=False,
                )
            except UnicodeDecodeError as exc:
                last_error = exc

        raise ValueError(f"Could not decode CSV: {last_error}")

    if suffix in {".xlsx", ".xls"}:
        return pd.read_excel(path)

    raise ValueError(f"Unsupported file type: {suffix}")


def check_dataset(path, numeric_columns=None, display_path=None):
    """Run data-quality checks on a single dataset."""
    findings = []
    file_label = display_path or path.name

    try:
        df = load_dataset(path)
    except Exception as exc:
        return {
            "overall_status": "NOT_TESTED",
            "summary": {
                "file": file_label,
                "files_checked": 0,
            },
            "findings": [
                make_finding(
                    "NOT_TESTED",
                    "dataset_read",
                    f"Could not read dataset: {exc}",
                    file=file_label,
                )
            ],
        }

    rows, columns = df.shape

    # 1. Empty dataset
    if df.empty:
        findings.append(
            make_finding(
                "WARNING",
                "empty_dataset",
                "The dataset has no data rows or no columns.",
                file=file_label,
            )
        )

    # 2. Duplicate column names
    column_names = [str(column) for column in df.columns]

    if len(column_names) != len(set(column_names)):
        findings.append(
            make_finding(
                "WARNING",
                "duplicate_column_names",
                "Duplicate column names were detected.",
                file=file_label,
                evidence=column_names,
            )
        )

    # 3. Blank or whitespace-padded column names
    blank_names = [
        str(column)
        for column in df.columns
        if not str(column).strip()
    ]

    padded_names = [
        str(column)
        for column in df.columns
        if str(column) != str(column).strip()
    ]

    if blank_names:
        findings.append(
            make_finding(
                "WARNING",
                "blank_column_names",
                f"Found {len(blank_names)} blank column name(s).",
                file=file_label,
                evidence=blank_names[:20],
            )
        )

    if padded_names:
        findings.append(
            make_finding(
                "INFO",
                "column_name_whitespace",
                "Some column names contain leading or trailing spaces.",
                file=file_label,
                evidence=padded_names[:20],
            )
        )

    # 4. Completely empty rows and columns
    empty_rows_mask = (
        df.isna().all(axis=1)
        if columns
        else pd.Series(True, index=df.index)
    )
    empty_rows = int(empty_rows_mask.sum())

    empty_columns = [
        str(column)
        for column in df.columns
        if df[column].isna().all()
    ]

    if empty_rows:
        findings.append(
            make_finding(
                "WARNING",
                "empty_rows",
                f"Found {empty_rows} completely empty row(s).",
                file=file_label,
                evidence={
                    "data_row_numbers": [
                        int(position) + 2
                        for position, is_empty in enumerate(
                            empty_rows_mask.tolist()
                        )
                        if is_empty
                    ][:20],
                    "note": (
                        "Row numbers assume a header in row 1. "
                        "Excel sheets may use different header positions."
                    ),
                },
            )
        )

    if empty_columns:
        findings.append(
            make_finding(
                "WARNING",
                "empty_columns",
                f"Found {len(empty_columns)} completely empty column(s).",
                file=file_label,
                evidence=empty_columns[:20],
            )
        )

    # 5. Missing values
    missing = df.isna().sum()
    missing = missing[missing > 0]
    missing_total = int(missing.sum())

    if missing_total:
        missing_details = {}

        for column, count in missing.items():
            missing_mask = df[column].isna()

            missing_details[str(column)] = {
                "missing_count": int(count),
                "missing_percentage": (
                    round(int(count) / rows * 100, 2)
                    if rows
                    else 0.0
                ),
                "example_data_row_numbers": [
                    int(position) + 2
                    for position, is_missing in enumerate(
                        missing_mask.tolist()
                    )
                    if is_missing
                ][:20],
            }

        findings.append(
            make_finding(
                "WARNING",
                "missing_values",
                (
                    f"Found {missing_total} missing value(s) "
                    f"across {len(missing)} column(s)."
                ),
                file=file_label,
                evidence=missing_details,
            )
        )
    else:
        findings.append(
            make_finding(
                "PASS",
                "missing_values",
                f"No missing values were detected in '{file_label}'.",
                file=file_label,
            )
        )

    # 6. Duplicate rows
    duplicate_mask = df.duplicated(keep="first")
    duplicate_positions = [
        position
        for position, is_duplicate in enumerate(
            duplicate_mask.tolist()
        )
        if is_duplicate
    ]
    duplicate_count = len(duplicate_positions)
    duplicate_evidence = []

    for duplicate_position in duplicate_positions[:20]:
        duplicate_row = df.iloc[duplicate_position]

        original_positions = [
            position
            for position in range(duplicate_position)
            if df.iloc[position].equals(duplicate_row)
        ]

        duplicate_evidence.append(
            {
                "duplicate_data_row_number": duplicate_position + 2,
                "matching_original_data_row_numbers": [
                    position + 2
                    for position in original_positions
                ],
            }
        )

    findings.append(
        make_finding(
            "WARNING" if duplicate_count else "PASS",
            "duplicate_rows",
            (
                f"Found {duplicate_count} duplicate row(s)."
                if duplicate_count
                else f"No duplicate rows were detected in '{file_label}'."
            ),
            file=file_label,
            evidence=duplicate_evidence if duplicate_count else None,
        )
    )

    # 7. Explicit numeric-column validation
    for column in numeric_columns or []:
        if column not in df.columns:
            findings.append(
                make_finding(
                    "WARNING",
                    "numeric_column_not_found",
                    f"Requested numeric column '{column}' was not found.",
                    file=file_label,
                )
            )
            continue

        values = df[column]
        converted = pd.to_numeric(values, errors="coerce")
        invalid = values.notna() & converted.isna()
        invalid_count = int(invalid.sum())

        if invalid_count:
            findings.append(
                make_finding(
                    "WARNING",
                    "invalid_numeric_values",
                    (
                        f"Column '{column}' contains {invalid_count} "
                        "non-numeric value(s)."
                    ),
                    file=file_label,
                    evidence={
                        "examples": (
                            values[invalid].astype(str).head(5).tolist()
                        ),
                        "example_data_row_numbers": [
                            int(position) + 2
                            for position, is_invalid in enumerate(
                                invalid.tolist()
                            )
                            if is_invalid
                        ][:20],
                    },
                )
            )
        else:
            findings.append(
                make_finding(
                    "PASS",
                    "numeric_column_validation",
                    (
                        f"Column '{column}' has no detected "
                        "invalid non-numeric values."
                    ),
                    file=file_label,
                )
            )

        numeric_values = converted.dropna()
        infinite_count = int(
            numeric_values.map(
                lambda value: not math.isfinite(float(value))
            ).sum()
        )

        if infinite_count:
            findings.append(
                make_finding(
                    "WARNING",
                    "infinite_values",
                    (
                        f"Column '{column}' contains "
                        f"{infinite_count} infinite value(s)."
                    ),
                    file=file_label,
                )
            )

    # 8. Mixed Python value types within a column
    for column in df.columns:
        values = df[column].dropna()

        if len(values) < 2:
            continue

        type_names = sorted(
            {
                type(value).__name__
                for value in values
            }
        )

        if len(type_names) > 1:
            findings.append(
                make_finding(
                    "INFO",
                    "mixed_data_types",
                    (
                        f"Column '{column}' contains "
                        "multiple Python value types."
                    ),
                    file=file_label,
                    evidence=type_names,
                )
            )

    statuses = {item["status"] for item in findings}

    overall = (
        "FAIL" if "FAIL" in statuses
        else "WARNING" if "WARNING" in statuses
        else "PASS"
    )

    return {
        "overall_status": overall,
        "summary": {
            "file": file_label,
            "files_checked": 1,
            "rows": int(rows),
            "columns": int(columns),
            "missing_values": missing_total,
            "duplicate_rows": duplicate_count,
            "empty_rows": empty_rows,
            "empty_columns": len(empty_columns),
        },
        "findings": findings,
    }


def check_data_quality(data_path, numeric_columns=None):
    """Find and test datasets under a file or directory."""
    root = Path(data_path).expanduser().resolve()

    empty_summary = {
        "files_found": 0,
        "files_checked": 0,
        "files_not_read": 0,
        "total_rows": 0,
        "total_columns": 0,
        "total_missing_values": 0,
        "total_duplicate_rows": 0,
    }

    if not root.exists():
        message = f"Dataset search path does not exist: {root}"

        return {
            "overall_status": "NOT_TESTED",
            "summary": empty_summary,
            "files": [],
            "findings": [
                make_finding(
                    "NOT_TESTED",
                    "data_quality_availability",
                    message,
                )
            ],
            "message": message,
        }

    files = discover_datasets(root)

    if not files:
        message = (
            f"No supported CSV or Excel datasets were found under {root}. "
            "Use --data-path to specify the source-data location."
        )

        return {
            "overall_status": "NOT_TESTED",
            "summary": empty_summary,
            "files": [],
            "findings": [
                make_finding(
                    "NOT_TESTED",
                    "data_quality_availability",
                    message,
                )
            ],
            "message": message,
        }

    results = []

    for path in files:
        try:
            relative_path = (
                str(path.relative_to(root))
                if root.is_dir()
                else path.name
            )
        except ValueError:
            relative_path = path.name

        results.append(
            check_dataset(
                path,
                numeric_columns=numeric_columns,
                display_path=relative_path,
            )
        )

    findings = [
        item
        for result in results
        for item in result["findings"]
    ]

    statuses = {
        result["overall_status"]
        for result in results
    }

    # Overall status reflects warnings and incomplete testing.
    if "FAIL" in statuses:
        overall = "FAIL"
    elif "WARNING" in statuses:
        overall = "WARNING"
    elif "NOT_TESTED" in statuses:
        overall = "WARNING"
    elif "PASS" in statuses:
        overall = "PASS"
    else:
        overall = "NOT_TESTED"

    checked = [
        result
        for result in results
        if result["summary"].get("files_checked", 0) == 1
    ]

    return {
        "overall_status": overall,
        "summary": {
            "files_found": len(files),
            "files_checked": len(checked),
            "files_not_read": len(files) - len(checked),
            "total_rows": sum(
                result["summary"].get("rows", 0)
                for result in checked
            ),
            "total_columns": sum(
                result["summary"].get("columns", 0)
                for result in checked
            ),
            "total_missing_values": sum(
                result["summary"].get("missing_values", 0)
                for result in checked
            ),
            "total_duplicate_rows": sum(
                result["summary"].get("duplicate_rows", 0)
                for result in checked
            ),
        },
        "files": results,
        "findings": findings,
    }


def check_data_directory(data_path, numeric_columns=None):
    """Compatibility wrapper used by main.py."""
    return check_data_quality(
        data_path,
        numeric_columns=numeric_columns,
    )


def main():
    parser = argparse.ArgumentParser(
        description="Check data quality in CSV and Excel datasets."
    )

    parser.add_argument(
        "--data-path",
        required=True,
        help="Path to a dataset file or directory to scan.",
    )
    parser.add_argument(
        "--numeric-columns",
        default="",
        help="Comma-separated list of columns to validate as numeric.",
    )
    parser.add_argument(
        "--output",
        default="",
        help="Optional path for saving the JSON report.",
    )

    args = parser.parse_args()

    numeric_columns = [
        name.strip()
        for name in args.numeric_columns.split(",")
        if name.strip()
    ]

    result = check_data_quality(
        args.data_path,
        numeric_columns=numeric_columns,
    )

    output = json.dumps(
        result,
        indent=2,
        ensure_ascii=False,
    )

    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )
        output_path.write_text(
            output,
            encoding="utf-8",
        )

    print(output)


if __name__ == "__main__":
    main()
