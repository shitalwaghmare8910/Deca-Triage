# src/backend/report_template.py
# ADDITIVE FEATURE — Deutsche Bank styled HTML "Alert Investigation Report".
# Pure rendering module: no external deps, no side effects, no changes to
# existing pipeline behavior. Given an incident dict + parsed orchestrator
# response it derives everything it needs (with safe fallbacks) so it also
# works on incidents that were stored before this feature existed.

import html
import re
from datetime import datetime

# --- CAID prefix -> human label -------------------------------------------------
CAID_TYPE_MAP = {
    "MMDEOFRA": "MnM (Mortgage & More) Request",
    "MMDEOPRA": "MnM (Mortgage & More) Request",
    "PBDECOFI": "CoFi (Consumer Finance) Request",
    "COFI": "CoFi (Consumer Finance) Request",
}

# HTTP status -> (bg, fg) colour pair for the results table cells
STATUS_COLORS = {
    "2": ("#F0FAF4", "#059669"),   # 2xx success -> green
    "4": ("#FEF0F2", "#C8102E"),   # 4xx client  -> red
    "5": ("#FFF7ED", "#C05621"),   # 5xx server  -> orange
}
STATUS_SPECIAL = {
    "401": ("#FFF7ED", "#C05621"),  # unauthorised -> orange (matches sample)
    "403": ("#FFF7ED", "#C05621"),
}


def _esc(v):
    return html.escape("" if v is None else str(v))


def _status_style(code):
    code = str(code).strip()
    if code in STATUS_SPECIAL:
        return STATUS_SPECIAL[code]
    return STATUS_COLORS.get(code[:1], ("#F4F5F7", "#64748B"))


def _find_caid(ctx_text):
    """Best-effort CAID extraction supporting both dash and space formats."""
    if not ctx_text:
        return None
    m = re.search(r'((?:MMDEOFRA|MMDEOPRA|PBDECOFI)[-\s][\w\-]+)', ctx_text)
    return m.group(1).strip() if m else None


def _caid_prefix(caid):
    if not caid:
        return None
    m = re.match(r'([A-Z]+)', caid)
    return m.group(1) if m else None


def _compute_confidence(runbook, query_results, rows, failures, escalation, report):
    """Deterministic, explainable confidence (0-100) from the incident evidence.

    Fallback used when neither the orchestrator nor the model supplied a score,
    so legacy incidents still get a value that reflects diagnostic quality.
    """
    score = 100
    runbook_matched = bool(runbook) and str(runbook).strip().lower() not in ("", "n/a", "no runbook found")
    if not runbook_matched:
        score -= 30
    errored = any(isinstance(q, dict) and q.get("error") for q in (query_results or []))
    if query_results:
        if errored:
            score -= 20
        if not rows:
            score -= 25  # observability gap: no rows returned
    else:
        score -= 15  # no queries executed
    if escalation:
        score -= 15
    if not (report or {}).get("key_findings"):
        score -= 10
    return max(5, min(100, score))


