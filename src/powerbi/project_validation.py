import re
import json
import zipfile
import tempfile
import shutil
import subprocess
from pathlib import Path, PurePosixPath
import requests
import time
from functools import lru_cache
from urllib.parse import urlparse
from google.genai import errors
from src.core.findings import add_finding
from src.data_analysis.csv_quality import inspect_csv
from src.data_analysis.sql_validation import inspect_sql
from src.data_analysis.csv_quality import inspect_text_metadata
from src.powerbi.model_validation import inspect_tmdl_definitions
from src.data_analysis.csv_quality import validate_constant_csv_columns
from src.powerbi.dax_validation import validate_dax_measures
from src.powerbi.dax_validation import validate_dax_references
from src.powerbi.dax_validation import validate_duplicate_measure_names
from src.powerbi.model_validation import validate_duplicate_relationships
from src.powerbi.dax_validation import validate_empty_measure_expressions
from src.powerbi.dax_validation import validate_measure_dependencies
from src.powerbi.model_validation import validate_model_relationships
from src.powerbi.model_validation import validate_relationship_columns
from src.powerbi.model_validation import validate_relationship_quality
from src.core.config import MAX_SCHEMA_BYTES, MAX_TEXT_FILE_BYTES, MAX_ZIP_FILES, MAX_ZIP_UNCOMPRESSED_BYTES, OFFICIAL_SCHEMA_HOST


def _relative_name(path, root):
    try:
        return str(path.relative_to(root)).replace("\\", "/")
    except ValueError:
        return str(path).replace("\\", "/")


