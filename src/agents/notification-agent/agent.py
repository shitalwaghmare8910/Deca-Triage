# src/agents/notification-agent/agent.py
# DEFINITIVE "DEMO MODE" VERSION
import os
from fastapi import FastAPI, Request
from dotenv import load_dotenv
import report_template

load_dotenv()
app = FastAPI(title="Notification Agent (DEMO MODE)")

# Where generated HTML email reports are written (generate-only; no SMTP send).
REPORTS_DIR = os.getenv("REPORTS_DIR", "/tmp/sre_reports")

@app.post("/send-notification")
async def send_notification(request: Request):
    print("\n--- Notification Agent Activated ---")
    print("Received request from Orchestrator to send notification.")
    data = await request.json()
    actions = data.get("recommended_actions", []) or data.get("actions", [])
    print(f"SIMULATING: Sending notification to SRE team with recommended actions: {actions}")

    # --- ADDITIVE: build a styled HTML investigation report (generate-only) ---
    report_html = None
    incident_id = data.get("incident_id", "incident")
    try:
        orch = {
            "alert_name": data.get("summary") or incident_id,
            "report_context": data.get("report_context") or {},
            "detailed_analysis_report": data.get("detailed_analysis_report") or {},
            "query_results": data.get("query_results") or [],
            "recommended_actions": actions,
        }
        inc = {"number": incident_id, "short_description": data.get("summary")}
        report_html = report_template.render_report(inc, orch)
        os.makedirs(REPORTS_DIR, exist_ok=True)
        safe_id = "".join(c if c.isalnum() or c in "-_" else "_" for c in str(incident_id))
        out_path = os.path.join(REPORTS_DIR, f"{safe_id}.html")
        with open(out_path, "w", encoding="utf-8") as fh:
            fh.write(report_html)
        print(f"Investigation report generated: {out_path}")
    except Exception as e:
        print(f"WARN: could not generate HTML report: {e}")

    print("--- Notification Agent Task Complete ---\n")
    return {"status": "notification sent", "report_generated": bool(report_html), "report_html": report_html}

@app.get("/health")
def health(): return {"status": "healthy"}