def build_context(inc, orch):
    """Normalise an incident + orchestrator response into a flat context dict.

    Prefers an explicit ``report_context`` block if the orchestrator provided
    one, otherwise derives every field from the stored analysis data.
    """
    inc = inc or {}
    orch = orch or {}
    rc = orch.get("report_context") or {}
    report = orch.get("detailed_analysis_report") or {}

    alert_name = rc.get("alert_name") or orch.get("alert_name") or inc.get("short_description") or "Alert"
    runbook = rc.get("runbook_matched") or orch.get("runbook_matched") or "N/A"

    # --- CAID ------------------------------------------------------------------
    caid = rc.get("extracted_caid")
    query_results = orch.get("query_results") or []
    if not caid:
        # scan any filled_query / purpose strings, then the detailed analysis text
        haystack = " ".join(
            str(q.get("filled_query", "")) + " " + str(q.get("purpose", ""))
            for q in query_results
        )
        haystack += " " + str(report.get("detailed_analysis", "")) + " " + str(alert_name)
        caid = _find_caid(haystack)
    prefix = rc.get("caid_prefix") or _caid_prefix(caid)
    caid_label = rc.get("caid_type_label") or CAID_TYPE_MAP.get((prefix or "").upper(), "—")

    # --- SQL rows --------------------------------------------------------------
    filled_query = rc.get("filled_query")
    rows, columns = [], []
    for q in query_results:
        res = q.get("result") or {}
        data = res.get("data")
        if not filled_query:
            filled_query = q.get("filled_query")
        if isinstance(data, list) and data:
            rows = data
            columns = list(data[0].keys())
            break

    # failure accounting on any http-status-like column
    status_col = None
    for c in columns:
        if c.lower() in ("http_status", "status", "code", "status_code"):
            status_col = c
            break
    failures = []
    if status_col:
        for r in rows:
            code = str(r.get(status_col, "")).strip()
            if code and not code.startswith("2"):
                failures.append(code)

    # --- confidence / escalation ----------------------------------------------
    escalation = bool(rc.get("escalation_needed", report.get("escalation_needed", False)))
    confidence = rc.get("confidence_score", report.get("confidence_score"))
    if confidence is None:
        confidence = _compute_confidence(runbook, query_results, rows, failures, escalation, report)

    return {
        "alert_name": alert_name,
        "number": inc.get("number") or orch.get("incident_id") or "—",
        "short_description": inc.get("short_description") or alert_name,
        "priority_label": inc.get("priority_label") or "—",
        "triggered": inc.get("opened_at") or inc.get("created_at") or "—",
        "runbook": runbook,
        "caid": caid,
        "caid_prefix": prefix,
        "caid_label": caid_label,
        "filled_query": filled_query,
        "columns": columns,
        "rows": rows,
        "status_col": status_col,
        "failures": failures,
        "confidence": int(confidence),
        "escalation": escalation,
        "escalation_reason": rc.get("escalation_reason") or report.get("escalation_reason"),
        "root_cause_summary": report.get("root_cause_summary") or orch.get("analysis_summary") or "—",
        "detailed_analysis": report.get("detailed_analysis") or "",
        "affected_components": report.get("affected_components") or [],
        "key_findings": report.get("key_findings") or [],
        "recommended_actions": report.get("recommended_actions") or orch.get("recommended_actions") or [],
        "contacts": report.get("contacts") or [],
        "sql_status": orch.get("sql_query_result") or "N/A",
        # Deep-RCA enrichment (from the RCA agent). Optional/additive: legacy
        # incidents without these simply render nothing extra.
        "root_cause_category": report.get("root_cause_category") or "",
        "causal_chain": report.get("causal_chain") or [],
        "contributing_factors": report.get("contributing_factors") or [],
        "blast_radius": report.get("blast_radius") or "",
    }


