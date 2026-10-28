
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
}

FILE_TYPES = {
    "pbix_files": {".pbix"},
    "pbip_files": {".pbip"},
    "report_definitions": {".pbir"},
    "tmdl_files": {".tmdl"},
    "model_files": {".bim"},
    "report_files": {".rdl"},
    "json_files": {".json"},
    "csv_datasets": {".csv"},
    "excel_datasets": {".xlsx", ".xls", ".xlsm"},
    "sql_files": {".sql"},
    "power_query_files": {".m", ".pq"},
    "dax_files": {".dax"},
    "text_files": {".txt", ".md"},
}


def discover_files(project_path):
    """Discover supported artifacts and estimate available test capabilities."""
    root = Path(project_path).expanduser().resolve()

    if not root.exists() or not root.is_dir():
        raise ValueError(f"Project directory does not exist: {root}")

    inventory = {category: [] for category in FILE_TYPES}
    report_folders = []
    semantic_model_folders = []
    scan_errors = []

    def walk_error(error):
        scan_errors.append(str(error))

    for current, directories, filenames in __import__("os").walk(
        root, onerror=walk_error
    ):
        directories[:] = [
            name for name in directories
            if name.lower() not in SKIP_DIRECTORIES
        ]

        current_path = Path(current)

        if current_path.name.endswith(".Report"):
            report_folders.append(
                str(current_path.relative_to(root))
            )

        if current_path.name.endswith(".SemanticModel"):
            semantic_model_folders.append(
                str(current_path.relative_to(root))
            )

        for filename in filenames:
            path = current_path / filename
            extension = path.suffix.lower()

            relative_path = str(path.relative_to(root))

            for category, extensions in FILE_TYPES.items():
                if extension in extensions:
                    inventory[category].append(relative_path)

    for category in inventory:
        inventory[category].sort()

    report_folders.sort()
    semantic_model_folders.sort()

    pbix_available = bool(inventory["pbix_files"])
    pbip_available = bool(inventory["pbip_files"])
    tmdl_available = bool(inventory["tmdl_files"])
    report_metadata_available = bool(
        inventory["report_definitions"]
        or report_folders
    )

    capabilities = {
        "project_format_detection": True,
        "dataset_quality": bool(
            inventory["csv_datasets"] or inventory["excel_datasets"]
        ),
        "sql_static_checks": bool(inventory["sql_files"]),
        "semantic_model_inspection": tmdl_available or bool(
            inventory["model_files"]
        ),
        "dax_static_checks": tmdl_available or bool(
            inventory["dax_files"]
        ),
        "relationship_metadata_checks": tmdl_available or bool(
            inventory["model_files"]
        ),
        "report_metadata_inspection": report_metadata_available,
        "pbix_detected": pbix_available,
        "pbip_detected": pbip_available,
        "pbix_internal_extraction_available": False,
    }

    if pbip_available or tmdl_available:
        project_format = "PBIP_OR_TMDL"
    elif pbix_available:
        project_format = "PBIX"
    else:
        project_format = "UNKNOWN"

    return {
        "project_path": str(root),
        "project_format": project_format,
        "inventory": inventory,
        "report_folders": report_folders,
        "semantic_model_folders": semantic_model_folders,
        "capabilities": capabilities,
        "scan_errors": scan_errors,
        "summary": {
            "files_by_type": {
                category: len(paths)
                for category, paths in inventory.items()
            },
            "report_folders_found": len(report_folders),
            "semantic_model_folders_found": len(
                semantic_model_folders
            ),
            "scan_errors": len(scan_errors),
        },
    }


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Discover Power BI project files and test capabilities."
    )
    parser.add_argument(
        "--project-path",
        required=True,
        help="Path to a downloaded or extracted project directory",
    )
    parser.add_argument(
        "--output",
        help="Optional path for saving the inventory as JSON",
    )
    args = parser.parse_args()

    result = discover_files(args.project_path)
    output = json.dumps(result, indent=2)

    print(output)

    if args.output:
        output_path = Path(args.output).expanduser().resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(output, encoding="utf-8")
        print(f"\nInventory saved to: {output_path}")
