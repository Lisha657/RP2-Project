import json
import re
from pathlib import Path


SKIP_DIRECTORIES = {
    ".git",
    ".venv",
    "venv",
    "__pycache__",
    "node_modules",
    ".idea",
    ".pytest_cache",
}


def check_requirements(project_path, requirements_path=None):
    """Check Power BI project files and optional explicit requirements."""

    root = Path(project_path).expanduser().resolve()
    findings = []

    def add_finding(status, check, message, evidence=None):
        finding = {
            "status": status,
            "source": "requirements",
            "check": check,
            "message": message,
        }
        if evidence is not None:
            finding["evidence"] = evidence
        findings.append(finding)

    def finish():
        statuses = {item["status"] for item in findings}

        if "FAIL" in statuses:
            overall_status = "FAIL"
        elif "WARNING" in statuses:
            overall_status = "WARNING"
        elif "PASS" in statuses:
            overall_status = "PASS"
        else:
            overall_status = "NOT_TESTED"

        return {
            "overall_status": overall_status,
            "summary": {
                "requirements_checked": len(findings),
                "requirements_passed": sum(
                    item["status"] == "PASS" for item in findings
                ),
                "requirements_failed": sum(
                    item["status"] == "FAIL" for item in findings
                ),
                "requirements_not_tested": sum(
                    item["status"] == "NOT_TESTED" for item in findings
                ),
                "requirements_warnings": sum(
                    item["status"] == "WARNING" for item in findings
                ),
            },
            "findings": findings,
        }

    if not root.exists() or not root.is_dir():
        add_finding(
            "FAIL",
            "project_path",
            f"Project directory does not exist: {root}",
        )
        return finish()

    # Recursively find Power BI artifacts, excluding common
    # virtual-environment and version-control directories.
    def should_skip(path):
        return any(
            part.lower() in SKIP_DIRECTORIES
            for part in path.relative_to(root).parts
        )

    all_files = []
    all_dirs = []

    for path in root.rglob("*"):
        if should_skip(path):
            continue

        if path.is_file():
            all_files.append(path)
        elif path.is_dir():
            all_dirs.append(path)

    pbip_files = [
        path for path in all_files
        if path.suffix.lower() == ".pbip"
    ]
    pbix_files = [
        path for path in all_files
        if path.suffix.lower() == ".pbix"
    ]
    tmdl_files = [
        path for path in all_files
        if path.suffix.lower() == ".tmdl"
    ]
    report_dirs = [
        path for path in all_dirs
        if path.name.endswith(".Report")
    ]
    semantic_model_dirs = [
        path for path in all_dirs
        if path.name.endswith(".SemanticModel")
    ]

    has_pbip = bool(
        pbip_files or report_dirs or semantic_model_dirs
    )
    has_pbix = bool(pbix_files)

    if has_pbip:
        project_format = "PBIP"
    elif has_pbix:
        project_format = "PBIX"
    else:
        project_format = "UNKNOWN"

    add_finding(
        "PASS" if project_format != "UNKNOWN" else "WARNING",
        "project_format_detection",
        f"Detected project format: {project_format}",
        {
            "pbip_files": [
                str(path.relative_to(root)) for path in pbip_files
            ],
            "pbix_files": [
                str(path.relative_to(root)) for path in pbix_files
            ],
            "report_folders": [
                str(path.relative_to(root)) for path in report_dirs
            ],
            "semantic_model_folders": [
                str(path.relative_to(root))
                for path in semantic_model_dirs
            ],
        },
    )

    # Read optional explicit project requirements.
    required_files = []
    required_tables = []
    required_measures = []

    if requirements_path:
        config_path = Path(requirements_path).expanduser().resolve()

        try:
            with config_path.open("r", encoding="utf-8") as file:
                custom = json.load(file)

            required_files = custom.get("required_files", [])
            required_tables = custom.get("required_tables", [])
            required_measures = custom.get("required_measures", [])

            if not isinstance(required_files, list):
                raise ValueError("'required_files' must be a list.")
            if not isinstance(required_tables, list):
                raise ValueError("'required_tables' must be a list.")
            if not isinstance(required_measures, list):
                raise ValueError("'required_measures' must be a list.")

        except (OSError, json.JSONDecodeError, ValueError) as exc:
            add_finding(
                "FAIL",
                "requirements_config",
                f"Could not read requirements configuration: {exc}",
            )
            return finish()

    # Match required file patterns against discovered files.
    # Patterns may match a filename or a path relative to the project root.
    for pattern in required_files:
        matches = []

        for path in all_files:
            relative_path = path.relative_to(root).as_posix()

            if (
                path.match(pattern)
                or relative_path == pattern.replace("\\", "/")
                or Path(relative_path).match(pattern.replace("\\", "/"))
            ):
                matches.append(path)

        if matches:
            add_finding(
                "PASS",
                f"required_file:{pattern}",
                f"Found required project item: {pattern}",
                [
                    str(path.relative_to(root))
                    for path in matches
                ],
            )
        else:
            add_finding(
                "FAIL",
                f"required_file:{pattern}",
                f"Required project item was not found: {pattern}",
            )

    # PBIX extraction is handled by the main pipeline.
    # This module checks requirements against available project files
    # and extracted metadata; it does not perform PBIX extraction itself.
    if project_format == "PBIX":
        add_finding(
            "INFO",
            "pbix_metadata_access",
            "PBIX files were detected. Requirement checks in this "
            "module use accessible project files and metadata. "
            "See the main pipeline's extraction and model inspection "
            "results for actual PBIX metadata coverage.",
            [
                str(path.relative_to(root))
                for path in pbix_files
            ],
        )

    elif project_format == "UNKNOWN":
        add_finding(
            "NOT_TESTED",
            "powerbi_artifact_detection",
            "No PBIP or PBIX artifact was detected. "
            "Power BI-specific checks cannot be assessed.",
        )

    # Read model declarations from accessible TMDL files.
    tmdl_text = ""

    for path in tmdl_files:
        try:
            tmdl_text += "\n" + path.read_text(
                encoding="utf-8-sig",
                errors="replace",
            )
        except OSError as exc:
            add_finding(
                "WARNING",
                "tmdl_read_error",
                f"Could not read TMDL file {path.name}: {exc}",
            )

    table_names = set(
        re.findall(
            r"""(?m)^\s*table\s+['"]?([^'"\r\n]+?)['"]?\s*$""",
            tmdl_text,
        )
    )

    measure_names = set(
        re.findall(
            r"""(?m)^\s*measure\s+['"]?([^'"=\r\n]+?)['"]?\s*=""",
            tmdl_text,
        )
    )

    normalized_tables = {
        name.strip().casefold() for name in table_names
    }
    normalized_measures = {
        name.strip().casefold() for name in measure_names
    }

    for table in required_tables:
        if not tmdl_files:
            add_finding(
                "NOT_TESTED",
                f"required_table:{table}",
                f"Cannot verify table '{table}': "
                "no TMDL metadata is available.",
            )
            continue

        found = str(table).strip().casefold() in normalized_tables

        add_finding(
            "PASS" if found else "FAIL",
            f"required_table:{table}",
            (
                f"Table declaration found: {table}"
                if found
                else f"Table declaration not found: {table}"
            ),
        )

    for measure in required_measures:
        if not tmdl_files:
            add_finding(
                "NOT_TESTED",
                f"required_measure:{measure}",
                f"Cannot verify measure '{measure}': "
                "no TMDL metadata is available.",
            )
            continue

        found = str(measure).strip().casefold() in normalized_measures

        add_finding(
            "PASS" if found else "FAIL",
            f"required_measure:{measure}",
            (
                f"Measure declaration found: {measure}"
                if found
                else f"Measure declaration not found: {measure}"
            ),
        )

    if project_format == "PBIP" and not tmdl_files:
        add_finding(
            "NOT_TESTED",
            "semantic_model_metadata",
            "A PBIP-style project was detected, but no TMDL files "
            "were available to inspect table and measure declarations.",
        )

    return finish()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Check Power BI project files and requirements."
    )
    parser.add_argument("--project-path", required=True)
    parser.add_argument("--requirements-path", default=None)
    parser.add_argument(
        "--output",
        default="reports/requirements_results.json",
    )

    args = parser.parse_args()

    result = check_requirements(
        args.project_path,
        args.requirements_path,
    )

    output_path = Path(args.output).expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(result, indent=2),
        encoding="utf-8",
    )

    print(f"Project requirement status: {result['overall_status']}")
    print(
        f"Requirements checked: "
        f"{result['summary']['requirements_checked']}"
    )
    print(f"Passed: {result['summary']['requirements_passed']}")
    print(f"Failed: {result['summary']['requirements_failed']}")
    print(f"Not tested: {result['summary']['requirements_not_tested']}")
    print(f"Warnings: {result['summary']['requirements_warnings']}")
    print(f"Report saved to: {output_path}")