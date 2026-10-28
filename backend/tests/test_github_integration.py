import unittest
import requests
import tempfile
from unittest.mock import Mock, patch

from github_integration import (
    parse_github_url,
    fetch_repository_files,
)


class TestGitHubURLParsing(unittest.TestCase):

    def test_valid_repository_url(self):
        owner, repo = parse_github_url(
            "https://github.com/Lisha657/RP2-Project"
        )
        self.assertEqual(owner, "Lisha657")
        self.assertEqual(repo, "RP2-Project")

    def test_repository_url_with_git_suffix(self):
        owner, repo = parse_github_url(
            "https://github.com/Lisha657/RP2-Project.git"
        )
        self.assertEqual(owner, "Lisha657")
        self.assertEqual(repo, "RP2-Project")

    def test_invalid_domain(self):
        with self.assertRaises(ValueError):
            parse_github_url("https://example.com/owner/repo")

    def test_incomplete_url(self):
        with self.assertRaises(ValueError):
            parse_github_url("https://github.com/Lisha657")


class TestGitHubFileRetrieval(unittest.TestCase):

    @patch("github_integration.requests.get")
    def test_downloads_csv_and_sql_files(self, mock_get):
        # Simulate the GitHub repository file listing.
        tree_response = Mock()
        tree_response.json.return_value = {
            "tree": [
                {
                    "path": "data/sales.csv",
                    "type": "blob",
                    "size": 30,
                },
                {
                    "path": "queries/check.sql",
                    "type": "blob",
                    "size": 20,
                },
                {
                    "path": "README.md",
                    "type": "blob",
                    "size": 100,
                },
            ]
        }
        tree_response.raise_for_status.return_value = None

        # Simulate downloading the CSV and SQL files.
        csv_response = Mock()
        csv_response.content = b"order_id,sales\n1,100\n"
        csv_response.raise_for_status.return_value = None

        sql_response = Mock()
        sql_response.content = b"SELECT * FROM orders;"
        sql_response.raise_for_status.return_value = None

        mock_get.side_effect = [
            tree_response,
            csv_response,
            sql_response,
        ]

        with self.subTest("temporary output directory"):
            import tempfile
            from pathlib import Path

            with tempfile.TemporaryDirectory() as temp_dir:
                files = fetch_repository_files(
                    "https://github.com/example/repo",
                    output_dir=temp_dir,
                )

                self.assertEqual(len(files), 2)
                self.assertTrue(
                    any(Path(file).suffix == ".csv" for file in files)
                )
                self.assertTrue(
                    any(Path(file).suffix == ".sql" for file in files)
                )


if __name__ == "__main__":
    unittest.main()

class TestGitHubErrorHandling(unittest.TestCase):

    @patch("github_integration.requests.get")
    def test_repository_not_found(self, mock_get):
        mock_response = Mock()
        mock_response.status_code = 404
        mock_response.raise_for_status.side_effect = (
            requests.exceptions.HTTPError(response=mock_response)
        )
        mock_get.return_value = mock_response

        with self.assertRaisesRegex(RuntimeError, "Repository not found"):
            fetch_repository_files("https://github.com/example/missing-repo")

    @patch("github_integration.requests.get")
    def test_network_failure(self, mock_get):
        mock_get.side_effect = requests.exceptions.ConnectionError()

        with self.assertRaisesRegex(RuntimeError, "Could not connect to GitHub"):
            fetch_repository_files("https://github.com/example/test-repo")

    @patch("github_integration.requests.get")
    def test_request_timeout(self, mock_get):
        mock_get.side_effect = requests.exceptions.Timeout()

        with self.assertRaisesRegex(RuntimeError, "timed out"):
            fetch_repository_files("https://github.com/example/test-repo")

    @patch("github_integration.requests.get")
    def test_repository_without_csv_or_sql(self, mock_get):
        mock_response = Mock()
        mock_response.raise_for_status.return_value = None
        mock_response.json.return_value = {
            "tree": [
                {"path": "README.md", "type": "blob", "size": 100},
                {"path": "src/main.py", "type": "blob", "size": 200},
            ]
        }
        mock_get.return_value = mock_response

        with tempfile.TemporaryDirectory() as temp_dir:
            files = fetch_repository_files(
                "https://github.com/example/test-repo",
                output_dir=temp_dir,
            )

        self.assertEqual(files, [])
        mock_get.assert_called_once()