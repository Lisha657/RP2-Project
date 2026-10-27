import pandas as pd
from pathlib import Path


def check_data_quality(file_path):
    """Analyse a CSV dataset and report data quality issues."""

    results = {
        "file": str(file_path),
        "status": "success",
        "total_rows": 0,
        "total_columns": 0,
        "missing_values": {},
        "duplicate_rows": 0,
        "data_types": {},
        "empty_rows": 0,
        "empty_columns": [],
        "issues_found": []
    }

    try:
        path = Path(file_path)

        if not path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        if not path.is_file():
            raise ValueError(f"Path is not a file: {file_path}")

        if path.stat().st_size == 0:
            raise ValueError("CSV file is empty.")

        df = pd.read_csv(path)

        results["total_rows"] = len(df)
        results["total_columns"] = len(df.columns)

        if df.empty:
            results["status"] = "issues_found"
            results["issues_found"].append({
                "issue": "Empty dataset",
                "severity": "High",
                "details": "The CSV contains column headers but no data rows."
            })
            results["data_types"] = {
                column: str(dtype)
                for column, dtype in df.dtypes.items()
            }
            return results

        # Missing values by column
        missing_values = df.isnull().sum()

        missing_summary = {
            column: int(count)
            for column, count in missing_values.items()
            if count > 0
        }

        results["missing_values"] = missing_summary

        if missing_summary:
            results["issues_found"].append({
                "issue": "Missing values",
                "severity": "Medium",
                "details": missing_summary
            })

        # Duplicate rows
        duplicate_count = int(df.duplicated().sum())
        results["duplicate_rows"] = duplicate_count

        if duplicate_count > 0:
            results["issues_found"].append({
                "issue": "Duplicate rows",
                "severity": "Medium",
                "details": f"{duplicate_count} duplicate rows detected"
            })

        # Completely empty rows
        empty_row_count = int(df.isnull().all(axis=1).sum())
        results["empty_rows"] = empty_row_count

        if empty_row_count > 0:
            results["issues_found"].append({
                "issue": "Empty rows",
                "severity": "Medium",
                "details": f"{empty_row_count} completely empty rows detected"
            })

        # Completely empty columns
        empty_columns = [
            column for column in df.columns
            if df[column].isnull().all()
        ]
        results["empty_columns"] = empty_columns

        if empty_columns:
            results["issues_found"].append({
                "issue": "Empty columns",
                "severity": "Medium",
                "details": empty_columns
            })

        # Column data types
        results["data_types"] = {
            column: str(dtype)
            for column, dtype in df.dtypes.items()
        }

        if results["issues_found"]:
            results["status"] = "issues_found"

        return results

    except FileNotFoundError as error:
        results["status"] = "error"
        results["message"] = str(error)
        return results

    except (ValueError, pd.errors.EmptyDataError,
            pd.errors.ParserError, UnicodeDecodeError) as error:
        results["status"] = "error"
        results["message"] = f"Unable to analyse CSV: {error}"
        return results

    except OSError as error:
        results["status"] = "error"
        results["message"] = f"Unable to read file: {error}"
        return results