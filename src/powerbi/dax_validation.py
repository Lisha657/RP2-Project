import re
import json
from pathlib import Path, PurePosixPath
import requests
from google.genai import errors
from src.core.findings import add_finding


def validate_empty_measure_expressions(root, findings):
    """Detect measures that have no DAX expression."""

    measures = collect_tmdl_measures(root)
    empty_measures = [
        measure for measure in measures
        if not measure.get("expression", "").strip()
    ]

    if not empty_measures:
        add_finding(
            findings,
            "Empty Measure Expressions",
            "PASS",
            "All detected measures have DAX expressions."
        )
        return

    for measure in empty_measures:
        add_finding(
            findings,
            "Empty Measure Expressions",
            "WARNING",
            f"Measure '{measure.get('name', 'Unknown')}' "
            "has an empty DAX expression.",
            file=measure.get("file", "")
        )


def validate_dax_measures(root, findings):
    """Perform basic static checks on DAX measures in TMDL files."""

    import re
    from pathlib import Path

    root = Path(root)
    tmdl_files = list(root.rglob("*.tmdl"))

    if not tmdl_files:
        add_finding(
            findings,
            "DAX Validation",
            "NOT RUN",
            "No TMDL files were found for DAX measure validation."
        )
        return

    total_measures = 0
    checked_measures = 0
    seen_measures = set()

    for path in tmdl_files:
        try:
            lines = path.read_text(
                encoding="utf-8-sig",
                errors="replace"
            ).splitlines()
        except OSError:
            continue

        current_table = path.stem

        for index, line in enumerate(lines):
            stripped = line.strip()

            if stripped.startswith("table "):
                current_table = stripped[len("table "):].strip()

            match = re.match(
                r"^\s*measure\s+(.+?)\s*=\s*(.*)$",
                line
            )

            if not match:
                continue

            total_measures += 1
            measure_name = match.group(1).strip().strip("'\"")
            expression_start = match.group(2).strip()

            key = (current_table.casefold(), measure_name.casefold())

            if key in seen_measures:
                add_finding(
                    findings,
                    "DAX Validation",
                    "WARNING",
                    f"Possible duplicate measure '{measure_name}' "
                    f"in table '{current_table}'.",
                    str(path.relative_to(root))
                )
            else:
                seen_measures.add(key)

            expression_parts = (
                [expression_start] if expression_start else []
            )

            for next_line in lines[index + 1:]:
                next_stripped = next_line.strip()

                if re.match(
                    r"^\s*(measure|column|table|partition|"
                    r"relationship|expression)\s+",
                    next_line
                ):
                    break

                if re.match(
                    r"^[A-Za-z_]\w*\s*:",
                    next_stripped
                ):
                    break

                if next_stripped and not next_stripped.startswith("//"):
                    expression_parts.append(next_stripped)

            expression = " ".join(expression_parts).strip()

            if not expression:
                add_finding(
                    findings,
                    "DAX Validation",
                    "WARNING",
                    f"Measure '{measure_name}' has no detectable "
                    "DAX expression.",
                    str(path.relative_to(root))
                )
                continue

            checked_measures += 1

            if re.search(
                r"\b(TODO|FIXME|PLACEHOLDER)\b",
                expression,
                re.IGNORECASE
            ):
                add_finding(
                    findings,
                    "DAX Validation",
                    "WARNING",
                    f"Measure '{measure_name}' contains a "
                    "placeholder marker.",
                    str(path.relative_to(root))
                )

            if re.search(r"\bDIVIDE\s*\(", expression, re.IGNORECASE):
                add_finding(
                    findings,
                    "DAX Validation",
                    "INFO",
                    f"Measure '{measure_name}' uses DIVIDE(). "
                    "Review whether an alternate result is appropriate; "
                    "DIVIDE() is valid DAX and is not an error by itself.",
                    str(path.relative_to(root))
                )

    add_finding(
        findings,
        "DAX Validation",
        "PASS" if total_measures > 0 else "WARNING",
        f"Found {total_measures} measure declarations; "
        f"{checked_measures} had detectable expressions. "
        "Static checks do not execute DAX.",
        str(root)
    )


def validate_duplicate_measure_names(root, findings):
    """Detect measure names repeated across TMDL files."""

    measures = collect_tmdl_measures(root)

    names_by_key = {}

    for measure in measures:
        name = measure.get("name", "").strip()

        if not name:
            continue

        # Measure names are compared without case sensitivity.
        key = name.casefold()
        names_by_key.setdefault(key, []).append(measure)

    duplicates = {
        name: items
        for name, items in names_by_key.items()
        if len(items) > 1
    }

    if not duplicates:
        add_finding(
            findings,
            "Duplicate Measure Names",
            "PASS",
            "No duplicate measure names were detected."
        )
        return

    for name, items in duplicates.items():
        locations = [
            str(item.get("file", "Unknown file"))
            for item in items
        ]

        add_finding(
            findings,
            "Duplicate Measure Names",
            "WARNING",
            f"Measure name '{name}' appears {len(items)} times.",
            evidence="Files: " + ", ".join(locations)
        )


