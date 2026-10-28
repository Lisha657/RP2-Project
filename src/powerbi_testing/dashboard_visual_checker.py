
import argparse
import json
import os
from itertools import combinations
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

DECORATIVE_TYPES = {"shape", "image", "textbox", "visualgroup"}

MIN_OVERLAP_RATIO = 0.15
WARNING_OVERLAP_RATIO = 0.30


def load_json(file_path):
    """Load a JSON object safely."""
    try:
        with open(file_path, "r", encoding="utf-8-sig") as file:
            value = json.load(file)
        return value if isinstance(value, dict) else None
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None


def discover_report_directories(project_path):
    """Find report folders recursively, supporting PBIR and pbi-tools."""
    project_path = Path(project_path).expanduser()

    if not project_path.exists():
        return []

    if project_path.is_file():
        if project_path.suffix.casefold() == ".pbix":
            return []
        root = project_path.parent
    else:
        root = project_path

    reports = []

    def is_report_directory(path):
        return (
            path.name.casefold().endswith(".report")
            or (path / "sections").is_dir()
            or (path / "definition" / "pages").is_dir()
        )

    if root.is_dir() and is_report_directory(root):
        reports.append(root)

    if root.is_dir():
        for current, dirs, _ in os.walk(root):
            dirs[:] = [
                name
                for name in dirs
                if name.casefold() not in SKIP_DIRECTORIES
            ]

            current_path = Path(current)

            if current_path != root and is_report_directory(current_path):
                reports.append(current_path)
                dirs[:] = []

    unique_reports = {
        str(path.resolve()): path for path in reports
    }

    return [
        unique_reports[key]
        for key in sorted(unique_reports, key=str.casefold)
    ]


def get_bounds(rect):
    """Convert a rectangle to left, top, right and bottom coordinates."""
    if not isinstance(rect, dict):
        return None

    try:
        x = float(rect["x"])
        y = float(rect["y"])
        width = float(rect["width"])
        height = float(rect["height"])

        if not all(map(
            lambda value: value == value
            and abs(value) != float("inf"),
            (x, y, width, height),
        )):
            return None

        if width <= 0 or height <= 0:
            return None

        return x, y, x + width, y + height

    except (KeyError, TypeError, ValueError, OverflowError):
        return None


def overlap_metrics(a, b, tolerance=2):
    """Calculate overlap area and ratio relative to the smaller visual."""
    first = get_bounds(a)
    second = get_bounds(b)

    if not first or not second:
        return None

    ax1, ay1, ax2, ay2 = first
    bx1, by1, bx2, by2 = second

    width = min(ax2, bx2) - max(ax1, bx1)
    height = min(ay2, by2) - max(ay1, by1)

    if width <= tolerance or height <= tolerance:
        return None

    area = width * height
    smaller = min(
        (ax2 - ax1) * (ay2 - ay1),
        (bx2 - bx1) * (by2 - by1),
    )

    if smaller <= 0:
        return None

    return {
        "area": area,
        "ratio": min(1.0, area / smaller),
    }


def identify_report_pages(report_dir):
    """Return (page name, page path, layout type) tuples."""
    pages = []

    modern = report_dir / "definition" / "pages"
    extracted = report_dir / "sections"

    if modern.is_dir():
        for page in sorted(modern.iterdir(), key=lambda p: p.name.casefold()):
            if page.is_dir():
                pages.append((page.name, page, "pbir"))

    if extracted.is_dir():
        for page in sorted(
            extracted.iterdir(), key=lambda p: p.name.casefold()
        ):
            if page.is_dir():
                pages.append((page.name, page, "pbi-tools"))

    return pages


def discover_visual_files(page_path, layout):
    """Find visual definition files for supported report formats."""
    if layout == "pbir":
        visual_root = page_path / "visuals"
        if not visual_root.is_dir():
            return []

        return sorted(
            visual_root.glob("*/visual.json"),
            key=lambda path: str(path).casefold(),
        )

    visual_root = page_path / "visualContainers"
    if not visual_root.is_dir():
        return []

    return sorted(
        visual_root.glob("*/config.json"),
        key=lambda path: str(path).casefold(),
    )


