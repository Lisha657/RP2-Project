import re
from pathlib import Path, PurePosixPath
from src.core.findings import add_finding


def inspect_tmdl_definitions(root, findings):
    """Perform basic static checks on TMDL model definitions."""
    root = Path(root)

    tmdl_files = list(root.rglob("*.tmdl"))

    if not tmdl_files:
        add_finding(
            findings,
            "TMDL Validation",
            "NOT RUN",
            "No TMDL files found"
        )
        return

    table_names = set()
    measures_by_table = {}
    measure_locations = []
    relationship_lines = []

    for path in tmdl_files:
        try:
            content = path.read_text(
                encoding="utf-8-sig",
                errors="replace"
            )
        except OSError:
            continue

        relative_path = str(path.relative_to(root))
        current_table = None

        for line_number, line in enumerate(
            content.splitlines(), start=1
        ):
            stripped = line.strip()

            if not stripped or stripped.startswith("//"):
                continue

            # Detect table declarations.
            if stripped.startswith("table "):
                current_table = stripped[len("table "):].strip()
                table_names.add(current_table)

                measures_by_table.setdefault(
                    current_table, []
                )

            # Detect measure declarations.
            elif stripped.startswith("measure "):
                declaration = stripped[len("measure "):].strip()

                measure_name = declaration.split("=", 1)[0].strip()
                measure_name = measure_name.strip("'").strip('"')

                measure_locations.append({
                    "table": current_table,
                    "name": measure_name,
                    "file": relative_path,
                    "line": line_number,
                    "expression": (
                        declaration.split("=", 1)[1].strip()
                        if "=" in declaration else ""
                    )
                })

                if current_table:
                    measures_by_table.setdefault(
                        current_table, []
                    ).append(measure_name)

            # Collect relationship declarations for review.
            elif stripped.startswith("relationship "):
                relationship_lines.append({
                    "file": relative_path,
                    "line": line_number,
                    "declaration": stripped
                })

    # Check duplicate measure names within each table.
    for table, names in measures_by_table.items():
        seen = set()

        for name in names:
            if name in seen:
                add_finding(
                    findings,
                    "DAX / Model",
                    "WARNING",
                    f"Duplicate measure declaration: {name}",
                    evidence=f"Table: {table}"
                )
            seen.add(name)

    # Check whether measures have an inline expression.
    # Multi-line expressions require more complete TMDL parsing.
    for measure in measure_locations:
        if not measure["expression"]:
            add_finding(
                findings,
                "DAX / Model",
                "WARNING",
                f"Measure may have an empty or multiline expression: "
                f"{measure['name']}",
                measure["file"],
                f"Line {measure['line']}; inspect the full TMDL definition."
            )

    add_finding(
        findings,
        "TMDL Validation",
        "INFO",
        f"Discovered {len(table_names)} table declaration(s)",
        evidence="Table names were collected from TMDL declarations."
    )

    add_finding(
        findings,
        "TMDL Validation",
        "INFO",
        f"Discovered {len(measure_locations)} measure declaration(s)",
        evidence=(
            "Measure expressions have not been executed or fully "
            "validated against the Power BI engine."
        )
    )

    add_finding(
        findings,
        "TMDL Validation",
        "WARNING",
        f"Found {len(relationship_lines)} relationship declaration(s) "
        "for further inspection",
        evidence=(
            "This basic scanner does not yet validate relationship "
            "endpoints, cardinality, or filter direction."
        )
    )


def validate_model_relationships(root, findings):
    """Check whether model relationship definitions are present."""

    from pathlib import Path
    import re

    root = Path(root)
    relationship_count = 0
    checked_files = 0

    for path in root.rglob("*.tmdl"):
        try:
            content = path.read_text(
                encoding="utf-8-sig",
                errors="replace"
            )
        except OSError:
            continue

        checked_files += 1

        for line in content.splitlines():
            match = re.match(
                r"^\s*relationship\s+(.+?)\s*$",
                line
            )

            if match:
                relationship_count += 1

    if checked_files == 0:
        add_finding(
            findings,
            "Model Relationship Validation",
            "NOT RUN",
            "No TMDL files were found to inspect.",
            str(root)
        )
        return

    if relationship_count == 0:
        add_finding(
            findings,
            "Model Relationship Validation",
            "WARNING",
            "No relationship declarations were detected in the "
            "TMDL files. Verify whether relationships are expected.",
            str(root)
        )
    else:
        add_finding(
            findings,
            "Model Relationship Validation",
            "INFO",
            f"Detected {relationship_count} relationship declaration(s) "
            f"across {checked_files} TMDL file(s).",
            str(root),
            "This confirms declarations were detected, not that "
            "the relationships are valid or correctly configured."
        )


