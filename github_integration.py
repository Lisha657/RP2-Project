import re
from pathlib import Path
from urllib.parse import urlparse

import requests


def parse_github_url(repo_url):
    """Extract the owner and repository name from a GitHub URL."""
    parsed_url = urlparse(repo_url.strip())

    if parsed_url.hostname not in {"github.com", "www.github.com"}:
        raise ValueError("Please provide a valid GitHub repository URL.")

    parts = parsed_url.path.strip("/").split("/")

    if len(parts) < 2:
        raise ValueError("The URL must include the owner and repository name.")

    owner, repo = parts[0], parts[1]
    repo = re.sub(r"\.git$", "", repo)

    return owner, repo


def fetch_repository_files(repo_url, output_dir="downloaded_repo"):
    """Download CSV and SQL files from a public GitHub repository."""
    owner, repo = parse_github_url(repo_url)

    api_url = (
        f"https://api.github.com/repos/{owner}/{repo}/git/trees/HEAD"
        "?recursive=1"
    )

    response = requests.get(
        api_url,
        headers={"Accept": "application/vnd.github+json"},
        timeout=20,
    )
    response.raise_for_status()

    tree = response.json().get("tree", [])
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    downloaded_files = []

    for item in tree:
        if item.get("type") != "blob":
            continue

        file_path = item.get("path", "")

        if Path(file_path).suffix.lower() not in {".csv", ".sql"}:
            continue

        # Avoid downloading unusually large files.
        if item.get("size", 0) > 5 * 1024 * 1024:
            continue

        download_url = (
            f"https://raw.githubusercontent.com/"
            f"{owner}/{repo}/HEAD/{file_path}"
        )

        file_response = requests.get(download_url, timeout=20)
        file_response.raise_for_status()

        # Keep files inside the output directory.
        safe_path = (output_path / file_path).resolve()
        if output_path.resolve() not in safe_path.parents:
            continue

        safe_path.parent.mkdir(parents=True, exist_ok=True)
        safe_path.write_bytes(file_response.content)
        downloaded_files.append(str(safe_path))

    return downloaded_files