def extract_visual_metadata(file_path, layout):
    """Extract visual type, position and layer order."""
    data = load_json(file_path)

    if not isinstance(data, dict):
        return None

    if layout == "pbir":
        position = data.get("position", {})
        visual_info = data.get("visual", {})

        if not isinstance(visual_info, dict):
            visual_info = {}

        visual_type = (
            "visualGroup"
            if data.get("visualGroup")
            else str(visual_info.get("visualType", "unknown"))
        )
    else:
        visual_info = data.get("singleVisual", {})

        if not isinstance(visual_info, dict):
            visual_info = {}

        visual_type = str(visual_info.get("visualType", "unknown"))
        position = {}

        position_file = file_path.parent / "visualContainer.json"
        if position_file.is_file():
            position_data = load_json(position_file)
            if isinstance(position_data, dict):
                position = position_data

        if not position:
            layouts = data.get("layouts", [])
            if isinstance(layouts, list) and layouts:
                first_layout = layouts[0]
                if isinstance(first_layout, dict):
                    position = first_layout.get("position", {})

    if not isinstance(position, dict):
        position = {}

    rect = None
    z_order = 0

    try:
        candidate = {
            "x": float(position["x"]),
            "y": float(position["y"]),
            "width": float(position["width"]),
            "height": float(position["height"]),
        }

        if get_bounds(candidate) is not None:
            rect = candidate

        z_order = float(position.get("z", 0))
    except (KeyError, TypeError, ValueError, OverflowError):
        pass

    return {
        "id": file_path.parent.name,
        "file": str(file_path),
        "type": visual_type,
        "rect": rect,
        "z": z_order,
    }


def make_result(
    status,
    pages_checked,
    visuals_checked,
    overlap_pairs_checked,
    intentional_overlap_pairs_skipped,
    positions_checked,
    visual_types,
    findings,
):
    """Build the structured JSON result."""
    return {
        "status": status,
        "pages_checked": pages_checked,
        "visuals_checked": visuals_checked,
        "positions_checked": positions_checked,
        "overlap_pairs_checked": overlap_pairs_checked,
        "intentional_overlap_pairs_skipped": (
            intentional_overlap_pairs_skipped
        ),
        "findings_count": len(findings),
        "errors": sum(item["severity"] == "ERROR" for item in findings),
        "warnings": sum(item["severity"] == "WARNING" for item in findings),
        "info": sum(item["severity"] == "INFO" for item in findings),
        "visual_types": visual_types,
        "findings": findings,
    }


