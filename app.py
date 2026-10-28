import json
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse

import streamlit as st


# ============================================================
# 1. PROJECT CONFIGURATION
# ============================================================

BASE_DIR = Path(__file__).resolve().parent
MAIN_FILE = BASE_DIR / "src" / "main.py"

REPORT_DIR = BASE_DIR / "reports"
JSON_REPORT = REPORT_DIR / "pbip_check_results.json"
MARKDOWN_REPORT = REPORT_DIR / "testing_summary.md"

PROCESS_TIMEOUT = 1800


# ============================================================
# 2. PAGE CONFIGURATION
# ============================================================

st.set_page_config(
    page_title="Power BI Dashboard Testing Agent",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="collapsed",
)


# ============================================================
# 3. CSS
# ============================================================

st.markdown(
    """
    <style>
    [data-testid="stSidebar"], [data-testid="collapsedControl"] {
        display: none;
    }
    .stApp {
        background-color: #F3F6FA;
        color: #172033;
    }
    .main .block-container {
        max-width: 1250px;
        padding-top: 2rem;
        padding-bottom: 3rem;
    }
    .stApp h1, .stApp h2, .stApp h3, .stApp h4 {
        color: #172033;
    }
    .stApp p, .stApp li, .stApp label {
        color: #263449;
    }
    .stTextInput input {
        background-color: #FFFFFF !important;
        color: #172033 !important;
        border: 1px solid #9AA8BB !important;
        border-radius: 8px !important;
    }
    .stButton > button, .stFormSubmitButton > button,
    .stDownloadButton > button {
        background-color: #155EEF;
        color: #FFFFFF !important;
        border: 1px solid #155EEF;
        border-radius: 8px;
        font-weight: 600;
        min-height: 42px;
    }
    .stButton > button:hover, .stFormSubmitButton > button:hover,
    .stDownloadButton > button:hover {
        background-color: #1248C5;
        border-color: #1248C5;
        color: #FFFFFF !important;
    }
    [data-testid="stMetric"] {
        background-color: #FFFFFF;
        border: 1px solid #D5DDE8;
        border-radius: 10px;
        padding: 16px;
    }
    [data-testid="stMetricLabel"] { color: #475569 !important; }
    [data-testid="stMetricValue"] { color: #172033 !important; }
    [data-testid="stExpander"] {
        background-color: #FFFFFF;
        border: 1px solid #D5DDE8;
        border-radius: 8px;
    }
    .result-card {
        background-color: #FFFFFF;
        border: 1px solid #D5DDE8;
        border-radius: 12px;
        padding: 20px;
        margin: 10px 0;
    }
    .status-badge {
        display: inline-block;
        padding: 7px 14px;
        border-radius: 6px;
        font-weight: 700;
        font-size: 14px;
    }
    .status-pass { background-color: #DCFCE7; color: #166534; }
    .status-fail { background-color: #FEE2E2; color: #991B1B; }
    .status-warning { background-color: #FEF3C7; color: #92400E; }
    .status-other { background-color: #E2E8F0; color: #334155; }
    hr { border-color: #D5DDE8; }
    </style>
    """,
    unsafe_allow_html=True,
)


# ============================================================
# 4. SESSION STATE
# ============================================================

DEFAULT_STATE = {
    "page": "Home",
    "repo_url": "",
    "process_logs": "",
    "process_exit_code": None,
    "execution_error": "",
}

for key, value in DEFAULT_STATE.items():
    if key not in st.session_state:
        st.session_state[key] = value


# ============================================================
# 5. HELPER FUNCTIONS
# ============================================================

def validate_github_url(url):
    """Validate a GitHub repository URL."""
    url = url.strip()

    if not url:
        return False, "Please enter a GitHub repository URL."

    if any(char.isspace() for char in url):
        return False, "The URL must not contain spaces."

    parsed = urlparse(url)

    if parsed.scheme not in ("https", "http"):
        return False, "The URL must start with https:// or http://."

    if parsed.netloc.lower() not in ("github.com", "www.github.com"):
        return False, "Please enter a URL from github.com."

    parts = [part for part in parsed.path.strip("/").split("/") if part]

    if len(parts) < 2:
        return False, (
            "Enter a repository URL, for example "
            "https://github.com/owner/repository"
        )

    if parts[0].lower() in {
        "settings", "features", "topics", "marketplace",
    }:
        return False, "Please enter a GitHub repository URL."

    return True, ""