def validate_pbip_project_structure(root, findings):
    """Validate common PBIP folder/file expectations without opening Power BI Desktop."""
    root = Path(root)
    pbip_files = list(root.rglob("*.pbip"))

    if not pbip_files:
        add_finding(
            findings, "PBIP Project Structure", "WARNING",
            "No .pbip entry file was found in the uploaded project.",
            str(root),
            "The ZIP may contain only a report/model folder, or may be nested unexpectedly."
        )
        project_root = root
    else:
        # Prefer the project folder containing the first PBIP entry file.
        project_root = pbip_files[0].parent
        add_finding(
            findings, "PBIP Project Structure", "PASS",
            f"Found {len(pbip_files)} .pbip project entry file(s).",
            _relative_name(pbip_files[0], root),
            "The entry file is present; this does not prove the project opens successfully."
        )

    report_dirs = sorted(
        [p for p in project_root.iterdir() if p.is_dir() and p.name.lower().endswith(".report")]
    ) if project_root.exists() else []
    model_dirs = sorted(
        [p for p in project_root.iterdir() if p.is_dir() and p.name.lower().endswith(".semanticmodel")]
    ) if project_root.exists() else []

    if report_dirs:
        add_finding(
            findings, "PBIP Project Structure", "PASS",
            f"Found {len(report_dirs)} report folder(s).",
            evidence="Expected folder names usually end in .Report."
        )
    else:
        add_finding(
            findings, "PBIP Project Structure", "WARNING",
            "No top-level *.Report folder was found next to the project entry file.",
            evidence="A report-only upload or nonstandard/nested layout may require manual review."
        )

    if model_dirs:
        add_finding(
            findings, "PBIP Project Structure", "PASS",
            f"Found {len(model_dirs)} semantic model folder(s).",
            evidence="Expected folder names usually end in .SemanticModel."
        )
    else:
        add_finding(
            findings, "PBIP Project Structure", "WARNING",
            "No top-level *.SemanticModel folder was found.",
            evidence="This can be valid for a report that connects to an external semantic model."
        )

    for report_dir in report_dirs:
        pbir = report_dir / "definition.pbir"
        if pbir.is_file():
            try:
                data = json.loads(pbir.read_text(encoding="utf-8-sig"))
                if not isinstance(data, dict):
                    raise ValueError("The top-level JSON value is not an object.")
                add_finding(
                    findings, "PBIR Definition", "PASS",
                    "definition.pbir exists and contains valid JSON.",
                    _relative_name(pbir, root),
                    "Only JSON syntax was checked; the full Power BI schema was not validated."
                )
            except Exception as exc:
                add_finding(
                    findings, "PBIR Definition", "FAIL",
                    f"definition.pbir could not be parsed: {exc}",
                    _relative_name(pbir, root)
                )
        else:
            add_finding(
                findings, "PBIR Definition", "WARNING",
                "definition.pbir is missing from a report folder.",
                _relative_name(report_dir, root),
                "Check whether this project uses a legacy or incomplete report layout."
            )

        definition_dir = report_dir / "definition"
        if definition_dir.is_dir():
            page_files = list(definition_dir.rglob("page.json"))
            visual_files = list(definition_dir.rglob("visual.json"))
            # Legacy report.json is noted but not edited or schema-validated here.
            legacy_report = report_dir / "report.json"
            add_finding(
                findings, "Report Metadata", "INFO",
                f"Discovered {len(page_files)} page definition file(s) and {len(visual_files)} visual definition file(s).",
                _relative_name(definition_dir, root),
                "Counts are based on filenames; visual rendering and interaction behavior are not tested."
            )
        elif (report_dir / "report.json").is_file():
            add_finding(
                findings, "Report Metadata", "INFO",
                "Found legacy report.json format.",
                _relative_name(report_dir / "report.json", root),
                "This scanner checks JSON syntax but does not validate the undocumented legacy report schema."
            )
        else:
            add_finding(
                findings, "Report Metadata", "WARNING",
                "No definition folder or legacy report.json was found in this report folder.",
                _relative_name(report_dir, root)
            )

    for model_dir in model_dirs:
        pbism = model_dir / "definition.pbism"
        if pbism.is_file():
            try:
                data = json.loads(pbism.read_text(encoding="utf-8-sig"))
                if not isinstance(data, dict):
                    raise ValueError("The top-level JSON value is not an object.")
                add_finding(
                    findings, "Semantic Model Definition", "PASS",
                    "definition.pbism exists and contains valid JSON.",
                    _relative_name(pbism, root),
                    "This validates JSON syntax, not model-engine compatibility."
                )
            except Exception as exc:
                add_finding(
                    findings, "Semantic Model Definition", "FAIL",
                    f"definition.pbism could not be parsed: {exc}",
                    _relative_name(pbism, root)
                )
        else:
            add_finding(
                findings, "Semantic Model Definition", "WARNING",
                "definition.pbism is missing from a semantic model folder.",
                _relative_name(model_dir, root)
            )

        tmdl_dir = model_dir / "definition"
        tmdl_files = list(tmdl_dir.rglob("*.tmdl")) if tmdl_dir.is_dir() else []
        model_bim = model_dir / "model.bim"
        if tmdl_files:
            add_finding(
                findings, "Semantic Model Definition", "PASS",
                f"Found {len(tmdl_files)} TMDL definition file(s).",
                _relative_name(tmdl_dir, root),
                "TMDL syntax and semantic correctness still require Power BI/TOM validation."
            )
        elif model_bim.is_file():
            try:
                data = json.loads(model_bim.read_text(encoding="utf-8-sig"))
                model_obj = data.get("model", data) if isinstance(data, dict) else None
                if not isinstance(model_obj, dict):
                    raise ValueError("Expected a JSON object containing model metadata.")
                tables = model_obj.get("tables", [])
                relationships = model_obj.get("relationships", [])
                add_finding(
                    findings, "TMSL Model Definition", "INFO",
                    f"Parsed model.bim JSON; found {len(tables) if isinstance(tables, list) else 0} table entries and {len(relationships) if isinstance(relationships, list) else 0} relationship entries.",
                    _relative_name(model_bim, root),
                    "Only basic JSON/object structure was checked; model semantics were not validated."
                )
            except Exception as exc:
                add_finding(
                    findings, "TMSL Model Definition", "FAIL",
                    f"model.bim could not be parsed as expected JSON: {exc}",
                    _relative_name(model_bim, root)
                )
        else:
            add_finding(
                findings, "Semantic Model Definition", "WARNING",
                "No TMDL definition folder or model.bim file was found.",
                _relative_name(model_dir, root)
            )


