import json
from pathlib import Path

import pandas as pd
import requests
import streamlit as st
from dotenv import load_dotenv

from src.ai.recommendations import generate_ai_recommendations
from src.core.config import MAX_TEXT_FILE_BYTES
from src.core.findings import add_finding, summarize_findings
from src.data_analysis.csv_quality import inspect_csv
from src.data_analysis.sql_validation import inspect_sql
from src.github_scanner.repository_scanner import github_repo_files
from src.powerbi.project_validation import (
    inspect_pbip_zip,
    inspect_pbix,
    inspect_single_upload,
)
from src.reports.html_report import create_html_report


load_dotenv(Path(__file__).resolve().parent.parent / ".env")


def main():
    st.set_page_config(
        page_title="AI-Powered Power BI Dashboard Testing Agent",
        layout="wide"
    )

    # Sidebar input panel
    with st.sidebar:
        st.header("⚙️ Test Configuration")

        source = st.radio(
            "Select Input Source",
            [
                "🌐 Public GitHub Repository",
                "📊 Upload Power BI PBIX (.pbix)",
                "📁 Upload PBIP Project (.zip)",
                "📄 Direct Upload Single File",
            ],
            index=0,
        )

        github_url = ""
        uploaded_file = None

        if source == "🌐 Public GitHub Repository":
            github_url = st.text_input(
                "GitHub Repository URL",
                placeholder="https://github.com/owner/repository"
            )
            st.caption("Public repositories only.")

        elif source == "📊 Upload Power BI PBIX (.pbix)":
            uploaded_file = st.file_uploader(
                "Upload Power BI PBIX file",
                type=["pbix"]
            )

        elif source == "📁 Upload PBIP Project (.zip)":
            uploaded_file = st.file_uploader(
                "Upload PBIP project ZIP",
                type=["zip"],
                help=(
                    "Include the .pbip entry file and its matching "
                    "Report and SemanticModel folders."
                )
            )

        else:
            uploaded_file = st.file_uploader(
                "Upload Supported File",
                type=[
                    "csv", "sql", "dax", "tmdl", "json",
                    "pbir", "pbip", "bim", "txt", "pbix"
                ],
                help="Single-file scans may not have enough project context."
            )


        st.divider()

        run_clicked = st.button(
            "🚀 Run Testing Pipeline",
            type="primary",
            use_container_width=True
        )

       

    st.title("📊 AI-Powered Power BI Dashboard Testing Agent")

    st.write(
        "Automated testing pipeline for Power BI projects. "
        "Inspects supported data quality, SQL scripts, and PBIP metadata. "
        "Provides Gemini AI recommendations and downloadable audit reports."
    )

    if "findings" not in st.session_state:
        st.session_state.findings = None

    if "recommendations" not in st.session_state:
        st.session_state.recommendations = None
    if run_clicked:
        findings = []

        try:
            if source == "🌐 Public GitHub Repository":
                if not github_url.strip():
                    st.error("Enter a GitHub repository URL in the sidebar.")
                    st.stop()

                owner, repo, branch, items = github_repo_files(
                    github_url.strip()
                )

                checked = 0

                for item in items:
                    path = item.get("path", "")

                    if item.get("type") != "blob":
                        continue

                    if not path.lower().endswith((".csv", ".sql")):
                        continue

                    if item.get("size", 0) > MAX_TEXT_FILE_BYTES:
                        add_finding(
                            findings, "GitHub Repository", "WARNING",
                            "File skipped because it exceeds 1 MB", path
                        )
                        continue

                    raw_url = (
                        "https://raw.githubusercontent.com/"
                        f"{owner}/{repo}/{branch}/"
                        f"{requests.utils.quote(path, safe='/')}"
                    )

                    response = requests.get(raw_url, timeout=20)

                    if not response.ok:
                        add_finding(
                            findings, "GitHub Repository", "WARNING",
                            f"Could not download file: HTTP {response.status_code}",
                            path
                        )
                        continue

                    checked += 1

                    if path.lower().endswith(".csv"):
                        inspect_csv(response.text, path, findings)
                    else:
                        inspect_sql(response.text, path, findings)

                add_finding(
                    findings, "GitHub Repository", "INFO",
                    f"Inspected {checked} CSV/SQL file(s) from {owner}/{repo}",
                    evidence="This GitHub path currently scans CSV/SQL only."
                )

            elif uploaded_file is None:
                st.error("Choose a file to upload in the sidebar.")
                st.stop()

            elif source == "📁 Upload PBIP Project (.zip)":
                with st.spinner("Extracting project and checking metadata..."):
                    inspect_pbip_zip(uploaded_file, findings)

            elif source == "📊 Upload Power BI PBIX (.pbix)":
                with st.spinner("Attempting PBIX extraction with pbi-tools..."):
                    inspect_pbix(uploaded_file, findings)

            else:
                inspect_single_upload(uploaded_file, findings)

            st.session_state.findings = findings
            st.session_state.recommendations = None

        except requests.RequestException as exc:
            st.error(f"GitHub request failed: {exc}")

        except Exception as exc:
            st.error(f"Testing failed: {exc}")

    if st.session_state.findings is not None:
        findings = st.session_state.findings

        summary = summarize_findings(findings)
        st.write("Overall Status:", summary["overall_status"])


        st.subheader("Testing Execution Summary")

        c1, c2, c3, c4, c5 = st.columns(5)

        c1.metric("Findings", len(findings))
        c2.metric(
            "Failed Checks",
            sum(x["Status"] == "FAIL" for x in findings)
        )
        c3.metric(
            "Warnings",
            sum(x["Status"] == "WARNING" for x in findings)
        )
        c4.metric(
            "Passed Checks",
            sum(x["Status"] == "PASS" for x in findings)
        )
        c5.metric(
            "Checks Not Run",
            sum(x["Status"] == "NOT RUN" for x in findings)
        )

        st.subheader(f"Detailed Findings ({len(findings)})")

        st.dataframe(
            pd.DataFrame(findings),
            use_container_width=True,
            hide_index=True
        )

        st.download_button(
            "⬇️ Download findings as JSON",
            data=json.dumps(
                findings, indent=2, ensure_ascii=False
            ).encode("utf-8"),
            file_name="power_bi_testing_findings.json",
            mime="application/json"
        )

        st.subheader("AI Recommendations")

        if st.button("Generate AI Recommendations"):
            with st.spinner("Gemini is analysing the findings..."):
                st.session_state.recommendations = (
                    generate_ai_recommendations(findings)
                )

        recommendations = st.session_state.recommendations

        if recommendations:
            st.markdown(recommendations)

            st.download_button(
                "⬇️ Download AI recommendations (TXT)",
                data=recommendations,
                file_name="power_bi_ai_recommendations.txt",
                mime="text/plain"
            )

        html_report = create_html_report(
            findings, recommendations
        )

        st.download_button(
            "⬇️ Download complete report as HTML",
            data=html_report.encode("utf-8"),
            file_name="power_bi_testing_report.html",
            mime="text/html"
        )


if __name__ == "__main__":
    main()