def reset_results():
    """Remove old final reports so they cannot be mistaken for new ones."""
    REPORT_DIR.mkdir(parents=True, exist_ok=True)

    for path in (JSON_REPORT, MARKDOWN_REPORT):
        try:
            if path.exists():
                path.unlink()
        except OSError as exc:
            st.session_state.process_logs += (
                f"\nWarning: could not remove old report {path}: {exc}\n"
            )


def load_json_report():
    """Load the latest JSON report."""
    if not JSON_REPORT.is_file():
        return None

    try:
        with JSON_REPORT.open("r", encoding="utf-8") as file:
            report = json.load(file)
        return report if isinstance(report, dict) else None
    except (OSError, json.JSONDecodeError):
        return None


def load_markdown_report():
    """Load the Markdown report, if it exists."""
    if not MARKDOWN_REPORT.is_file():
        return None

    try:
        return MARKDOWN_REPORT.read_text(encoding="utf-8")
    except OSError:
        return None


def first_available(data, keys, default=None):
    """Return the first non-empty dictionary value."""
    if not isinstance(data, dict):
        return default

    for key in keys:
        value = data.get(key)
        if value is not None and value != "":
            return value

    return default


def normalize_status(value):
    """Standardize status names."""
    if value is None:
        return "UNKNOWN"

    status = str(value).strip().upper().replace(" ", "_")

    aliases = {
        "SUCCESS": "PASS",
        "PASSED": "PASS",
        "OK": "PASS",
        "FAILED": "FAIL",
        "FAILURE": "FAIL",
        "ERROR": "FAIL",
        "WARN": "WARNING",
        "NOTTESTED": "NOT_TESTED",
        "NOT-TESTED": "NOT_TESTED",
        "N/A": "NOT_APPLICABLE",
    }

    return aliases.get(status, status)


def get_summary_dict(report):
    """Get the summary section from the report."""
    if not isinstance(report, dict):
        return {}

    for key in (
        "summary", "statistics", "stats", "totals", "overall_summary",
    ):
        value = report.get(key)
        if isinstance(value, dict):
            return value

    return {}


def collect_findings(report):
    """Extract findings from nested report data."""
    findings = []
    seen = set()

    status_keys = ("status", "result", "test_status", "severity_status")
    title_keys = (
        "title", "name", "check", "test_name", "rule", "check_name",
    )
    message_keys = (
        "message", "description", "details", "issue", "finding",
        "error", "reason",
    )
    recommendation_keys = (
        "recommendation", "suggestion", "recommended_action",
        "fix", "solution", "remediation",
    )

    def walk(node, path=""):
        if isinstance(node, dict):
            status = first_available(node, status_keys)
            title = first_available(node, title_keys)
            message = first_available(node, message_keys)

            path_lower = path.lower()
            is_aggregate = any(
                part in path_lower
                for part in ("summary", "statistics", "metadata")
            )

            if (
                status is not None
                and not is_aggregate
                and (title is not None or message is not None)
            ):
                normalized = normalize_status(status)

                item = {
                    "title": str(title or message or "Untitled finding"),
                    "status": normalized,
                    "message": str(message or title or "No details provided."),
                    "recommendation": str(
                        first_available(node, recommendation_keys, "")
                    ),
                    "category": str(
                        first_available(
                            node,
                            ("category", "module", "component", "test_type"),
                            "General",
                        )
                    ),
                    "path": path or "report",
                    "raw": node,
                }

                signature = (
                    item["title"], item["status"], item["message"],
                )
                if signature not in seen:
                    seen.add(signature)
                    findings.append(item)

            for key, value in node.items():
                child_path = f"{path}.{key}" if path else str(key)
                walk(value, child_path)

        elif isinstance(node, list):
            for index, item in enumerate(node):
                walk(item, f"{path}[{index}]")

    walk(report)
    return findings


