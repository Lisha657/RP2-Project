import re
import json
import html
import pandas as pd


def _format_inline_md(text):
    text = html.escape(str(text))
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"`(.+?)`", r"<code class='inline-code'>\1</code>", text)
    return text


def _format_markdown_for_html(md_text):
    if not md_text or not str(md_text).strip():
        return "<p class='no-rec'>AI recommendations were not generated for this evaluation run.</p>"

    lines = str(md_text).splitlines()
    html_lines = []
    in_code_block = False
    in_list = False

    for line in lines:
        stripped = line.strip()

        if stripped.startswith("```"):
            if in_code_block:
                html_lines.append("</code></pre>")
                in_code_block = False
            else:
                lang = stripped[3:].strip()
                html_lines.append(f"<pre class='code-block'><code class='language-{html.escape(lang)}'>")
                in_code_block = True
            continue

        if in_code_block:
            html_lines.append(html.escape(line) + "\n")
            continue

        if not stripped:
            if in_list:
                html_lines.append("</ul>")
                in_list = False
            continue

        if stripped.startswith("### "):
            if in_list:
                html_lines.append("</ul>")
                in_list = False
            html_lines.append(f"<h4 class='rec-h4'>{_format_inline_md(stripped[4:])}</h4>")
            continue
        elif stripped.startswith("## "):
            if in_list:
                html_lines.append("</ul>")
                in_list = False
            html_lines.append(f"<h3 class='rec-h3'>{_format_inline_md(stripped[3:])}</h3>")
            continue
        elif stripped.startswith("# "):
            if in_list:
                html_lines.append("</ul>")
                in_list = False
            html_lines.append(f"<h2 class='rec-h2'>{_format_inline_md(stripped[2:])}</h2>")
            continue

        if stripped.startswith(("- ", "* ", "• ")):
            if not in_list:
                html_lines.append("<ul class='rec-list'>")
                in_list = True
            html_lines.append(f"<li>{_format_inline_md(stripped[2:])}</li>")
            continue

        if re.match(r"^\d+\.\s+", stripped):
            if in_list:
                html_lines.append("</ul>")
                in_list = False
            num_match = re.match(r"^(\d+)\.\s+(.*)$", stripped)
            if num_match:
                num, item_text = num_match.group(1), num_match.group(2)
                html_lines.append(
                    f"<div class='rec-numbered-item'><span class='num-badge'>{num}</span>"
                    f"<div>{_format_inline_md(item_text)}</div></div>"
                )
            continue

        if in_list:
            html_lines.append("</ul>")
            in_list = False

        html_lines.append(f"<p class='rec-p'>{_format_inline_md(stripped)}</p>")

    if in_list:
        html_lines.append("</ul>")
    if in_code_block:
        html_lines.append("</code></pre>")

    return "\n".join(html_lines)