@lru_cache(maxsize=128)
def _download_official_json_schema(schema_url):
    """Download and cache only official Microsoft PBIR JSON schemas."""
    parsed = urlparse(schema_url)
    if parsed.scheme != "https" or parsed.hostname != OFFICIAL_SCHEMA_HOST:
        raise ValueError("Schema URL is not on the approved Microsoft schema host.")
    if not parsed.path.startswith("/json-schemas/fabric/") or not parsed.path.endswith("/schema.json"):
        raise ValueError("Schema URL is not a supported Microsoft Fabric schema URL.")

    response = requests.get(schema_url, timeout=15)
    response.raise_for_status()
    if len(response.content) > MAX_SCHEMA_BYTES:
        raise ValueError("Downloaded JSON schema exceeds the size limit.")
    schema = response.json()
    if not isinstance(schema, dict):
        raise ValueError("The downloaded JSON schema is not a JSON object.")
    return schema


def validate_official_pbir_schemas(root, findings):
    """Validate PBIR JSON documents that declare an official Microsoft $schema URL."""
    try:
        import jsonschema
    except ImportError:
        add_finding(
            findings, "PBIR JSON Schema", "NOT RUN",
            "The jsonschema package is not installed.",
            evidence="Install it with: python -m pip install jsonschema"
        )
        return

    root = Path(root)
    candidates = []
    for path in root.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in {".json", ".pbir", ".pbip", ".pbism"}:
            continue
        if path.stat().st_size > MAX_TEXT_FILE_BYTES:
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            # Syntax errors are reported by the existing JSON validation functions.
            continue
        if isinstance(data, dict) and isinstance(data.get("$schema"), str):
            schema_url = data["$schema"]
            if "developer.microsoft.com/json-schemas/fabric/" in schema_url:
                candidates.append((path, data, schema_url))

    if not candidates:
        add_finding(
            findings, "PBIR JSON Schema", "NOT RUN",
            "No JSON documents declaring a supported official Microsoft Fabric schema were found.",
            evidence="PBIR files should include their official $schema URL. Legacy report.json files may not have a public schema."
        )
        return

    passed = 0
    failed = 0
    skipped = 0
    for path, data, schema_url in candidates:
        relative = _relative_name(path, root)
        try:
            schema = _download_official_json_schema(schema_url)
            validator_cls = jsonschema.validators.validator_for(schema)
            validator_cls.check_schema(schema)
            validator = validator_cls(schema)
            errors = sorted(validator.iter_errors(data), key=lambda err: list(map(str, err.absolute_path)))
            if errors:
                failed += 1
                details = []
                for error in errors[:5]:
                    location = ".".join(str(part) for part in error.absolute_path) or "$"
                    details.append(f"{location}: {error.message}")
                extra = f"; plus {len(errors) - 5} more error(s)" if len(errors) > 5 else ""
                add_finding(
                    findings, "PBIR JSON Schema", "FAIL",
                    f"Official schema validation found {len(errors)} issue(s){extra}.",
                    relative, " | ".join(details)
                )
            else:
                passed += 1
                add_finding(
                    findings, "PBIR JSON Schema", "PASS",
                    "Document conforms to the official schema declared in $schema.",
                    relative, schema_url
                )
        except requests.RequestException as exc:
            skipped += 1
            add_finding(
                findings, "PBIR JSON Schema", "NOT RUN",
                f"Could not download the official schema: {exc}",
                relative, "Check internet access and retry; this is not a document validation failure."
            )
        except Exception as exc:
            skipped += 1
            add_finding(
                findings, "PBIR JSON Schema", "NOT RUN",
                f"Schema validation could not be completed: {exc}",
                relative, "The file's JSON syntax may be valid, but schema compliance remains unverified."
            )

    add_finding(
        findings, "PBIR JSON Schema Summary",
        "FAIL" if failed else ("WARNING" if skipped else "PASS"),
        f"Official schema validation: {passed} passed, {failed} failed, {skipped} not run.",
        evidence="Schema checks validate document structure, not whether Power BI Desktop can render the report or execute its model."
    )