def _rows_table(ctx):
    cols = ctx["columns"]
    rows = ctx["rows"]
    if not cols:
        return ('<div style="font-size:12px;color:#64748B;padding:10px 0;">'
                'No SQL result rows were returned for this investigation.</div>')

    header = "".join(
        f'<td style="padding:7px 10px;color:#fff;font-weight:700;font-size:9px;'
        f'text-transform:uppercase;letter-spacing:0.8px;">{_esc(c)}</td>' for c in cols
    )
    body = []
    for i, r in enumerate(rows):
        bg = "#FAFAFA" if i % 2 else "#FFFFFF"
        cells = []
        for c in cols:
            val = r.get(c)
            if c == ctx["status_col"]:
                bgc, fgc = _status_style(val)
                cells.append(
                    f'<td style="padding:8px 10px;"><span style="background:{bgc};'
                    f'color:{fgc};font-weight:700;font-size:10px;padding:2px 6px;'
                    f'border-radius:2px;">{_esc(val)}</span></td>')
            else:
                cells.append(
                    f'<td style="padding:8px 10px;font-family:monospace;font-size:10px;'
                    f'color:#0A1628;">{_esc(val)}</td>')
        body.append(f'<tr style="border-top:1px solid #ECEEF2;background:{bg};">{"".join(cells)}</tr>')

    fail = ctx["failures"]
    if fail:
        from collections import Counter
        summary = ", ".join(f"{n}× {code}" for code, n in Counter(fail).items())
        footer = (
            f'<tr style="border-top:1px solid #ECEEF2;"><td colspan="{len(cols)}" '
            f'align="right" style="padding:8px 10px;font-family:monospace;font-size:10px;color:#64748B;">'
            f'{len(rows)} rows returned &nbsp;·&nbsp; '
            f'<strong style="color:#C8102E;">{len(fail)} failures detected ({_esc(summary)})</strong></td></tr>')
    else:
        footer = (
            f'<tr style="border-top:1px solid #ECEEF2;"><td colspan="{len(cols)}" '
            f'align="right" style="padding:8px 10px;font-family:monospace;font-size:10px;color:#64748B;">'
            f'{len(rows)} rows returned</td></tr>')

    return (
        '<table width="100%" cellpadding="0" cellspacing="0" style="border:1px solid #ECEEF2;'
        'border-radius:3px;margin-bottom:18px;font-size:11px;overflow:hidden;">'
        f'<tr style="background:#003087;">{header}</tr>{"".join(body)}{footer}</table>')


def _list_block(items, ordered=False):
    if not items:
        return '<div style="font-size:12px;color:#64748B;">None recorded.</div>'
    steps = []
    for i, it in enumerate(items, 1):
        num = (f'<td width="28" style="vertical-align:top;padding-top:1px;">'
               f'<span style="display:inline-block;width:20px;height:20px;background:#003087;'
               f'color:#fff;font-size:9px;font-weight:700;text-align:center;line-height:20px;'
               f'border-radius:50%;">{i}</span></td>') if ordered else ''
        steps.append(
            f'<tr><td style="padding:8px 0;border-bottom:1px solid #ECEEF2;vertical-align:top;">'
            f'<table cellpadding="0" cellspacing="0" width="100%"><tr>{num}'
            f'<td style="padding-left:{8 if ordered else 0}px;font-size:12px;color:#0A1628;'
            f'line-height:1.6;">{_esc(it)}</td></tr></table></td></tr>')
    return f'<table width="100%" cellpadding="0" cellspacing="0" style="margin-bottom:18px;">{"".join(steps)}</table>'


def _findings_block(findings):
    if not findings:
        return ""
    sev_color = {"CRITICAL": "#C8102E", "HIGH": "#D97706", "MEDIUM": "#7C3AED", "LOW": "#059669"}
    rows = []
    for f in findings:
        if isinstance(f, dict):
            sev = str(f.get("severity", "INFO")).upper()
            txt = f.get("finding", "")
        else:
            sev, txt = "INFO", str(f)
        col = sev_color.get(sev, "#64748B")
        rows.append(
            f'<tr style="border-top:1px solid #ECEEF2;"><td style="padding:9px 12px;width:90px;'
            f'vertical-align:top;"><span style="background:{col}18;color:{col};font-weight:700;'
            f'font-size:9px;padding:2px 8px;border-radius:2px;">{_esc(sev)}</span></td>'
            f'<td style="padding:9px 12px;font-size:12px;color:#4A5568;line-height:1.6;">{_esc(txt)}</td></tr>')
    return (
        '<table width="100%" cellpadding="0" cellspacing="0" style="border:1px solid #ECEEF2;'
        'border-radius:3px;margin-bottom:18px;overflow:hidden;">'
        f'{"".join(rows)}</table>')


