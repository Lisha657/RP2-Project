import argparse
import json
import re
from pathlib import Path


def normalize_name(name):
    """Normalize names for case-insensitive metadata comparisons."""
    return (
        name.strip()
        .strip("'")
        .strip('"')
        .replace("''", "'")
        .casefold()
    )


def add_finding(findings, status, check, message, evidence=None):
    findings.append({
        "status": status,
        "check": check,
        "message": message,
        "evidence": evidence or [],
    })


def find_tmdl_roots(root):
    """Find accessible TMDL directories without merging unrelated models."""
    root = root.resolve()

    if root.is_file():
        return []

    if root.name.casefold() == "definition" and any(root.rglob("*.tmdl")):
        return [root]

    if root.name.casefold() == "model" and any(root.rglob("*.tmdl")):
        return [root]

    if root.name.casefold().endswith(".semanticmodel"):
        definition = root / "definition"

        if definition.is_dir() and any(definition.rglob("*.tmdl")):
            return [definition]

        if any(root.rglob("*.tmdl")):
            return [root]

    model_roots = []

    for semantic_model in root.rglob("*.SemanticModel"):
        definition = semantic_model / "definition"

        if definition.is_dir() and any(definition.rglob("*.tmdl")):
            model_roots.append(definition.resolve())

    if not model_roots:
        for model_dir in root.rglob("Model"):
            if model_dir.is_dir() and any(model_dir.rglob("*.tmdl")):
                model_roots.append(model_dir.resolve())

    if not model_roots and any(root.rglob("*.tmdl")):
        model_roots.append(root)

    return sorted(set(model_roots))


def read_tmdl_files(root):
    """Read TMDL files and report files that could not be read."""
    contents = []
    findings = []

    for path in sorted(root.rglob("*.tmdl")):
        try:
            contents.append(
                (path, path.read_text(encoding="utf-8-sig"))
            )
        except (OSError, UnicodeError) as exc:
            add_finding(
                findings,
                "WARNING",
                "tmdl_read",
                f"Could not read {path.name}: {exc}",
                [str(path)],
            )

    return contents, findings


def strip_dax_comments_and_strings(expression):
    """
    Mask DAX strings and comments while preserving character positions
    and line breaks. Supports //, --, and /* ... */ comments.
    """
    chars = list(expression)
    i = 0
    length = len(expression)

    while i < length:
        # Mask quoted DAX strings, including escaped double quotes.
        if expression[i] == '"':
            chars[i] = " "
            i += 1

            while i < length:
                if expression[i] == '"':
                    chars[i] = " "

                    # DAX escapes a double quote by doubling it.
                    if i + 1 < length and expression[i + 1] == '"':
                        chars[i + 1] = " "
                        i += 2
                        continue

                    i += 1
                    break

                chars[i] = "\n" if expression[i] == "\n" else " "
                i += 1

            continue

        # Mask single-line comments: // and --.
        if expression.startswith("//", i) or expression.startswith("--", i):
            while i < length and expression[i] not in "\r\n":
                chars[i] = " "
                i += 1

            continue

        # Mask block comments.
        if expression.startswith("/*", i):
            end = expression.find("*/", i + 2)

            if end == -1:
                while i < length:
                    chars[i] = "\n" if expression[i] == "\n" else " "
                    i += 1
                break

            while i < end + 2:
                if expression[i] != "\n":
                    chars[i] = " "
                i += 1

            continue

        i += 1

    return "".join(chars)


