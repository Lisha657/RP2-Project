import pandas as pd


def validate_kpi(
    file_path,
    column,
    expected_value,
    operation="sum",
    tolerance=0.01
):
    """Calculate a KPI and compare it with an expected value."""

    try:
        df = pd.read_csv(file_path)

        if column not in df.columns:
            return {
                "status": "error",
                "message": f"Column '{column}' was not found."
            }

        values = pd.to_numeric(df[column], errors="coerce").dropna()

        if values.empty:
            return {
                "status": "error",
                "message": f"Column '{column}' has no valid numeric values."
            }

        if operation == "sum":
            actual_value = float(values.sum())
        elif operation == "mean":
            actual_value = float(values.mean())
        elif operation == "count":
            actual_value = int(values.count())
        elif operation == "min":
            actual_value = float(values.min())
        elif operation == "max":
            actual_value = float(values.max())
        else:
            return {
                "status": "error",
                "message": f"Unsupported operation: {operation}"
            }

        difference = actual_value - expected_value
        passed = abs(difference) <= tolerance

        return {
            "file": file_path,
            "column": column,
            "operation": operation,
            "expected_value": expected_value,
            "actual_value": actual_value,
            "difference": difference,
            "status": "passed" if passed else "failed"
        }

    except (OSError, pd.errors.ParserError) as error:
        return {
            "status": "error",
            "message": str(error)
        }