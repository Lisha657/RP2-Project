import html
import json
import re
import subprocess
import sys
import time
from pathlib import Path

import streamlit as st

# ============================================================
# 1. PROJECT CONFIGURATION
# ============================================================

BASE_DIR = Path(__file__).resolve().parent
MAIN_FILE = BASE_DIR / "src" / "main.py"
REPORT_DIR = BASE_DIR / "reports"

JSON_REPORT = REPORT_DIR / "pbip_check_results.json"
MARKDOWN_REPORT = REPORT_DIR / "testing_summary.md"

st.set_page_config(
    page_title="Power BI Testing Agent",
    page_icon="ðŸ“Š",
    layout="wide",
    initial_sidebar_state="collapsed",
)


# ============================================================
# 2. HIGH-CONTRAST CSS
# ============================================================

st.markdown(
    """
    <style>
    .stApp {
        background-color: #F1F5F9;
        color: #172033;
    }

    .main .block-container {
        max-width: 1300px;
        padding-top: 2rem;
        padding-bottom: 3rem;
    }

    h1, h2, h3, h4, p, li, label,
    .stMarkdown, .stCaption {
        color: #172033;
    }

    h1 {
        font-weight: 800 !important;
    }

    .hero {
        background-color: #173B72;
        padding: 30px;
        border-radius: 16px;
        margin-bottom: 24px;
        border: 1px solid #102D58;
    }

    .hero h1 {
        color: #FFFFFF !important;
        margin: 0;
        font-size: 34px;
    }

    .hero p {
        color: #EAF2FF !important;
        font-size: 16px;
        margin-top: 10px;
        margin-bottom: 0;
    }

    .custom-card {
        background-color: #FFFFFF;
        padding: 22px;
        border: 1px solid #D5DFEC;
        border-radius: 14px;
        margin-bottom: 16px;
        box-shadow: 0 3px 10px rgba(30, 50, 80, 0.06);
    }

    .custom-card h3 {
        color: #173B72 !important;
        margin-top: 0;
    }

    .custom-card p {
        color: #334155 !important;
    }

    .status-pass {
        background-color: #DCFCE7;
        border: 2px solid #15803D;
        border-radius: 12px;
        padding: 20px;
        color: #14532D !important;
    }

    .status-warning {
        background-color: #FEF3C7;
        border: 2px solid #B45309;
        border-radius: 12px;
        padding: 20px;
        color: #78350F !important;
    }

    .status-fail {
        background-color: #FEE2E2;
        border: 2px solid #B91C1C;
        border-radius: 12px;
        padding: 20px;
        color: #7F1D1D !important;
    }

    .status-neutral {
        background-color: #E2E8F0;
        border: 2px solid #64748B;
        border-radius: 12px;
        padding: 20px;
        color: #1E293B !important;
    }

    .status-pass h2, .status-warning h2,
    .status-fail h2, .status-neutral h2 {
        color: inherit !important;
        margin-top: 0;
    }

    .stTextInput input {
        background-color: #FFFFFF !important;
        color: #111827 !important;
        border: 2px solid #CBD5E1 !important;
        border-radius: 8px !important;
    }

    .stTextInput input::placeholder {
        color: #64748B !important;
        opacity: 1 !important;
    }

    .stButton > button {
        background-color: #1D4ED8 !important;
        color: #FFFFFF !important;
        border: 1px solid #1D4ED8 !important;
        border-radius: 9px !important;
        font-weight: 700 !important;
        min-height: 44px;
    }

    .stButton > button:hover {
        background-color: #1E40AF !important;
        color: #FFFFFF !important;
        border-color: #1E40AF !important;
    }

    .stDownloadButton > button {
        background-color: #047857 !important;
        color: #FFFFFF !important;
        border: 1px solid #047857 !important;
        border-radius: 8px !important;
        font-weight: 700 !important;
    }

    [data-testid="stMetric"] {
        background-color: #FFFFFF;
        border: 1px solid #D5DFEC;
        border-radius: 12px;
        padding: 16px;
    }

    [data-testid="stMetricValue"] {
        color: #173B72 !important;
        font-weight: 800 !important;
    }

    [data-testid="stMetricLabel"] {
        color: #334155 !important;
    }

    [data-testid="stExpander"] {
        background-color: #FFFFFF !important;
        border: 1px solid #CBD5E1 !important;
        border-radius: 10px !important;
    }

    [data-testid="stExpander"] summary,
    [data-testid="stExpander"] summary p {
        color: #172033 !important;
    }

    [data-baseweb="select"] > div {
        background-color: #FFFFFF !important;
        color: #172033 !important;
        border-color: #CBD5E1 !important;
    }

    [data-testid="stProgressBar"] > div > div {
        background-color: #2563EB !important;
    }

    hr {
        border-color: #CBD5E1 !important;
    }

    .footer {
        text-align: center;
        color: #475569 !important;
        padding: 20px 0;
        font-size: 13px;
    }

    @media (max-width: 768px) {
        .hero {
            padding: 20px;
        }

        .hero h1 {
            font-size: 26px;
        }

        .main .block-container {
            padding-left: 1rem;
            padding-right: 1rem;
        }
    }
    </style>
    """,
    unsafe_allow_html=True,
)