def parse_metadata(tmdl_files):
    """Extract table, column, and measure metadata from TMDL."""
    tables = set()
    columns = {}
    measures = set()
    measure_records = []
    measure_definitions = {}
    duplicate_measures = []

    def declaration_name(match):
        quoted_name = match.group(1)
        plain_name = match.group(2)
        name = quoted_name if quoted_name is not None else plain_name
        return normalize_name(name or "")

    table_pattern = re.compile(
        r"""(?m)^[ \t]*table[ \t]+
        (?:'((?:[^']|'')+)'|([^\r\n]+?))[ \t]*$""",
        re.VERBOSE,
    )

    column_pattern = re.compile(
        r"""(?m)^[ \t]*column[ \t]+
        (?:'((?:[^']|'')+)'|([^:=\r\n]+?))
        [ \t]*(?::=|=|$)""",
        re.VERBOSE,
    )

    measure_pattern = re.compile(
        r"""(?m)^[ \t]*measure[ \t]+
        (?:'((?:[^']|'')+)'|([^:=\r\n]+?))
        [ \t]*(?::=|=)[ \t]*""",
        re.VERBOSE,
    )

    object_boundary_pattern = re.compile(
        r"""(?mi)^[ \t]{0,8}
        (?:column|partition|hierarchy|annotation|variation|
        calculationItem|measure|table|ref)\b"""
    )

    property_pattern = re.compile(
        r"""^(?:formatString|displayFolder|description|lineageTag|
        annotation|dataCategory|isHidden|detailRowsDefinition|
        formatStringDefinition|changedProperty|queryGroup|
        sourceLineageTag|formatByColumn|summarizeBy|dataType|
        isNameInferred|sourceColumn)\s*:""",
        re.VERBOSE | re.IGNORECASE,
    )

    for path, content in tmdl_files:
        table_matches = list(table_pattern.finditer(content))

        for table_index, table_match in enumerate(table_matches):
            table_name = declaration_name(table_match)

            if not table_name:
                continue

            tables.add(table_name)
            columns.setdefault(table_name, set())

            section_end = (
                table_matches[table_index + 1].start()
                if table_index + 1 < len(table_matches)
                else len(content)
            )

            section = content[table_match.end():section_end]

            for match in column_pattern.finditer(section):
                column_name = declaration_name(match)

                if column_name:
                    columns[table_name].add(column_name)

            measure_matches = list(measure_pattern.finditer(section))

            for index, match in enumerate(measure_matches):
                measure_name = declaration_name(match)

                if not measure_name:
                    continue

                expression_start = match.end()

                next_measure_start = (
                    measure_matches[index + 1].start()
                    if index + 1 < len(measure_matches)
                    else len(section)
                )

                expression_block = section[
                    expression_start:next_measure_start
                ]

                boundary = object_boundary_pattern.search(expression_block)

                if boundary:
                    expression_block = expression_block[:boundary.start()]

                expression_lines = []

                for line in expression_block.splitlines():
                    stripped = line.strip()

                    if not stripped:
                        continue

                    if property_pattern.match(stripped):
                        break

                    expression_lines.append(stripped)

                # Preserve the original expression. Comment masking is
                # performed separately during the checking stage.
                expression = " ".join(expression_lines).strip()

                # Remove optional TMDL DAX code fences from the expression.
                expression = re.sub(
                    r"^\s*```(?:dax)?\s*|\s*```\s*$",
                    "",
                    expression,
                    flags=re.IGNORECASE,
                ).strip()

                record = {
                    "table": table_name,
                    "measure": measure_name,
                    "expression": expression,
                    "file": path.name,
                    "path": str(path),
                }

                measure_records.append(record)
                measure_key = (table_name, measure_name)

                if measure_key in measure_definitions:
                    duplicate_measures.append({
                        "measure": measure_name,
                        "table": table_name,
                        "file": path.name,
                    })

                measure_definitions.setdefault(
                    measure_key, []
                ).append(record)

                measures.add(measure_name)

    return (
        tables,
        columns,
        measures,
        measure_records,
        measure_definitions,
        duplicate_measures,
    )


