
import argparse
import json
import re
from pathlib import Path


def normalize_name(name):
    """Normalize a TMDL identifier for case-insensitive comparison."""
    return name.strip().strip("'").strip('"').replace("''", "'").casefold()


def add_finding(findings, status, check, message, evidence=None):
    findings.append({
        "status": status,
        "check": check,
        "message": message,
        "evidence": evidence or [],
    })


def find_model_directories(root):
    """Find accessible semantic-model definition directories."""
    root = root.resolve()

    # If the caller supplies a definition directory directly, use it.
    if root.name.casefold() == "definition" and any(root.rglob("*.tmdl")):
        return [root]

    # If the caller supplies an extracted Model directory, use it.
    if root.name.casefold() == "model" and any(root.rglob("*.tmdl")):
        return [root]

    # If the caller supplies a semantic-model folder, prefer its definition.
    if root.name.casefold().endswith(".semanticmodel"):
        definition = root / "definition"
        if definition.is_dir() and any(definition.rglob("*.tmdl")):
            return [definition]
        if any(root.rglob("*.tmdl")):
            return [root]

    # Discover PBIP semantic models below the supplied path.
    model_dirs = []
    for semantic_model in root.rglob("*.SemanticModel"):
        definition = semantic_model / "definition"
        if definition.is_dir() and any(definition.rglob("*.tmdl")):
            model_dirs.append(definition.resolve())

    # Fall back to pbi-tools extracted models only when no PBIP models exist.
    if not model_dirs:
        for model_dir in root.rglob("Model"):
            if model_dir.is_dir() and any(model_dir.rglob("*.tmdl")):
                model_dirs.append(model_dir.resolve())

    # Avoid duplicate directories.
    return sorted(set(model_dirs))


def parse_endpoint(endpoint):
    """
    Parse endpoints such as:
        Sales.ProductID
        'Sales Data'.'Product ID'
        'Sales Data'.ProductID

    Splits at the first dot outside quoted identifiers.
    """
    endpoint = endpoint.strip()

    if endpoint.endswith(","):
        endpoint = endpoint[:-1].strip()

    in_quotes = False
    split_at = None
    i = 0

    while i < len(endpoint):
        char = endpoint[i]

        if char == "'":
            # Two apostrophes inside a quoted identifier represent one.
            if in_quotes and i + 1 < len(endpoint) and endpoint[i + 1] == "'":
                i += 2
                continue

            in_quotes = not in_quotes

        elif char == "." and not in_quotes:
            split_at = i
            break

        i += 1

    if split_at is None:
        return None, None

    table_name = normalize_name(endpoint[:split_at])
    column_name = normalize_name(endpoint[split_at + 1:])

    if not table_name or not column_name:
        return None, None

    return table_name, column_name


def parse_table_metadata(model_dir, findings):
    """Read table and column declarations from the selected model."""
    tables = {}
    read_errors = 0

    for file_path in sorted(model_dir.rglob("*.tmdl")):
        try:
            content = file_path.read_text(encoding="utf-8-sig")
        except (OSError, UnicodeError) as exc:
            read_errors += 1
            add_finding(
                findings,
                "WARNING",
                "tmdl_read",
                f"Could not read {file_path.name}: {exc}",
                [str(file_path)],
            )
            continue

        table_matches = list(re.finditer(
            r"(?m)^[ \t]*table[ \t]+(.+?)[ \t]*$",
            content,
        ))

        for index, match in enumerate(table_matches):
            raw_table_name = match.group(1).strip()
            table_name = normalize_name(raw_table_name)

            section_end = (
                table_matches[index + 1].start()
                if index + 1 < len(table_matches)
                else len(content)
            )
            section = content[match.end():section_end]

            columns = {
                normalize_name(column)
                for column in re.findall(
                    r"(?m)^[ \t]*column[ \t]+(.+?)[ \t]*$",
                    section,
                )
            }

            # Merge declarations if a model declares a table in more than
            # one parsed section, rather than discarding previously seen columns.
            tables.setdefault(table_name, set()).update(columns)

    return tables, read_errors


def parse_relationships(model_dir, findings):
    """Extract relationship declarations from TMDL files."""
    relationships = []
    seen = set()
    read_errors = 0

    for file_path in sorted(model_dir.rglob("*.tmdl")):
        try:
            content = file_path.read_text(encoding="utf-8-sig")
        except (OSError, UnicodeError):
            read_errors += 1
            continue

        # A relationship block starts at a relationship declaration and
        # continues until the next relationship declaration or end of file.
        matches = list(re.finditer(
            r"(?m)^[ \t]*relationship(?:[ \t]+.*)?$",
            content,
        ))

        for index, match in enumerate(matches):
            end = matches[index + 1].start() if index + 1 < len(matches) else len(content)
            block = content[match.start():end]

            from_match = re.search(
                r"(?m)^[ \t]*fromColumn[ \t]*:[ \t]*(.+?)[ \t]*$",
                block,
            )
            to_match = re.search(
                r"(?m)^[ \t]*toColumn[ \t]*:[ \t]*(.+?)[ \t]*$",
                block,
            )

            if not from_match or not to_match:
                add_finding(
                    findings,
                    "WARNING",
                    "relationship_syntax",
                    "A relationship declaration could not be fully parsed.",
                    [f"File: {file_path}", block.strip()[:300]],
                )
                continue

            from_endpoint = from_match.group(1).strip()
            to_endpoint = to_match.group(1).strip()

            # Include model identity in the key because the same endpoints
            # may occur in different semantic models.
            key = (
                normalize_name(from_endpoint),
                normalize_name(to_endpoint),
            )

            if key in seen:
                continue

            seen.add(key)
            relationships.append({
                "from": from_endpoint,
                "to": to_endpoint,
                "file": str(file_path),
            })

    return relationships, read_errors