# ============================================================
# 3. SESSION STATE
# ============================================================

DEFAULTS = {
    "page": "home",
    "repo_url": "",
    "report": None,
    "log": "",
    "exit_code": None,
    "inventory": None,
}

for key, value in DEFAULTS.items():
    if key not in st.session_state:
        st.session_state[key] = value


# ============================================================
# 4. GENERAL HELPER FUNCTIONS
# ============================================================

def valid_github_url(url):
    """Validate a standard public GitHub repository URL."""
    pattern = (
        r"^https://github\.com/"
        r"[A-Za-z0-9_.-]+/"
        r"[A-Za-z0-9_.-]+"
        r"(?:\.git)?/?$"
    )
    return bool(re.fullmatch(pattern, url.strip()))


def safe_text(value):
    """Escape text before inserting it into HTML."""
    return html.escape(str(value if value is not None else ""))


def load_json_report():
    """Load the JSON report generated by main.py."""
    if not JSON_REPORT.exists():
        return None

    try:
        with JSON_REPORT.open("r", encoding="utf-8") as file:
            return json.load(file)
    except (json.JSONDecodeError, OSError):
        return None


def get_value(item, *keys, default=""):
    """Get the first available value from a dictionary."""
    if not isinstance(item, dict):
        return default

    for key in keys:
        value = item.get(key)
        if value is not None and value != "":
            return value

    return default


def normalize_status(value):
    """Normalize report status labels."""
    value = str(value or "").strip().upper().replace("-", "_")

    if value in {"FAIL", "FAILED", "ERROR", "CRITICAL"}:
        return "FAIL"

    if value in {"WARNING", "WARN"}:
        return "WARNING"

    if value in {"NOT_TESTED", "NOT TESTED", "SKIPPED", "PARTIAL"}:
        return "NOT TESTED" if value != "PARTIAL" else "PARTIAL"

    if value in {"PASS", "PASSED", "SUCCESS"}:
        return "PASS"

    if value in {"INFO", "INFORMATIONAL"}:
        return "INFO"

    if value in {"NOT_APPLICABLE", "N/A"}:
        return "NOT APPLICABLE"

    return "UNKNOWN"


def find_findings(data):
    """Find a findings list in common report structures."""
    if isinstance(data, list):
        return data

    if not isinstance(data, dict):
        return []

    for key in ("findings", "issues", "results", "checks"):
        value = data.get(key)

        if isinstance(value, list):
            return value

        if isinstance(value, dict):
            nested = find_findings(value)
            if nested:
                return nested

    for value in data.values():
        if isinstance(value, dict):
            nested = find_findings(value)
            if nested:
                return nested

    return []


