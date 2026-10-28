
import json
import subprocess
from pathlib import Path


DEFAULT_PBI_TOOLS = Path(r"C:\Tools\pbi-tools.exe")


def extract_pbix(pbix_path, pbi_tools_path=DEFAULT_PBI_TOOLS):
    """
    Extract a PBIX file with pbi-tools and locate its model files.

    Returns a dictionary describing extraction and discovered metadata.
    """
    pbix_path = Path(pbix_path).resolve()
    pbi_tools_path = Path(pbi_tools_path).resolve()

    result = {
        "pbix_path": str(pbix_path),
        "extraction_status": "NOT_TESTED",
        "extraction_directory": None,
        "model_directory": None,
        "tmdl_files": [],
        "measure_count": 0,
        "message": "",
    }

    if not pbix_path.is_file() or pbix_path.suffix.lower() != ".pbix":
        result["message"] = "The specified PBIX file does not exist."
        return result

    if not pbi_tools_path.is_file():
        result["message"] = (
            f"pbi-tools executable not found: {pbi_tools_path}"
        )
        return result

    # pbi-tools normally extracts into a folder named after the PBIX.
    extraction_directory = pbix_path.parent / pbix_path.stem
    result["extraction_directory"] = str(extraction_directory)

    try:
        completed = subprocess.run(
            [
                str(pbi_tools_path),
                "extract",
                str(pbix_path),
            ],
            capture_output=True,
            text=True,
            timeout=600,
            check=False,
        )

        if completed.returncode != 0:
            result["message"] = (
                "pbi-tools extraction failed. "
                f"Exit code: {completed.returncode}. "
                f"Details: {(completed.stderr or completed.stdout).strip()}"
            )
            return result

        if not extraction_directory.is_dir():
            result["message"] = (
                "Extraction command completed, but the expected "
                f"directory was not found: {extraction_directory}"
            )
            return result

        model_directory = extraction_directory / "Model"
        result["model_directory"] = (
            str(model_directory) if model_directory.is_dir() else None
        )

        tmdl_files = []

        if model_directory.is_dir():
            tmdl_files = sorted(
                model_directory.rglob("*.tmdl")
            )

        result["tmdl_files"] = [str(path) for path in tmdl_files]

        measure_count = 0

        for tmdl_file in tmdl_files:
            try:
                content = tmdl_file.read_text(encoding="utf-8-sig")
            except (OSError, UnicodeError):
                continue

            for line in content.splitlines():
                # Count TMDL measure declarations, not every reference
                # to a measure in another expression.
                if line.lstrip().startswith("measure "):
                    measure_count += 1

        result["measure_count"] = measure_count
        result["extraction_status"] = (
            "PASS" if model_directory.is_dir() else "PARTIAL"
        )

        result["message"] = (
            f"Extraction completed. Found {len(tmdl_files)} TMDL files "
            f"and {measure_count} measure declarations."
        )

        return result

    except subprocess.TimeoutExpired:
        result["message"] = (
            "PBIX extraction timed out after 600 seconds."
        )
        return result

    except OSError as exc:
        result["message"] = f"Could not run pbi-tools: {exc}"
        return result


def save_extraction_result(result, output_path):
    """Save extraction information as JSON."""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    output_path.write_text(
        json.dumps(result, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Extract PBIX model metadata using pbi-tools."
    )
    parser.add_argument("--pbix", required=True)
    parser.add_argument(
        "--pbi-tools",
        default=str(DEFAULT_PBI_TOOLS),
    )
    parser.add_argument(
        "--output",
        default="reports/pbix_extraction_results.json",
    )

    args = parser.parse_args()

    extraction = extract_pbix(
        args.pbix,
        args.pbi_tools,
    )

    save_extraction_result(extraction, args.output)

    print(f"Extraction status: {extraction['extraction_status']}")
    print(extraction["message"])
    print(f"TMDL files: {len(extraction['tmdl_files'])}")
    print(f"Measures found: {extraction['measure_count']}")
    print(f"Result saved to: {Path(args.output).resolve()}")

    if extraction["extraction_status"] != "PASS":
        raise SystemExit(1)