def check_one_model(model_dir):
    """Validate relationship endpoints within one semantic model."""
    findings = []

    tables, table_read_errors = parse_table_metadata(model_dir, findings)
    relationships, relationship_read_errors = parse_relationships(
        model_dir,
        findings,
    )

    if not tables:
        add_finding(
            findings,
            "NOT_TESTED",
            "table_metadata",
            "No table and column declarations could be extracted.",
            [str(model_dir)],
        )

    if not relationships:
        add_finding(
            findings,
            "NOT_TESTED",
            "relationship_inventory",
            "No complete relationship definitions were parsed. "
            "This does not prove that the model has no relationships.",
            [str(model_dir)],
        )
    else:
        add_finding(
            findings,
            "PASS",
            "relationship_inventory",
            f"Parsed {len(relationships)} relationship definition(s).",
            [str(model_dir)],
        )

    for index, relationship in enumerate(relationships, start=1):
        endpoint_errors = []

        for direction in ("from", "to"):
            endpoint = relationship[direction]
            table_name, column_name = parse_endpoint(endpoint)

            if table_name is None:
                endpoint_errors.append(
                    f"Could not parse {direction} endpoint: {endpoint}"
                )
                continue

            if table_name not in tables:
                endpoint_errors.append(
                    f"Table not found in extracted metadata: {table_name}"
                )
            elif column_name not in tables[table_name]:
                endpoint_errors.append(
                    f"Column not found in extracted metadata: "
                    f"{table_name}.{column_name}"
                )

        if endpoint_errors:
            add_finding(
                findings,
                "WARNING",
                f"relationship_{index}_endpoints",
                "One or both relationship endpoints could not be matched "
                "to the extracted table and column metadata. "
                "Check the evidence before treating this as a model defect.",
                endpoint_errors + [f"File: {relationship['file']}"],
            )
        else:
            add_finding(
                findings,
                "PASS",
                f"relationship_{index}_endpoints",
                "Both relationship endpoints match extracted table and column declarations.",
                [relationship["from"], relationship["to"]],
            )

    if table_read_errors or relationship_read_errors:
        add_finding(
            findings,
            "WARNING",
            "metadata_read_completeness",
            "Some TMDL files could not be read; relationship validation may be incomplete.",
            [
                f"Table metadata read errors: {table_read_errors}",
                f"Relationship metadata read errors: {relationship_read_errors}",
            ],
        )

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
        "model_directory": str(model_dir),
        "overall_status": overall_status,
        "summary": {
            "tables_detected": len(tables),
            "columns_detected": sum(len(columns) for columns in tables.values()),
            "relationships_parsed": len(relationships),
        },
        "findings": findings,
    }


def check_relationships(project_path):
    """Validate relationships in accessible Power BI semantic models."""
    root = Path(project_path).expanduser().resolve()

    if not root.is_dir():
        return {
            "overall_status": "FAIL",
            "summary": {
                "model_directories_checked": 0,
                "tables_detected": 0,
                "relationships_parsed": 0,
            },
            "findings": [{
                "status": "FAIL",
                "check": "project_path",
                "message": f"Project directory does not exist: {root}",
                "evidence": [str(root)],
            }],
        }

    model_dirs = find_model_directories(root)

    if not model_dirs:
        pbix_files = list(root.rglob("*.pbix"))
        pbip_files = list(root.rglob("*.pbip"))

        if pbix_files:
            message = (
                "PBIX files were found, but no accessible extracted TMDL model "
                "was available for relationship inspection."
            )
        elif pbip_files:
            message = (
                "PBIP files were found, but no accessible semantic-model "
                "TMDL definitions were discovered."
            )
        else:
            message = "No accessible semantic-model definition was found."

        return {
            "overall_status": "NOT_TESTED",
            "summary": {
                "model_directories_checked": 0,
                "tables_detected": 0,
                "relationships_parsed": 0,
            },
            "findings": [{
                "status": "NOT_TESTED",
                "check": "relationship_metadata",
                "message": message,
                "evidence": [str(path) for path in (pbix_files + pbip_files)[:10]],
            }],
        }

    # Keep each model's metadata separate to avoid matching a relationship
    # against a similarly named table in another semantic model.
    model_results = [check_one_model(model_dir) for model_dir in model_dirs]

    combined_findings = []
    total_tables = 0
    total_relationships = 0

    for result in model_results:
        model_label = result["model_directory"]
        total_tables += result["summary"]["tables_detected"]
        total_relationships += result["summary"]["relationships_parsed"]

        for finding in result["findings"]:
            item = dict(finding)
            item["evidence"] = [f"Model: {model_label}"] + item.get("evidence", [])
            combined_findings.append(item)

    statuses = {item["status"] for item in combined_findings}

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
            "model_directories_checked": len(model_dirs),
            "tables_detected": total_tables,
            "relationships_parsed": total_relationships,
        },
        "models": model_results,
        "findings": combined_findings,
    }


def main():
    parser = argparse.ArgumentParser(
        description="Validate Power BI relationship metadata."
    )
    parser.add_argument(
        "--project-path",
        required=True,
        help="Path to a PBIP project, repository, or extracted Model folder.",
    )
    parser.add_argument("--output", help="Optional JSON output path.")
    args = parser.parse_args()

    result = check_relationships(args.project_path)
    output = json.dumps(result, indent=2, ensure_ascii=False)
    print(output)

    if args.output:
        output_path = Path(args.output).expanduser()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(output + "\n", encoding="utf-8")
        print(f"\nResults saved to: {output_path.resolve()}")


if __name__ == "__main__":
    main()