def validate_dax_references(root, findings):
    """Validate explicit table-column references in DAX expressions."""

    from pathlib import Path
    import re

    root = Path(root)
    measures = collect_tmdl_measures(root)

    if not measures:
        add_finding(
            findings,
            "DAX Reference Validation",
            "NOT RUN",
            "No TMDL measure expressions were detected."
        )
        return

    tables = set()
    columns = set()

    for path in root.rglob("*.tmdl"):
        try:
            lines = path.read_text(
                encoding="utf-8-sig",
                errors="replace"
            ).splitlines()
        except OSError:
            continue

        current_table = path.stem

        for line in lines:
            stripped = line.strip()

            table_match = re.match(
                r"^table\s+(.+?)\s*$", stripped
            )

            if table_match:
                current_table = table_match.group(1).strip().strip("'\"")
                tables.add(current_table.casefold())
                continue

            column_match = re.match(
                r"^column\s+(.+?)\s*$", stripped
            )

            if column_match:
                column_name = column_match.group(1).split("=", 1)[0]
                column_name = column_name.strip().strip("'\"")

                columns.add(
                    (current_table.casefold(), column_name.casefold())
                )

    checked = 0
    unresolved = 0

    for measure in measures:
        expression = measure.get("expression", "")

        references = re.findall(
            r"'((?:[^']|'')+)'\s*\[([^\]]+)\]",
            expression
        )

        for table_name, column_name in references:
            table_name = table_name.replace("''", "'").casefold()
            column_name = column_name.strip().casefold()

            if table_name not in tables:
                unresolved += 1
                add_finding(
                    findings,
                    "DAX Reference Validation",
                    "WARNING",
                    f"Measure '{measure['name']}' references table "
                    f"'{table_name}' not detected in TMDL.",
                    measure.get("file", "")
                )

            elif (table_name, column_name) not in columns:
                unresolved += 1
                add_finding(
                    findings,
                    "DAX Reference Validation",
                    "WARNING",
                    f"Measure '{measure['name']}' references column "
                    f"'{column_name}' not detected in table '{table_name}'.",
                    measure.get("file", "")
                )

            else:
                checked += 1

    add_finding(
        findings,
        "DAX Reference Validation",
        "INFO",
        f"Checked {checked} qualified column reference(s); "
        f"{unresolved} need review.",
        str(root),
        "Static checks only; unresolved references are not confirmed errors."
    )


def validate_measure_dependencies(root, findings):
    """Check references between DAX measures using static analysis."""

    import re
    from pathlib import Path

    root = Path(root)
    measures = collect_tmdl_measures(root)

    if not measures:
        add_finding(
            findings,
            "Measure Dependency Validation",
            "NOT RUN",
            "No TMDL measure expressions were detected."
        )
        return

    known_measures = {
        measure.get("name", "").strip().casefold()
        for measure in measures
        if measure.get("name", "").strip()
    }

    checked = 0
    unresolved = 0

    for measure in measures:
        expression = measure.get("expression", "")
        measure_name = measure.get("name", "Unknown measure")
        file_name = measure.get("file", "")

        # Find references such as [Total Sales].
        references = re.findall(
            r"(?<!\[)\[([^\]]+)\]",
            expression
        )

        for reference in references:
            reference = reference.strip()

            if not reference:
                continue

            # DAX uses square brackets for both measure references
            # and column references. This check is therefore heuristic.
            if reference.casefold() in known_measures:
                checked += 1
            else:
                unresolved += 1
                add_finding(
                    findings,
                    "Measure Dependency Validation",
                    "INFO",
                    f"Measure '{measure_name}' references "
                    f"'[{reference}]', which was not matched to a "
                    "known measure name. It may be a column, parameter, "
                    "or an undetected measure.",
                    file_name,
                    "Review manually; this is not a confirmed error."
                )

    add_finding(
        findings,
        "Measure Dependency Validation",
        "INFO",
        f"Matched {checked} measure reference(s); "
        f"{unresolved} reference(s) need manual review.",
        str(root),
        "Static name matching only; dependencies are not fully parsed."
    )