def check_model_dax(model_root):
    """Run static DAX checks against one semantic model."""
    findings = []

    tmdl_files, read_findings = read_tmdl_files(model_root)
    findings.extend(read_findings)

    if not tmdl_files:
        add_finding(
            findings,
            "NOT_TESTED",
            "measure_extraction",
            "No accessible TMDL files were found for this model.",
            [str(model_root)],
        )

        add_finding(
            findings,
            "NOT_TESTED",
            "dax_execution",
            "DAX execution requires a compatible model engine.",
            [str(model_root)],
        )

        return {
            "model_directory": str(model_root),
            "overall_status": "NOT_TESTED",
            "summary": {
                "measures_detected": 0,
                "tables_detected": 0,
                "columns_detected": 0,
                "measure_expressions_inspected": 0,
                "empty_or_unparsed_expressions": 0,
                "unmatched_references": 0,
                "unqualified_references_for_review": 0,
                "duplicate_measure_names": 0,
                "runtime_execution": "NOT_TESTED",
                "numerical_validation": "NOT_TESTED",
            },
            "findings": findings,
        }

    (
        tables,
        columns,
        measures,
        measure_records,
        measure_definitions,
        duplicate_measures,
    ) = parse_metadata(tmdl_files)

    if measures:
        add_finding(
            findings,
            "PASS",
            "measure_extraction",
            f"Detected {len(measures)} distinct measure name(s).",
            [f"Model: {model_root}"],
        )
    else:
        add_finding(
            findings,
            "WARNING",
            "measure_extraction",
            "No measure declarations were detected. The model may have no "
            "measures, or its TMDL syntax may require additional parser support.",
            [f"Model: {model_root}"],
        )

    qualified_pattern = re.compile(
        r"""(?ix)
        (?<![\w'])
        (?:'((?:[^']|'')+)'|([A-Za-z_][A-Za-z0-9_ ]*))
        \s*\[\s*((?:[^\]])+?)\s*\]
        """
    )

    unqualified_pattern = re.compile(
        r"""(?<![\w\]])
        \[\s*((?:[^\]])+?)\s*\]"""
    )

    risky_patterns = [
        (
            re.compile(r"\bDIVIDE\s*\(", re.IGNORECASE),
            "division_review",
            "Review DIVIDE alternate-result behavior and denominator handling.",
        ),
        (
            re.compile(r"(?<![A-Za-z0-9_])/(?![/\*])"),
            "division_review",
            "Direct division detected; consider DIVIDE() if zero denominators are possible.",
        ),
        (
            re.compile(r"\bSELECTEDVALUE\s*\(", re.IGNORECASE),
            "filter_context_review",
            "Review behavior when zero or multiple values are selected.",
        ),
        (
            re.compile(r"\bALL\s*\(", re.IGNORECASE),
            "filter_context_review",
            "Review whether removing filters is intended.",
        ),
        (
            re.compile(r"\bREMOVEFILTERS\s*\(", re.IGNORECASE),
            "filter_context_review",
            "Review whether removing filters is intended.",
        ),
        (
            re.compile(r"\b(?:TODAY|NOW)\s*\(", re.IGNORECASE),
            "time_dependency_review",
            "The expression depends on the current date or time.",
        ),
    ]

    unmatched_references = set()
    review_references = set()
    reported_patterns = set()
    empty_expressions = 0
    checked_expressions = 0

    for item in measure_records:
        expression = item["expression"]

        if not expression:
            empty_expressions += 1

            add_finding(
                findings,
                "WARNING",
                "empty_measure_expression",
                f"Measure '{item['measure']}' has an empty or unparsed expression.",
                [f"Table: {item['table']}", f"File: {item['path']}"],
            )

            continue

        checked_expressions += 1

        # Ignore references and operators inside DAX comments and strings.
        cleaned = strip_dax_comments_and_strings(expression)
        qualified_spans = []

        for match in qualified_pattern.finditer(cleaned):
            raw_table = match.group(1) or match.group(2)

            table_name = normalize_name(
                raw_table.replace("''", "'")
            )

            object_name = normalize_name(match.group(3))
            qualified_spans.append(match.span())

            if table_name not in tables:
                unmatched_references.add((
                    item["file"],
                    item["measure"],
                    "table",
                    table_name,
                    match.group(0).strip(),
                ))
                continue

            if (
                object_name not in columns.get(table_name, set())
                and object_name not in measures
            ):
                unmatched_references.add((
                    item["file"],
                    item["measure"],
                    "column_or_measure",
                    table_name,
                    match.group(0).strip(),
                ))

        chars = list(cleaned)

        for start, end in qualified_spans:
            for position in range(start, end):
                chars[position] = " "

        unqualified_text = "".join(chars)

        for match in unqualified_pattern.finditer(unqualified_text):
            reference_name = normalize_name(match.group(1))

            if reference_name not in measures:
                review_references.add((
                    item["file"],
                    item["measure"],
                    reference_name,
                ))

        for pattern, check_name, message in risky_patterns:
            if pattern.search(cleaned):
                key = (item["file"], item["measure"], check_name)

                if key not in reported_patterns:
                    reported_patterns.add(key)

                    add_finding(
                        findings,
                        "INFO",
                        check_name,
                        message,
                        [
                            f"Measure: {item['measure']}",
                            f"Table: {item['table']}",
                            f"File: {item['path']}",
                        ],
                    )

    for file_name, measure_name, kind, table_name, reference in sorted(
        unmatched_references
    ):
        add_finding(
            findings,
            "WARNING",
            "unmatched_reference",
            f"Could not resolve {kind} reference '{reference}' "
            f"in measure '{measure_name}'. This may indicate missing "
            "metadata or a genuine DAX reference issue.",
            [f"File: {file_name}", f"Table: {table_name}"],
        )

    for file_name, measure_name, reference_name in sorted(review_references):
        add_finding(
            findings,
            "INFO",
            "unqualified_reference_review",
            f"Reference '[{reference_name}]' in measure '{measure_name}' "
            "could not be confidently resolved as a measure by static matching. "
            "It may be a valid column reference.",
            [f"File: {file_name}"],
        )

    for duplicate in duplicate_measures:
        add_finding(
            findings,
            "WARNING",
            "duplicate_measure_name",
            f"Measure '{duplicate['measure']}' is declared more than once "
            f"within table '{duplicate['table']}'.",
            [f"File: {duplicate['file']}"],
        )

    add_finding(
        findings,
        "INFO",
        "dax_measure_validation",
        "DAX expressions were inspected statically. Individual measure "
        "results have not been validated against expected numerical values. "
        "A successful runtime query does not by itself prove KPI correctness.",
        [f"Model: {model_root}"],
    )

    statuses = {finding["status"] for finding in findings}

    if "FAIL" in statuses:
        overall_status = "FAIL"
    elif "WARNING" in statuses:
        overall_status = "WARNING"
    elif "PASS" in statuses:
        overall_status = "PASS"
    else:
        overall_status = "NOT_TESTED"

    return {
        "model_directory": str(model_root),
        "overall_status": overall_status,
        "summary": {
            "measures_detected": len(measures),
            "tables_detected": len(tables),
            "columns_detected": sum(
                len(value) for value in columns.values()
            ),
            "measure_expressions_inspected": checked_expressions,
            "empty_or_unparsed_expressions": empty_expressions,
            "unmatched_references": len(unmatched_references),
            "unqualified_references_for_review": len(review_references),
            "duplicate_measure_names": len(duplicate_measures),
            "runtime_execution": "NOT_TESTED",
            "numerical_validation": "NOT_TESTED",
        },
        "findings": findings,
    }


