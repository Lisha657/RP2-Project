import re
from pathlib import Path
from urllib.parse import urlparse

import requests


MAX_FILE_SIZE = 5 * 1024 * 1024
REQUEST_TIMEOUT = 20


def parse_github_url(repo_url):
    """Extract and validate the owner and repository name."""
    if not isinstance(repo_url, str) or not repo_url.strip():
        raise ValueError("Please provide a GitHub repository URL.")

    parsed_url = urlparse(repo_url.strip())

    if parsed_url.scheme not in {"https", "http"}:
        raise ValueError("The URL must start with https:// or http://.")

    if parsed_url.hostname not in {"github.com", "www.github.com"}:
        raise ValueError("Please provide a valid GitHub repository URL.")

    parts = parsed_url.path.strip("/").split("/")

    if len(parts) != 2 or not all(parts):
        raise ValueError(
            "The URL must contain only the owner and repository name."
        )

    owner, repo = parts

    if repo.endswith(".git"):
        repo = repo[:-4]

    if not re.fullmatch(r"[A-Za-z0-9-]+", owner):
        raise ValueError("Invalid GitHub repository owner.")

    if not re.fullmatch(r"[A-Za-z0-9_.-]+", repo):
        raise ValueError("Invalid GitHub repository name.")

    return owner, repo