def validate_report_json_files(root, findings):
    """Parse report-related JSON files and report broken JSON separately."""
    root = Path(root)
    report_json_files = []
    for path in root.rglob("*.json"):
        lower_parts = [part.lower() for part in path.parts]
        if any(part.endswith(".report") for part in lower_parts) or "report" in path.name.lower() or "visual" in path.name.lower() or "page" in path.name.lower():
            report_json_files.append(path)

    if not report_json_files:
        add_finding(
            findings, "Report JSON Validation", "NOT RUN",
            "No report/page/visual JSON files were detected.",
            evidence="This may occur with legacy report formats or an incomplete project upload."
        )
        return

    valid = 0
    invalid = 0
    for path in report_json_files:
        try:
            if path.stat().st_size > MAX_TEXT_FILE_BYTES:
                add_finding(
                    findings, "Report JSON Validation", "WARNING",
                    "Report JSON skipped because it exceeds the 1 MB text-file limit.",
                    _relative_name(path, root)
                )
                continue
            data = json.loads(path.read_text(encoding="utf-8-sig"))
            if not isinstance(data, (dict, list)):
                raise ValueError("Expected a JSON object or array at the top level.")
            valid += 1
        except Exception as exc:
            invalid += 1
            add_finding(
                findings, "Report JSON Validation", "FAIL",
                f"Invalid report-related JSON: {exc}",
                _relative_name(path, root)
            )

    add_finding(
        findings, "Report JSON Validation", "PASS" if invalid == 0 else "WARNING",
        f"Parsed {valid} report-related JSON file(s); {invalid} invalid file(s).",
        evidence="JSON syntax validation only; this is not full JSON Schema validation and does not test rendering."
    )