def finding_status(item):
    return normalize_status(
        get_value(
            item,
            "status",
            "severity",
            "result",
            "level",
            default="UNKNOWN",
        )
    )


def finding_title(item, index):
    return str(
        get_value(
            item,
            "title",
            "name",
            "check",
            "rule",
            "issue",
            "message",
            default=f"Finding {index}",
        )
    )


def get_overall_status(data, findings, exit_code):
    """Prefer the agent's reported status and preserve failures."""
    if isinstance(data, dict):
        for key in ("overall_status", "overall_result", "status"):
            value = data.get(key)
            if value:
                return normalize_status(value)

    statuses = [finding_status(item) for item in findings]

    if exit_code not in (0, None):
        return "FAIL"

    if "FAIL" in statuses:
        return "FAIL"

    if "WARNING" in statuses:
        return "WARNING"

    if "PARTIAL" in statuses:
        return "PARTIAL"

    if "NOT TESTED" in statuses or "UNKNOWN" in statuses:
        return "NOT TESTED"

    if statuses and all(
        status in ("PASS", "INFO", "NOT APPLICABLE")
        for status in statuses
    ):
        return "PASS"

    return "NOT TESTED"


def status_class(status):
    if status == "PASS":
        return "status-pass"
    if status in ("WARNING", "PARTIAL"):
        return "status-warning"
    if status == "FAIL":
        return "status-fail"
    return "status-neutral"


# ============================================================
# 5. REPOSITORY INVENTORY
# ============================================================

def parse_project_paths(log_text):
    """Read repository/project paths printed by main.py."""
    paths = {"repository": None, "project": None}

    for line in (log_text or "").splitlines():
        line = line.strip()

        if line.lower().startswith("repository location:"):
            paths["repository"] = Path(
                line.split(":", 1)[1].strip()
            )

        elif line.lower().startswith("project location:"):
            paths["project"] = Path(
                line.split(":", 1)[1].strip()
            )

    return paths


def build_repository_inventory(log_text):
    """
    Inventory the downloaded repository and selected Power BI project.

    The actual file system is used, rather than guessing file counts
    from report summary values.
    """
    paths = parse_project_paths(log_text)
    repo_path = paths["repository"]
    project_path = paths["project"]

    inventory = {
        "repository_path": str(repo_path) if repo_path else None,
        "project_path": str(project_path) if project_path else None,
        "repository_exists": bool(repo_path and repo_path.is_dir()),
        "project_exists": bool(project_path and project_path.is_dir()),
        "file_counts": {},
        "total_files": 0,
        "total_folders": 0,
        "project_files": [],
        "important_files": [],
        "warnings": [],
    }

    if not inventory["repository_exists"]:
        inventory["warnings"].append(
            "The repository path could not be identified from the logs."
        )
        return inventory

    excluded = {
        ".git",
        ".venv",
        "venv",
        "__pycache__",
        "node_modules",
        ".idea",
        ".pytest_cache",
    }

    file_counts = {}
    all_files = []
    important_files = []
    folder_count = 0

    try:
        for path in repo_path.rglob("*"):
            # Ignore generated/environment directories.
            relative_parts = path.relative_to(repo_path).parts

            if any(part.lower() in excluded for part in relative_parts):
                continue

            if path.is_dir():
                folder_count += 1
                continue

            if not path.is_file():
                continue

            all_files.append(path)

            extension = path.suffix.lower() or "[no extension]"
            file_counts[extension] = file_counts.get(extension, 0) + 1

            relative = str(path.relative_to(repo_path))
            name = path.name.lower()

            if (
                extension in {".pbix", ".pbip", ".tmdl", ".dax", ".sql"}
                or name in {
                    "model.bim",
                    "report.json",
                    "requirements.txt",
                    "readme.md",
                }
                or ".semanticmodel" in relative.lower()
                or ".report" in relative.lower()
            ):
                important_files.append(relative)

    except OSError as exc:
        inventory["warnings"].append(
            f"Some repository files could not be inspected: {exc}"
        )

    inventory["file_counts"] = dict(
        sorted(file_counts.items(), key=lambda item: item[0])
    )
    inventory["total_files"] = len(all_files)
    inventory["total_folders"] = folder_count
    inventory["important_files"] = sorted(important_files)[:500]

    if project_path and project_path.is_dir():
        project_files = []

        try:
            for path in project_path.rglob("*"):
                relative_parts = path.relative_to(project_path).parts

                if any(part.lower() in excluded for part in relative_parts):
                    continue

                if path.is_file():
                    project_files.append(
                        str(path.relative_to(project_path))
                    )

            inventory["project_files"] = sorted(project_files)[:1000]

        except OSError as exc:
            inventory["warnings"].append(
                f"Some project files could not be listed: {exc}"
            )

    return inventory