def validate_duplicate_relationships(root, findings):
    """Detect repeated relationship endpoints in TMDL files."""

    import re
    from pathlib import Path

    root = Path(root)
    relationships = {}

    for path in root.rglob("*.tmdl"):
        try:
            lines = path.read_text(
                encoding="utf-8-sig",
                errors="replace"
            ).splitlines()
        except OSError:
            continue

        current = None

        def save_relationship():
            if not current:
                return

            source = current.get("fromcolumn")
            target = current.get("tocolumn")

            if source and target:
                key = (source.casefold(), target.casefold())
                relationships.setdefault(key, []).append(
                    str(path.relative_to(root))
                )

        for line in lines:
            stripped = line.strip()

            if re.match(r"^relationship\s+", stripped, re.IGNORECASE):
                save_relationship()
                current = {}
                continue

            if current is None:
                continue

            match = re.match(
                r"^(fromColumn|toColumn)\s*:\s*(.+)$",
                stripped,
                re.IGNORECASE
            )

            if match:
                current[match.group(1).casefold()] = (
                    match.group(2).strip()
                )

        save_relationship()

    duplicates = {
        endpoints: files
        for endpoints, files in relationships.items()
        if len(files) > 1
    }

    if not duplicates:
        add_finding(
            findings,
            "Duplicate Relationships",
            "PASS",
            "No repeated relationship endpoints were detected."
        )
        return

    for endpoints, files in duplicates.items():
        add_finding(
            findings,
            "Duplicate Relationships",
            "WARNING",
            f"Relationship endpoints '{endpoints[0]}' -> "
            f"'{endpoints[1]}' appear more than once.",
            evidence="Files: " + ", ".join(files)
        )


def validate_relationship_columns(root, findings):
    """Check whether relationship endpoint columns exist in TMDL files."""

    from pathlib import Path
    import re

    root = Path(root)
    tables = {}
    relationships = []

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
                r"^table\s+(.+?)\s*$",
                stripped
            )
            if table_match:
                current_table = table_match.group(1).strip().strip("'\"")
                tables.setdefault(current_table.casefold(), set())
                continue

            column_match = re.match(
                r"^column\s+(.+?)\s*$",
                stripped
            )
            if column_match:
                column_name = column_match.group(1).split("=", 1)[0]
                column_name = column_name.strip().strip("'\"")
                tables.setdefault(current_table.casefold(), set()).add(
                    column_name.casefold()
                )
                continue

            relationship_match = re.match(
                r"^relationship\s+(.+?)\s*$",
                stripped
            )
            if relationship_match:
                relationships.append({
                    "name": relationship_match.group(1),
                    "file": str(path),
                    "properties": {}
                })
                continue

            if relationships:
                property_match = re.match(
                    r"^(fromColumn|toColumn)\s*:\s*(.+?)\s*$",
                    stripped,
                    re.IGNORECASE
                )
                if property_match:
                    relationships[-1]["properties"][
                        property_match.group(1).casefold()
                    ] = property_match.group(2).strip()

    if not relationships:
        add_finding(
            findings,
            "Relationship Column Validation",
            "NOT RUN",
            "No relationship declarations were detected.",
            str(root)
        )
        return

    checked = 0
    unresolved = 0

    for relationship in relationships:
        properties = relationship["properties"]
        from_column = properties.get("fromcolumn")
        to_column = properties.get("tocolumn")

        if not from_column or not to_column:
            unresolved += 1
            add_finding(
                findings,
                "Relationship Column Validation",
                "WARNING",
                f"Relationship '{relationship['name']}' is missing "
                "a detectable fromColumn or toColumn property.",
                relationship["file"]
            )
            continue

        def parse_endpoint(endpoint):
            match = re.match(
                r"^\s*'((?:[^']|'')+)'\s*\[([^\]]+)\]\s*$",
                endpoint
            )
            if not match:
                return None

            table_name = match.group(1).replace("''", "'").casefold()
            column_name = match.group(2).strip().casefold()
            return table_name, column_name

        endpoints = [
            parse_endpoint(from_column),
            parse_endpoint(to_column)
        ]

        if any(endpoint is None for endpoint in endpoints):
            unresolved += 1
            add_finding(
                findings,
                "Relationship Column Validation",
                "INFO",
                f"Could not parse both endpoints for relationship "
                f"'{relationship['name']}'.",
                relationship["file"],
                "Review the relationship definition manually."
            )
            continue

        missing = []
        for table_name, column_name in endpoints:
            if table_name not in tables:
                missing.append(f"table '{table_name}' was not detected")
            elif column_name not in tables[table_name]:
                missing.append(
                    f"column '{column_name}' was not detected "
                    f"in table '{table_name}'"
                )

        if missing:
            unresolved += 1
            add_finding(
                findings,
                "Relationship Column Validation",
                "WARNING",
                f"Relationship '{relationship['name']}': "
                + "; ".join(missing) + ".",
                relationship["file"]
            )
        else:
            checked += 1

    add_finding(
        findings,
        "Relationship Column Validation",
        "INFO",
        f"Validated {checked} relationship endpoint pair(s); "
        f"{unresolved} relationship(s) need review.",
        str(root),
        "Static checks only; verify results against the Power BI model."
    )


