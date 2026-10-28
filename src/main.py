
import argparse
import json
import re
import shutil
import subprocess
import urllib.request
import urllib.error
import zipfile
from pathlib import Path

from src.powerbi_testing.file_discovery import discover_files
from src.powerbi_testing.requirements import check_requirements
from src.powerbi_testing.pbip_project_checker import check_powerbi_project
from src.powerbi_testing.semantic_model_checker import check_semantic_model
from src.powerbi_testing.relationship_checker import check_relationships
from src.powerbi_testing.report_generator import generate_markdown_report
from src.powerbi_testing.dax_checker import check_dax
from src.powerbi_testing.dax_execution_checker import (
    execute_dax_query,
    validate_total_sales,
)
from src.data_quality.data_quality_checker import check_data_directory
from src.powerbi_testing.dashboard_visual_checker import check_dashboard_visuals


REPORTS_DIR = Path("reports")
PBI_TOOLS = Path(r"C:\Tools\pbi-tools.exe")


def download_github_repo(repo_url):
    """Download and safely extract a public GitHub repository."""
    repo_url = repo_url.strip().removesuffix(".git").rstrip("/")

    match = re.fullmatch(
        r"https://github\.com/([^/]+)/([^/]+)",
        repo_url,
        re.IGNORECASE,
    )
    if not match:
        raise ValueError(
            "Use a public GitHub URL like "
            "https://github.com/owner/repository"
        )

    owner, repo = match.groups()
    headers = {"User-Agent": "PowerBI-Dashboard-Testing-Agent"}

    request = urllib.request.Request(
        f"https://api.github.com/repos/{owner}/{repo}",
        headers=headers,
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        repo_info = json.loads(response.read().decode("utf-8"))

    archive_url = (
        f"https://api.github.com/repos/{owner}/{repo}/zipball/"
        f"{repo_info['default_branch']}"
    )

    download_root = Path("downloaded_repositories").resolve()
    download_root.mkdir(parents=True, exist_ok=True)

    project_dir = download_root / f"{owner}_{repo}"
    zip_path = download_root / f"{owner}_{repo}.zip"

    if project_dir.exists():
        shutil.rmtree(project_dir)

    request = urllib.request.Request(archive_url, headers=headers)

    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            zip_path.write_bytes(response.read())

        project_dir.mkdir(parents=True, exist_ok=True)

        with zipfile.ZipFile(zip_path, "r") as archive:
            root = project_dir.resolve()

            for member in archive.infolist():
                destination = (project_dir / member.filename).resolve()
                if destination != root and root not in destination.parents:
                    raise ValueError(
                        "Unsafe path found in repository archive."
                    )

            archive.extractall(project_dir)
    finally:
        zip_path.unlink(missing_ok=True)

    children = list(project_dir.iterdir())
    if len(children) == 1 and children[0].is_dir():
        return children[0].resolve()

    return project_dir.resolve()


def find_powerbi_project(root_path):
    """Find a likely Power BI project inside a repository."""
    root = Path(root_path).resolve()

    pbip_files = sorted(root.rglob("*.pbip"))
    if pbip_files:
        return pbip_files[0].parent

    for folder in [root, *root.rglob("*")]:
        if not folder.is_dir():
            continue

        if (
            any(folder.glob("*.Report"))
            and any(folder.glob("*.SemanticModel"))
        ):
            return folder

    return root


def find_pbip_model(project_path):
    """Locate a PBIP semantic model definition folder."""
    root = Path(project_path).resolve()

    for semantic_model in sorted(root.rglob("*.SemanticModel")):
        definition = semantic_model / "definition"
        if definition.is_dir() and any(definition.rglob("*.tmdl")):
            return definition.resolve()

    return None


def find_extracted_model(project_path):
    """Locate an extracted PBIX model containing TMDL files."""
    root = Path(project_path).resolve()

    if root.is_dir() and any(root.rglob("*.tmdl")):
        if root.name.lower() in {"model", "definition"}:
            return root

    candidates = [
        folder for folder in root.rglob("Model")
        if folder.is_dir() and any(folder.rglob("*.tmdl"))
    ]

    if candidates:
        return sorted(
            candidates,
            key=lambda path: len(path.parts),
        )[0].resolve()

    return None


def extract_one_pbix(project_path, selected_pbix=None):
    """Use an accessible PBIP/TMDL model or extract one PBIX."""
    root = Path(project_path).resolve()

    existing_model = find_pbip_model(root)
    if existing_model:
        return existing_model, {
            "status": "PASS",
            "method": "PBIP",
            "message": "Using the accessible PBIP semantic model.",
            "model_path": str(existing_model),
        }

    existing_model = find_extracted_model(root)
    if existing_model:
        return existing_model, {
            "status": "PASS",
            "method": "EXISTING_TMDL",
            "message": "An accessible extracted TMDL model was found.",
            "model_path": str(existing_model),
        }

    pbix_files = sorted(root.rglob("*.pbix"))
    if not pbix_files:
        return None, {
            "status": "NOT_TESTED",
            "method": "NONE",
            "message": "No PBIP model or PBIX file was found.",
        }

    if selected_pbix:
        requested = Path(selected_pbix).expanduser()
        if not requested.is_absolute():
            requested = (root / requested).resolve()

        matches = [
            path for path in pbix_files
            if path.resolve() == requested.resolve()
        ]
        if not matches:
            return None, {
                "status": "NOT_TESTED",
                "method": "PBIX",
                "message": (
                    "The selected PBIX was not found inside the project. "
                    "Use --pbix-path with a path relative to the repository."
                ),
            }
        pbix = matches[0]
    else:
        pbix = pbix_files[0]

    if not PBI_TOOLS.is_file():
        return None, {
            "status": "NOT_TESTED",
            "method": "PBIX",
            "file": str(pbix.relative_to(root)),
            "message": (
                f"pbi-tools was not found at {PBI_TOOLS}. "
                "Install it or update PBI_TOOLS in main.py."
            ),
        }

    try:
        process = subprocess.run(
            [str(PBI_TOOLS), "extract", str(pbix)],
            capture_output=True,
            text=True,
            timeout=300,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return None, {
            "status": "NOT_TESTED",
            "method": "PBIX",
            "file": str(pbix.relative_to(root)),
            "message": f"PBIX extraction could not run: {exc}",
        }

    model_path = find_extracted_model(pbix.parent)

    if model_path is None:
        possible_output = pbix.with_suffix("")
        if possible_output.is_dir():
            model_path = find_extracted_model(possible_output)

    if process.returncode == 0 and model_path:
        return model_path, {
            "status": "PASS",
            "method": "PBIX_EXTRACTION",
            "file": str(pbix.relative_to(root)),
            "model_path": str(model_path),
            "tmdl_files": len(list(model_path.rglob("*.tmdl"))),
            "message": "PBIX extraction produced accessible TMDL files.",
        }

    details = (process.stderr or process.stdout or "").strip()
    return None, {
        "status": "NOT_TESTED",
        "method": "PBIX_EXTRACTION",
        "file": str(pbix.relative_to(root)),
        "message": (
            "Extraction did not produce an accessible TMDL model. "
            + details[:1500]
        ),
    }


def save_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def safe_status(result):
    return str(result.get("overall_status", "NOT_TESTED")).upper()


def finding(status, check, message, source):
    return {
        "status": status,
        "check": check,
        "message": message,
        "source": source,
    }


def deduplicate_findings(findings):
    """Remove identical findings while retaining distinct issues."""
    unique = []
    seen = set()

    for item in findings:
        key = (
            item.get("source"),
            item.get("check"),
            item.get("file"),
            item.get("dataset"),
            item.get("column"),
            item.get("status"),
            item.get("message"),
        )

        if key not in seen:
            seen.add(key)
            unique.append(item)

    return unique


def run_dax_runtime_test(enabled, expected_total_sales=None):
    """
    Optionally test the currently open Power BI Desktop model.

    Important: This model may differ from the GitHub repository
    currently being inspected.
    """
    if not enabled:
        return {
            "status": "NOT_TESTED",
            "check": "dax_runtime",
            "message": (
                "Runtime testing was not enabled. Use "
                "--enable-dax-runtime to run it."
            ),
        }

    if expected_total_sales is not None:
        result = validate_total_sales(expected_total_sales)
    else:
        result = execute_dax_query(
            'EVALUATE ROW("ConnectionTest", 1)'
        )

    return {
        **result,
        "check": result.get("check", "dax_runtime"),
    }


def main():
    parser = argparse.ArgumentParser(
        description="AI-Powered Power BI Dashboard Testing Agent"
    )

    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--github-url",
        help="Public GitHub repository URL",
    )
    group.add_argument(
        "--project-path",
        help="Path to an already downloaded repository or project",
    )

    parser.add_argument(
        "--data-path",
        default=None,
        help="Optional CSV/Excel file or dataset folder",
    )
    parser.add_argument(
        "--numeric-columns",
        default="",
        help="Comma-separated list of columns expected to be numeric",
    )
    parser.add_argument(
        "--kpi-rules",
        default="kpi_rules.json",
        help="Path to KPI validation rules JSON",
    )
    parser.add_argument(
        "--pbix-path",
        default=None,
        help="Optional PBIX path relative to the repository",
    )
    parser.add_argument(
        "--enable-dax-runtime",
        action="store_true",
        help="Execute DAX against an open Power BI Desktop model",
    )
    parser.add_argument(
        "--expected-total-sales",
        type=float,
        default=None,
        help="Trusted expected Total Sales value for runtime validation",
    )

    args = parser.parse_args()
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    try:
        if args.github_url:
            print("\nDownloading GitHub repository...")
            repository_path = download_github_repo(args.github_url)
        else:
            repository_path = Path(
                args.project_path
            ).expanduser().resolve()

            if not repository_path.is_dir():
                parser.error(
                    "The supplied project directory does not exist."
                )

        project_path = find_powerbi_project(repository_path)

    except (
        ValueError,
        urllib.error.URLError,
        urllib.error.HTTPError,
        OSError,
        zipfile.BadZipFile,
    ) as exc:
        parser.exit(1, f"\nRepository preparation failed: {exc}\n")

    print(f"\nRepository location: {repository_path}")
    print(f"Project location:    {project_path}")

    # 1. Discover repository files.
    print("\n[1/8] Discovering repository files...")
    discovery_result = discover_files(repository_path)
    save_json(REPORTS_DIR / "file_inventory.json", discovery_result)

    print(
        "Detected format:",
        discovery_result.get("project_format", "UNKNOWN"),
    )

    for file_type, count in discovery_result.get(
        "summary", {}
    ).get("files_by_type", {}).items():
        if count:
            print(f"  {file_type}: {count}")

    # 2. Prepare semantic model.
    print("\n[2/8] Preparing the semantic model...")
    model_path, model_preparation = extract_one_pbix(
        repository_path,
        selected_pbix=args.pbix_path,
    )

    print("Model preparation:", model_preparation["status"])
    print(model_preparation["message"])

    if model_path:
        print("Model location:", model_path)

    save_json(
        REPORTS_DIR / "model_preparation_results.json",
        model_preparation,
    )

    all_findings = []
    combined_summary = {
        "model_preparation_status": model_preparation["status"],
        "model_preparation_method": model_preparation.get(
            "method", "NONE"
        ),
    }

    if model_preparation["status"] != "PASS":
        all_findings.append(finding(
            "NOT_TESTED",
            "model_preparation",
            model_preparation["message"],
            "model_preparation",
        ))

    # 3. Check project structure.
    print("\n[3/8] Checking project structure...")
    project_result = check_powerbi_project(str(project_path))
    print("Project status:", safe_status(project_result))

    all_findings.extend(project_result.get("findings", []))
    combined_summary.update(project_result.get("summary", {}))

    if (
        model_path
        and model_preparation.get("method") == "PBIX_EXTRACTION"
    ):
        checker_model_path = model_path
    else:
        checker_model_path = project_path

    # 4. Check semantic model.
    print("\n[4/8] Checking semantic model...")

    if model_path:
        semantic_result = check_semantic_model(
            str(checker_model_path)
        )

        if (
            safe_status(semantic_result) == "NOT_TESTED"
            and model_preparation.get("method") == "PBIX_EXTRACTION"
        ):
            tmdl_files = list(model_path.rglob("*.tmdl"))
            table_names = set()
            measure_count = 0
            column_count = 0

            for file_path in tmdl_files:
                try:
                    content = file_path.read_text(
                        encoding="utf-8-sig"
                    )
                except (OSError, UnicodeError):
                    continue

                table_names.update(re.findall(
                    r"(?m)^\s*table\s+(?:'([^']+)'|([^\s=]+))",
                    content,
                ))

                measure_count += len(re.findall(
                    r"(?m)^\s*measure\s+.+?=",
                    content,
                ))

                column_count += len(re.findall(
                    r"(?m)^\s*column\s+",
                    content,
                ))

            normalized_tables = {
                next((part for part in item if part), "")
                for item in table_names
            }

            semantic_result = {
                "overall_status": "PASS" if tmdl_files else "NOT_TESTED",
                "summary": {
                    "tmdl_files_checked": len(tmdl_files),
                    "tables_detected": len(normalized_tables),
                    "measures_detected": measure_count,
                    "columns_detected": column_count,
                    "metadata_inventory_fallback": True,
                },
                "findings": [{
                    "status": "INFO" if tmdl_files else "NOT_TESTED",
                    "check": "extracted_model_inventory",
                    "message": (
                        "TMDL metadata was inventoried. This is an "
                        "inventory fallback, not full semantic validation."
                        if tmdl_files
                        else "No readable TMDL files were found."
                    ),
                }],
            }
    else:
        semantic_result = {
            "overall_status": "NOT_TESTED",
            "summary": {
                "tmdl_files_checked": 0,
                "tables_detected": 0,
                "measures_detected": 0,
                "columns_detected": 0,
            },
            "findings": [{
                "status": "NOT_TESTED",
                "check": "semantic_model",
                "message": "No accessible semantic model was available.",
            }],
        }

    print("Semantic model status:", safe_status(semantic_result))
    all_findings.extend(semantic_result.get("findings", []))
    combined_summary.update(semantic_result.get("summary", {}))

    # 5. Check relationships.
    print("\n[5/8] Checking relationships...")

    if model_path:
        relationship_result = check_relationships(
            str(checker_model_path)
        )
    else:
        relationship_result = {
            "overall_status": "NOT_TESTED",
            "summary": {},
            "findings": [{
                "status": "NOT_TESTED",
                "check": "relationship_validation",
                "message": "No accessible model metadata was available.",
            }],
        }

    print("Relationship status:", safe_status(relationship_result))
    all_findings.extend(relationship_result.get("findings", []))
    combined_summary.update(relationship_result.get("summary", {}))

    # 6. Static DAX checks and optional runtime execution.
    print("\n[6/8] Checking DAX...")

    if model_path:
        dax_result = check_dax(str(checker_model_path))
    else:
        dax_result = {
            "overall_status": "NOT_TESTED",
            "summary": {},
            "findings": [{
                "status": "NOT_TESTED",
                "check": "dax_static_inspection",
                "message": "No accessible TMDL files were available.",
            }],
        }

    print("Static DAX status:", safe_status(dax_result))
    all_findings.extend(dax_result.get("findings", []))
    combined_summary.update(dax_result.get("summary", {}))

    print("\nAutomatically testing DAX runtime...")

    runtime_result = run_dax_runtime_test(
        enabled=True,
        expected_total_sales=args.expected_total_sales,
    )

    runtime_status = str(
        runtime_result.get("status", "NOT_TESTED")
    ).upper()

    combined_summary["dax_runtime_status"] = runtime_status

    save_json(
        REPORTS_DIR / "dax_runtime_results.json",
        runtime_result,
    )

    all_findings.append({
        **runtime_result,
        "source": "dax_runtime",
    })

    print("DAX runtime status:", runtime_status)
    print("DAX runtime message:", runtime_result.get("message", ""))

    if "actual" in runtime_result:
        combined_summary["dax_runtime_actual"] = (
            runtime_result["actual"]
        )
        combined_summary["dax_runtime_expected"] = (
            runtime_result["expected"]
        )

    # 7. Check data quality
    print("\n[7/8] Checking data quality")

    data_path = (
        Path(args.data_path).expanduser().resolve()
        if args.data_path
        else repository_path.resolve()
    )
    numeric_columns = [
        item.strip()
        for item in args.numeric_columns.split(",")
        if item.strip()
    ]

    data_result = check_data_directory(
        data_path,
        numeric_columns=numeric_columns,
    )

    data_summary = data_result.get("summary", {})
    datasets_checked = data_summary.get(
        "files_checked",
        data_result.get("datasets_checked", 0),
    )
    datasets_found = data_summary.get(
        "files_found", datasets_checked
    )
    data_status = safe_status(data_result)

    data_findings = [
        {**item, "source": "data_quality"}
        for item in data_result.get("findings", [])
    ]

    if datasets_checked == 0:
        data_status = "NOT_TESTED"

        availability_exists = any(
            item.get("check") == "data_quality_availability"
            for item in data_findings
        )

        if not availability_exists:
            data_findings.append(finding(
                "NOT_TESTED",
                "data_quality_availability",
                data_result.get(
                    "message",
                    data_result.get(
                        "error",
                        "No supported datasets were checked.",
                    ),
                ),
                "data_quality",
            ))

    all_findings.extend(data_findings)

    combined_summary.update({
        "data_quality_status": data_status,
        "datasets_found": datasets_found,
        "datasets_checked": datasets_checked,
        "data_quality_rows_checked": data_summary.get(
            "total_rows", 0
        ),
        "data_quality_columns_checked": data_summary.get(
            "total_columns", 0
        ),
        "data_quality_missing_values": data_summary.get(
            "total_missing_values", 0
        ),
        "data_quality_duplicate_rows": data_summary.get(
            "total_duplicate_rows", 0
        ),
    })

    print("Data quality status:", data_status)


    # 8. Check dashboard visuals and requirements.
    print("\n[8/8] Checking dashboard visuals and requirements...")

    try:
        visual_result = check_dashboard_visuals(str(project_path))

        visual_status = visual_result.get(
            "status",
            visual_result.get("overall_status", "NOT_TESTED"),
        )

        combined_summary.update({
            "dashboard_visual_status": visual_status,
            "dashboard_pages_checked": visual_result.get(
                "pages_checked", 0
            ),
            "dashboard_visuals_checked": visual_result.get(
                "visuals_checked", 0
            ),
            "dashboard_visual_findings": visual_result.get(
                "findings_count", 0
            ),
        })

        for item in visual_result.get("findings", []):
            severity = str(
                item.get("severity", "INFO")
            ).upper()

            status = {
                "ERROR": "FAIL",
                "WARNING": "WARNING",
            }.get(severity, "INFO")

            all_findings.append({
                **item,
                "source": "dashboard_visual",
                "check": item.get(
                    "check", "dashboard_visual_testing"
                ),
                "status": status,
            })

        print("Dashboard visual status:", visual_status)

    except Exception as exc:
        combined_summary["dashboard_visual_status"] = "NOT_TESTED"

        all_findings.append(finding(
            "NOT_TESTED",
            "dashboard_visual_testing",
            f"Visual inspection could not run: {exc}",
            "dashboard_visual",
        ))

        print("Dashboard visual inspection could not run:", exc)

    try:
        requirement_result = check_requirements(str(project_path))

        combined_summary["requirement_status"] = safe_status(
            requirement_result
        )

        all_findings.extend(
            requirement_result.get("findings", [])
        )

        for key, value in requirement_result.get(
            "summary", {}
        ).items():
            combined_summary[f"requirements_{key}"] = value

        print(
            "Requirement status:",
            safe_status(requirement_result),
        )

    except Exception as exc:
        combined_summary["requirement_status"] = "NOT_TESTED"

        all_findings.append(finding(
            "NOT_TESTED",
            "requirement_validation",
            f"Requirement checks could not run: {exc}",
            "requirements",
        ))

    # Remove identical findings before calculating report totals.
    all_findings = deduplicate_findings(all_findings)

    # Aggregate findings.
    statuses = [
        str(item.get("status", "NOT_TESTED")).upper()
        for item in all_findings
    ]

    if "FAIL" in statuses:
        overall_status = "FAIL"
    elif "WARNING" in statuses:
        overall_status = "WARNING"
    elif "NOT_TESTED" in statuses:
        overall_status = "PARTIAL"
    else:
        overall_status = "PASS"

    combined_summary.update({
        "total_findings": len(all_findings),
        "failures": statuses.count("FAIL"),
        "warnings": statuses.count("WARNING"),
        "not_tested": statuses.count("NOT_TESTED"),
        "informational": statuses.count("INFO"),
        "passed_findings": statuses.count("PASS"),
    })

    combined_result = {
        "project_path": str(project_path),
        "repository_path": str(repository_path),
        "repository_url": args.github_url,
        "overall_status": overall_status,
        "summary": combined_summary,
        "findings": all_findings,
        "file_discovery": discovery_result,
        "model_preparation": model_preparation,
        "dax_runtime": runtime_result,
    }

    json_report = REPORTS_DIR / "pbip_check_results.json"
    markdown_report = REPORTS_DIR / "testing_summary.md"

    save_json(json_report, combined_result)
    generate_markdown_report(json_report, markdown_report)

    print("\n" + "=" * 55)
    print("TESTING COMPLETED")
    print("=" * 55)
    print("Overall status:", overall_status)
    print("Total findings:", len(all_findings))
    print("Failures:", combined_summary["failures"])
    print("Warnings:", combined_summary["warnings"])
    print("Not tested:", combined_summary["not_tested"])
    print("DAX runtime status:", runtime_status)
    print("JSON report:", json_report.resolve())
    print("Markdown report:", markdown_report.resolve())


if __name__ == "__main__":
    main()
