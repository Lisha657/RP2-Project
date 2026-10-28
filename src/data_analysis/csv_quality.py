import json
from pathlib import Path, PurePosixPath
from io import StringIO
import pandas as pd
from src.core.findings import add_finding
from src.core.config import MAX_TEXT_FILE_BYTES


def inspect_csv(content, path, findings):
    try:
        df = pd.read_csv(StringIO(content))

        missing = int(df.isna().sum().sum())
        duplicates = int(df.duplicated().sum())

        if missing:
            add_finding(
                findings, "Data Cleaning", "WARNING",
                f"{missing} missing cells", path,
                "Counted using pandas."
            )

        if duplicates:
            add_finding(
                findings, "Data Cleaning", "WARNING",
                f"{duplicates} duplicate rows", path,
                "Counted using pandas."
            )

        if not missing and not duplicates:
            add_finding(
                findings, "Data Cleaning", "PASS",
                "No missing cells or duplicate rows detected",
                path,
                f"Rows: {len(df)}; columns: {len(df.columns)}."
            )

    except Exception as exc:
        add_finding(
            findings, "Data Cleaning", "FAIL",
            f"Could not read CSV: {exc}", path
        )


def inspect_text_metadata(root, findings):
    root = Path(root)

    files_seen = 0
    model_files = 0
    report_files = 0
    visual_files = 0
    title_warnings = 0
    dax_files = 0
    measures = 0
    relationships = 0
    found_pbip = False

    allowed = {
        ".pbip", ".json", ".tmdl", ".dax",
        ".yaml", ".yml", ".pbir", ".txt", ".bim"
    }

    ignored = {
        ".git", "node_modules", "venv", "__pycache__"
    }

    for path in root.rglob("*"):
        if not path.is_file():
            continue

        if any(part.lower() in ignored for part in path.parts):
            continue

        suffix = path.suffix.lower()
        filename = path.name.lower()
        path_text = str(path).lower()

        if suffix == ".pbip":
            found_pbip = True

        if suffix not in allowed:
            continue

        try:
            if path.stat().st_size > MAX_TEXT_FILE_BYTES:
                add_finding(
                    findings, "PBIP Metadata", "WARNING",
                    "File skipped because it exceeds 1 MB",
                    str(path.relative_to(root))
                )
                continue

            content = path.read_text(
                encoding="utf-8-sig",
                errors="replace"
            )

        except OSError:
            continue

        files_seen += 1
        relative = str(path.relative_to(root)).replace("\\", "/")
        lower = content.lower()

        if (
            suffix == ".tmdl"
            or "semanticmodel" in path_text
            or "model" in filename
        ):
            model_files += 1

            if suffix == ".tmdl":
                measures += lower.count("measure ")
                relationships += lower.count("relationship ")

        if suffix == ".dax":
            dax_files += 1
            add_finding(
                findings, "DAX Static Check", "WARNING",
                "DAX found but not fully validated or executed",
                relative,
                "Runtime validation is still required."
            )

        if "report" in path_text or suffix == ".pbir":
            report_files += 1

        if suffix == ".json" and "visual" in path_text:
            visual_files += 1

            if '"title"' not in lower and '"showtitle"' not in lower:
                title_warnings += 1
                add_finding(
                    findings, "Visual Metadata", "WARNING",
                    "No obvious title property found",
                    relative,
                    "Heuristic only; verify the report definition."
                )

        if suffix == ".json":
            try:
                json.loads(content)
            except Exception as exc:
                add_finding(
                    findings, "PBIP Metadata", "FAIL",
                    f"JSON parsing failed: {exc}", relative
                )

    if found_pbip:
        add_finding(
            findings, "PBIP Metadata", "PASS",
            "Found a .pbip project entry file"
        )
    else:
        add_finding(
            findings, "PBIP Metadata", "WARNING",
            "No .pbip project entry file found"
        )

    if model_files:
        add_finding(
            findings, "Data Model Metadata", "WARNING",
            f"Found {model_files} candidate model/TMDL files",
            evidence=(
                f"Approximate measure declarations: {measures}; "
                f"relationship declarations: {relationships}. "
                "These counts are heuristic."
            )
        )
    else:
        add_finding(
            findings, "Data Model Metadata", "NOT RUN",
            "No obvious model/TMDL files found"
        )

    if report_files:
        add_finding(
            findings, "Report Metadata", "WARNING",
            f"Found {report_files} candidate report files",
            evidence="Static discovery only."
        )

    if visual_files:
        add_finding(
            findings, "Visual Metadata", "WARNING",
            f"Found {visual_files} visual JSON files; "
            f"{title_warnings} lacked an obvious title property",
            evidence="Heuristic only."
        )

    if dax_files:
        add_finding(
            findings, "DAX Static Check", "WARNING",
            f"Found {dax_files} standalone DAX file(s)"
        )

    add_finding(
        findings, "Runtime Validation", "NOT RUN",
        "Visual rendering, interactions, performance, and live DAX "
        "results were not tested"
    )

    return files_seen


def validate_constant_csv_columns(root, findings):
    """Flag CSV columns with only one distinct non-empty value."""

    import csv
    from pathlib import Path

    root = Path(root)
    csv_files = list(root.rglob("*.csv"))

    if not csv_files:
        add_finding(
            findings,
            "CSV Constant Columns",
            "INFO",
            "No CSV files were found to check."
        )
        return

    for path in csv_files:
        try:
            with path.open(
                "r",
                encoding="utf-8-sig",
                newline=""
            ) as file:
                reader = csv.DictReader(file)
                rows = list(reader)
        except (OSError, csv.Error, UnicodeError) as error:
            add_finding(
                findings,
                "CSV Constant Columns",
                "WARNING",
                f"Could not inspect CSV: {error}",
                file=str(path.relative_to(root))
            )
            continue

        if not reader.fieldnames:
            continue

        for column in reader.fieldnames:
            values = {
                row.get(column, "").strip()
                for row in rows
                if row.get(column, "").strip()
            }

            if len(rows) > 0 and len(values) == 1:
                add_finding(
                    findings,
                    "CSV Constant Columns",
                    "WARNING",
                    f"Column '{column}' contains only one "
                    "distinct non-empty value.",
                    file=str(path.relative_to(root))
                )