def _causal_chain_block(chain):
    """Render the RCA agent's 5-Whys causal chain as a vertical timeline."""
    if not chain:
        return ""
    steps = []
    n = len(chain)
    for i, step in enumerate(chain, 1):
        if isinstance(step, dict):
            why = step.get("why", "")
            because = step.get("because", "")
        else:
            why, because = str(step), ""
        last = i == n
        connector = ("" if last else
                     '<div style="width:2px;height:100%;background:#C8102E33;position:absolute;'
                     'left:11px;top:24px;"></div>')
        because_html = (f'<div style="font-size:11px;color:#64748B;line-height:1.6;margin-top:3px;">'
                        f'<strong style="color:#C8102E;">Because:</strong> {_esc(because)}</div>') if because else ""
        steps.append(
            f'<tr><td style="position:relative;padding:0 0 14px 0;vertical-align:top;">'
            f'<table cellpadding="0" cellspacing="0" width="100%"><tr>'
            f'<td width="30" style="vertical-align:top;position:relative;">{connector}'
            f'<span style="display:inline-block;width:22px;height:22px;background:#C8102E;color:#fff;'
            f'font-size:10px;font-weight:700;text-align:center;line-height:22px;border-radius:50%;'
            f'position:relative;z-index:1;">{i}</span></td>'
            f'<td style="padding-left:10px;vertical-align:top;">'
            f'<div style="font-size:12px;color:#0A1628;font-weight:600;line-height:1.55;">{_esc(why)}</div>'
            f'{because_html}</td></tr></table></td></tr>')
    return (
        '<table width="100%" cellpadding="0" cellspacing="0" style="border:1px solid #ECEEF2;'
        'border-radius:3px;margin-bottom:18px;padding:14px 16px;background:#FCFCFD;">'
        f'{"".join(steps)}</table>')


