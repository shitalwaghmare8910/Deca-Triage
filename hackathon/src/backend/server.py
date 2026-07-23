# src/backend/server.py
# DEFINITIVE GOLDEN STATE (Corrected)

import threading, time, json, requests, logging, os, io, base64
from flask import Flask, jsonify, send_from_directory, Response, request
from flask_cors import CORS
import database as db
import report_template

app = Flask(__name__, static_folder='static', static_url_path='')
CORS(app)
logging.basicConfig(level=logging.INFO, format='[%(levelname)s] %(asctime)s - %(message)s')

SERVICENOW_URL = 'http://localhost:5001'
ORCHESTRATOR_URL = 'http://localhost:8080'
COPILOT_URL = os.getenv('COPILOT_URL', 'http://localhost:8010')
POLL_INTERVAL = 10# Optional: deliver the Post-Analysis Investigation Report back to a mailbox
# (e.g. the Mock Outlook inbox). Empty by default => feature off, no behavior
# change. Set OUTLOOK_DELIVERY_URL to enable (start_all.sh sets it for the demo).
OUTLOOK_DELIVERY_URL = os.getenv('OUTLOOK_DELIVERY_URL', '')
sse_clients = []
AGENT_ENDPOINTS = {
    "Root Orchestrator": "http://localhost:8080/health",
    "Knowledge Ingestion": "http://localhost:8001/health",
    "Postgres Agent": "http://localhost:8003/health",
    "Critic Agent": "http://localhost:8004/health",
    "Concept Agent": "http://localhost:8005/health",
    "Jira Agent": "http://localhost:8006/health",
    #"Confluence Agent": "http://localhost:8007/health",
    "Incident Logger Agent": "http://localhost:8007/health",
    "Notification Agent": "http://localhost:8008/health",
    "Anomaly Detection Agent": "http://localhost:8009/health",
    "SRE Copilot Agent": "http://localhost:8010/health",
    "RCA Agent": "http://localhost:8011/health",
    "ServiceNow Mock": "http://localhost:5001/health",
}

def send_sse_event(event_type, data):
    message = f"event: {event_type}\ndata: {json.dumps(data)}\n\n"
    for q in sse_clients:
        try: q.append(message)
        except Exception: pass

def _html_to_pdf(html):
    """Convert report HTML to PDF bytes using xhtml2pdf. Returns None on failure
    (delivery then falls back to the inline HTML only)."""
    try:
        from xhtml2pdf import pisa
    except ImportError:
        logging.warning("[REPORT] xhtml2pdf not installed; skipping PDF attachment.")
        return None
    try:
        buf = io.BytesIO()
        result = pisa.CreatePDF(src=html, dest=buf, encoding='utf-8')
        if result.err:
            logging.warning("[REPORT] PDF conversion reported %s error(s).", result.err)
            return None
        return buf.getvalue()
    except Exception as e:
        logging.warning("[REPORT] PDF conversion failed: %s", e)
        return None

def _deliver_report_email(incident_id, orchestrator_json):
    """Best-effort: email the Post-Analysis Investigation Report back to the
    inbox after an investigation completes. Never raises into the pipeline.
    Disabled unless OUTLOOK_DELIVERY_URL is set."""
    if not OUTLOOK_DELIVERY_URL:
        return
    try:
        inc = db.get_incident(incident_id)
        if not inc:
            return
        alert = inc.get('short_description') or 'Alert'
        try:
            body_html = report_template.render_report(inc, orchestrator_json)
        except Exception as e:
            logging.warning(f"[REPORT] Could not render report HTML: {e}")
            body_html = ''
        parts = []
        runbook = orchestrator_json.get('runbook_matched')
        if runbook: parts.append(f"Runbook matched: {runbook}")
        qr = orchestrator_json.get('query_results')
        if isinstance(qr, list): parts.append(f"Executed {len(qr)} diagnostic queries.")
        for k in ('final_summary', 'summary', 'analysis', 'ai_summary', 'conclusion'):
            v = orchestrator_json.get(k)
            if isinstance(v, str) and v.strip():
                parts.append(v.strip()); break
        body = "\n".join(parts) or "Investigation complete. See the attached report."
        payload = {
            'subject': f"Investigation Report: {alert}",
            'from': 'ai-triage@octopus.local',
            'body': body,
            'body_html': body_html,
        }
        # Attach the report as a PDF (the format generated after analysis).
        if body_html:
            pdf = _html_to_pdf(body_html)
            if pdf:
                safe = ''.join(c if c.isalnum() or c in ('-', '_') else '_' for c in str(alert))[:60] or 'report'
                payload['attachments'] = [{
                    'name': f"Investigation_Report_{safe}.pdf",
                    'contentType': 'application/pdf',
                    'size': len(pdf),
                    'contentBytes': base64.b64encode(pdf).decode('ascii'),
                }]
        requests.post(OUTLOOK_DELIVERY_URL, json=payload, timeout=15)
        logging.info(f"[REPORT] Delivered investigation report to inbox for incident {incident_id}")
    except Exception as e:
        logging.warning(f"[REPORT] Could not deliver report email: {e}")