def create_html_report(findings, recommendations=None):
    total = len(findings)
    fail_count = sum(1 for f in findings if str(f.get("Status", "")).upper() == "FAIL")
    warning_count = sum(1 for f in findings if str(f.get("Status", "")).upper() == "WARNING")
    pass_count = sum(1 for f in findings if str(f.get("Status", "")).upper() == "PASS")
    info_count = sum(1 for f in findings if str(f.get("Status", "")).upper() in ("INFO", "NOT RUN"))

    if fail_count > 0:
        overall_text = "CRITICAL ISSUES DETECTED"
        overall_badge_class = "verdict-fail"
    elif warning_count > 0:
        overall_text = "NEEDS ATTENTION (WARNINGS)"
        overall_badge_class = "verdict-warning"
    elif pass_count > 0:
        overall_text = "ALL AUDITED CHECKS PASSED"
        overall_badge_class = "verdict-pass"
    else:
        overall_text = "INSUFFICIENT DATA"
        overall_badge_class = "verdict-neutral"

    categories = sorted(list({str(f.get("Category", "")) for f in findings if f.get("Category")}))

    rows = []
    for f in findings:
        status_raw = str(f.get("Status", "INFO")).upper()
        status_clean = status_raw.lower().replace(" ", "-")
        cat_raw = str(f.get("Category", "General"))
        issue_raw = str(f.get("Issue", ""))
        file_raw = str(f.get("File", ""))
        evidence_raw = str(f.get("Evidence", ""))

        file_html = (
            f"<code class='file-chip'>{html.escape(file_raw)}</code>"
            if file_raw else "<span class='text-muted'>—</span>"
        )
        evidence_html = (
            f"<div class='evidence-box'>{html.escape(evidence_raw)}</div>"
            if evidence_raw else "<span class='text-muted'>—</span>"
        )

        rows.append(
            f'<tr data-status="{html.escape(status_clean)}" data-category="{html.escape(cat_raw)}">'
            f'<td><span class="cat-pill">{html.escape(cat_raw)}</span></td>'
            f'<td><span class="badge badge-{html.escape(status_clean)}"><span class="dot"></span>{html.escape(status_raw)}</span></td>'
            f'<td class="issue-cell"><strong>{html.escape(issue_raw)}</strong></td>'
            f'<td>{file_html}</td>'
            f'<td>{evidence_html}</td>'
            f'</tr>'
        )

    recommendation_html = _format_markdown_for_html(recommendations)
    generated = pd.Timestamp.now().strftime("%B %d, %Y at %H:%M:%S UTC")

    category_options = "".join(f'<option value="{html.escape(c)}">{html.escape(c)}</option>' for c in categories)

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Power BI Testing & Audit Report</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>
:root {{
  --bg: #f5f1e8;
  --surface: #fffdf8;
  --surface-2: #f2ede3;
  --surface-3: #e8e0d3;
  --border: #ddd4c5;
  --border-light: #ece5d9;
  --text-main: #29251f;
  --text-sub: #625b50;
  --text-muted: #8b8173;
  --primary: #476b8f;
  --primary-glow: rgba(71,107,143,0.15);
  --pass: #24804a;
  --pass-bg: rgba(36,128,74,0.1);
  --pass-border: rgba(36,128,74,0.3);
  --warning: #9a6a0a;
  --warning-bg: rgba(154,106,10,0.1);
  --warning-border: rgba(154,106,10,0.3);
  --fail: #c53030;
  --fail-bg: rgba(197,48,48,0.1);
  --fail-border: rgba(197,48,48,0.3);
  --info: #2563a6;
  --info-bg: rgba(37,99,166,0.1);
  --info-border: rgba(37,99,166,0.3);
  --purple: #6659a6;
  --purple-bg: rgba(102,89,166,0.1);
  --radius: 10px;
  --shadow: 0 8px 24px rgba(60,45,20,0.08);
}}

* {{ box-sizing: border-box; margin: 0; padding: 0; }}

body {{
  font-family: 'Plus Jakarta Sans', -apple-system, BlinkMacSystemFont, sans-serif;
  background: var(--bg);
  color: var(--text-main);
  line-height: 1.6;
  padding: 24px;
  min-height: 100vh;
}}

a {{ color: var(--primary); text-decoration: none; }}

.container {{ max-width: 1400px; margin: 0 auto; }}