def render_report(inc, orch):
    """Return a full standalone HTML document for the incident investigation."""
    ctx = build_context(inc, orch)
    conf = ctx["confidence"]
    conf_color = "#C8102E" if conf < 80 else "#059669"
    escalated = ctx["escalation"]
    status_pill = ("⬆ ESCALATED TO HUMAN", "#FEF0F2", "#C8102E") if escalated else ("✓ AUTO-RESOLVED", "#F0FAF4", "#059669")

    caid_display = _esc(ctx["caid"]) if ctx["caid"] else "—"
    caid_type_display = (f'{_esc(ctx["caid_prefix"])} ({_esc(ctx["caid_label"])})'
                         if ctx["caid_prefix"] else "—")

    # CAID extraction table
    caid_table = ""
    if ctx["caid"]:
        sqlf = (f'<tr style="border-top:1px solid #ECEEF2;background:#FAFAFA;">'
                f'<td style="padding:9px 12px;color:#64748B;font-weight:600;border-right:1px solid #ECEEF2;">'
                f'SQL Filter Applied</td><td style="padding:9px 12px;font-family:monospace;font-size:10px;'
                f'color:#059669;">{_esc(ctx["filled_query"])}</td></tr>') if ctx["filled_query"] else ""
        caid_table = f"""
      <div style="font-size:11px;font-weight:700;color:#003087;text-transform:uppercase;
        letter-spacing:1.2px;border-bottom:1px solid #ECEEF2;padding-bottom:7px;margin-bottom:14px;">
        🔬 Log Analysis — CAID Extraction</div>
      <table width="100%" cellpadding="0" cellspacing="0" style="border:1px solid #ECEEF2;
        border-radius:3px;margin-bottom:18px;font-size:11px;overflow:hidden;">
        <tr style="background:#F4F5F7;">
          <td style="padding:7px 12px;font-weight:700;color:#8A95A3;text-transform:uppercase;
            font-size:9px;letter-spacing:1px;width:35%;border-right:1px solid #ECEEF2;">Field</td>
          <td style="padding:7px 12px;font-weight:700;color:#8A95A3;text-transform:uppercase;
            font-size:9px;letter-spacing:1px;">Value</td></tr>
        <tr style="border-top:1px solid #ECEEF2;">
          <td style="padding:9px 12px;color:#64748B;font-weight:600;border-right:1px solid #ECEEF2;">CA_ID Extracted</td>
          <td style="padding:9px 12px;font-family:monospace;font-size:11px;color:#7C3AED;font-weight:600;">{caid_display}</td></tr>
        <tr style="border-top:1px solid #ECEEF2;background:#FAFAFA;">
          <td style="padding:9px 12px;color:#64748B;font-weight:600;border-right:1px solid #ECEEF2;">CAID Prefix</td>
          <td style="padding:9px 12px;color:#0A1628;font-weight:600;">
            <span style="background:#F5F3FF;color:#7C3AED;padding:2px 8px;border-radius:2px;
              font-size:10px;font-weight:700;">{_esc(ctx["caid_prefix"] or "—")}</span>
            &nbsp; → &nbsp;<strong>{_esc(ctx["caid_label"])}</strong></td></tr>
        <tr style="border-top:1px solid #ECEEF2;">
          <td style="padding:9px 12px;color:#64748B;font-weight:600;border-right:1px solid #ECEEF2;">Source</td>
          <td style="padding:9px 12px;color:#0A1628;">GCP Logs — xs2a-outbound service</td></tr>
        {sqlf}
      </table>"""

    # SQL query block
    sql_block = ""
    if ctx["filled_query"]:
        sql_block = f"""
      <table width="100%" cellpadding="0" cellspacing="0" style="margin-bottom:14px;">
        <tr><td style="background:#0A0F1E;border-radius:4px;padding:14px 16px;">
          <div style="font-size:9px;font-weight:700;color:#475569;text-transform:uppercase;
            letter-spacing:1.5px;margin-bottom:8px;">Executed Query</div>
          <pre style="margin:0;font-family:'Courier New',monospace;font-size:11px;line-height:1.7;
            color:#E2E8F0;white-space:pre-wrap;">{_esc(ctx["filled_query"])}</pre>
        </td></tr></table>"""

    impact_block = ""
    if ctx["affected_components"]:
        comps = ", ".join(_esc(c) for c in ctx["affected_components"])
        impact_block = f"""
      <table width="100%" cellpadding="0" cellspacing="0" style="margin-bottom:18px;">
        <tr><td style="background:#FEF0F2;border-left:3px solid #C8102E;border-radius:0 3px 3px 0;padding:12px 14px;">
          <div style="font-size:10px;font-weight:700;color:#C8102E;text-transform:uppercase;
            letter-spacing:1px;margin-bottom:5px;">⚠ Affected Components</div>
          <div style="font-size:12px;color:#4A5568;line-height:1.7;">{comps}</div>
        </td></tr></table>"""

    findings_html = _findings_block(ctx["key_findings"])
    findings_section = f"""
      <div style="font-size:11px;font-weight:700;color:#003087;text-transform:uppercase;
        letter-spacing:1.2px;border-bottom:1px solid #ECEEF2;padding-bottom:7px;margin-bottom:14px;">
        ⚡ Key Findings</div>{findings_html}""" if findings_html else ""

    # --- Deep RCA sections (from RCA agent) — additive, render only if present ---
    category_badge = ""
    if ctx["root_cause_category"]:
        category_badge = (
            f'<span style="display:inline-block;background:#EEF2FF;color:#003087;font-size:10px;'
            f'font-weight:700;padding:3px 10px;border-radius:2px;letter-spacing:0.5px;'
            f'text-transform:uppercase;border:1px solid #00308720;margin-left:8px;">'
            f'{_esc(ctx["root_cause_category"])}</span>')

    blast_block = ""
    if ctx["blast_radius"]:
        blast_block = f"""
      <table width="100%" cellpadding="0" cellspacing="0" style="margin-bottom:18px;">
        <tr><td style="background:#FFF7ED;border-left:3px solid #C05621;border-radius:0 3px 3px 0;padding:12px 14px;">
          <div style="font-size:10px;font-weight:700;color:#C05621;text-transform:uppercase;
            letter-spacing:1px;margin-bottom:5px;">💥 Blast Radius</div>
          <div style="font-size:12px;color:#4A5568;line-height:1.7;">{_esc(ctx["blast_radius"])}</div>
        </td></tr></table>"""

    causal_html = _causal_chain_block(ctx["causal_chain"])
    causal_section = f"""
      <div style="font-size:11px;font-weight:700;color:#C8102E;text-transform:uppercase;letter-spacing:1.2px;
        border-bottom:1px solid #ECEEF2;padding-bottom:7px;margin-bottom:14px;">
        🔗 Causal Chain — 5 Whys</div>{causal_html}""" if causal_html else ""

    contrib_section = ""
    if ctx["contributing_factors"]:
        contrib_section = f"""
      <div style="font-size:11px;font-weight:700;color:#003087;text-transform:uppercase;letter-spacing:1.2px;
        border-bottom:1px solid #ECEEF2;padding-bottom:7px;margin-bottom:14px;">
        🧩 Contributing Factors</div>{_list_block(ctx["contributing_factors"])}"""

    escalation_note = (_esc(ctx["escalation_reason"]) if ctx["escalation_reason"]
                       else ("Escalated — insufficient data to auto-remediate" if escalated
                             else "Automated analysis completed with high confidence"))
    decision_label = "ESCALATE TO HUMAN" if escalated else "AUTO-RESOLVED"
    decision_bg, decision_fg = ("#FEF0F2", "#C8102E") if escalated else ("#F0FAF4", "#059669")

    generated = datetime.now().strftime("%d %b %Y, %H:%M")

    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1.0"/>