def process_incident(incident_id, short_description):
    logging.info(f"[PIPELINE] Starting for incident {incident_id}: {short_description}")
    try:
        db.update_step_status(incident_id, 1, 'running'); send_sse_event('step_update', {'incident_id': incident_id, 'step_number': 1, 'status': 'running'})
        time.sleep(0.5)
        db.update_step_status(incident_id, 1, 'completed', "Received incident from listener."); send_sse_event('step_update', {'incident_id': incident_id, 'step_number': 1, 'status': 'completed'})
        
        logging.info(f"[PIPELINE] Calling orchestrator with: {{'alert_name': '{short_description}'}}")
        resp = requests.post(f'{ORCHESTRATOR_URL}/process-alert', json={'alert_name': short_description}, timeout=240)
        resp.raise_for_status()
        orchestrator_json = resp.json()
        db.update_step_status(incident_id, 2, 'completed', "Parameters extracted."); send_sse_event('step_update', {'incident_id': incident_id, 'step_number': 2, 'status': 'completed'})
        db.update_step_status(incident_id, 3, 'completed', f"Runbook found: {orchestrator_json.get('runbook_matched', 'N/A')}"); send_sse_event('step_update', {'incident_id': incident_id, 'step_number': 3, 'status': 'completed'})
        db.update_step_status(incident_id, 4, 'completed', f"Executed {len(orchestrator_json.get('query_results', []))} SQL queries."); send_sse_event('step_update', {'incident_id': incident_id, 'step_number': 4, 'status': 'completed'})
        db.update_step_status(incident_id, 5, 'completed', "Gemini analysis complete."); send_sse_event('step_update', {'incident_id': incident_id, 'step_number': 5, 'status': 'completed'})
        db.update_step_status(incident_id, 6, 'completed', "Post-analysis actions triggered."); send_sse_event('step_update', {'incident_id': incident_id, 'step_number': 6, 'status': 'completed'})
        
        db.complete_incident(incident_id, 'Report Generated', orchestrator_json)
        send_sse_event('incident_completed', {'incident_id': incident_id, 'analysis': orchestrator_json})
        _deliver_report_email(incident_id, orchestrator_json)
        logging.info(f"[PIPELINE] Completed incident {incident_id}")
    except Exception as e:
        error_message = f"Pipeline failed: {str(e)}"; logging.error(error_message, exc_info=True)
        db.fail_incident(incident_id, error_message)
        send_sse_event('incident_failed', {'incident_id': incident_id, 'error': error_message})

def poll_servicenow():
    logging.info("[LISTENER] Started polling ServiceNow...")
    while True:
        try:
            resp = requests.get(f'{SERVICENOW_URL}/api/now/table/incident', params={'sysparm_query': 'state=1'}, timeout=10)
            new_incidents = resp.json().get('result', [])
            for inc in new_incidents:
                if db.get_incident_by_snow_id(inc['sys_id']): continue
                
                logging.info(f"[LISTENER] New incident: {inc['number']} — {inc['short_description']}")
                
                # --- DEFINITIVE FIX: These three lines are the heart of the Golden State logic ---
                incident_id = db.create_incident(inc)
                send_sse_event('new_incident', db.get_incident(incident_id))
                threading.Thread(target=process_incident, args=(incident_id, inc['short_description']), daemon=True).start()
                # --- END OF FIX ---
                
                requests.patch(f"{SERVICENOW_URL}/api/now/table/incident/{inc['sys_id']}", json={'state': 2}, timeout=5)
        except requests.exceptions.RequestException: pass
        except Exception as e: logging.error(f"[LISTENER] Unhandled error: {e}", exc_info=True)
        time.sleep(POLL_INTERVAL)

# --- All API routes are correct and do not need changes ---
@app.route('/')
def serve_ui(): return send_from_directory('static', 'index.html')
@app.route('/api/dashboard/stats')
def dashboard_stats(): return jsonify(db.get_dashboard_stats())
@app.route('/api/incidents')
def list_incidents():
    incidents = db.get_all_incidents()
    for inc in incidents: inc['steps'] = db.get_pipeline_steps(inc['id'])
    return jsonify({'result': incidents})