def validate_pbir_visual_details(root, findings):
    """
    Detailed static inspection of PBIR visual definitions, layouts, titles,
    slicers, and page clutter.
    """
    import re
    root = Path(root)
    visual_files = list(root.rglob("visual.json"))
    page_files = list(root.rglob("page.json"))

    if not visual_files and not page_files:
        legacy_reports = list(root.rglob("report.json"))
        if legacy_reports:
            add_finding(
                findings, "Visual Static Inspection", "INFO",
                f"Found legacy report.json layout ({len(legacy_reports)} file(s)). PBIR visual-level layout files not present.",
                str(root),
                "PBIR format provides granular visual.json files for layout and slicer inspection."
            )
        else:
            add_finding(
                findings, "Visual Static Inspection", "NOT RUN",
                "No PBIR visual or page JSON definitions detected.",
                str(root)
            )
        return

    # 1. Page inspection
    page_names = []
    default_named_pages = []
    for page_path in page_files:
        try:
            page_data = json.loads(page_path.read_text(encoding="utf-8-sig", errors="replace"))
            display_name = page_data.get("displayName") or page_data.get("name") or page_path.parent.name
            page_names.append(str(display_name))
            if re.match(r"^(Page\s*\d+|ReportSection\d*)$", str(display_name), re.IGNORECASE):
                default_named_pages.append(str(display_name))
        except Exception:
            continue

    if default_named_pages:
        add_finding(
            findings, "Visual & Page Configuration", "WARNING",
            f"Pages with default/generic names detected: {', '.join(default_named_pages)}.",
            evidence="Descriptive page names improve report accessibility and navigation."
        )
    elif page_names:
        add_finding(
            findings, "Visual & Page Configuration", "PASS",
            f"Found {len(page_names)} page(s) with descriptive naming: {', '.join(page_names)}."
        )

    # 2. Visual inspection
    visual_types = {}
    missing_titles = []
    zero_dimension_visuals = []
    off_canvas_visuals = []
    slicer_count = 0
    button_count = 0
    visuals_by_page = {}
    seen_positions = {}

    for v_path in visual_files:
        rel_path = _relative_name(v_path, root)
        parts = v_path.parts
        page_id = "General"
        for i, part in enumerate(parts):
            if part.lower() == "pages" and i + 1 < len(parts):
                page_id = parts[i + 1]
                break
        visuals_by_page.setdefault(page_id, []).append(v_path)

        try:
            data = json.loads(v_path.read_text(encoding="utf-8-sig", errors="replace"))
        except Exception:
            continue

        v_obj = data.get("visual", {}) if isinstance(data, dict) else {}
        v_type = v_obj.get("visualType") or (data.get("visualType") if isinstance(data, dict) else None) or "unknown"
        visual_types[v_type] = visual_types.get(v_type, 0) + 1

        if "slicer" in v_type.lower():
            slicer_count += 1
        if "button" in v_type.lower() or "actionbutton" in v_type.lower():
            button_count += 1

        # Check Position / Layout
        pos = data.get("position", {}) if isinstance(data, dict) else {}
        x = pos.get("x")
        y = pos.get("y")
        w = pos.get("width")
        h = pos.get("height")

        if w is not None and h is not None:
            if w <= 0 or h <= 0:
                zero_dimension_visuals.append(f"{v_type} ({rel_path})")
            if (x is not None and x < 0) or (y is not None and y < 0):
                off_canvas_visuals.append(f"{v_type} ({rel_path}) at x={x}, y={y}")

            if x is not None and y is not None:
                coord_key = (page_id, x, y, w, h)
                seen_positions.setdefault(coord_key, []).append((v_type, rel_path))

        # Check Titles
        decorative_types = {"shape", "line", "image", "textbox", "actionbutton", "basicshape"}
        if v_type.lower() not in decorative_types:
            has_title = False
            objects = v_obj.get("visualContainerObjects") or (data.get("objects") if isinstance(data, dict) else None) or {}
            if isinstance(objects, dict):
                title_config = objects.get("title", [])
                if isinstance(title_config, list) and title_config:
                    props = title_config[0].get("properties", {})
                    show_prop = props.get("show", {}).get("expr", {}).get("Literal", {}).get("Value")
                    if str(show_prop).lower() == "false":
                        has_title = False
                    else:
                        text_val = props.get("text", {}).get("expr", {}).get("Literal", {}).get("Value")
                        if text_val:
                            has_title = True
                elif isinstance(title_config, dict):
                    has_title = True

            if not has_title:
                raw_lower = json.dumps(data).lower()
                if '"title"' in raw_lower and ('"show":true' in raw_lower or '"show": true' in raw_lower or '"titletext"' in raw_lower):
                    has_title = True

            if not has_title:
                missing_titles.append(f"{v_type} on {page_id}")

    # Summary findings:
    if visual_types:
        types_summary = ", ".join(f"{count}x {vtype}" for vtype, count in sorted(visual_types.items(), key=lambda x: -x[1]))
        add_finding(
            findings, "Visual Static Inspection", "PASS",
            f"Detected {len(visual_files)} visual definition(s) across {len(visuals_by_page)} page(s).",
            evidence=f"Visual types breakdown: {types_summary}."
        )

    if slicer_count > 0 or button_count > 0:
        add_finding(
            findings, "Interactive Controls", "PASS",
            f"Found {slicer_count} interactive slicer(s) and {button_count} action button(s).",
            evidence="Dashboard includes interactive elements for user-driven filtering and navigation."
        )
    elif len(visual_files) > 3:
        add_finding(
            findings, "Interactive Controls", "WARNING",
            "No interactive slicers or filter controls detected in PBIR visuals.",
            evidence="Users may not be able to slice or filter dashboard data dynamically."
        )

    if missing_titles:
        sample_missing = missing_titles[:5]
        extra = f" (+{len(missing_titles) - 5} more)" if len(missing_titles) > 5 else ""
        add_finding(
            findings, "Visual Title & Accessibility", "WARNING",
            f"{len(missing_titles)} chart/data visual(s) lack an explicit title property.",
            evidence=f"Examples: {', '.join(sample_missing)}{extra}. Consider adding explicit titles for accessibility."
        )
    elif visual_files:
        add_finding(
            findings, "Visual Title & Accessibility", "PASS",
            "All non-decorative data visuals have title configurations enabled."
        )

    if zero_dimension_visuals:
        add_finding(
            findings, "Visual Layout & Coordinates", "WARNING",
            f"{len(zero_dimension_visuals)} visual(s) have zero width or height.",
            evidence=", ".join(zero_dimension_visuals[:3])
        )
    if off_canvas_visuals:
        add_finding(
            findings, "Visual Layout & Coordinates", "WARNING",
            f"{len(off_canvas_visuals)} visual(s) have negative off-canvas coordinates.",
            evidence=", ".join(off_canvas_visuals[:3])
        )

    overlapping_stacks = [items for items in seen_positions.values() if len(items) > 1]
    if overlapping_stacks:
        add_finding(
            findings, "Visual Layout & Coordinates", "INFO",
            f"Detected {len(overlapping_stacks)} visual stack(s) with identical positions (possible bookmark overlays).",
            evidence="Stacked visuals are common with bookmark toggling, but verify they are not accidental duplicates."
        )
    elif not zero_dimension_visuals and not off_canvas_visuals and visual_files:
        add_finding(
            findings, "Visual Layout & Coordinates", "PASS",
            "Visual layout coordinates are valid and within expected canvas bounds."
        )

    cluttered_pages = []
    for page_id, vlist in visuals_by_page.items():
        if len(vlist) > 12:
            cluttered_pages.append(f"{page_id} ({len(vlist)} visuals)")
    if cluttered_pages:
        add_finding(
            findings, "Dashboard Design & Clutter", "WARNING",
            f"High visual density detected on: {', '.join(cluttered_pages)}.",
            evidence="Over 12 visuals per page may cause cognitive overload, slow report rendering, and poor UX."
        )
    elif visual_files:
        add_finding(
            findings, "Dashboard Design & Clutter", "PASS",
            "Visual density per page is well-balanced (all pages have <= 12 visuals)."
        )