def get_overall_status(report, findings):
    """Read overall status or infer it from findings."""
    summary = get_summary_dict(report)

    status = first_available(
        report,
        ("overall_status", "overall_result", "final_status", "test_status"),
    )

    if status is None:
        status = first_available(
            summary,
            ("overall_status", "overall_result", "final_status", "status"),
        )

    if status is None and isinstance(report, dict):
        status = report.get("status")

    if status is not None:
        return normalize_status(status)

    statuses = [item["status"] for item in findings]

    if "FAIL" in statuses:
        return "FAIL"
    if "WARNING" in statuses:
        return "WARNING"
    if "NOT_TESTED" in statuses:
        return "NOT_TESTED"
    if "PASS" in statuses:
        return "PASS"

    return "NOT_TESTED"


def get_summary_counts(report, findings):
    """Read summary counts, falling back to findings."""
    summary = get_summary_dict(report)
    if not summary and isinstance(report, dict):
        summary = report

    status_counts = {}
    for item in findings:
        status = item["status"]
        status_counts[status] = status_counts.get(status, 0) + 1

    def read_count(keys, fallback):
        value = first_available(summary, keys)
        if value is None:
            return fallback
        try:
            return int(value)
        except (ValueError, TypeError):
            return fallback

    return {
        "total": read_count(
            ("total_findings", "findings_count", "total_checks", "total_tests"),
            len(findings),
        ),
        "fail": read_count(
            ("fail", "fail_count", "failed", "failures", "total_failures"),
            status_counts.get("FAIL", 0),
        ),
        "warning": read_count(
            ("warning", "warning_count", "warnings", "total_warnings"),
            status_counts.get("WARNING", 0),
        ),
        "pass": read_count(
            ("pass", "pass_count", "passed", "passes", "total_passed"),
            status_counts.get("PASS", 0),
        ),
        "not_tested": read_count(
            ("not_tested", "not_tested_count", "untested"),
            status_counts.get("NOT_TESTED", 0),
        ),
    }


def status_class(status):
    """Return the CSS class for a status badge."""
    status = normalize_status(status)

    if status == "PASS":
        return "status-pass"
    if status == "FAIL":
        return "status-fail"
    if status == "WARNING":
        return "status-warning"

    return "status-other"


def make_markdown_report(report, findings, overall_status, counts):
    """Build a Markdown report if the engine did not create one."""
    lines = [
        "# Power BI Dashboard Testing Report",
        "",
        f"**Repository:** {st.session_state.repo_url}",
        f"**Overall Status:** {overall_status}",
        "",
        "## Summary",
        "",
        f"- Total findings/checks: {counts['total']}",
        f"- Failures: {counts['fail']}",
        f"- Warnings: {counts['warning']}",
        f"- Passed: {counts['pass']}",
        f"- Not tested: {counts['not_tested']}",
        "",
        "## Findings",
        "",
    ]

    if not findings:
        lines.append(
            "No individual findings could be extracted from the JSON report."
        )

    for index, item in enumerate(findings, start=1):
        lines.extend([
            f"### {index}. {item['title']}",
            "",
            f"- **Status:** {item['status']}",
            f"- **Category:** {item['category']}",
            f"- **Details:** {item['message']}",
        ])

        if item["recommendation"]:
            lines.append(
                f"- **Recommendation:** {item['recommendation']}"
            )

        lines.append("")

    lines.extend([
        "## Original JSON",
        "",
        "Download the JSON file for the complete structured results.",
        "",
    ])

    return "\n".join(lines)


# ============================================================
# 6. TESTING ENGINE EXECUTION
# ============================================================

