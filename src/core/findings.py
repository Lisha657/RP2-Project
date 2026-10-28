def add_finding(findings, category, status, issue, file="", evidence=""):
    findings.append({
        "Category": category,
        "Status": status,
        "Issue": issue,
        "File": file,
        "Evidence": evidence,
    })


def summarize_findings(findings):
    """Count findings by status for the final test report."""

    summary = {
        "PASS": 0,
        "INFO": 0,
        "WARNING": 0,
        "ERROR": 0,
    }

    for finding in findings:
        status = str(finding.get("Status", "")).upper()

        if status in summary:
            summary[status] += 1

    summary["TOTAL"] = len(findings)
    return summary


def summarize_findings(findings):
    """Summarize test results for the final report."""

    summary = {
        "PASS": 0,
        "WARNING": 0,
        "FAIL": 0,
        "INFO": 0,
        "NOT RUN": 0,
    }

    for finding in findings:
        status = str(finding.get("Status", "")).upper()

        if status in summary:
            summary[status] += 1

    if summary["FAIL"] > 0:
        overall_status = "FAIL"
    elif summary["WARNING"] > 0:
        overall_status = "NEEDS REVIEW"
    elif summary["PASS"] > 0:
        overall_status = "PASS"
    else:
        overall_status = "NOT ENOUGH RESULTS"

    return {
        "overall_status": overall_status,
        "total_checks": len(findings),
        "counts": summary,
    }
