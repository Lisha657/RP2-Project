
import json
import os
import re
import subprocess
import time
from pathlib import Path


def find_adomd_dll():
    """Locate the ADOMD.NET DLL installed with Power BI Desktop."""
    root = Path(r"C:\Program Files\WindowsApps")
    known = root / (
        r"Microsoft.MicrosoftPowerBIDesktop_2.159.883.0_x64__8wekyb3d8bbwe"
        r"\bin\Microsoft.PowerBI.AdomdClient.dll"
    )

    if known.is_file():
        return known

    try:
        matches = [
            p for p in root.glob(
                "Microsoft.MicrosoftPowerBIDesktop_*/bin/"
                "Microsoft.PowerBI.AdomdClient.dll"
            )
            if p.is_file()
        ]
        if matches:
            return max(matches, key=lambda p: p.stat().st_mtime)
    except OSError:
        pass

    raise FileNotFoundError(
        "Microsoft.PowerBI.AdomdClient.dll was not found."
    )


def _get_port_files():
    """Find Power BI Store App workspace port files."""
    root = (
        Path.home()
        / "Microsoft"
        / "Power BI Desktop Store App"
        / "AnalysisServicesWorkspaces"
    )

    if not root.exists():
        raise FileNotFoundError(
            f"Power BI workspace directory not found: {root}"
        )

    files = list(root.glob("**/msmdsrv.port.txt"))
    if not files:
        raise FileNotFoundError("No Power BI port files were found.")

    return sorted(
        files,
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )


def _read_port_file(path):
    """Read a port number from a Power BI workspace file."""
    raw = path.read_bytes()

    for encoding in ("utf-16", "utf-8-sig", "utf-8"):
        try:
            value = raw.decode(encoding).replace("\x00", "").strip()
            if value.isdigit() and 1 <= int(value) <= 65535:
                return value
        except (UnicodeError, ValueError):
            continue

    return None


def _expected_tables(model_path=None):
    """Read table declarations from extracted TMDL, if available."""
    if not model_path:
        return set()

    root = Path(model_path)
    if not root.is_dir():
        return set()

    names = set()
    pattern = re.compile(
        r"""(?mi)^\s*table\s+(?:'((?:[^']|'')+)'|([^\s=]+))"""
    )

    for file in root.rglob("*.tmdl"):
        try:
            content = file.read_text(encoding="utf-8-sig")
        except (OSError, UnicodeError):
            continue

        for match in pattern.finditer(content):
            name = (match.group(1) or match.group(2)).replace("''", "'")
            names.add(name.casefold())

    return names


def _run_powershell(script, env, timeout=30):
    """Run a PowerShell operation and return its result."""
    return subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            script,
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        env=env,
        check=False,
    )


