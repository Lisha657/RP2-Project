import requests
import streamlit as st


def github_repo_files(github_url):
    parts = github_url.rstrip("/").split("/")

    if len(parts) < 5 or parts[2].lower() != "github.com":
        raise ValueError(
            "Enter a URL like https://github.com/owner/repository"
        )

    owner, repo = parts[3], parts[4].removesuffix(".git")

    response = requests.get(
        f"https://api.github.com/repos/{owner}/{repo}",
        timeout=20,
    )
    response.raise_for_status()

    branch = response.json()["default_branch"]

    tree_url = (
        f"https://api.github.com/repos/{owner}/{repo}"
        f"/git/trees/{branch}?recursive=1"
    )

    tree_response = requests.get(tree_url, timeout=30)
    tree_response.raise_for_status()

    data = tree_response.json()

    if data.get("truncated"):
        st.warning("GitHub returned a partial file list.")

    return owner, repo, branch, data.get("tree", [])