def fetch_repository_files(repo_url, output_dir="downloaded_repo"):
    """Download CSV and SQL files from a public GitHub repository."""
    owner, repo = parse_github_url(repo_url)

    api_url = (
        f"https://api.github.com/repos/{owner}/{repo}/git/trees/HEAD"
        "?recursive=1"
    )

    try:
        response = requests.get(
            api_url,
            headers={"Accept": "application/vnd.github+json"},
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        tree = response.json().get("tree", [])

    except requests.exceptions.Timeout as exc:
        raise RuntimeError("GitHub request timed out. Try again.") from exc

    except requests.exceptions.HTTPError as exc:
        status_code = exc.response.status_code if exc.response else None

        if status_code == 404:
            raise RuntimeError(
                "Repository not found or inaccessible. "
                "Check the URL and ensure the repository is public."
            ) from exc

        if status_code == 403:
            raise RuntimeError(
                "GitHub access was denied or the API rate limit was reached."
            ) from exc

        raise RuntimeError(
            f"GitHub API returned an HTTP error: {status_code}."
        ) from exc

    except requests.exceptions.RequestException as exc:
        raise RuntimeError(
            "Could not connect to GitHub. Check your internet connection."
        ) from exc

    except ValueError as exc:
        raise RuntimeError("GitHub returned an invalid JSON response.") from exc

    output_path = Path(output_dir).resolve()
    output_path.mkdir(parents=True, exist_ok=True)

    downloaded_files = []

    for item in tree:
        if item.get("type") != "blob":
            continue

        file_path = item.get("path", "")
        relative_path = Path(file_path)

        if relative_path.suffix.lower() not in {".csv", ".sql"}:
            continue

        if item.get("size", 0) > MAX_FILE_SIZE:
            continue

        safe_path = (output_path / relative_path).resolve()

        if output_path not in safe_path.parents:
            continue

        download_url = (
            f"https://raw.githubusercontent.com/"
            f"{owner}/{repo}/HEAD/{file_path}"
        )

        try:
            file_response = requests.get(
                download_url,
                timeout=REQUEST_TIMEOUT,
            )
            file_response.raise_for_status()

        except requests.exceptions.RequestException as exc:
            raise RuntimeError(
                f"Failed to download repository file: {file_path}"
            ) from exc

        safe_path.parent.mkdir(parents=True, exist_ok=True)
        safe_path.write_bytes(file_response.content)
        downloaded_files.append(str(safe_path))

    return downloaded_files

def fetch_dataset_url(dataset_url, output_dir="downloaded_repo"):
    """Download a public CSV dataset from a direct URL."""

    from urllib.parse import urlparse, unquote
    import re

    if not isinstance(dataset_url, str) or not dataset_url.strip():
        raise ValueError("Please provide a dataset URL.")

    parsed_url = urlparse(dataset_url.strip())

    if parsed_url.scheme not in {"https", "http"}:
        raise ValueError("The dataset URL must start with http:// or https://.")

    if not parsed_url.hostname:
        raise ValueError("Please provide a valid dataset URL.")

    if parsed_url.username or parsed_url.password:
        raise ValueError("URLs containing embedded credentials are not supported.")

    filename = unquote(parsed_url.path.split("/")[-1])

    if not filename.lower().endswith(".csv"):
        raise ValueError("Please provide a direct URL to a CSV file.")

    # Keep the filename safe for saving locally.
    filename = re.sub(r"[^A-Za-z0-9._-]", "_", filename)

    if filename in {"", ".", ".."}:
        raise ValueError("Could not determine the dataset filename.")

    output_path = Path(output_dir).resolve()
    output_path.mkdir(parents=True, exist_ok=True)

    destination = output_path / filename

    try:
        response = requests.get(
            dataset_url.strip(),
            timeout=REQUEST_TIMEOUT,
            stream=True,
            allow_redirects=True,
        )
        response.raise_for_status()

        final_url = urlparse(response.url)

        if final_url.scheme not in {"https", "http"}:
            raise ValueError("The download redirected to an unsupported URL.")

        content_length = response.headers.get("Content-Length")

        if content_length and int(content_length) > MAX_FILE_SIZE:
            raise ValueError("The dataset exceeds the 5 MB download limit.")

        total_size = 0

        with destination.open("wb") as file:
            for chunk in response.iter_content(chunk_size=8192):
                if not chunk:
                    continue

                total_size += len(chunk)

                if total_size > MAX_FILE_SIZE:
                    raise ValueError("The dataset exceeds the 5 MB download limit.")

                file.write(chunk)

        if total_size == 0:
            destination.unlink(missing_ok=True)
            raise ValueError("The downloaded dataset is empty.")

        # Verify that the downloaded file can be read as a CSV.
        import pandas as pd

        try:
            pd.read_csv(destination, nrows=5)
        except (pd.errors.ParserError, UnicodeDecodeError, ValueError) as exc:
            destination.unlink(missing_ok=True)
            raise ValueError("The URL did not return a readable CSV dataset.") from exc

        return str(destination)

    except requests.exceptions.Timeout as exc:
        destination.unlink(missing_ok=True)
        raise RuntimeError("The dataset download timed out.") from exc

    except requests.exceptions.HTTPError as exc:
        destination.unlink(missing_ok=True)
        status = exc.response.status_code if exc.response is not None else "unknown"
        raise RuntimeError(f"Dataset download failed with HTTP status {status}.") from exc

    except requests.exceptions.RequestException as exc:
        destination.unlink(missing_ok=True)
        raise RuntimeError("Could not download the dataset. Check the URL and connection.") from exc

    except (OSError, ValueError):
        destination.unlink(missing_ok=True)
        raise
def fetch_sql_url(sql_url, output_dir="downloaded_repo"):
    """Download a public SQL file from a direct URL."""

    if not isinstance(sql_url, str) or not sql_url.strip():
        raise ValueError("Please provide a SQL file URL.")

    parsed_url = urlparse(sql_url.strip())

    if parsed_url.scheme not in {"https", "http"}:
        raise ValueError("The SQL URL must start with http:// or https://.")

    if parsed_url.hostname not in {"github.com", "www.github.com",
                                   "raw.githubusercontent.com"}:
        raise ValueError(
            "Please provide a direct SQL file URL from GitHub."
        )

    if parsed_url.username or parsed_url.password:
        raise ValueError("URLs containing credentials are not supported.")

    filename = Path(parsed_url.path).name

    if not filename.lower().endswith(".sql"):
        raise ValueError("The URL must point directly to a .sql file.")

    filename = re.sub(r"[^A-Za-z0-9._-]", "_", filename)

    output_path = Path(output_dir).resolve()
    output_path.mkdir(parents=True, exist_ok=True)
    destination = output_path / filename

    try:
        with requests.get(
            sql_url.strip(),
            timeout=REQUEST_TIMEOUT,
            stream=True,
        ) as response:
            response.raise_for_status()

            content_length = response.headers.get("Content-Length")
            if content_length and int(content_length) > MAX_FILE_SIZE:
                raise ValueError("The SQL file exceeds the 5 MB limit.")

            total_size = 0

            with destination.open("wb") as file:
                for chunk in response.iter_content(chunk_size=8192):
                    if not chunk:
                        continue

                    total_size += len(chunk)

                    if total_size > MAX_FILE_SIZE:
                        raise ValueError("The SQL file exceeds the 5 MB limit.")

                    file.write(chunk)

        if total_size == 0:
            raise ValueError("The downloaded SQL file is empty.")

        return str(destination)

    except requests.exceptions.Timeout as exc:
        destination.unlink(missing_ok=True)
        raise RuntimeError("The SQL download timed out.") from exc

    except requests.exceptions.HTTPError as exc:
        destination.unlink(missing_ok=True)
        status = exc.response.status_code if exc.response is not None else "unknown"
        raise RuntimeError(
            f"SQL download failed with HTTP status {status}."
        ) from exc

    except requests.exceptions.RequestException as exc:
        destination.unlink(missing_ok=True)
        raise RuntimeError("Could not download the SQL file.") from exc

    except (OSError, ValueError):
        destination.unlink(missing_ok=True)
        raise