def find_report_value(data, wanted_keys):
    """Recursively locate a useful summary value in the JSON report."""
    if isinstance(data, dict):
        for key, value in data.items():
            if key.lower() in wanted_keys and value not in (None, ""):
                return value

        for value in data.values():
            found = find_report_value(value, wanted_keys)
            if found not in (None, ""):
                return found

    elif isinstance(data, list):
        for value in data:
            found = find_report_value(value, wanted_keys)
            if found not in (None, ""):
                return found

    return None


# ============================================================
# 6. RUN TESTS
# ============================================================

def run_tests(repo_url):
    """Run main.py and capture its console output."""
    REPORT_DIR.mkdir(parents=True, exist_ok=True)

    # Remove old reports so an unsuccessful run cannot display stale data.
    for report_file in (JSON_REPORT, MARKDOWN_REPORT):
        try:
            report_file.unlink(missing_ok=True)
        except OSError:
            pass

    command = [
        sys.executable,
        "-u",
        str(MAIN_FILE),
        "--github-url",
        repo_url,
    ]

    progress = st.progress(0, text="Preparing the testing process...")
    stage = st.empty()
    log_area = st.empty()

    log_lines = []
    started = time.monotonic()
    timeout_seconds = 900

    stages = [
        ("Starting the testing agent", 10),
        ("Scanning the repository and project files", 30),
        ("Running model, DAX and data checks", 55),
        ("Preparing the testing report", 80),
        ("Finishing the testing process", 95),
    ]

    try:
        process = subprocess.Popen(
            command,
            cwd=str(BASE_DIR),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )
    except OSError as exc:
        progress.empty()
        stage.error(f"Could not start the testing process: {exc}")
        return 1, str(exc)

    current_stage = 0
    stage.info(f"Step 1 of 5: {stages[0][0]}...")

    timed_out = False

    while True:
        if time.monotonic() - started > timeout_seconds:
            timed_out = True
            process.kill()
            process.wait()
            log_lines.append("ERROR: Testing timed out after 15 minutes.")
            break

        line = process.stdout.readline() if process.stdout else ""

        if line:
            clean_line = line.rstrip()
            log_lines.append(clean_line)

            # Keep the live log reasonably small.
            combined = "\n".join(log_lines[-40:])
            log_area.code(combined, language="text")

            text_line = clean_line.lower()

            if any(word in text_line for word in (
                "discover", "clone", "repository", "scanning", "file"
            )):
                current_stage = max(current_stage, 1)

            if any(word in text_line for word in (
                "data quality", "relationship", "semantic",
                "dax", "kpi", "visual", "check"
            )):
                current_stage = max(current_stage, 2)

            if any(word in text_line for word in (
                "report", "json", "markdown", "summary"
            )):
                current_stage = max(current_stage, 3)

            label, percent = stages[current_stage]
            progress.progress(percent, text=f"{label}...")
            stage.info(f"Step {current_stage + 1} of 5: {label}...")

        elif process.poll() is not None:
            break

    return_code = process.wait()
    progress.progress(100, text="Testing process finished.")

    if timed_out:
        stage.error("Testing timed out after 15 minutes.")
    elif return_code == 0:
        stage.success("Testing process completed. Loading results...")
    else:
        stage.error(
            f"Testing process exited with code {return_code}. "
            "Review the captured logs."
        )

    return return_code, "\n".join(log_lines)


