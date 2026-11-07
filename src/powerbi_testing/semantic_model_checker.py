
import re
import json
import argparse
from pathlib import Path


def normalize_name(name):
    """Normalize a TMDL object name for consistent counting."""
    return name.strip().replace("''", "'").casefold()


def extract_declarations(content, keyword):
<<<<<<< HEAD
    """Extract TMDL declarations, including names enclosed in quotes."""
    pattern = re.compile(
        rf"""(?mi)^[ \t]*{re.escape(keyword)}[ \t]+
        (?:'((?:[^']|'')+)'|([^\r\n]+?))
=======
    """
    Extract TMDL declarations, including quoted names and varied indentation.
    Supports table, measure, and column declarations.
    """
    pattern = re.compile(
        rf"""(?mi)^[ \t]*{re.escape(keyword)}[ \t]+
        (?:'((?:[^']|'')+)'|([^\r\n=]+?))
>>>>>>> origin/main
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

<<<<<<< HEAD
=======
    # --------------------------------------------------------
    # Find accessible semantic model directories
    # --------------------------------------------------------
>>>>>>> origin/main
    model_dirs = []

    for path in root.rglob("*.SemanticModel"):
        definition = path / "definition"
<<<<<<< HEAD
=======

>>>>>>> origin/main
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

<<<<<<< HEAD
    if not model_dirs:
        pbix_files = list(root.rglob("*.pbix"))
=======
    # --------------------------------------------------------
    # Handle repositories without accessible TMDL files
    # --------------------------------------------------------
    if not model_dirs:
        pbix_files = list(root.rglob("*.pbix")) if root.is_dir() else []
>>>>>>> origin/main

        add(
            "NOT_TESTED",
            "semantic_model_folder",
            (
                "PBIX files were found, but their internal models have not "
<<<<<<< HEAD
                "been extracted. Run pbi-tools extraction first."
=======
                "been extracted. Extract them to an accessible format such "
                "as TMDL before performing static semantic-model checks."
>>>>>>> origin/main
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

<<<<<<< HEAD
=======
    # --------------------------------------------------------
    # Collect declarations across the discovered model files
    # --------------------------------------------------------
>>>>>>> origin/main
    tables = {}
    measures = {}
    columns = {}
    total_tmdl_files = 0
    relationship_count = 0
<<<<<<< HEAD
=======
    read_errors = 0
>>>>>>> origin/main

    for model_dir in model_dirs:
        tmdl_files = sorted(model_dir.rglob("*.tmdl"))
        total_tmdl_files += len(tmdl_files)

        for file_path in tmdl_files:
            try:
                content = file_path.read_text(encoding="utf-8-sig")
            except (OSError, UnicodeError) as error:
<<<<<<< HEAD
=======
                read_errors += 1
>>>>>>> origin/main
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
<<<<<<< HEAD
                re.findall(r"(?mi)^[ \t]*relationship[ \t]+", content)
            )

=======
                re.findall(
                    r"(?mi)^[ \t]*relationship[ \t]+",
                    content,
                )
            )

    # --------------------------------------------------------
    # Inventory summary
    # --------------------------------------------------------
>>>>>>> origin/main
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
<<<<<<< HEAD
        ],
    )

=======
            f"Relationships declared: {relationship_count}",
        ],
    )

    # --------------------------------------------------------
    # Table declarations
    # --------------------------------------------------------
>>>>>>> origin/main
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

<<<<<<< HEAD
=======
    # --------------------------------------------------------
    # Measure declarations
    # --------------------------------------------------------
>>>>>>> origin/main
    add(
        "PASS" if measures else "WARNING",
        "measure_declarations",
        (
            f"Found {len(measures)} distinct measure name(s) across "
            "the inspected TMDL files."
            if measures
<<<<<<< HEAD
            else "No measure declarations were detected by the text scan."
=======
            else (
                "No measure declarations were detected by the text scan. "
                "The model may contain no measures, or its TMDL syntax "
                "may require additional parser support."
            )
>>>>>>> origin/main
        ),
        sorted(measures.values(), key=str.casefold),
    )

<<<<<<< HEAD
=======
    # --------------------------------------------------------
    # Column declarations
    # --------------------------------------------------------
>>>>>>> origin/main
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

<<<<<<< HEAD
=======
    # --------------------------------------------------------
    # Relationship inventory
    # --------------------------------------------------------
>>>>>>> origin/main
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

<<<<<<< HEAD
=======
    # --------------------------------------------------------
    # Determine overall status
    # --------------------------------------------------------
>>>>>>> origin/main
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
<<<<<<< HEAD
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-path", required=True)
    args = parser.parse_args()

=======
    parser = argparse.ArgumentParser(
        description="Inspect Power BI semantic model TMDL files."
    )
    parser.add_argument(
        "--project-path",
        required=True,
        help="Path to the Power BI project or extracted repository.",
    )

    args = parser.parse_args()
>>>>>>> origin/main
    result = check_semantic_model(args.project_path)
    print(json.dumps(result, indent=2))
