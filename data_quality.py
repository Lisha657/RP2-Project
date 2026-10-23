import pandas as pd


def check_data_quality(file_path):
    """Analyse a CSV dataset and report basic data quality issues."""

    try:
        df = pd.read_csv(file_path)

        # Basic dataset information
        total_rows = len(df)
        total_columns = len(df.columns)

        # Count missing values
        missing_values = df.isnull().sum()

        missing_summary = {
            column: int(count)
            for column, count in missing_values.items()
            if count > 0
        }

        # Count duplicate rows
        duplicate_count = int(df.duplicated().sum())

        # Identify columns containing mixed or unexpected data types
        data_types = {
            column: str(dtype)
            for column, dtype in df.dtypes.items()
        }

        # Prepare results
        results = {
            "file": file_path,
            "status": "success",
            "total_rows": total_rows,
            "total_columns": total_columns,
            "missing_values": missing_summary,
            "duplicate_rows": duplicate_count,
            "data_types": data_types,
            "issues_found": []
        }

        if missing_summary:
            results["issues_found"].append({
                "issue": "Missing values",
                "severity": "Medium",
                "details": missing_summary
            })

        if duplicate_count > 0:
            results["issues_found"].append({
                "issue": "Duplicate rows",
                "severity": "Medium",
                "details": f"{duplicate_count} duplicate rows detected"
            })

        return results

    except Exception as error:
        return {
            "file": file_path,
            "status": "error",
            "message": str(error),
            "issues_found": []
        }