def validate_dax_structure(root, findings):
    """Perform basic static checks on DAX measure expressions."""

    from pathlib import Path

    root = Path(root)
    measures = collect_tmdl_measures(root)

    if not measures:
        add_finding(
            findings,

            "DAX Structure Validation",
            "NOT RUN",
            "No TMDL measure expressions were detected."
        )
        return

    checked = 0
    issues = 0

    for measure in measures:
        expression = measure.get("expression", "")
        measure_name = measure.get("name", "Unknown measure")
        file_name = measure.get("file", "")

        if not expression.strip():
            issues += 1
            add_finding(
                findings,
                "DAX Structure Validation",
                "WARNING",
                f"Measure '{measure_name}' has an empty expression.",
                file_name
            )
            continue

        # Remove quoted strings before checking delimiters.
        cleaned = []
        in_string = False
        i = 0

        while i < len(expression):
            char = expression[i]

            if char == '"':
                if in_string and i + 1 < len(expression) \
                        and expression[i + 1] == '"':
                    i += 2
                    continue

                in_string = not in_string
                cleaned.append(" ")
                i += 1
                continue

            cleaned.append(" " if in_string else char)
            i += 1

        text = "".join(cleaned)

        if in_string:
            issues += 1
            add_finding(
                findings,
                "DAX Structure Validation",
                "WARNING",
                f"Measure '{measure_name}' may contain an "
                "unclosed text string.",
                file_name
            )

        # Check parentheses and square brackets.
        pairs = {")": "(", "]": "["}
        stack = []
        mismatch = False

        for char in text:
            if char in ("(", "["):
                stack.append(char)
            elif char in (")", "]"):
                if not stack or stack[-1] != pairs[char]:
                    mismatch = True
                    break
                stack.pop()

        if mismatch or stack:
            issues += 1
            add_finding(
                findings,
                "DAX Structure Validation",
                "WARNING",
                f"Measure '{measure_name}' may have mismatched "
                "parentheses or square brackets.",
                file_name
            )
        else:
            checked += 1

    add_finding(
        findings,
        "DAX Structure Validation",
        "INFO",
        f"Checked {len(measures)} measure expression(s); "
        f"{issues} possible structural issue(s) found.",
        str(root),
        "Static checks only; this does not execute DAX in Power BI."
    )


def collect_tmdl_measures(root):
    """Collect measure names and multiline DAX expressions from TMDL."""

    from pathlib import Path
    import re

    root = Path(root)
    measures = []

    for path in root.rglob("*.tmdl"):
        try:
            lines = path.read_text(
                encoding="utf-8-sig",
                errors="replace"
            ).splitlines()
        except OSError:
            continue

        current_table = path.stem
        current_measure = None
        expression_lines = []

        def save_measure():
            if current_measure is not None:
                measures.append({
                    "table": current_table,
                    "name": current_measure,
                    "expression": "\n".join(expression_lines).strip(),
                    "file": str(path.relative_to(root)),
                })

        for line in lines:
            stripped = line.strip()

            table_match = re.match(r"^table\s+(.+?)\s*$", stripped)
            if table_match:
                save_measure()
                current_measure = None
                expression_lines = []
                current_table = table_match.group(1).strip()
                continue

            measure_match = re.match(
                r"^measure\s+(.+?)\s*=\s*(.*)$",
                stripped
            )

            if measure_match:
                save_measure()
                current_measure = measure_match.group(1).strip().strip("'")
                first_expression = measure_match.group(2).strip()
                expression_lines = (
                    [first_expression] if first_expression else []
                )
                continue

            # End the current measure at another TMDL object or property.
            if current_measure is not None:
                if re.match(
                    r"^(measure|column|table|partition|relationship|"
                    r"hierarchy|level|annotation|expression)\s+",
                    stripped
                ) or re.match(r"^[A-Za-z_]\w*\s*:", stripped):
                    save_measure()
                    current_measure = None
                    expression_lines = []
                    continue

                if stripped:
                    expression_lines.append(stripped)

        save_measure()

    return measures


def execute_powerbi_dax_query(access_token, dataset_id, dax_query, findings):
    """Run one DAX query through the Power BI Execute Queries REST API."""
    if not access_token or not dataset_id or not dax_query.strip():
        add_finding(findings, "DAX Runtime", "NOT RUN", "A Power BI access token, dataset ID, and DAX query are required.")
        return
    url = f"https://api.powerbi.com/v1.0/myorg/datasets/{dataset_id}/executeQueries"
    headers = {"Authorization": f"Bearer {access_token.strip()}", "Content-Type": "application/json"}
    payload = {"queries": [{"query": dax_query}], "serializerSettings": {"includeNulls": True}}
    try:
        response = requests.post(url, headers=headers, json=payload, timeout=60)
        if response.ok:
            body = response.json()
            query_results = body.get("results", [])
            errors = [item.get("error") for item in query_results if item.get("error")]
            if errors:
                add_finding(findings, "DAX Runtime", "FAIL", "Power BI returned a DAX query error.", evidence=json.dumps(errors, ensure_ascii=False)[:2000])
            else:
                add_finding(findings, "DAX Runtime", "PASS", "DAX query executed successfully against the selected semantic model.", evidence=json.dumps(body, ensure_ascii=False)[:2000])
        else:
            add_finding(findings, "DAX Runtime", "FAIL", f"Power BI API returned HTTP {response.status_code}.", evidence=response.text[:2000])
    except Exception as exc:
        add_finding(findings, "DAX Runtime", "FAIL", f"DAX query request failed: {exc}")