def check_dashboard_visuals(project_path):
    """Inspect report pages and identify potential visual overlaps."""
    project_path = Path(project_path).expanduser()

    findings = []
    visual_types = {}

    pages_checked = 0
    visuals_checked = 0
    positions_checked = 0
    overlap_pairs_checked = 0
    intentional_overlap_pairs_skipped = 0

    def finding(severity, kind, message, **extra):
        findings.append({
            "severity": severity,
            "type": kind,
            "message": message,
            "source": "dashboard_visual",
            "check": "dashboard_visual_testing",
            "status": severity,
            **extra,
        })

    if not project_path.exists():
        finding(
            "INFO",
            "project_path_not_found",
            "The supplied project path does not exist.",
            file=str(project_path),
        )
        return make_result(
            "NOT_TESTED", pages_checked, visuals_checked,
            overlap_pairs_checked, intentional_overlap_pairs_skipped,
            positions_checked, visual_types, findings,
        )

    report_dirs = discover_report_directories(project_path)

    if not report_dirs:
        finding(
            "INFO",
            "report_visuals_unavailable",
            "No extracted report definition was found. "
            "PBIX files must be extracted before visual metadata "
            "can be inspected.",
            file=str(project_path),
        )
        return make_result(
            "NOT_TESTED", pages_checked, visuals_checked,
            overlap_pairs_checked, intentional_overlap_pairs_skipped,
            positions_checked, visual_types, findings,
        )

    for report_dir in report_dirs:
        pages = identify_report_pages(report_dir)

        if not pages:
            finding(
                "INFO",
                "pages_folder_missing",
                "No supported report page structure was found.",
                report=report_dir.name,
                file=str(report_dir),
            )
            continue

        for page_name, page_path, layout in pages:
            pages_checked += 1
            page_label = f"{report_dir.name} / {page_name}"

            visual_files = discover_visual_files(page_path, layout)

            if not visual_files:
                finding(
                    "INFO",
                    "visual_metadata_unavailable",
                    "No supported visual definition files were found.",
                    page=page_label,
                    file=str(page_path),
                )
                continue

            page_visuals = []

            for visual_file in visual_files:
                visual = extract_visual_metadata(visual_file, layout)

                if visual is None:
                    finding(
                        "INFO",
                        "visual_json_unreadable",
                        "The visual definition was not a readable JSON object.",
                        page=page_label,
                        file=str(visual_file),
                    )
                    continue

                visuals_checked += 1
                visual_type = visual["type"]
                visual_types[visual_type] = (
                    visual_types.get(visual_type, 0) + 1
                )

                if visual["rect"] is None:
                    finding(
                        "INFO",
                        "position_unavailable",
                        "Visual metadata was found, but its position "
                        "could not be recognized. Overlap testing "
                        "was skipped for this visual.",
                        page=page_label,
                        visual=visual["id"],
                        file=str(visual_file),
                    )
                    continue

                positions_checked += 1
                page_visuals.append(visual)

            for first, second in combinations(page_visuals, 2):
                metrics = overlap_metrics(first["rect"], second["rect"])

                if not metrics:
                    continue

                first_type = first["type"].casefold()
                second_type = second["type"].casefold()

                # Count geometric overlaps, including those skipped below.
                overlap_pairs_checked += 1

                # Skip likely decorative/group overlays.
                if (
                    first_type in DECORATIVE_TYPES
                    or second_type in DECORATIVE_TYPES
                ):
                    intentional_overlap_pairs_skipped += 1
                    continue

                # Tiny overlaps are unlikely to affect readability.
                if metrics["ratio"] < MIN_OVERLAP_RATIO:
                    continue

                # Layer order helps reviewers understand the overlap.
                severity = (
                    "WARNING"
                    if metrics["ratio"] >= WARNING_OVERLAP_RATIO
                    else "INFO"
                )

                finding(
                    severity,
                    "possible_overlap",
                    "Overlapping visual bounds detected. "
                    "Review in Power BI to determine whether the overlap "
                    "is intentional or affects readability.",
                    report=report_dir.name,
                    page=page_label,
                    visual_a=first["id"],
                    visual_b=second["id"],
                    visual_a_type=first["type"],
                    visual_b_type=second["type"],
                    z_order_a=first["z"],
                    z_order_b=second["z"],
                    file_a=first["file"],
                    file_b=second["file"],
                    overlap_area=round(metrics["area"], 2),
                    overlap_ratio=round(metrics["ratio"], 4),
                )

    if any(item["severity"] == "ERROR" for item in findings):
        status = "FAIL"
    elif any(item["severity"] == "WARNING" for item in findings):
        status = "WARNING"
    elif pages_checked == 0 or visuals_checked == 0:
        status = "NOT_TESTED"
    elif positions_checked == 0:
        status = "PARTIAL"
    else:
        status = "PASS"

    return make_result(
        status,
        pages_checked,
        visuals_checked,
        overlap_pairs_checked,
        intentional_overlap_pairs_skipped,
        positions_checked,
        visual_types,
        findings,
    )


def main():
    parser = argparse.ArgumentParser(
        description="Check Power BI report visual metadata."
    )
    parser.add_argument(
        "--project-path",
        required=True,
        help="Path to an extracted report or project directory.",
    )
    parser.add_argument(
        "--output",
        default="reports/dashboard_visual_results.json",
        help="Path for the output JSON report.",
    )

    args = parser.parse_args()
    result = check_dashboard_visuals(args.project_path)

    output_path = Path(args.output).expanduser()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(result, indent=2),
        encoding="utf-8",
    )

    print("Power BI Dashboard Visual Check")
    print("=" * 40)
    print(f"Status: {result['status']}")
    print(f"Pages checked: {result['pages_checked']}")
    print(f"Visual metadata files checked: {result['visuals_checked']}")
    print(f"Positions checked: {result['positions_checked']}")
    print(f"Geometric overlap pairs checked: {result['overlap_pairs_checked']}")
    print(
        "Decorative overlap pairs skipped: "
        f"{result['intentional_overlap_pairs_skipped']}"
    )
    print(f"Findings: {result['findings_count']}")
    print(f"Errors: {result['errors']}")
    print(f"Warnings: {result['warnings']}")
    print(f"Info: {result['info']}")
    print(f"\nJSON report saved to: {output_path.resolve()}")


if __name__ == "__main__":
    main()
