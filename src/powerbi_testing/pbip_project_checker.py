import json
from pathlib import Path


SKIP_DIRECTORIES = {
    ".git",
    ".venv",
    "venv",
    "__pycache__",
    "node_modules",
    ".idea",
    ".pytest_cache",
    "staticresources",
}


def check_powerbi_project(project_path):
    """Inspect accessible Power BI project files and report findings."""

    root = Path(project_path).expanduser().resolve()
    findings = []
    page_count = None
    visual_files = []

    def add(status, check, message, evidence=None):
        findings.append({
            "status": status,
            "check": check,
            "message": message,
            "evidence": evidence if evidence is not None else [],
        })

    def should_skip(path):
        try:
            relative = path.relative_to(root)
        except ValueError:
            return True

        return any(
            part.casefold() in SKIP_DIRECTORIES
            for part in relative.parts
        )

    def finish(project_format, pbip_files, pbix_files,
               json_files_checked=0):
        statuses = {item["status"] for item in findings}

        if "FAIL" in statuses:
            overall_status = "FAIL"
        elif "WARNING" in statuses:
            overall_status = "WARNING"
        elif "NOT_TESTED" in statuses:
            overall_status = "NOT_TESTED"
        else:
            overall_status = "PASS"

        return {
            "project_path": str(root),
            "overall_status": overall_status,
            "summary": {
                "project_format": project_format,
                "pbip_files_found": len(pbip_files),
                "pbix_files_found": len(pbix_files),
                "json_files_checked": json_files_checked,
                "visual_files_found": len(visual_files),
                "page_count": page_count,
                "findings_count": len(findings),
                "failures": sum(
                    item["status"] == "FAIL" for item in findings
                ),
                "warnings": sum(
                    item["status"] == "WARNING" for item in findings
                ),
                "not_tested": sum(
                    item["status"] == "NOT_TESTED" for item in findings
                ),
            },
            "findings": findings,
        }

    if not root.exists() or not root.is_dir():
        add(
            "FAIL",
            "project_path",
            "Project folder does not exist or is not a directory.",
            [str(root)],
        )
        return finish("UNKNOWN", [], [])

    # Discover files recursively, excluding common generated folders.
    all_files = []
    all_dirs = []
    scan_errors = []

    for current_path in [root]:
        # The recursive walk below avoids entering skipped directories.
        pass

    import os

    for current, dirs, files in os.walk(root):
        current_path = Path(current)

        dirs[:] = [
            directory for directory in dirs
            if directory.casefold() not in SKIP_DIRECTORIES
        ]

        for filename in files:
            path = current_path / filename

            if not should_skip(path):
                all_files.append(path)

        for directory in dirs:
            path = current_path / directory

            if not should_skip(path):
                all_dirs.append(path)

    pbip_files = [
        path for path in all_files
        if path.suffix.casefold() == ".pbip"
    ]

    pbix_files = [
        path for path in all_files
        if path.suffix.casefold() == ".pbix"
    ]

    report_folders = [
        path for path in all_dirs
        if path.name.casefold().endswith(".report")
    ]

    semantic_folders = [
        path for path in all_dirs
        if path.name.casefold().endswith(".semanticmodel")
    ]

    tmdl_files = [
        path for path in all_files
        if path.suffix.casefold() == ".tmdl"
    ]

    json_files = [
        path for path in all_files
        if path.suffix.casefold() == ".json"
        and "staticresources" not in {
            part.casefold() for part in path.parts
        }
    ]

    if pbip_files or report_folders or semantic_folders:
        project_format = "PBIP"
    elif pbix_files:
        project_format = "PBIX"
    else:
        project_format = "UNKNOWN"

    add(
        "PASS" if project_format != "UNKNOWN" else "WARNING",
        "project_format_detection",
        f"Detected project format: {project_format}",
        {
            "pbip_files": [
                str(path.relative_to(root))
                for path in pbip_files[:10]
            ],
            "pbix_files": [
                str(path.relative_to(root))
                for path in pbix_files[:10]
            ],
            "report_folders": [
                str(path.relative_to(root))
                for path in report_folders[:10]
            ],
            "semantic_model_folders": [
                str(path.relative_to(root))
                for path in semantic_folders[:10]
            ],
        },
    )

    # Check whether the expected kinds of PBIP artifacts exist.
    if project_format == "PBIP":
        report_definition_files = [
            path for path in all_files
            if path.name.casefold() == "definition.pbir"
        ]

        report_json_files = [
            path for path in json_files
            if path.name.casefold() == "report.json"
            and any(
                part.casefold().endswith(".report")
                for part in path.parts
            )
        ]

        pages_json_files = [
            path for path in json_files
            if path.name.casefold() == "pages.json"
            and any(
                part.casefold() == "pages"
                for part in path.parts
            )
            and any(
                part.casefold().endswith(".report")
                for part in path.parts
            )
        ]

        model_definition_files = [
            path for path in tmdl_files
            if path.name.casefold() == "model.tmdl"
            and any(
                part.casefold().endswith(".semanticmodel")
                for part in path.parts
            )
        ]

        # A PBIP project can have a different structure or a report-only
        # or model-only layout. Missing components are not always failures.
        checks = [
            (
                "report_definition",
                report_definition_files,
                "No definition.pbir file was found.",
            ),
            (
                "report_json",
                report_json_files,
                "No report.json file was found inside a report folder.",
            ),
            (
                "pages_json",
                pages_json_files,
                "No pages.json file was found inside a report pages folder.",
            ),
            (
                "model_tmdl",
                model_definition_files,
                "No model.tmdl file was found inside a semantic model folder.",
            ),
        ]

        for check_name, matches, missing_message in checks:
            if matches:
                add(
                    "PASS",
                    check_name,
                    f"Found {len(matches)} matching project item(s).",
                    [
                        str(path.relative_to(root))
                        for path in matches[:10]
                    ],
                )
            else:
                add(
                    "NOT_TESTED",
                    check_name,
                    missing_message
                    + " The project may use another supported layout "
                      "or may not contain this component.",
                )

        # Validate JSON syntax for all discovered report/model JSON files.
        invalid_json = []
        valid_json_count = 0

        for path in json_files:
            try:
                with path.open("r", encoding="utf-8-sig") as file:
                    json.load(file)
                valid_json_count += 1

            except (
                json.JSONDecodeError,
                UnicodeDecodeError,
                OSError,
            ) as error:
                invalid_json.append({
                    "file": str(path.relative_to(root)),
                    "error": str(error),
                })

        if invalid_json:
            add(
                "FAIL",
                "json_validation",
                f"Found {len(invalid_json)} invalid or unreadable "
                "JSON file(s).",
                invalid_json[:50],
            )
        else:
            add(
                "PASS",
                "json_validation",
                f"All {valid_json_count} discovered JSON files "
                "were parsed successfully.",
            )

        # Read page order from the first accessible pages.json file.
        pages_file = next(
            (path for path in pages_json_files if path.is_file()),
            None,
        )

        if pages_file:
            try:
                with pages_file.open(
                    "r", encoding="utf-8-sig"
                ) as file:
                    pages_data = json.load(file)

                if isinstance(pages_data, dict):
                    page_order = pages_data.get("pageOrder")

                    if isinstance(page_order, list):
                        page_count = len(page_order)
                        add(
                            "PASS",
                            "report_page_count",
                            f"Found {page_count} page reference(s).",
                            [str(pages_file.relative_to(root))],
                        )
                    else:
                        add(
                            "NOT_TESTED",
                            "report_page_count",
                            "The pages.json file does not contain a "
                            "pageOrder list in the expected format.",
                            [str(pages_file.relative_to(root))],
                        )
                else:
                    add(
                        "NOT_TESTED",
                        "report_page_count",
                        "The pages.json root value is not a JSON object.",
                    )

            except (json.JSONDecodeError, OSError, UnicodeDecodeError) as error:
                add(
                    "FAIL",
                    "report_page_count",
                    "Could not parse the discovered pages.json file.",
                    [str(error)],
                )
        else:
            add(
                "NOT_TESTED",
                "report_page_count",
                "Page count could not be checked because pages.json "
                "was not found.",
            )

        # Visual definition files are generally nested under report folders.
        visual_files = [
            path for path in all_files
            if path.name.casefold() == "visual.json"
            and any(
                part.casefold().endswith(".report")
                for part in path.parts
            )
        ]

        if visual_files:
            add(
                "PASS",
                "visual_files",
                f"Found {len(visual_files)} visual definition file(s).",
                [
                    str(path.relative_to(root))
                    for path in visual_files[:10]
                ],
            )
        else:
            add(
                "NOT_TESTED",
                "visual_files",
                "No accessible visual.json files were found. "
                "Visual definitions may use another layout or format.",
            )

        # A PBIP can contain a report without a local semantic model,
        # so TMDL absence alone is not necessarily a project failure.
        if tmdl_files:
            add(
                "PASS",
                "tmdl_files",
                f"Found {len(tmdl_files)} TMDL file(s).",
                [
                    str(path.relative_to(root))
                    for path in tmdl_files[:10]
                ],
            )
        else:
            add(
                "NOT_TESTED",
                "tmdl_files",
                "No TMDL files were found; semantic model checks may "
                "not be possible from this repository.",
            )

    elif project_format == "PBIX":
        add(
            "INFO",
            "pbix_internal_inspection",
            "PBIX files were detected. Internal inspection depends "
            "on whether extraction has been performed by the main "
            "pipeline. Check the extracted model and report metadata "
            "results for the actual inspection coverage.",
            [
                str(path.relative_to(root))
                for path in pbix_files[:10]
            ],
        )

    else:
        add(
            "NOT_TESTED",
            "powerbi_project_inspection",
            "No PBIP or PBIX artifact was found. The repository may "
            "contain source files without an accessible Power BI project.",
        )

    return finish(
        project_format,
        pbip_files,
        pbix_files,
        json_files_checked=len(json_files) if project_format == "PBIP" else 0,
    )


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Inspect available Power BI project artifacts."
    )

    parser.add_argument(
        "--project-path",
        required=True,
        help="Path to the Power BI project folder.",
    )

    args = parser.parse_args()
    result = check_powerbi_project(args.project_path)

    print(json.dumps(result, indent=2))

    output_dir = Path("reports")
    output_dir.mkdir(parents=True, exist_ok=True)

    output_file = output_dir / "pbip_check_results.json"
    output_file.write_text(
        json.dumps(result, indent=2),
        encoding="utf-8",
    )

    print(f"\nReport saved to: {output_file.resolve()}")