def check_dax(project_path):
    """Run static DAX checks on accessible semantic models."""
    root = Path(project_path).expanduser().resolve()

    empty_summary = {
        "measures_detected": 0,
        "tables_detected": 0,
        "columns_detected": 0,
        "measure_expressions_inspected": 0,
        "empty_or_unparsed_expressions": 0,
        "unmatched_references": 0,
        "unqualified_references_for_review": 0,
        "duplicate_measure_names": 0,
        "runtime_execution": "NOT_TESTED",
        "numerical_validation": "NOT_TESTED",
    }

    if not root.is_dir():
        return {
            "overall_status": "FAIL",
            "summary": empty_summary,
            "findings": [{
                "status": "FAIL",
                "check": "project_path",
                "message": f"Project directory does not exist: {root}",
                "evidence": [str(root)],
            }],
        }

    model_roots = find_tmdl_roots(root)

    if not model_roots:
        message = (
            "No accessible TMDL files were found. PBIX files require an "
            "extraction tool or an accessible semantic-model definition."
        )

        return {
            "overall_status": "NOT_TESTED",
            "summary": empty_summary,
            "findings": [{
                "status": "NOT_TESTED",
                "check": "measure_extraction",
                "message": message,
                "evidence": [str(root)],
            }],
        }

    model_results = [
        check_model_dax(model_root)
        for model_root in model_roots
    ]

    combined_findings = []

    totals = {
        "measures_detected": 0,
        "tables_detected": 0,
        "columns_detected": 0,
        "measure_expressions_inspected": 0,
        "empty_or_unparsed_expressions": 0,
        "unmatched_references": 0,
        "unqualified_references_for_review": 0,
        "duplicate_measure_names": 0,
    }

    for result in model_results:
        model_label = result["model_directory"]

        for key in totals:
            totals[key] += result["summary"].get(key, 0)

        for finding in result["findings"]:
            item = dict(finding)
            evidence = list(item.get("evidence", []))
            model_entry = f"Model: {model_label}"

            if model_entry not in evidence:
                evidence.insert(0, model_entry)

            item["evidence"] = evidence
            combined_findings.append(item)

    statuses = {
        finding["status"]
        for finding in combined_findings
    }

    if "FAIL" in statuses:
        overall_status = "FAIL"
    elif "WARNING" in statuses:
        overall_status = "WARNING"
    elif "PASS" in statuses:
        overall_status = "PASS"
    else:
        overall_status = "NOT_TESTED"

    totals["runtime_execution"] = "NOT_TESTED"
    totals["numerical_validation"] = "NOT_TESTED"

    return {
        "overall_status": overall_status,
        "summary": totals,
        "models": model_results,
        "findings": combined_findings,
    }


def main():
    parser = argparse.ArgumentParser(
        description="Static DAX checks for Power BI projects."
    )

    parser.add_argument(
        "--project-path",
        required=True,
        help=(
            "Path to a PBIP project, semantic-model folder, "
            "or extracted Model folder."
        ),
    )

    parser.add_argument(
        "--output",
        help="Optional path to save the JSON results.",
    )

    args = parser.parse_args()
    result = check_dax(args.project_path)
    output = json.dumps(result, indent=2, ensure_ascii=False)

    print(output)

    if args.output:
        output_path = Path(args.output).expanduser()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(output + "\n", encoding="utf-8")
        print(f"\nResults saved to: {output_path.resolve()}")


if __name__ == "__main__":
    main()