def _read_live_tables(port, dll):
    """Return the table names exposed by a live Power BI model."""
    env = os.environ.copy()
    env["POWERBI_ADOMD_DLL"] = str(dll)
    env["POWERBI_PORT"] = str(port)

    script = r"""
$ErrorActionPreference = 'Stop'
$conn = $null
$reader = $null

try {
    Add-Type -Path $env:POWERBI_ADOMD_DLL -ErrorAction Stop
    $conn = New-Object Microsoft.AnalysisServices.AdomdClient.AdomdConnection
    $conn.ConnectionString = "Data Source=localhost:$env:POWERBI_PORT"
    $conn.Open()

    $cmd = $conn.CreateCommand()
    $cmd.CommandText = 'SELECT [Name] FROM $SYSTEM.TMSCHEMA_TABLES'
    $reader = $cmd.ExecuteReader()

    $names = [System.Collections.Generic.List[string]]::new()
    while ($reader.Read()) {
        if (-not $reader.IsDBNull(0)) {
            $names.Add([string]$reader.GetValue(0))
        }
    }

    $reader.Close()
    $reader = $null
    ConvertTo-Json -InputObject @($names.ToArray()) -Compress
}
catch {
    Write-Error $_.Exception.ToString()
    exit 1
}
finally {
    if ($reader) { $reader.Close() }
    if ($conn -and $conn.State -eq 'Open') { $conn.Close() }
}
"""

    try:
        result = _run_powershell(script, env, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return None

    if result.returncode != 0:
        return None

    lines = [
        line.strip()
        for line in result.stdout.splitlines()
        if line.strip()
    ]

    for line in reversed(lines):
        try:
            data = json.loads(line)
            if isinstance(data, str):
                return [data]
            if isinstance(data, list):
                return [str(x) for x in data]
        except json.JSONDecodeError:
            continue

    return None


def _matches_expected(live_names, expected_names):
    """Avoid selecting a different open report's model."""
    if not live_names:
        return False

    if not expected_names:
        return True

    live = {name.casefold() for name in live_names}
    # Require every expected table to be present.
    return expected_names.issubset(live)


def find_powerbi_port(model_path=None, wait_seconds=0):
    """
    Find a live model matching the extracted model's table names.
    When wait_seconds is positive, poll while the report is loading.
    """
    dll = find_adomd_dll()
    expected = _expected_tables(model_path)
    deadline = time.monotonic() + max(0, wait_seconds)
    last_checked = set()

    while True:
        for port_file in _get_port_files():
            port = _read_port_file(port_file)

            if not port or port in last_checked:
                # During polling, ports can become usable later.
                if not port:
                    continue
                if time.monotonic() < deadline:
                    last_checked.discard(port)
                else:
                    continue

            last_checked.add(port)
            names = _read_live_tables(port, dll)

            if names and _matches_expected(names, expected):
                print(
                    f"Connected to Power BI port {port}; "
                    f"{len(names)} model tables detected."
                )
                return port

        if time.monotonic() >= deadline:
            break

        time.sleep(2)
        # Recheck previously seen ports because their models may load later.
        last_checked.clear()

    if expected:
        raise RuntimeError(
            "No live Power BI model matched the selected report's "
            f"expected tables: {', '.join(sorted(expected))}. "
            "The report may still be loading, or a refresh/credential "
            "prompt may need attention."
        )

    raise RuntimeError(
        "No usable Power BI model with tables was found. "
        "Open the intended report and wait for its model to load."
    )


def _open_pbix(pbix_path):
    """Ask Windows to open a PBIX through its registered application."""
    path = Path(pbix_path).expanduser().resolve()

    if not path.is_file() or path.suffix.casefold() != ".pbix":
        raise FileNotFoundError(f"PBIX file not found: {path}")

    # Passing the PBIX path to Windows uses the registered Power BI app.
    os.startfile(str(path))


def _execute_on_port(dax_query, port, dll):
    """Execute a DAX query and return its rows or an error."""
    env = os.environ.copy()
    env["POWERBI_DAX_QUERY"] = dax_query
    env["POWERBI_ADOMD_DLL"] = str(dll)
    env["POWERBI_PORT"] = str(port)

    script = r"""
$ErrorActionPreference = 'Stop'
$conn = $null
$reader = $null

try {
    Add-Type -Path $env:POWERBI_ADOMD_DLL -ErrorAction Stop
    $conn = New-Object Microsoft.AnalysisServices.AdomdClient.AdomdConnection
    $conn.ConnectionString = "Data Source=localhost:$env:POWERBI_PORT"
    $conn.Open()

    $cmd = $conn.CreateCommand()
    $cmd.CommandText = $env:POWERBI_DAX_QUERY
    $reader = $cmd.ExecuteReader()

    $rows = [System.Collections.Generic.List[object]]::new()
    while ($reader.Read()) {
        $row = [System.Collections.Generic.List[object]]::new()

        for ($i = 0; $i -lt $reader.FieldCount; $i++) {
            $value = $reader.GetValue($i)

            if ($null -eq $value -or $value -is [DBNull]) {
                $row.Add($null)
            }
            elseif ($value -is [datetime]) {
                $row.Add($value.ToString("o"))
            }
            elseif ($value -is [bool]) {
                $row.Add($value)
            }
            elseif ($value -is [System.IConvertible]) {
                $row.Add($value)
            }
            else {
                $row.Add($value.ToString())
            }
        }

        $rows.Add($row.ToArray())
    }

    $reader.Close()
    $reader = $null

    @{ success = $true; rows = $rows.ToArray() } |
        ConvertTo-Json -Depth 10 -Compress
}
catch {
    @{ success = $false; error = $_.Exception.ToString() } |
        ConvertTo-Json -Depth 5 -Compress
}
finally {
    if ($reader) { $reader.Close() }
    if ($conn -and $conn.State -eq 'Open') { $conn.Close() }
}
"""

    result = _run_powershell(script, env, timeout=60)

    if result.returncode != 0 and not result.stdout.strip():
        return {
            "success": False,
            "error": result.stderr.strip() or "PowerShell failed.",
        }

    for line in reversed(result.stdout.splitlines()):
        try:
            response = json.loads(line.strip())
            if isinstance(response, dict) and "success" in response:
                return response
        except json.JSONDecodeError:
            continue

    return {
        "success": False,
        "error": (
            "Could not parse PowerShell output. "
            + (result.stderr.strip() or result.stdout.strip())
        ),
    }


def execute_dax_query(
    dax_query,
    pbix_path=None,
    model_path=None,
    wait_seconds=90,
):
    """
    Execute DAX against the selected model.

    If pbix_path is provided, open it when no matching model is ready.
    """
    try:
        dll = find_adomd_dll()
        expected = _expected_tables(model_path)

        # Reuse a model only if it matches this report's TMDL tables.
        try:
            port = find_powerbi_port(
                model_path=model_path,
                wait_seconds=0,
            )
        except (RuntimeError, OSError, FileNotFoundError):
            port = None

        if port is None and pbix_path:
            _open_pbix(pbix_path)

        if port is None:
            port = find_powerbi_port(
                model_path=model_path,
                wait_seconds=wait_seconds,
            )

        response = _execute_on_port(dax_query, port, dll)

        if not response.get("success"):
            return {
                "status": "FAIL",
                "check": "dax_execution",
                "message": response.get(
                    "error", "Power BI rejected the DAX query."
                ),
                "port": port,
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
            "message": "DAX execution timed out.",
        }
    except (FileNotFoundError, RuntimeError, ValueError, OSError) as exc:
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


def validate_total_sales(
    expected_value,
    pbix_path=None,
    model_path=None,
):
    """Compare [Total Sales] with an independently verified value."""
    result = execute_dax_query(
        'EVALUATE ROW("Total Sales", [Total Sales])',
        pbix_path=pbix_path,
        model_path=model_path,
    )

    if result["status"] != "PASS":
        return {
            **result,
            "check": "dax_runtime_value",
            "measure": "Total Sales",
        }

    rows = result.get("rows", [])
    if not rows or not rows[0]:
        return {
            "status": "FAIL",
            "check": "dax_runtime_value",
            "measure": "Total Sales",
            "message": "The query returned no measure value.",
        }

    try:
        actual = float(rows[0][0])
        expected = float(expected_value)
    except (TypeError, ValueError, OverflowError):
        return {
            "status": "FAIL",
            "check": "dax_runtime_value",
            "measure": "Total Sales",
            "message": "Actual or expected value is not numeric.",
        }

    tolerance = 1e-9 * max(1.0, abs(expected))

    if abs(actual - expected) > tolerance:
        return {
            "status": "FAIL",
            "check": "dax_runtime_value",
            "measure": "Total Sales",
            "actual": actual,
            "expected": expected,
            "message": "The actual measure differs from the expected value.",
        }

    return {
        "status": "PASS",
        "check": "dax_runtime_value",
        "measure": "Total Sales",
        "actual": actual,
        "expected": expected,
        "message": "The measure result matches the expected value.",
    }


if __name__ == "__main__":
    print("Power BI DAX Runtime Checker")
    print("=" * 40)
    result = execute_dax_query(
        'EVALUATE ROW("ConnectionTest", 1)'
    )
    print(json.dumps(result, indent=2))
