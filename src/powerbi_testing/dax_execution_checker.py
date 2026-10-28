
import json
import os
import subprocess
from pathlib import Path


# ---------------------------------------------------------
# 1. Find Power BI Desktop's local model port
# ---------------------------------------------------------
def find_powerbi_port():
    """Find the port of the running Power BI Desktop model."""

    workspace_root = (
        Path.home()
        / "Microsoft"
        / "Power BI Desktop Store App"
        / "AnalysisServicesWorkspaces"
    )

    port_files = list(
        workspace_root.glob("**/msmdsrv.port.txt")
    )

    if not port_files:
        raise FileNotFoundError(
            "Power BI port file not found. Open Power BI Desktop "
            "with a report loaded and try again."
        )

    # Prefer the most recently modified port file.
    port_file = max(
        port_files,
        key=lambda path: path.stat().st_mtime
    )

    raw_port = port_file.read_bytes()

    try:
        port = raw_port.decode("utf-16").strip()
    except UnicodeError:
        port = raw_port.decode("utf-8-sig").strip()

    port = port.replace("\x00", "").strip()

    if not port.isdigit():
        raise ValueError(
            f"Invalid Power BI port found: {port}"
        )

    return port


# ---------------------------------------------------------
# 2. Find the ADOMD.NET client DLL
# ---------------------------------------------------------
def find_adomd_dll():
    """Locate the ADOMD.NET DLL installed with Power BI Desktop."""

    known_dll = Path(
        r"C:\Program Files\WindowsApps"
        r"\Microsoft.MicrosoftPowerBIDesktop_2.159.883.0_x64__8wekyb3d8bbwe"
        r"\bin\Microsoft.PowerBI.AdomdClient.dll"
    )

    # Use the exact installation path verified earlier.
    if known_dll.is_file():
        return known_dll

    # Fallback: search installed Power BI Desktop versions.
    windows_apps = Path(
        r"C:\Program Files\WindowsApps"
    )

    try:
        matches = list(
            windows_apps.glob(
                "Microsoft.MicrosoftPowerBIDesktop_*/bin/"
                "Microsoft.PowerBI.AdomdClient.dll"
            )
        )

        matches = [
            path for path in matches if path.is_file()
        ]

        if matches:
            # Prefer the newest modified DLL.
            return max(
                matches,
                key=lambda path: path.stat().st_mtime
            )

    except (OSError, PermissionError):
        pass

    raise FileNotFoundError(
        "Microsoft.PowerBI.AdomdClient.dll was not found. "
        "Check your Power BI Desktop installation path."
    )