<title>SRE Investigation Report — {_esc(ctx["alert_name"])}</title></head>
<body style="margin:0;padding:0;background:#F0F2F5;font-family:'Segoe UI',Arial,sans-serif;">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#F0F2F5;padding:28px 16px;">
<tr><td align="center">
<table width="640" cellpadding="0" cellspacing="0" style="max-width:640px;width:100%;">

  <tr><td style="background:#001C4E;padding:0;border-radius:4px 4px 0 0;overflow:hidden;">
    <table width="100%" cellpadding="0" cellspacing="0"><tr>
      <td width="56" style="padding:18px 0 18px 20px;vertical-align:middle;">
        <table cellpadding="0" cellspacing="0"><tr><td style="background:#003087;border:2px solid #4472C4;
          width:36px;height:36px;text-align:center;vertical-align:middle;">
          <svg width="26" height="26" viewBox="0 0 48 48" fill="none" xmlns="http://www.w3.org/2000/svg">
            <rect x="3" y="3" width="42" height="42" fill="none" stroke="white" stroke-width="2.5"/>
            <line x1="12" y1="36" x2="36" y2="12" stroke="white" stroke-width="7" stroke-linecap="square"/>
          </svg></td></tr></table></td>
      <td style="padding:18px 16px;vertical-align:middle;">
        <div style="font-size:11px;font-weight:600;color:rgba(255,255,255,.45);text-transform:uppercase;
          letter-spacing:2px;margin-bottom:3px;">Deutsche Bank · SRE Intelligence Platform</div>
        <div style="font-size:17px;font-weight:700;color:#FFFFFF;letter-spacing:-0.2px;">Alert Investigation Report</div></td>
      <td align="right" style="padding:18px 20px 18px 0;vertical-align:middle;white-space:nowrap;">
        <span style="display:inline-block;background:{status_pill[1]};color:{status_pill[2]};font-size:10px;
          font-weight:700;padding:4px 10px;border-radius:2px;letter-spacing:0.8px;text-transform:uppercase;
          border:1px solid {status_pill[2]}40;">{status_pill[0]}</span></td>
    </tr></table></td></tr>

  <tr><td style="background:#C8102E;padding:12px 20px;">
    <table width="100%" cellpadding="0" cellspacing="0"><tr>
      <td><div style="font-size:15px;font-weight:700;color:#FFFFFF;margin-bottom:2px;">{_esc(ctx["alert_name"])}</div>
        <div style="font-size:11px;color:rgba(255,255,255,.7);font-family:monospace;">
          {_esc(ctx["number"])} &nbsp;·&nbsp; {_esc(ctx["runbook"])}</div></td>
      <td align="right" style="white-space:nowrap;padding-left:12px;">
        <span style="display:inline-block;background:rgba(255,255,255,.18);color:#fff;font-size:10px;
          font-weight:700;padding:3px 10px;border-radius:2px;border:1px solid rgba(255,255,255,.3);">
          {_esc(ctx["priority_label"])}</span></td>
    </tr></table></td></tr>

  <tr><td style="background:#FFFFFF;border-left:1px solid #D8DCE6;border-right:1px solid #D8DCE6;padding:0;">
    <table width="100%" cellpadding="0" cellspacing="0" style="border-bottom:1px solid #ECEEF2;"><tr>
      <td style="padding:11px 20px;border-right:1px solid #ECEEF2;width:25%;">
        <div style="font-size:9px;font-weight:700;color:#8A95A3;text-transform:uppercase;letter-spacing:1px;margin-bottom:3px;">Alert ID</div>
        <div style="font-size:12px;font-weight:700;color:#003087;font-family:monospace;">{_esc(ctx["number"])}</div></td>
      <td style="padding:11px 16px;border-right:1px solid #ECEEF2;width:25%;">
        <div style="font-size:9px;font-weight:700;color:#8A95A3;text-transform:uppercase;letter-spacing:1px;margin-bottom:3px;">Triggered</div>
        <div style="font-size:12px;font-weight:600;color:#0A1628;">{_esc(ctx["triggered"])}</div></td>
      <td style="padding:11px 16px;border-right:1px solid #ECEEF2;width:25%;">
        <div style="font-size:9px;font-weight:700;color:#8A95A3;text-transform:uppercase;letter-spacing:1px;margin-bottom:3px;">CAID Type</div>
        <div style="font-size:12px;font-weight:700;color:#7C3AED;font-family:monospace;">{caid_type_display}</div></td>
      <td style="padding:11px 16px;width:25%;">
        <div style="font-size:9px;font-weight:700;color:#8A95A3;text-transform:uppercase;letter-spacing:1px;margin-bottom:3px;">Confidence</div>
        <div style="font-size:12px;font-weight:700;color:{conf_color};">{conf}%</div></td>
    </tr></table></td></tr>

  <tr><td style="background:#FFFFFF;padding:22px 20px;border-left:1px solid #D8DCE6;border-right:1px solid #D8DCE6;">

      <table width="100%" cellpadding="0" cellspacing="0" style="margin-bottom:18px;">
        <tr><td style="background:#F4F5F7;border-left:3px solid #003087;border-radius:0 3px 3px 0;padding:12px 14px;">
          <div style="font-size:10px;font-weight:700;color:#003087;text-transform:uppercase;letter-spacing:1px;margin-bottom:5px;">
            ℹ Root Cause Summary</div>
          <div style="font-size:12px;color:#4A5568;line-height:1.7;">{_esc(ctx["root_cause_summary"])}</div>
        </td></tr></table>

      {impact_block}
      {caid_table}

      <div style="font-size:11px;font-weight:700;color:#003087;text-transform:uppercase;letter-spacing:1.2px;
        border-bottom:1px solid #ECEEF2;padding-bottom:7px;margin-bottom:14px;">
        🗄️ SQL Investigation — audit_log</div>
      {sql_block}
      {_rows_table(ctx)}

      {findings_section}

      <div style="font-size:11px;font-weight:700;color:#003087;text-transform:uppercase;letter-spacing:1.2px;
        border-bottom:1px solid #ECEEF2;padding-bottom:7px;margin-bottom:14px;">🧠 AI Root Cause Analysis{category_badge}</div>
      <table width="100%" cellpadding="0" cellspacing="0" style="border:1px solid #ECEEF2;border-radius:3px;
        margin-bottom:18px;overflow:hidden;"><tr><td style="padding:0;">
        <table width="100%" cellpadding="0" cellspacing="0"><tr>
          <td style="padding:12px 14px;border-right:1px solid #ECEEF2;vertical-align:top;width:50%;">
            <div style="font-size:9px;font-weight:700;color:#8A95A3;text-transform:uppercase;letter-spacing:1px;margin-bottom:6px;">Root Cause</div>
            <div style="font-size:12px;font-weight:700;color:#0A1628;margin-bottom:4px;">{_esc(ctx["root_cause_summary"])}</div>
            <div style="font-size:11px;color:#64748B;line-height:1.6;">{_esc(ctx["detailed_analysis"])}</div></td>
          <td style="padding:12px 14px;vertical-align:top;width:50%;">
            <div style="font-size:9px;font-weight:700;color:#8A95A3;text-transform:uppercase;letter-spacing:1px;margin-bottom:6px;">Confidence</div>
            <div style="font-size:22px;font-weight:700;color:{conf_color};margin-bottom:8px;">{conf}%</div>
            <div style="background:#ECEEF2;height:5px;border-radius:3px;overflow:hidden;">
              <div style="width:{conf}%;height:100%;background:{conf_color};border-radius:3px;"></div></div>
            <div style="font-size:9px;color:#8A95A3;margin-top:4px;">{escalation_note}</div></td>
        </tr></table></td></tr></table>

      {causal_section}
      {blast_block}
      {contrib_section}

      <table width="100%" cellpadding="0" cellspacing="0" style="margin-bottom:18px;">
        <tr><td style="background:{decision_bg};border:1px solid {decision_fg}30;border-radius:3px;padding:14px 16px;">
          <table width="100%" cellpadding="0" cellspacing="0"><tr>
            <td><div style="font-size:13px;font-weight:700;color:{decision_fg};margin-bottom:6px;">Decision: {decision_label}</div>
              <div style="font-size:11px;color:#4A5568;line-height:1.7;">{escalation_note}</div></td>
            <td align="right" style="padding-left:16px;white-space:nowrap;vertical-align:middle;">
              <span style="display:inline-block;background:{decision_fg};color:#fff;font-size:10px;font-weight:700;
                padding:5px 12px;border-radius:2px;letter-spacing:0.5px;">
                {"ACTION REQUIRED" if escalated else "RESOLVED"}</span></td>
          </tr></table></td></tr></table>

      <div style="font-size:11px;font-weight:700;color:#003087;text-transform:uppercase;letter-spacing:1.2px;
        border-bottom:1px solid #ECEEF2;padding-bottom:7px;margin-bottom:14px;">📋 Recommended Actions</div>
      {_list_block(ctx["recommended_actions"], ordered=True)}

  </td></tr>

  <tr><td style="background:#001C4E;padding:14px 20px;border-radius:0 0 4px 4px;">
    <table width="100%" cellpadding="0" cellspacing="0"><tr>
      <td><div style="font-size:10px;color:rgba(255,255,255,.5);line-height:1.6;">
        Generated by <strong style="color:rgba(255,255,255,.7);">SRE Intelligence Platform</strong> ·
        Deutsche Bank Group Technology<br/>Generated: {generated} &nbsp;·&nbsp; Model: Gemini 2.5 Flash</div></td>
      <td align="right" style="white-space:nowrap;padding-left:16px;">
        <div style="font-size:9px;color:rgba(255,255,255,.3);font-family:monospace;">{_esc(ctx["number"])}</div></td>
    </tr></table></td></tr>

</table></td></tr></table></body></html>"""