def run_tests(repo_url):
    """Execute src.main and collect the resulting report and logs."""
    st.session_state.process_logs = ""
    st.session_state.process_exit_code = None
    st.session_state.execution_error = ""

    if not MAIN_FILE.is_file():
        st.session_state.execution_error = (
            f"Testing engine not found: {MAIN_FILE}"
        )
        return

    REPORT_DIR.mkdir(parents=True, exist_ok=True)

    # Remove old final reports to prevent stale results from being displayed.
    reset_results()

    command = [
        sys.executable,
        "-u",
        "-m",
        "src.main",
        "--github-url",
        repo_url,
    ]

    st.session_state.process_logs += (
        "Starting Power BI Dashboard Testing Agent...\n"
        f"Python executable: {sys.executable}\n"
        f"Working directory: {BASE_DIR}\n"
        f"Repository: {repo_url}\n"
        f"Command: {' '.join(command)}\n\n"
    )

    try:
        with st.spinner(
            "Testing in progress. Please wait; large repositories may take time..."
        ):
            completed = subprocess.run(
                command,
                cwd=str(BASE_DIR),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=PROCESS_TIMEOUT,
                check=False,
            )

        stdout = completed.stdout or ""
        stderr = completed.stderr or ""

        st.session_state.process_logs += stdout

        if stderr.strip():
            st.session_state.process_logs += (
                "\n\n--- STDERR ---\n" + stderr
            )

        st.session_state.process_exit_code = completed.returncode

        # Check the actual report regardless of the process exit code.
        report = load_json_report()

        if report is None:
            message = (
                "The testing process finished, but a valid JSON report "
                f"was not found at:\n{JSON_REPORT}"
            )

            if completed.returncode != 0:
                message = (
                    f"The testing engine exited with code "
                    f"{completed.returncode}.\n{message}"
                )

            st.session_state.execution_error = message

            if not stdout.strip() and not stderr.strip():
                st.session_state.process_logs += (
                    "\nNo output was captured from the testing process."
                )

        elif completed.returncode != 0:
            st.session_state.execution_error = (
                f"The testing engine exited with code "
                f"{completed.returncode}, but a JSON report was generated. "
                "Review the logs before relying on the results."
            )

    except subprocess.TimeoutExpired as exc:
        st.session_state.execution_error = (
            f"Testing exceeded the {PROCESS_TIMEOUT}-second timeout."
        )

        partial_stdout = exc.stdout or ""
        partial_stderr = exc.stderr or ""

        if isinstance(partial_stdout, bytes):
            partial_stdout = partial_stdout.decode(
                "utf-8", errors="replace"
            )
        if isinstance(partial_stderr, bytes):
            partial_stderr = partial_stderr.decode(
                "utf-8", errors="replace"
            )

        st.session_state.process_logs += (
            "\nERROR: Testing process timed out.\n"
            + str(partial_stdout)
            + "\n"
            + str(partial_stderr)
        )

    except OSError as exc:
        st.session_state.execution_error = (
            f"Could not start the testing process: {exc}"
        )
        st.session_state.process_logs += f"\nERROR: {exc}"


# ============================================================
# 7. HOME PAGE
# ============================================================

if st.session_state.page == "Home":
    st.title("AI-Powered Power BI Dashboard Testing Agent")

    st.write(
        "Analyse a Power BI project from a GitHub repository "
        "and generate a structured testing report."
    )

    st.divider()
    st.subheader("Start Testing")

    with st.form("repository_form"):
        repo_url = st.text_input(
            "GitHub Repository URL",
            placeholder="https://github.com/owner/repository",
            value=st.session_state.repo_url,
        )

        start_testing = st.form_submit_button(
            "🚀 Start Testing",
            use_container_width=True,
        )

    if start_testing:
        is_valid, message = validate_github_url(repo_url)

        if not is_valid:
            st.error(message)
        else:
            st.session_state.repo_url = repo_url.strip()
            run_tests(st.session_state.repo_url)
            st.session_state.page = "Testing Results"
            st.rerun()

    st.divider()
    st.subheader("Testing Capabilities")

    col1, col2, col3 = st.columns(3)

    with col1:
        st.markdown("### Data Quality")
        st.write(
            "Inspect datasets for missing values, duplicates, "
            "and other configured data-quality issues."
        )

    with col2:
        st.markdown("### Semantic Model")
        st.write(
            "Inspect available model metadata, relationships, "
            "measures, and potential DAX issues."
        )

    with col3:
        st.markdown("### Dashboard Validation")
        st.write(
            "Review configured KPI checks and other supported "
            "dashboard testing results."
        )

    st.info(
        "Available checks depend on repository contents and the "
        "capabilities implemented in the testing engine."
    )


# ============================================================
# 8. RESULTS PAGE
# ============================================================