@app.route('/api/incidents/<int:incident_id>')
def get_incident(incident_id):
    inc = db.get_incident(incident_id)
    if not inc: return jsonify({'error': 'Not found'}), 404
    inc['steps'] = db.get_pipeline_steps(incident_id)
    if inc.get('orchestrator_response'):
        try: inc['orchestrator_response'] = json.loads(inc['orchestrator_response'])
        except Exception: pass
    return jsonify({'result': inc})
@app.route('/api/incidents/<int:incident_id>/report.html')
def incident_report(incident_id):
    """Read-only: render the styled HTML investigation report for an incident."""
    inc = db.get_incident(incident_id)
    if not inc:
        return Response('<h3 style="font-family:sans-serif">Incident not found.</h3>',
                        status=404, mimetype='text/html')
    orch = inc.get('orchestrator_response')
    if isinstance(orch, str):
        try: orch = json.loads(orch)
        except Exception: orch = None
    if not orch:
        return Response('<h3 style="font-family:sans-serif">Analysis not available yet '
                        'for this incident.</h3>', status=200, mimetype='text/html')
    try:
        html = report_template.render_report(inc, orch)
    except Exception as e:
        logging.error(f"[REPORT] Failed to render report for incident {incident_id}: {e}", exc_info=True)
        return Response('<h3 style="font-family:sans-serif">Failed to generate report.</h3>',
                        status=500, mimetype='text/html')
    return Response(html, mimetype='text/html')
@app.route('/api/incidents/stream')
def stream_events():
    def event_stream():
        q = []; sse_clients.append(q)
        try:
            yield f"data: {json.dumps({'type': 'connected'})}\n\n"
            while True:
                if q: yield q.pop(0)
                time.sleep(0.1)
        finally:
            if q in sse_clients: sse_clients.remove(q)
    return Response(event_stream(), mimetype='text/event-stream', headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})
@app.route('/api/ingest-alert', methods=['POST'])
def ingest_alert():
    """Ingest an external alert (e.g. from the email listener) and run the SAME
    dashboard pipeline the ServiceNow poller uses, so the investigation shows up
    on the frontend. Mirrors the three-line logic inside poll_servicenow()."""
    data = request.get_json(force=True, silent=True) or {}
    alert_name = (data.get('alert_name') or '').strip()
    if not alert_name:
        return jsonify({'error': 'alert_name is required'}), 400
    sender = (data.get('sender') or 'email').strip()
    body = (data.get('body') or '').strip()
    source = (data.get('source') or 'Email').strip()

    ts = str(int(time.time() * 1_000_000))
    inc = {
        'sys_id': f'email-{ts}',
        'number': f'EML{ts[-7:]}',
        'short_description': alert_name,
        'description': body or f'{source} alert received from {sender}.',
        'priority': 3,
        'priority_label': 'Medium',
        'category': source,
        'assignment_group': '',
        'opened_at': None,
    }
    incident_id = db.create_incident(inc)
    send_sse_event('new_incident', db.get_incident(incident_id))
    threading.Thread(target=process_incident, args=(incident_id, alert_name), daemon=True).start()
    logging.info(f"[INGEST] New {source} alert -> incident {incident_id}: {alert_name}")
    return jsonify({'result': {'incident_id': incident_id, 'number': inc['number']}}), 201
@app.route('/api/copilot/ask', methods=['POST'])
def copilot_ask():
    """Proxy the dashboard chat widget to the SRE Copilot agent (same-origin),
    so the browser doesn't need CORS to reach port 8010."""
    data = request.get_json(force=True, silent=True) or {}
    question = (data.get('question') or '').strip()
    if not question:
        return jsonify({'error': 'question is required'}), 400
    payload = {'question': question, 'history': data.get('history') or []}
    try:
        resp = requests.post(f'{COPILOT_URL}/ask', json=payload, timeout=90)
        return jsonify(resp.json()), resp.status_code
    except requests.exceptions.RequestException as e:
        logging.error(f"[COPILOT] Proxy failed: {e}")
        return jsonify({'error': 'SRE Copilot agent is unavailable.', 'detail': str(e)}), 502
@app.route('/api/agent-health')
def get_agent_health():
    statuses = []
    for name, url in AGENT_ENDPOINTS.items():
        try:
            resp = requests.get(url, timeout=2)
            statuses.append({'name': name, 'status': 'online' if resp.status_code == 200 else 'error'})
        except Exception:
            statuses.append({'name': name, 'status': 'offline'})
    return jsonify(statuses)

if __name__ == '__main__':
    db.init_db()
    listener = threading.Thread(target=poll_servicenow, daemon=True)
    listener.start()
    print("=" * 60 + "\n  AI Incident Triage Backend (Definitive Golden State)\n" + "=" * 60)
    app.run(host='0.0.0.0', port=5000, debug=False)