# ---------------------------------------------------------
# 3. Execute a DAX query against Power BI Desktop
# ---------------------------------------------------------
def execute_dax_query(dax_query):
    """
    Execute a DAX query against the currently loaded Power BI model.

    Returns:
        PASS: The query executed successfully.
        FAIL: Power BI rejected the query.
        NOT_TESTED: The connection or execution environment
                    could not be established.
    """

    conn = None
    reader = None

    try:
        port = find_powerbi_port()
        dll = find_adomd_dll()

        # Pass values through environment variables so special
        # characters in DAX do not break PowerShell quoting.
        env = os.environ.copy()
        env["POWERBI_DAX_QUERY"] = dax_query
        env["POWERBI_ADOMD_DLL"] = str(dll)
        env["POWERBI_PORT"] = port

        powershell_script = r"""
$ErrorActionPreference = 'Stop'
$conn = $null
$reader = $null

try {
    Add-Type -Path $env:POWERBI_ADOMD_DLL -ErrorAction Stop

    $conn = New-Object `
        Microsoft.AnalysisServices.AdomdClient.AdomdConnection

    $conn.ConnectionString = "Data Source=localhost:$env:POWERBI_PORT"
    $conn.Open()

    $cmd = $conn.CreateCommand()
    $cmd.CommandText = $env:POWERBI_DAX_QUERY

    $reader = $cmd.ExecuteReader()

    $rows = @()

    while ($reader.Read()) {
        $row = @()

        for ($i = 0; $i -lt $reader.FieldCount; $i++) {
            $value = $reader.GetValue($i)

            if ($null -eq $value -or $value -is [DBNull]) {
                $row += $null
            }
            elseif ($value -is [datetime]) {
                $row += $value.ToString("o")
            }
            elseif ($value -is [System.IConvertible]) {
                $row += $value
            }
            else {
                $row += $value.ToString()
            }
        }

        $rows += ,$row
    }

    @{
        success = $true
        rows = $rows
    } | ConvertTo-Json -Depth 8 -Compress
}
catch {
    @{
        success = $false
        error = $_.Exception.ToString()
    } | ConvertTo-Json -Depth 5 -Compress
}
finally {
    if ($reader) {
        $reader.Close()
    }

    if ($conn -and $conn.State -eq 'Open') {
        $conn.Close()
    }
}
"""

        result = subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                powershell_script,
            ],
            capture_output=True,
            text=True,
            timeout=60,
            env=env,
        )

        if result.returncode != 0:
            return {
                "status": "NOT_TESTED",
                "check": "dax_execution",
                "message": (
                    result.stderr.strip()
                    or "PowerShell execution failed."
                ),
            }

        output_lines = [
            line.strip()
            for line in result.stdout.splitlines()
            if line.strip()
        ]

        if not output_lines:
            return {
                "status": "NOT_TESTED",
                "check": "dax_execution",
                "message": "PowerShell returned no query result.",
            }

        response = json.loads(output_lines[-1])

        if not response.get("success"):
            return {
                "status": "FAIL",
                "check": "dax_execution",
                "message": response.get(
                    "error",
                    "Power BI rejected the DAX query.",
                ),
            }

        return {
            "status": "PASS",
            "check": "dax_execution",
            "message": "DAX query executed successfully.",
            "rows": response.get("rows", []),
            "port": port,
            "dll": str(dll),
        }

    except subprocess.TimeoutExpired:
        return {
            "status": "NOT_TESTED",
            "check": "dax_execution",
            "message": "DAX execution timed out after 60 seconds.",
        }

    except (FileNotFoundError, ValueError, OSError) as exc:
        return {
            "status": "NOT_TESTED",
            "check": "dax_execution",
            "message": str(exc),
        }

    except Exception as exc:
        return {
            "status": "NOT_TESTED",
            "check": "dax_execution",
            "message": f"Unexpected execution error: {exc}",
        }


# ---------------------------------------------------------
# 4. Validate the result of the Total Sales measure
# ---------------------------------------------------------
def validate_total_sales(expected_value):
    """
    Execute Total Sales and compare it with an expected value.

    The expected value must come from a trusted source dataset
    or a manually verified test fixture.
    """

    query = 'EVALUATE ROW("Total Sales", [Total Sales])'
    result = execute_dax_query(query)

    if result["status"] != "PASS":
        return result

    rows = result.get("rows", [])

    if not rows or not rows[0]:
        return {
            "status": "FAIL",
            "check": "dax_runtime_value",
            "measure": "Total Sales",
            "message": "The query returned no measure value.",
        }

    try:
        actual_value = float(rows[0][0])
        expected = float(expected_value)

    except (TypeError, ValueError, OverflowError):
        return {
            "status": "FAIL",
            "check": "dax_runtime_value",
            "measure": "Total Sales",
            "message": "Actual or expected value is not numeric.",
        }

    if not (
        abs(actual_value - expected)
        <= 1e-9 * max(1.0, abs(expected))
    ):
        return {
            "status": "FAIL",
            "check": "dax_runtime_value",
            "measure": "Total Sales",
            "actual": actual_value,
            "expected": expected,
            "message": (
                "The actual measure result differs from "
                "the expected value."
            ),
        }

    return {
        "status": "PASS",
        "check": "dax_runtime_value",
        "measure": "Total Sales",
        "actual": actual_value,
        "expected": expected,
        "message": (
            "The measure result matches the expected value."
        ),
    }


# ---------------------------------------------------------
# 5. Run standalone tests
# ---------------------------------------------------------
if __name__ == "__main__":
    print("Power BI DAX Runtime Checker")
    print("=" * 40)

    # Test 1: Can Power BI execute a simple DAX query?
    print("\nTest 1: Connection and query execution")

    connection_result = execute_dax_query(
        'EVALUATE ROW("ConnectionTest", 1)'
    )

    print(json.dumps(connection_result, indent=2))

    # Test 2: Does the actual Total Sales measure return 800?
    # This expected value is correct only for the sample data
    # containing Phone=500 and Tablet=300.
    print("\nTest 2: Total Sales validation")

    sales_result = validate_total_sales(800)

    print(json.dumps(sales_result, indent=2))