elif st.session_state.page == "Testing Results":
    st.title("Power BI Testing Results")
    st.caption(f"Repository: {st.session_state.repo_url}")

    if st.button("← Test Another Repository"):
        st.session_state.page = "Home"
        st.rerun()

    st.divider()

    if st.session_state.execution_error:
        st.error(st.session_state.execution_error)

    report = load_json_report()

    if report is None:
        st.warning(
            "The testing report could not be loaded. "
            "Check the execution logs below for details."
        )

        if st.session_state.process_logs:
            with st.expander("View Execution Logs", expanded=True):
                st.code(st.session_state.process_logs, language="text")

        if st.session_state.process_exit_code is not None:
            st.write(
                f"Testing process exit code: "
                f"{st.session_state.process_exit_code}"
            )

    else:
        findings = collect_findings(report)
        overall_status = get_overall_status(report, findings)
        counts = get_summary_counts(report, findings)

        st.header("1. Overall Status")
        css_class = status_class(overall_status)

        st.markdown(
            f"""
            <div class="result-card">
                <p><strong>Final Testing Result</strong></p>
                <span class="status-badge {css_class}">
                    {overall_status}
                </span>
            </div>
            """,
            unsafe_allow_html=True,
        )

        if overall_status == "PASS":
            st.success("Testing completed with a PASS result.")
        elif overall_status == "FAIL":
            st.error(
                "The report indicates failed checks that need attention."
            )
        elif overall_status == "WARNING":
            st.warning("Some checks need attention. Review the findings.")
        else:
            st.info(
                "The result is not fully determined. Review findings "
                "and checks that were not tested."
            )

        st.divider()
        st.header("2. Summary")

        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("Total Findings / Checks", counts["total"])
        with col2:
            st.metric("Failures", counts["fail"])
        with col3:
            st.metric("Warnings", counts["warning"])

        col4, col5 = st.columns(2)
        with col4:
            st.metric("Passed", counts["pass"])
        with col5:
            st.metric("Not Tested", counts["not_tested"])

        st.divider()
        st.header("3. Findings")

        if not findings:
            st.info(
                "No individual findings could be extracted from the report. "
                "Download the JSON report for complete structured results."
            )
        else:
            statuses = [
                "ALL", "FAIL", "WARNING", "PASS", "NOT_TESTED",
                "NOT_APPLICABLE", "INFO", "UNKNOWN",
            ]

            selected_filter = st.selectbox(
                "Filter findings by status",
                statuses,
            )

            filtered_findings = [
                item for item in findings
                if selected_filter == "ALL"
                or item["status"] == selected_filter
            ]

            st.caption(
                f"Showing {len(filtered_findings)} of {len(findings)} findings."
            )

            for index, item in enumerate(filtered_findings, start=1):
                heading = f"{index}. {item['title']} — {item['status']}"

                with st.expander(heading):
                    badge_class = status_class(item["status"])

                    st.markdown(
                        f"""
                        <span class="status-badge {badge_class}">
                            {item['status']}
                        </span>
                        """,
                        unsafe_allow_html=True,
                    )

                    st.markdown("**Category / Module**")
                    st.write(item["category"])

                    st.markdown("**Details**")
                    st.write(item["message"])

                    if item["recommendation"]:
                        st.markdown("**Recommendation**")
                        st.write(item["recommendation"])

                    st.markdown("**Report Location**")
                    st.code(item["path"])

                    with st.expander("View Raw Finding"):
                        st.json(item["raw"])

        st.divider()
        st.header("4. Download Detailed Report")

        st.write(
            "Download the structured JSON report or readable Markdown report."
        )

        download_col1, download_col2 = st.columns(2)

        with download_col1:
            st.markdown("**JSON Report**")
            st.caption("Complete structured testing results.")

            st.download_button(
                label="⬇ Download JSON Report",
                data=json.dumps(report, indent=2, ensure_ascii=False),
                file_name="pbip_check_results.json",
                mime="application/json",
                use_container_width=True,
            )

        with download_col2:
            st.markdown("**Detailed Markdown Report**")
            st.caption("Readable status, summary, and findings.")

            markdown_report = load_markdown_report()
            if not markdown_report:
                markdown_report = make_markdown_report(
                    report, findings, overall_status, counts
                )

            st.download_button(
                label="⬇ Download Detailed Report",
                data=markdown_report,
                file_name="testing_summary.md",
                mime="text/markdown",
                use_container_width=True,
            )

        with st.expander("View Complete JSON Report"):
            st.json(report)

        if st.session_state.process_logs:
            with st.expander("View Execution Logs"):
                st.code(st.session_state.process_logs, language="text")


# ============================================================
# 9. FOOTER
# ============================================================

st.divider()
st.caption("AI-Powered Power BI Dashboard Testing Agent")