def inspect_pbip_zip(uploaded_file, findings):
    with tempfile.TemporaryDirectory(prefix="pbip_test_") as temp_dir:
        root = Path(temp_dir)

        try:
            uploaded_file.seek(0)

            with zipfile.ZipFile(uploaded_file) as archive:
                members = archive.infolist()

                if len(members) > MAX_ZIP_FILES:
                    raise ValueError("ZIP contains too many files.")

                total_size = sum(m.file_size for m in members)

                if total_size > MAX_ZIP_UNCOMPRESSED_BYTES:
                    raise ValueError("ZIP expands to more than 100 MB.")

                for member in members:
                    member_path = PurePosixPath(member.filename)

                    if member_path.is_absolute() or ".." in member_path.parts:
                        raise ValueError("ZIP contains an unsafe path.")

                    mode = member.external_attr >> 16

                    if (mode & 0o170000) == 0o120000:
                        raise ValueError("ZIP contains a symbolic link.")

                archive.extractall(root)

        except zipfile.BadZipFile:
            raise ValueError("The uploaded ZIP is invalid.")

        count = inspect_text_metadata(root, findings)
        validate_pbip_project_structure(root, findings)
        validate_report_json_files(root, findings)
        validate_official_pbir_schemas(root, findings)
        validate_pbir_visual_details(root, findings)
        inspect_tmdl_definitions(root, findings)
        validate_dax_measures(root, findings)
        validate_model_relationships(root, findings)
        validate_relationship_columns(root, findings)
        validate_relationship_quality(root, findings)
        validate_dax_references(root, findings)
        validate_measure_dependencies(root, findings)
        validate_duplicate_measure_names(root, findings)
        validate_empty_measure_expressions(root, findings)
        validate_duplicate_relationships(root, findings)
        validate_constant_csv_columns(root, findings)

        add_finding(
            findings, "PBIP Metadata", "INFO",
            f"Scanned {count} supported metadata files",
            evidence="Power BI runtime was not executed."
        )