def validate_relationship_quality(root, findings):
    """Check relationship definitions for common modeling concerns."""

    from pathlib import Path
    import re

    root = Path(root)
    relationships = []

    for path in root.rglob("*.tmdl"):
        try:
            lines = path.read_text(
                encoding="utf-8-sig",
                errors="replace"
            ).splitlines()
        except OSError:
            continue

        current_relationship = None

        for line in lines:
            stripped = line.strip()

            match = re.match(
                r"^relationship\s+(.+?)\s*$",
                stripped
            )

            if match:
                current_relationship = {
                    "name": match.group(1),
                    "file": str(path),
                    "properties": {}
                }
                relationships.append(current_relationship)
                continue

            if current_relationship is None:
                continue

            property_match = re.match(
                r"^(fromColumn|toColumn|fromCardinality|toCardinality|"
                r"isActive|crossFilteringBehavior)\s*:\s*(.+?)\s*$",
                stripped,
                re.IGNORECASE
            )

            if property_match:
                key = property_match.group(1).casefold()
                value = property_match.group(2).strip()
                current_relationship["properties"][key] = value

    if not relationships:
        add_finding(
            findings,
            "Relationship Quality Validation",
            "NOT RUN",
            "No relationship declarations were detected.",
            str(root)
        )
        return

    reviewed = 0
    warnings = 0

    for relationship in relationships:
        properties = relationship["properties"]
        name = relationship["name"]
        file_name = relationship["file"]
        concerns = []

        if not properties.get("fromcolumn"):
            concerns.append("missing fromColumn")

        if not properties.get("tocolumn"):
            concerns.append("missing toColumn")

        from_cardinality = properties.get("fromcardinality", "").casefold()
        to_cardinality = properties.get("tocardinality", "").casefold()

        valid_cardinalities = {
            "one", "many"
        }

        for key, value in (
            ("fromCardinality", from_cardinality),
            ("toCardinality", to_cardinality)
        ):
            if value and value not in valid_cardinalities:
                concerns.append(
                    f"unrecognized {key} value '{value}'"
                )

        active_value = properties.get("isactive", "").casefold()
        if active_value and active_value not in {"true", "false"}:
            concerns.append(
                f"unrecognized isActive value "
                f"'{properties.get('isactive')}'"
            )

        cross_filter = properties.get(
            "crossfilteringbehavior", ""
        ).casefold()

        if cross_filter and cross_filter not in {
            "oneDirection".casefold(),
            "bothDirections".casefold(),
            "automatic"
        }:
            concerns.append(
                "unrecognized crossFilteringBehavior value "
                f"'{properties.get('crossfilteringbehavior')}'"
            )

        if concerns:
            warnings += 1
            add_finding(
                findings,
                "Relationship Quality Validation",
                "WARNING",
                f"Relationship '{name}': " + "; ".join(concerns) + ".",
                file_name,
                "Review the TMDL definition; this static check may not "
                "recognize every valid format."
            )
        else:
            reviewed += 1

    add_finding(
        findings,
        "Relationship Quality Validation",
        "INFO",
        f"Reviewed {reviewed + warnings} relationship(s); "
        f"{warnings} need review.",
        str(root),
        "This checks selected properties only, not full model correctness."
    )
