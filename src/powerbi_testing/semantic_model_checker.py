
import re
import json
import argparse
from pathlib import Path


def normalize_name(name):
    """Normalize a TMDL object name for consistent counting."""
    return name.strip().replace("''", "'").casefold()


def extract_declarations(content, keyword):
    """
    Extract TMDL declarations, including quoted names and varied indentation.
    Supports table, measure, and column declarations.
    """
    pattern = re.compile(
        rf"""(?mi)^[ \t]*{re.escape(keyword)}[ \t]+
        (?:'((?:[^']|'')+)'|([^\r\n=]+?))
        [ \t]*(?:=|:=)?[ \t]*$""",
        re.VERBOSE,
    )

    names = set()

    for match in pattern.finditer(content):
        name = (match.group(1) or match.group(2) or "").strip()

        if name:
            names.add(name.replace("''", "'"))

    return names


def check_semantic_model(project_path):
    """Inspect accessible Power BI semantic model TMDL files."""
    root = Path(project_path).expanduser().resolve()
    findings = []

    def add(status, check, message, evidence=None):
        findings.append({
            "status": status,
            "check": check,
            "message": message,
            "evidence": evidence or [],
        })

    # --------------------------------------------------------
    # Find accessible semantic model directories
    # --------------------------------------------------------
    model_dirs = []

    for path in root.rglob("*.SemanticModel"):
        definition = path / "definition"

        if definition.is_dir() and any(definition.rglob("*.tmdl")):
            model_dirs.append(definition)

    if not model_dirs:
        for model_dir in root.rglob("Model"):
            if model_dir.is_dir() and any(model_dir.rglob("*.tmdl")):
                model_dirs.append(model_dir)

    if root.is_dir() and any(root.rglob("*.tmdl")):
        if (
            (root / "model.tmdl").is_file()
            or (root / "database.tmdl").is_file()
            or root.name.casefold() == "definition"
        ):
            model_dirs.append(root)

    model_dirs = sorted(set(path.resolve() for path in model_dirs))

    # --------------------------------------------------------
    # Handle repositories without accessible TMDL files
    # --------------------------------------------------------
    if not model_dirs:
        pbix_files = list(root.rglob("*.pbix")) if root.is_dir() else []

        add(
            "NOT_TESTED",
            "semantic_model_folder",
            (
                "PBIX files were found, but their internal models have not "
                "been extracted. Extract them to an accessible format such "
                "as TMDL before performing static semantic-model checks."
                if pbix_files
                else "No accessible TMDL semantic model was found."
            ),
            [str(path.relative_to(root)) for path in pbix_files[:20]],
        )

        return {
            "overall_status": "NOT_TESTED",
            "summary": {
                "model_directories_checked": 0,
                "tmdl_files_checked": 0,
                "tables_detected": 0,
                "measures_detected": 0,
                "columns_detected": 0,
                "relationships_detected": 0,
            },
            "findings": findings,
        }

    # --------------------------------------------------------
    # Collect declarations across the discovered model files
    # --------------------------------------------------------
    tables = {}
    measures = {}
    columns = {}
    total_tmdl_files = 0
    relationship_count = 0
    read_errors = 0

    for model_dir in model_dirs:
        tmdl_files = sorted(model_dir.rglob("*.tmdl"))
        total_tmdl_files += len(tmdl_files)

        for file_path in tmdl_files:
            try:
                content = file_path.read_text(encoding="utf-8-sig")
            except (OSError, UnicodeError) as error:
                read_errors += 1
                add(
                    "WARNING",
                    "tmdl_read",
                    f"Could not read {file_path.name}: {error}",
                    [str(file_path)],
                )
                continue

            for name in extract_declarations(content, "table"):
                tables.setdefault(normalize_name(name), name)

            for name in extract_declarations(content, "measure"):
                measures.setdefault(normalize_name(name), name)

            for name in extract_declarations(content, "column"):
                columns.setdefault(normalize_name(name), name)

            relationship_count += len(
                re.findall(
                    r"(?mi)^[ \t]*relationship[ \t]+",
                    content,
                )
            )

    # --------------------------------------------------------
    # Inventory summary
    # --------------------------------------------------------
    add(
        "PASS",
        "tmdl_inventory",
        (
            f"Inspected {total_tmdl_files} TMDL files across "
            f"{len(model_dirs)} model directories."
        ),
        [
            f"Tables declared: {len(tables)}",
            f"Measures declared: {len(measures)}",
            f"Columns declared: {len(columns)}",
            f"Relationships declared: {relationship_count}",
        ],
    )

    # --------------------------------------------------------
    # Table declarations
    # --------------------------------------------------------
    add(
        "PASS" if tables else "WARNING",
        "table_declarations",
        (
            f"Found {len(tables)} distinct table declaration(s)."
            if tables
            else "No table declarations were detected by the text scan."
        ),
        sorted(tables.values(), key=str.casefold),
    )

    # --------------------------------------------------------
    # Measure declarations
    # --------------------------------------------------------
    add(
        "PASS" if measures else "WARNING",
        "measure_declarations",
        (
            f"Found {len(measures)} distinct measure name(s) across "
            "the inspected TMDL files."
            if measures
            else (
                "No measure declarations were detected by the text scan. "
                "The model may contain no measures, or its TMDL syntax "
                "may require additional parser support."
            )
        ),
        sorted(measures.values(), key=str.casefold),
    )

    # --------------------------------------------------------
    # Column declarations
    # --------------------------------------------------------
    add(
        "PASS" if columns else "WARNING",
        "column_declarations",
        (
            f"Found {len(columns)} distinct column name(s) across "
            "the inspected TMDL files."
            if columns
            else "No column declarations were detected by the text scan."
        ),
        sorted(columns.values(), key=str.casefold),
    )

    # --------------------------------------------------------
    # Relationship inventory
    # --------------------------------------------------------
    add(
        "PASS" if relationship_count else "NOT_TESTED",
        "relationship_inventory",
        (
            f"Found {relationship_count} relationship declaration(s) "
            "in the TMDL files."
            if relationship_count
            else "No relationship declarations were detected by the text scan."
        ),
    )

    # --------------------------------------------------------
    # Determine overall status
    # --------------------------------------------------------
    statuses = {finding["status"] for finding in findings}

    overall_status = (
        "FAIL" if "FAIL" in statuses
        else "WARNING" if "WARNING" in statuses
        else "PARTIAL" if "NOT_TESTED" in statuses
        else "PASS"
    )

    return {
        "overall_status": overall_status,
        "summary": {
            "model_directories_checked": len(model_dirs),
            "tmdl_files_checked": total_tmdl_files,
            "tables_detected": len(tables),
            "measures_detected": len(measures),
            "columns_detected": len(columns),
            "relationships_detected": relationship_count,
        },
        "findings": findings,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Inspect Power BI semantic model TMDL files."
    )
    parser.add_argument(
        "--project-path",
        required=True,
        help="Path to the Power BI project or extracted repository.",
    )

    args = parser.parse_args()
    result = check_semantic_model(args.project_path)
    print(json.dumps(result, indent=2))