def inspect_pbix(upload, findings):
    """Extract a PBIX with pbi-tools when installed, then run metadata checks."""
    executable = shutil.which("pbi-tools") or shutil.which("pbi-tools.exe")
    if not executable:
        add_finding(
            findings, "PBIX Extraction", "NOT RUN",
            "pbi-tools CLI was not found; PBIX model/report extraction was skipped.",
            upload.name,
            "Install pbi-tools and ensure pbi-tools.exe is on PATH, then restart the terminal and Streamlit."
        )
        return

    with tempfile.TemporaryDirectory(prefix="pbix_extract_") as temp_dir:
        temp = Path(temp_dir)
        pbix_path = temp / Path(upload.name).name
        extract_dir = temp / "extracted"
        pbix_path.write_bytes(upload.getvalue())
        try:
            result = subprocess.run(
                [executable, "extract", str(pbix_path), "-extractFolder", str(extract_dir)],
                capture_output=True, text=True, timeout=300, check=False
            )
        except subprocess.TimeoutExpired:
            add_finding(findings, "PBIX Extraction", "FAIL", "pbi-tools extraction timed out after 5 minutes.", upload.name)
            return
        except Exception as exc:
            add_finding(findings, "PBIX Extraction", "FAIL", f"Could not start pbi-tools: {exc}", upload.name)
            return

        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "No details returned")[-2500:]
            add_finding(findings, "PBIX Extraction", "FAIL", "pbi-tools could not extract this PBIX file.", upload.name, detail)
            return

        # pbi-tools versions may choose their own default folder or honor extractFolder.
        candidates = [extract_dir] if extract_dir.exists() else []
        candidates += [x for x in temp.iterdir() if x.is_dir() and x not in candidates]
        extracted_root = next((x for x in candidates if any(x.rglob("*.json")) or any(x.rglob("*.tmdl"))), None)
        if extracted_root is None:
            add_finding(findings, "PBIX Extraction", "WARNING", "Extraction command completed but no recognizable model/report metadata was found.", upload.name, (result.stdout or "")[-1500:])
            return

        add_finding(findings, "PBIX Extraction", "PASS", "PBIX contents were extracted with pbi-tools.", upload.name, "Running metadata checks on extracted contents.")
        validate_report_json_files(extracted_root, findings)
        validate_official_pbir_schemas(extracted_root, findings)
        validate_pbir_visual_details(extracted_root, findings)
        inspect_tmdl_definitions(extracted_root, findings)
        validate_dax_measures(extracted_root, findings)
        validate_model_relationships(extracted_root, findings)
        validate_relationship_columns(extracted_root, findings)
        validate_relationship_quality(extracted_root, findings)
        validate_dax_references(extracted_root, findings)
        validate_measure_dependencies(extracted_root, findings)
        validate_duplicate_measure_names(extracted_root, findings)
        validate_empty_measure_expressions(extracted_root, findings)
        validate_duplicate_relationships(extracted_root, findings)
        add_finding(findings, "PBIX Extraction", "INFO", "Extracted PBIX metadata checks finished.", upload.name, "This still does not execute the model in the Power BI engine or test report interactions.")