/* ═══ HERO ═══════════════════════════════════════════════════════ */
.hero {{
  position: relative;
  background: linear-gradient(135deg, #fffdf8 0%, #f5f1e8 55%, #eee6d8 100%);
  border: 1px solid var(--border);
  border-radius: 16px;
  padding: 40px 44px;
  margin-bottom: 24px;
  overflow: hidden;
  box-shadow: var(--shadow);
}}
.hero::before {{
  content: '';
  position: absolute;
  top: 0; left: 0; right: 0;
  height: 2px;
  background: linear-gradient(90deg, #58a6ff, #a5a0ff, #f85149, #3fb950, #d29922);
  background-size: 300% 100%;
  animation: shimmer 4s linear infinite;
}}
@keyframes shimmer {{
  0% {{ background-position: 0% 50%; }}
  100% {{ background-position: 300% 50%; }}
}}
.hero-glow {{
  position: absolute;
  top: -80px; right: -80px;
  width: 320px; height: 320px;
  background: radial-gradient(circle, rgba(71,107,143,0.12) 0%, transparent 70%);
  pointer-events: none;
}}
.hero-top {{
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 20px;
  flex-wrap: wrap;
}}
.hero h1 {{
  font-size: 30px;
  font-weight: 800;
  letter-spacing: -0.03em;
  background: linear-gradient(135deg, #29251f 0%, #6659a6 100%);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
}}
.hero-brand {{
  font-size: 12px;
  color: var(--text-sub);
  font-weight: 500;
  margin-top: 4px;
  letter-spacing: 0.03em;
}}
.hero-meta {{
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 20px;
  flex-wrap: wrap;
}}
.hero-ts {{
  font-size: 12px;
  color: var(--text-muted);
}}
.print-btn {{
  background: var(--surface-2);
  color: var(--text-sub);
  border: 1px solid var(--border);
  padding: 9px 18px;
  border-radius: 8px;
  font-family: inherit;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s;
  letter-spacing: 0.02em;
}}
.print-btn:hover {{
  background: var(--surface-2);
  color: var(--text-main);
  border-color: var(--primary);
}}

/* ═══ VERDICT PILL ══════════════════════════════════════════════ */
.verdict-pill {{
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 5px 14px;
  border-radius: 9999px;
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.06em;
  text-transform: uppercase;
}}
.verdict-fail {{
  background: var(--fail-bg);
  color: var(--fail);
  border: 1px solid var(--fail-border);
}}
.verdict-warning {{
  background: var(--warning-bg);
  color: var(--warning);
  border: 1px solid var(--warning-border);
}}
.verdict-pass {{
  background: var(--pass-bg);
  color: var(--pass);
  border: 1px solid var(--pass-border);
}}
.verdict-neutral {{
  background: var(--surface-2);
  color: var(--text-sub);
  border: 1px solid var(--border);
}}
.pulse-dot {{
  width: 8px;
  height: 8px;
  border-radius: 50%;
  flex-shrink: 0;
}}
.verdict-fail .pulse-dot {{
  background: var(--fail);
  box-shadow: 0 0 0 0 rgba(248,81,73,0.5);
  animation: pulse-red 1.5s ease infinite;
}}
.verdict-warning .pulse-dot {{
  background: var(--warning);
  box-shadow: 0 0 0 0 rgba(210,153,34,0.5);
  animation: pulse-yellow 1.5s ease infinite;
}}
.verdict-pass .pulse-dot {{
  background: var(--pass);
}}
@keyframes pulse-red {{
  0% {{ box-shadow: 0 0 0 0 rgba(248,81,73,0.5); }}
  70% {{ box-shadow: 0 0 0 8px rgba(248,81,73,0); }}
  100% {{ box-shadow: 0 0 0 0 rgba(248,81,73,0); }}
}}
@keyframes pulse-yellow {{
  0% {{ box-shadow: 0 0 0 0 rgba(210,153,34,0.5); }}
  70% {{ box-shadow: 0 0 0 8px rgba(210,153,34,0); }}
  100% {{ box-shadow: 0 0 0 0 rgba(210,153,34,0); }}
}}

/* ═══ METRICS GRID ══════════════════════════════════════════════ */
.metrics-grid {{
  display: grid;
  grid-template-columns: repeat(5, 1fr);
  gap: 14px;
  margin-bottom: 24px;
}}
@media (max-width: 900px) {{
  .metrics-grid {{ grid-template-columns: repeat(3, 1fr); }}
}}
.metric-card {{
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 18px 20px;
  position: relative;
  overflow: hidden;
  transition: transform 0.15s, box-shadow 0.15s;
}}
.metric-card:hover {{
  transform: translateY(-2px);
  box-shadow: var(--shadow);
}}
.metric-card::after {{
  content: '';
  position: absolute;
  top: 0; left: 0;
  width: 3px; height: 100%;
  border-radius: 3px 0 0 3px;
}}
.metric-card.total::after {{ background: var(--primary); }}
.metric-card.failed::after {{ background: var(--fail); }}
.metric-card.warning::after {{ background: var(--warning); }}
.metric-card.passed::after {{ background: var(--pass); }}
.metric-card.info::after {{ background: var(--info); }}
.metric-icon {{
  font-size: 22px;
  margin-bottom: 8px;
}}
.metric-label {{
  font-size: 10px;
  font-weight: 700;
  color: var(--text-sub);
  text-transform: uppercase;
  letter-spacing: 0.06em;
  margin-bottom: 4px;
}}
.metric-value {{
  font-size: 36px;
  font-weight: 800;
  line-height: 1;
}}
.metric-card.total .metric-value {{ color: var(--primary); }}
.metric-card.failed .metric-value {{ color: var(--fail); }}
.metric-card.warning .metric-value {{ color: var(--warning); }}
.metric-card.passed .metric-value {{ color: var(--pass); }}
.metric-card.info .metric-value {{ color: var(--info); }}

/* ═══ SECTION DIVIDER ═══════════════════════════════════════════ */
.section-header {{
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 14px;
  margin-top: 32px;
}}
.section-header:first-of-type {{ margin-top: 0; }}
.section-title-text {{
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 18px;
  font-weight: 700;
  color: var(--text-main);
}}
.section-icon {{
  width: 32px; height: 32px;
  border-radius: 8px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 16px;
}}
.section-icon.blue {{ background: var(--info-bg); border: 1px solid var(--info-border); }}
.section-icon.purple {{ background: var(--purple-bg); border: 1px solid rgba(165,160,255,0.3); }}
.visible-counter {{
  font-size: 11px;
  font-weight: 600;
  color: var(--text-sub);
  background: var(--surface-2);
  padding: 4px 12px;
  border-radius: 9999px;
  border: 1px solid var(--border);
}}

/* ═══ CATEGORY BREAKDOWN ════════════════════════════════════════ */
.breakdown-grid {{
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: 12px;
  margin-bottom: 24px;
}}
.breakdown-card {{
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 14px 16px;
  transition: border-color 0.2s;
}}
.breakdown-card:hover {{ border-color: var(--primary); }}
.breakdown-top {{
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
}}
.breakdown-name {{
  font-size: 12px;
  font-weight: 700;
  color: var(--text-main);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 60%;
}}
.breakdown-counts {{
  display: flex;
  gap: 6px;
}}
.mini-badge {{
  font-size: 10px;
  font-weight: 700;
  padding: 2px 7px;
  border-radius: 9999px;
}}
.mini-fail {{ background: var(--fail-bg); color: var(--fail); border: 1px solid var(--fail-border); }}
.mini-warn {{ background: var(--warning-bg); color: var(--warning); border: 1px solid var(--warning-border); }}
.mini-pass {{ background: var(--pass-bg); color: var(--pass); border: 1px solid var(--pass-border); }}
.progress-bar-wrap {{
  background: var(--surface-2);
  border-radius: 9999px;
  height: 5px;
  overflow: hidden;
}}
.progress-bar {{
  height: 100%;
  border-radius: 9999px;
  background: linear-gradient(90deg, var(--pass) 0%, var(--info) 100%);
  transition: width 0.6s ease;
}}
.progress-bar.has-fail {{ background: linear-gradient(90deg, var(--fail) 0%, var(--warning) 100%); }}
.progress-bar.has-warn {{ background: linear-gradient(90deg, var(--warning) 0%, var(--info) 100%); }}

/* ═══ FILTER BAR ════════════════════════════════════════════════ */
.filter-bar {{
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 12px 16px;
  margin-bottom: 14px;
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 12px;
}}
.filter-tabs {{
  display: flex;
  gap: 5px;
  flex-wrap: wrap;
}}
.filter-btn {{
  background: transparent;
  border: 1px solid var(--border);
  color: var(--text-sub);
  font-family: inherit;
  font-size: 11px;
  font-weight: 700;
  padding: 5px 13px;
  border-radius: 9999px;
  cursor: pointer;
  transition: all 0.15s;
  letter-spacing: 0.02em;
}}
.filter-btn:hover {{ background: var(--surface-2); color: var(--text-main); }}
.filter-btn.active {{ background: var(--primary); color: #0d1117; border-color: var(--primary); }}
.filter-inputs {{
  display: flex;
  gap: 8px;
  flex: 1;
  min-width: 0;
}}
.search-input {{
  flex: 1;
  min-width: 120px;
  padding: 7px 14px;
  background: var(--surface-2);
  border: 1px solid var(--border);
  border-radius: 8px;
  font-family: inherit;
  font-size: 12px;
  color: var(--text-main);
  outline: none;
  transition: border-color 0.2s;
}}
.search-input:focus {{ border-color: var(--primary); }}
.search-input::placeholder {{ color: var(--text-muted); }}
.cat-select {{
  padding: 7px 10px;
  background: var(--surface-2);
  border: 1px solid var(--border);
  border-radius: 8px;
  font-family: inherit;
  font-size: 12px;
  color: var(--text-main);
  outline: none;
  cursor: pointer;
}}

/* ═══ FINDINGS TABLE ════════════════════════════════════════════ */
.table-card {{
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  overflow: hidden;
  margin-bottom: 32px;
  box-shadow: var(--shadow);
}}
.table-wrap {{ overflow-x: auto; }}
table {{
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}}
thead tr {{
  background: var(--surface-2);
  border-bottom: 1px solid var(--border);
}}
th {{
  padding: 11px 16px;
  text-align: left;
  font-size: 10px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.07em;
  color: var(--text-sub);
  white-space: nowrap;
}}
tbody tr {{
  border-bottom: 1px solid var(--border-light);
  transition: background 0.1s;
}}
tbody tr:last-child {{ border-bottom: none; }}
tbody tr:hover {{ background: rgba(88,166,255,0.04); }}

/* left-border status stripe */
tbody tr[data-status="fail"] {{ border-left: 3px solid var(--fail); }}
tbody tr[data-status="warning"] {{ border-left: 3px solid var(--warning); }}
tbody tr[data-status="pass"] {{ border-left: 3px solid var(--pass); }}
tbody tr[data-status="info"],
tbody tr[data-status="not-run"] {{ border-left: 3px solid var(--info); }}

td {{
  padding: 13px 16px;
  vertical-align: top;
}}

.cat-pill {{
  display: inline-block;
  background: var(--surface-3);
  color: var(--text-sub);
  font-size: 10px;
  font-weight: 700;
  padding: 3px 9px;
  border-radius: 5px;
  white-space: nowrap;
  letter-spacing: 0.03em;
  text-transform: uppercase;
}}

.badge {{
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 4px 10px;
  border-radius: 6px;
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 0.04em;
  white-space: nowrap;
  text-transform: uppercase;
}}
.badge .dot {{
  width: 5px; height: 5px;
  border-radius: 50%;
  flex-shrink: 0;
}}
.badge-pass {{ background: var(--pass-bg); color: var(--pass); border: 1px solid var(--pass-border); }}
.badge-pass .dot {{ background: var(--pass); }}
.badge-warning {{ background: var(--warning-bg); color: var(--warning); border: 1px solid var(--warning-border); }}
.badge-warning .dot {{ background: var(--warning); }}
.badge-fail {{ background: var(--fail-bg); color: var(--fail); border: 1px solid var(--fail-border); }}
.badge-fail .dot {{ background: var(--fail); }}
.badge-info {{ background: var(--info-bg); color: var(--info); border: 1px solid var(--info-border); }}
.badge-info .dot {{ background: var(--info); }}
.badge-not-run {{ background: var(--surface-2); color: var(--text-sub); border: 1px solid var(--border); }}
.badge-not-run .dot {{ background: var(--text-muted); }}

.file-chip {{
  display: inline-block;
  font-family: 'JetBrains Mono', monospace;
  font-size: 11px;
  background: var(--surface-3);
  color: var(--primary);
  padding: 3px 8px;
  border-radius: 5px;
  word-break: break-all;
  border: 1px solid rgba(88,166,255,0.2);
}}

.evidence-box {{
  font-family: 'JetBrains Mono', monospace;
  font-size: 11px;
  color: var(--text-sub);
  background: var(--surface-2);
  border: 1px solid var(--border);
  padding: 6px 10px;
  border-radius: 6px;
  max-width: 400px;
  white-space: pre-wrap;
  word-break: break-word;
  line-height: 1.5;
}}

.issue-text {{
  font-size: 13px;
  font-weight: 600;
  color: var(--text-main);
  line-height: 1.4;
}}
.issue-sub {{
  font-size: 11px;
  color: var(--text-sub);
  margin-top: 3px;
}}
.text-muted {{ color: var(--text-muted); font-size: 12px; }}

/* ═══ AI CARD ═══════════════════════════════════════════════════ */
.ai-card {{
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 28px 32px;
  margin-bottom: 24px;
  box-shadow: var(--shadow);
  position: relative;
  overflow: hidden;
}}
.ai-card::before {{
  content: '';
  position: absolute;
  top: 0; left: 0; right: 0;
  height: 2px;
  background: linear-gradient(90deg, #6366f1, #a855f7, #ec4899);
}}
.ai-header {{
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 22px;
  padding-bottom: 16px;
  border-bottom: 1px solid var(--border-light);
}}
.ai-icon {{
  width: 36px; height: 36px;
  border-radius: 10px;
  background: linear-gradient(135deg, #6366f1, #a855f7);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 18px;
  flex-shrink: 0;
}}
.ai-title-group {{ flex: 1; }}
.ai-title {{
  font-size: 15px;
  font-weight: 700;
  color: var(--text-main);
}}
.ai-subtitle {{
  font-size: 11px;
  color: var(--text-sub);
  margin-top: 1px;
}}
.ai-badge {{
  background: linear-gradient(135deg, #6366f1, #a855f7);
  color: #ffffff;
  font-size: 9px;
  font-weight: 800;
  text-transform: uppercase;
  padding: 3px 10px;
  border-radius: 9999px;
  letter-spacing: 0.07em;
}}

/* Rich AI content styles */
.rec-h2 {{ font-size: 20px; font-weight: 800; color: var(--text-main); margin: 24px 0 12px; }}
.rec-h3 {{
  font-size: 15px;
  font-weight: 700;
  color: var(--text-main);
  margin: 20px 0 10px;
  padding: 8px 14px;
  background: var(--surface-2);
  border-left: 3px solid var(--purple);
  border-radius: 0 6px 6px 0;
}}
.rec-h4 {{
  font-size: 13px;
  font-weight: 700;
  color: var(--primary);
  margin: 14px 0 6px;
  text-transform: uppercase;
  letter-spacing: 0.04em;
}}
.rec-p {{
  font-size: 14px;
  color: var(--text-sub);
  margin-bottom: 12px;
  line-height: 1.7;
}}
.rec-list {{
  list-style: none;
  padding: 0;
  margin: 0 0 16px;
}}
.rec-list li {{
  font-size: 14px;
  color: var(--text-sub);
  line-height: 1.6;
  padding: 6px 0 6px 24px;
  position: relative;
  border-bottom: 1px solid var(--border-light);
}}
.rec-list li:last-child {{ border-bottom: none; }}
.rec-list li::before {{
  content: '›';
  position: absolute;
  left: 6px;
  color: var(--primary);
  font-weight: 800;
  font-size: 16px;
  line-height: 1.3;
}}
.rec-numbered-item {{
  display: flex;
  gap: 14px;
  align-items: flex-start;
  background: var(--surface-2);
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 14px 16px;
  margin-bottom: 10px;
  transition: border-color 0.2s;
}}
.rec-numbered-item:hover {{ border-color: var(--primary); }}
.num-badge {{
  background: linear-gradient(135deg, var(--primary), var(--purple));
  color: #0d1117;
  font-weight: 800;
  font-size: 12px;
  min-width: 26px;
  height: 26px;
  border-radius: 7px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}}
.rec-numbered-item > div {{
  font-size: 14px;
  color: var(--text-sub);
  line-height: 1.6;
  flex: 1;
}}
.code-block {{
  background: var(--surface-2);
  border: 1px solid var(--border);
  color: var(--text-main);
  font-family: 'JetBrains Mono', monospace;
  font-size: 12px;
  padding: 14px 16px;
  border-radius: 8px;
  margin: 12px 0;
  overflow-x: auto;
  white-space: pre;
  line-height: 1.6;
}}
.inline-code {{
  font-family: 'JetBrains Mono', monospace;
  background: var(--surface-3);
  color: #f97583;
  padding: 1px 6px;
  border-radius: 4px;
  font-size: 12px;
}}
.no-rec {{
  color: var(--text-muted);
  font-style: italic;
  font-size: 14px;
}}

/* ═══ FOOTER ════════════════════════════════════════════════════ */
.footer {{
  text-align: center;
  font-size: 11px;
  color: var(--text-muted);
  margin-top: 24px;
  padding: 18px 0;
  border-top: 1px solid var(--border-light);
  letter-spacing: 0.03em;
}}
.footer strong {{ color: var(--text-sub); }}

/* ═══ PRINT ══════════════════════════════════════════════════════ */
@media print {{
  body {{ background: #f5f1e8; color: #29251f; padding: 0; }}
  .hero {{ background: #fffdf8 !important; }}
  .hero-actions, .filter-bar, .breakdown-grid {{ display: none !important; }}
  .metric-card, .table-card, .ai-card {{ box-shadow: none !important; }}
  table {{ font-size: 11px; }}
  th, td {{ padding: 8px 10px; }}
}}
</style>
</head>
<body>
<div class="container">

  <!-- HERO BANNER -->
  <div class="hero">
    <div class="hero-glow"></div>
    <div class="hero-top">
      <div>
        <h1>&#128737;&#65039; Power BI Quality Audit Report</h1>
        <div class="hero-brand">AI-Powered Intelligence &bull; Automated Static Analysis Engine</div>
      </div>
      <button class="print-btn" onclick="window.print()">&#128424;&#65039; Export PDF</button>
    </div>
    <div class="hero-meta">
      <span class="verdict-pill {overall_badge_class}"><span class="pulse-dot"></span>{overall_text}</span>
      <span class="hero-ts">Audit executed {html.escape(generated)}</span>
    </div>
  </div>

  <!-- KPI METRIC CARDS -->
  <div class="metrics-grid">
    <div class="metric-card total">
      <div class="metric-icon">&#128203;</div>
      <div class="metric-label">Total Checks</div>
      <div class="metric-value">{total}</div>
    </div>
    <div class="metric-card failed">
      <div class="metric-icon">&#128308;</div>
      <div class="metric-label">Critical Failures</div>
      <div class="metric-value">{fail_count}</div>
    </div>
    <div class="metric-card warning">
      <div class="metric-icon">&#128993;</div>
      <div class="metric-label">Warnings</div>
      <div class="metric-value">{warning_count}</div>
    </div>
    <div class="metric-card passed">
      <div class="metric-icon">&#9989;</div>
      <div class="metric-label">Passed Checks</div>
      <div class="metric-value">{pass_count}</div>
    </div>
    <div class="metric-card info">
      <div class="metric-icon">&#8505;&#65039;</div>
      <div class="metric-label">Info / Not Run</div>
      <div class="metric-value">{info_count}</div>
    </div>
  </div>

  <!-- CATEGORY BREAKDOWN -->
  <div class="section-header">
    <div class="section-title-text">
      <div class="section-icon blue">&#128202;</div>
      Category Breakdown
    </div>
  </div>
  <div class="breakdown-grid" id="breakdownGrid"></div>

  <!-- FINDINGS TABLE -->
  <div class="section-header">
    <div class="section-title-text">
      <div class="section-icon blue">&#128269;</div>
      Detailed Findings Log
    </div>
    <span class="visible-counter" id="visibleCount">Showing {total} of {total}</span>
  </div>

  <div class="filter-bar">
    <div class="filter-tabs">
      <button class="filter-btn active" onclick="setStatusFilter('all', this)">All &nbsp;<strong>{total}</strong></button>
      <button class="filter-btn" onclick="setStatusFilter('fail', this)">&#128308; Failures &nbsp;<strong>{fail_count}</strong></button>
      <button class="filter-btn" onclick="setStatusFilter('warning', this)">&#128993; Warnings &nbsp;<strong>{warning_count}</strong></button>
      <button class="filter-btn" onclick="setStatusFilter('pass', this)">&#9989; Passed &nbsp;<strong>{pass_count}</strong></button>
      <button class="filter-btn" onclick="setStatusFilter('info', this)">&#8505;&#65039; Info &nbsp;<strong>{info_count}</strong></button>
    </div>
    <div class="filter-inputs">
      <input type="text" id="searchInput" class="search-input" placeholder="Search issue, file, evidence&hellip;" onkeyup="filterTable()">
      <select id="categoryFilter" class="cat-select" onchange="filterTable()">
        <option value="">All Categories</option>
        {category_options}
      </select>
    </div>
  </div>

  <div class="table-card">
    <div class="table-wrap">
      <table id="findingsTable">
        <thead>
          <tr>
            <th>Category</th>
            <th>Status</th>
            <th>Issue Description</th>
            <th>Target File</th>
            <th>Evidence / Details</th>
          </tr>
        </thead>
        <tbody>
          {''.join(rows)}
        </tbody>
      </table>
    </div>
  </div>

  <!-- AI RECOMMENDATIONS -->
  <div class="section-header">
    <div class="section-title-text">
      <div class="section-icon purple">&#10024;</div>
      AI Remediation Roadmap
    </div>
  </div>
  <div class="ai-card">
    <div class="ai-header">
      <div class="ai-icon">&#129302;</div>
      <div class="ai-title-group">const findingsData
        <div class="ai-title">Google Gemini Diagnostic Synthesis</div>
        <div class="ai-subtitle">Root-cause analysis, severity classification &amp; prioritised remediation plan</div>
      </div>
      <span class="ai-badge">Gemini AI</span>
    </div>
    {recommendation_html}
  </div>

  <div class="footer">
    <strong>AI-Powered Power BI Testing Agent</strong> &nbsp;&bull;&nbsp; Phase 2 Submission Deliverable &nbsp;&bull;&nbsp; Generated {html.escape(generated)}
  </div>

</div>

<script>
 const findingsData = {json.dumps([{"status": str(f.get("Status","")).lower().replace(" ","-"), "category": str(f.get("Category",""))} for f in findings])};

(function() {{
  const cats = {{}};
  findingsData.forEach(f => {{
    if (!cats[f.category]) cats[f.category] = {{fail:0, warn:0, pass:0, info:0, total:0}};
    cats[f.category].total++;
    if (f.status === 'fail') cats[f.category].fail++;
    else if (f.status === 'warning') cats[f.category].warn++;
    else if (f.status === 'pass') cats[f.category].pass++;
    else cats[f.category].info++;
  }});
  const grid = document.getElementById('breakdownGrid');
  Object.entries(cats).sort((a,b) => b[1].fail - a[1].fail || b[1].warn - a[1].warn).forEach(([cat, c]) => {{
    const passRate = Math.round((c.pass / c.total) * 100);
    const barClass = c.fail > 0 ? 'has-fail' : (c.warn > 0 ? 'has-warn' : '');
    const badges = [
      c.fail > 0 ? `<span class='mini-badge mini-fail'>${{c.fail}} FAIL</span>` : '',
      c.warn > 0 ? `<span class='mini-badge mini-warn'>${{c.warn}} WARN</span>` : '',
      c.pass > 0 ? `<span class='mini-badge mini-pass'>${{c.pass}} PASS</span>` : ''
    ].filter(Boolean).join('');
    grid.innerHTML += `<div class='breakdown-card' onclick="document.getElementById('categoryFilter').value='${{cat}}';filterTable()" style='cursor:pointer'><div class='breakdown-top'><span class='breakdown-name' title='${{cat}}'>${{cat}}</span><div class='breakdown-counts'>${{badges}}</div></div><div class='progress-bar-wrap'><div class='progress-bar ${{barClass}}' style='width:${{passRate}}%'></div></div></div>`;
  }});
}})();

let activeStatus = 'all';
function setStatusFilter(status, btn) {{
  activeStatus = status;
  document.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  filterTable();
}}
function filterTable() {{
  const query = (document.getElementById('searchInput').value || '').toLowerCase().trim();
  const selectedCat = (document.getElementById('categoryFilter').value || '').toLowerCase();
  const rows = document.querySelectorAll('#findingsTable tbody tr');
  let visible = 0;
  rows.forEach(row => {{
    const rowStatus = (row.getAttribute('data-status') || '').toLowerCase();
    const rowCat = (row.getAttribute('data-category') || '').toLowerCase();
    const rowText = row.innerText.toLowerCase();
    let statusMatch = (activeStatus === 'all');
    if (activeStatus === 'info') statusMatch = (rowStatus === 'info' || rowStatus === 'not-run');
    else if (!statusMatch) statusMatch = (rowStatus === activeStatus);
    const catMatch = !selectedCat || rowCat === selectedCat;
    const textMatch = !query || rowText.includes(query);
    if (statusMatch && catMatch && textMatch) {{ row.style.display = ''; visible++; }}
    else row.style.display = 'none';
  }});
  document.getElementById('visibleCount').innerText = `Showing ${{visible}} of ${{rows.length}} findings`;
}}
</script>
</body>
</html>"""