# ============================================================
# 7. SHARED HEADER
# ============================================================

def render_header():
    st.markdown(
        """
        <div class="hero">
            <h1>ðŸ“Š Power BI Testing Agent</h1>
            <p>
                Inspect repository contents, semantic models, data quality,
                DAX, dashboard metadata and testing findings.
            </p>
        </div>
        """,
        unsafe_allow_html=True,
    )


# ============================================================
# 8. HOME PAGE
# ============================================================

def render_home():
    render_header()

    st.markdown("## Test a Power BI GitHub Repository")

    st.write(
        "Enter a public GitHub repository URL. The agent will download "
        "the repository, inspect available files, run the testing pipeline, "
        "and generate structured reports."
    )

    st.markdown(
        """
        <div class="custom-card">
            <h3>Testing workflow</h3>
            <p><b>1.</b> Enter the GitHub repository URL.</p>
            <p><b>2.</b> Discover project files and available metadata.</p>
            <p><b>3.</b> Run the available data, model, DAX and visual checks.</p>
            <p><b>4.</b> Review repository contents and detailed findings.</p>
            <p><b>5.</b> Download the JSON and Markdown reports.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    with st.form("repository_form"):
        repo_url = st.text_input(
            "GitHub repository URL",
            value=st.session_state.repo_url,
            placeholder="https://github.com/owner/repository",
            help="Enter a repository URL, not a file or issue URL.",
        )

        submitted = st.form_submit_button(
            "ðŸš€ Start Testing",
            use_container_width=True,
        )

    if submitted:
        repo_url = repo_url.strip()

        if not valid_github_url(repo_url):
            st.error(
                "Enter a valid GitHub repository URL, for example "
                "https://github.com/owner/repository"
            )
            return

        if not MAIN_FILE.exists():
            st.error(f"main.py was not found: {MAIN_FILE}")
            return

        st.session_state.repo_url = repo_url
        st.session_state.report = None
        st.session_state.log = ""
        st.session_state.exit_code = None
        st.session_state.inventory = None

        with st.spinner("Running the testing pipeline..."):
            code, logs = run_tests(repo_url)

        st.session_state.exit_code = code
        st.session_state.log = logs
        st.session_state.report = load_json_report()
        st.session_state.inventory = build_repository_inventory(logs)
        st.session_state.page = "results"
        st.rerun()

    st.markdown("---")
    st.markdown(
        '<div class="footer">AI-Powered Power BI Dashboard Testing Agent</div>',
        unsafe_allow_html=True,
    )


# ============================================================
# 9. REPOSITORY ANALYSIS PAGE SECTION
# ============================================================


def render_repository_inventory(inventory, report):
    st.markdown("## Repository Analysis")
    st.caption(
        "Overview of files and folders discovered in the downloaded repository. "
        "File presence alone does not mean that a file was successfully tested."
    )

    if not inventory:
        st.warning("Repository inventory is unavailable.")
        return

    if not inventory.get("repository_exists"):
        st.warning(
            "The downloaded repository could not be identified from the logs."
        )
        for warning in inventory.get("warnings", []):
            st.warning(warning)
        return

    # Repository summary metrics
    counts = inventory.get("file_counts", {})

    c1, c2, c3 = st.columns(3)
    c1.metric("Repository files", inventory.get("total_files", 0))
    c2.metric("Folders", inventory.get("total_folders", 0))
    c3.metric("File types", len(counts))

    # Detected Power BI project format
    project_format = find_report_value(
        report or {},
        {"project_format", "detected_format"},
    )

    if project_format:
        st.markdown(f"**Detected project format:** `{safe_text(project_format)}`")

    # Selected project files
    project_files = inventory.get("project_files", [])

    with st.expander(
        f"View selected project files ({len(project_files)} listed)"
    ):
        if project_files:
            st.code("\n".join(project_files), language="text")
        else:
            st.info("No project file listing is available.")

    # Inventory warnings
    for warning in inventory.get("warnings", []):
        st.warning(warning)

# ============================================================
# 10. FINDING DETAILS
# ============================================================

def render_finding(item, index):
    status = finding_status(item)
    title = finding_title(item, index)

    severity = get_value(
        item, "severity", "priority", "level", default=status
    )

    file_path = get_value(
        item,
        "file",
        "file_path",
        "path",
        "source_file",
        default="Not provided",
    )

    line_number = get_value(
        item,
        "line",
        "line_number",
        "row",
        "row_number",
        default="Not provided",
    )

    description = get_value(
        item,
        "description",
        "details",
        "message",
        "issue",
        "finding",
        default="No description was provided by the report.",
    )

    recommendation = get_value(
        item,
        "recommendation",
        "suggestion",
        "recommendations",
        "fix",
        "remediation",
        default="Review this finding against the project requirements.",
    )

    evidence = get_value(
        item,
        "evidence",
        "actual",
        "value",
        default="No additional evidence provided.",
    )

    with st.expander(f"{index}. [{status}] {title}"):
        left, right = st.columns([1, 2])

        with left:
            st.markdown("**Status / severity**")
            st.write(f"{status} / {severity}")

            st.markdown("**File**")
            st.code(str(file_path), language="text")

            st.markdown("**Line / row**")
            st.write(str(line_number))

        with right:
            st.markdown("**Description**")
            st.write(str(description))

            st.markdown("**Evidence**")

            if isinstance(evidence, (dict, list)):
                st.json(evidence)
            else:
                st.write(str(evidence))

            st.markdown("**Recommendation**")
            st.info(str(recommendation))

        with st.expander("View complete finding data"):
            st.json(item)


# ============================================================
# 11. RESULTS PAGE
# ============================================================


def render_results():
    render_header()

    st.markdown("## Testing Results")

    if st.button("â† Test another repository"):
        st.session_state.page = "home"
        st.rerun()

    st.write(f"**Repository:** {st.session_state.repo_url}")

    data = st.session_state.report
    exit_code = st.session_state.exit_code

    # --------------------------------------------------------
    # 1. OVERALL RESULT
    # --------------------------------------------------------

    if data is None:
        st.error(
            "No readable JSON report was generated. "
            "Review the testing logs below."
        )

        if exit_code not in (None, 0):
            st.write(f"Process exit code: {exit_code}")

        st.markdown("### Repository Analysis")
        render_repository_inventory(
            st.session_state.get("inventory"),
            data,
        )

        st.markdown("### Download Reports")

        if MARKDOWN_REPORT.exists():
            st.download_button(
                "â¬‡ï¸ Download Markdown Report",
                data=MARKDOWN_REPORT.read_bytes(),
                file_name="testing_summary.md",
                mime="text/markdown",
            )

        with st.expander("View testing logs", expanded=True):
            st.code(
                st.session_state.log or "No console output captured.",
                language="text",
            )

        return

    findings = find_findings(data)
    statuses = [finding_status(item) for item in findings]
    overall = get_overall_status(data, findings, exit_code)

    count_fail = statuses.count("FAIL")
    count_warning = statuses.count("WARNING")
    count_pass = statuses.count("PASS")
    count_not_tested = statuses.count("NOT TESTED")
    count_info = statuses.count("INFO")
    count_not_applicable = statuses.count("NOT APPLICABLE")

    st.markdown("### Overall Result")

    st.markdown(
        f"""
        <div class="{status_class(overall)}">
            <h2>Overall Status: {safe_text(overall)}</h2>
            <p>
                This status reflects the testing report and process result.
                Untested checks are not treated as passed.
            </p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # --------------------------------------------------------
    # 2. TEST FINDINGS SUMMARY
    # --------------------------------------------------------

    st.markdown("### Test Findings Summary")

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Total findings", len(findings))
    c2.metric("Failures", count_fail)
    c3.metric("Warnings", count_warning)
    c4.metric("Passed", count_pass)
    c5.metric("Not tested", count_not_tested)

    st.caption(
        f"Informational: {count_info} Â· "
        f"Not applicable: {count_not_applicable}"
    )

    # --------------------------------------------------------
    # 3. REPOSITORY ANALYSIS
    # --------------------------------------------------------

    st.markdown("---")
    st.markdown("### Repository Analysis")

    render_repository_inventory(
        st.session_state.get("inventory"),
        data,
    )

    # --------------------------------------------------------
    # 4. FILE TYPES DISCOVERED
    # --------------------------------------------------------
    # File types are displayed inside render_repository_inventory().
    # This heading makes that section easier to locate.

    st.markdown("### File Types Discovered")

    counts = (
        st.session_state.get("inventory") or {}
    ).get("file_counts", {})

    if counts:
        st.dataframe(
            [
                {"Extension": extension, "File count": count}
                for extension, count in counts.items()
            ],
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.info("No file types were discovered.")

    # --------------------------------------------------------
    # 5. DETAILED FINDINGS
    # --------------------------------------------------------

    st.markdown("---")
    st.markdown("### Detailed Findings")

    if not findings:
        st.info("No findings list was detected in the JSON report.")
    else:
        filter_status = st.selectbox(
            "Filter findings by status",
            options=[
                "ALL",
                "FAIL",
                "WARNING",
                "PASS",
                "NOT TESTED",
                "PARTIAL",
                "INFO",
                "NOT APPLICABLE",
                "UNKNOWN",
            ],
        )

        search_text = st.text_input(
            "Search findings",
            placeholder="Search title, file, message, evidence...",
        ).strip().lower()

        visible = []

        for item in findings:
            status = finding_status(item)
            title = finding_title(item, 0)

            searchable = json.dumps(
                item,
                ensure_ascii=False,
                default=str,
            ).lower()

            if filter_status != "ALL" and status != filter_status:
                continue

            if (
                search_text
                and search_text not in searchable
                and search_text not in title.lower()
            ):
                continue

            visible.append(item)

        st.caption(
            f"Showing {len(visible)} of {len(findings)} findings."
        )

        for index, item in enumerate(visible, start=1):
            render_finding(item, index)

    with st.expander("View complete JSON report"):
        st.json(data)

    with st.expander("View testing logs"):
        st.code(
            st.session_state.log or "No console output was captured.",
            language="text",
        )

    # --------------------------------------------------------
    # 6. DOWNLOAD REPORTS
    # --------------------------------------------------------

    st.markdown("---")
    st.markdown("### Download Reports")

    d1, d2 = st.columns(2)

    with d1:
        if JSON_REPORT.exists():
            st.download_button(
                "â¬‡ï¸ Download JSON Report",
                data=JSON_REPORT.read_bytes(),
                file_name="pbip_check_results.json",
                mime="application/json",
                use_container_width=True,
            )
        else:
            st.warning("JSON report file is unavailable.")

    with d2:
        if MARKDOWN_REPORT.exists():
            st.download_button(
                "â¬‡ï¸ Download Markdown Report",
                data=MARKDOWN_REPORT.read_bytes(),
                file_name="testing_summary.md",
                mime="text/markdown",
                use_container_width=True,
            )
        else:
            st.warning("Markdown report file is unavailable.")

    st.markdown("---")
    st.markdown(
        '<div class="footer">AI-Powered Power BI Dashboard Testing Agent</div>',
        unsafe_allow_html=True,
    )



# ============================================================
# 12. APPLICATION ENTRY POINT
# ============================================================

if st.session_state.page == "results":
    render_results()
else:
    render_home()
