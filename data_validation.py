import pandas as pd
import math


def validate_kpi(
    file_path,
    column,
    expected_value,
    operation="sum",
    tolerance=0.01
):
    """Calculate a KPI and compare it with an expected value."""

    try:
        # Validate inputs
        if not isinstance(expected_value, (int, float)):
            return {
                "status": "error",
                "message": "Expected value must be a number."
            }

        if not math.isfinite(expected_value):
            return {
                "status": "error",
                "message": "Expected value must be finite."
            }

        if not isinstance(tolerance, (int, float)) or not math.isfinite(tolerance) or tolerance < 0:
            return {
                "status": "error",
                "message": "Tolerance must be a finite, non-negative number."
            }

        allowed_operations = ["sum", "mean", "count", "min", "max"]

        if operation not in allowed_operations:
            return {
                "status": "error",
                "message": f"Unsupported operation: {operation}"
            }

        # Load dataset
        df = pd.read_csv(file_path)

        if column not in df.columns:
            return {
                "status": "error",
                "message": f"Column '{column}' was not found."
            }

        # Convert column values to numbers
        numeric_values = pd.to_numeric(df[column], errors="coerce")

        # Identify invalid values, excluding genuinely empty cells
        invalid_mask = df[column].notna() & numeric_values.isna()
        invalid_count = int(invalid_mask.sum())

        values = numeric_values.dropna()

        if values.empty:
            return {
                "status": "error",
                "message": f"Column '{column}' has no valid numeric values."
            }

        # Calculate KPI
        if operation == "sum":
            actual_value = float(values.sum())
        elif operation == "mean":
            actual_value = float(values.mean())
        elif operation == "count":
            actual_value = int(values.count())
        elif operation == "min":
            actual_value = float(values.min())
        else:
            actual_value = float(values.max())

        difference = actual_value - expected_value
        passed = abs(difference) <= tolerance

        return {
            "file": file_path,
            "column": column,
            "operation": operation,
            "expected_value": expected_value,
            "actual_value": actual_value,
            "difference": difference,
            "invalid_values_ignored": invalid_count,
            "status": "passed" if passed else "failed"
        }

    except (OSError, pd.errors.ParserError, UnicodeDecodeError) as error:
        return {
            "status": "error",
            "message": str(error)
        }