def export_powerbi_report_pdf(access_token, workspace_id, report_id, findings):
    """Ask Power BI Service to render/export a report to PDF and poll the export job."""
    if not all([access_token, workspace_id, report_id]):
        add_finding(findings, "Visual Rendering", "NOT RUN", "Power BI access token, workspace ID, and report ID are required for service-side PDF rendering.")
        return None
    headers = {"Authorization": f"Bearer {access_token.strip()}", "Content-Type": "application/json"}
    report_base = f"https://api.powerbi.com/v1.0/myorg/groups/{workspace_id}/reports/{report_id}"
    export_url = f"{report_base}/ExportTo"
    try:
        response = requests.post(export_url, headers=headers, json={"format": "PDF"}, timeout=60)
        if response.status_code not in (200, 202):
            add_finding(findings, "Visual Rendering", "FAIL", f"Power BI export request failed (HTTP {response.status_code}).", evidence=response.text[:2000])
            return None
        job = response.json()
        export_id = job.get("id")
        if not export_id:
            add_finding(findings, "Visual Rendering", "FAIL", "Power BI export response did not contain an export job ID.", evidence=json.dumps(job)[:1500])
            return None
        status_url = f"{report_base}/exports/{export_id}"
        for _ in range(30):
            time.sleep(2)
            status_response = requests.get(status_url, headers=headers, timeout=30)
            if not status_response.ok:
                add_finding(findings, "Visual Rendering", "FAIL", f"Could not check export status (HTTP {status_response.status_code}).", evidence=status_response.text[:1500])
                return None
            status_data = status_response.json()
            status = str(status_data.get("status", "")).lower()
            if status == "failed":
                add_finding(findings, "Visual Rendering", "FAIL", "Power BI Service failed to render the report PDF.", evidence=json.dumps(status_data)[:1500])
                return None
            if status == "succeeded":
                file_url = f"{report_base}/exports/{export_id}/file"
                file_response = requests.get(file_url, headers=headers, timeout=120)
                if not file_response.ok:
                    add_finding(findings, "Visual Rendering", "FAIL", f"Could not download rendered PDF (HTTP {file_response.status_code}).")
                    return None
                add_finding(findings, "Visual Rendering", "PASS", "Power BI Service rendered the report to PDF.", evidence="This verifies export/rendering only, not interactive visual behavior.")
                return file_response.content
        add_finding(findings, "Visual Rendering", "WARNING", "Power BI report export did not finish within 60 seconds.")
        return None
    except Exception as exc:
        add_finding(findings, "Visual Rendering", "FAIL", f"Power BI report rendering request failed: {exc}")
        return None


def inspect_single_upload(upload, findings):
    name = upload.name
    suffix = Path(name).suffix.lower()

    if suffix == ".csv":
        inspect_csv(
            upload.getvalue().decode("utf-8-sig", errors="replace"),
            name, findings
        )

    elif suffix == ".sql":
        inspect_sql(
            upload.getvalue().decode("utf-8-sig", errors="replace"),
            name, findings
        )

    elif suffix in {
        ".dax", ".tmdl", ".json", ".pbir", ".pbip", ".bim", ".txt"
    }:
        content = upload.getvalue().decode(
            "utf-8-sig", errors="replace"
        )

        add_finding(
            findings, "File Metadata", "INFO",
            f"Uploaded {suffix} file", name,
            "Single-file scan only; related project files may be needed."
        )

        if suffix == ".json":
            try:
                json.loads(content)
                add_finding(
                    findings, "JSON", "PASS",
                    "Valid JSON syntax", name
                )
            except Exception as exc:
                add_finding(
                    findings, "JSON", "FAIL",
                    f"JSON parsing failed: {exc}", name
                )

        if suffix == ".dax":
            add_finding(
                findings, "DAX Static Check", "WARNING",
                "DAX expression was not executed or fully validated",
                name
            )

        if suffix == ".pbip":
            add_finding(
                findings, "PBIP Metadata", "WARNING",
                "Upload the complete PBIP project ZIP, not only the entry file",
                name
            )

    elif suffix == ".pbix":
        inspect_pbix(upload, findings)

    else:
        add_finding(
            findings, "Upload", "WARNING",
            "Unsupported file type", name
        )
