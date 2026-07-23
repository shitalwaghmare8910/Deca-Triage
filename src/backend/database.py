# src/backend/database.py
# DEFINITIVE GOLDEN STATE (with NaN Fix)

import sqlite3
import json
from datetime import datetime, timezone

DB_PATH = 'triage.db'
STEP_DESCRIPTIONS = {
    1: 'Alert Reception', 2: 'Parameter Extraction', 3: 'Runbook Search',
    4: 'Diagnostic Queries', 5: 'AI Root Cause Analysis', 6: 'Post-Analysis Actions'
}

def adapt_datetime_iso(val):
    return val.isoformat()
def convert_timestamp(val):
    cleaned_val = val.decode().replace('Z', '+00:00')
    return datetime.fromisoformat(cleaned_val)

sqlite3.register_adapter(datetime, adapt_datetime_iso)
sqlite3.register_converter("timestamp", convert_timestamp)

def get_conn():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False, detect_types=sqlite3.PARSE_DECLTYPES)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with get_conn() as conn:
        c = conn.cursor()
        c.execute("""
        CREATE TABLE IF NOT EXISTS incidents (
            id INTEGER PRIMARY KEY AUTOINCREMENT, snow_sys_id TEXT UNIQUE NOT NULL, number TEXT NOT NULL,
            short_description TEXT, description TEXT, priority INTEGER, priority_label TEXT,
            category TEXT, assignment_group TEXT, opened_at TIMESTAMP, created_at TIMESTAMP NOT NULL,
            completed_at TIMESTAMP, state TEXT NOT NULL, orchestrator_response TEXT, ai_decision TEXT
        );""")
        c.execute("""
        CREATE TABLE IF NOT EXISTS pipeline_steps (
            id INTEGER PRIMARY KEY AUTOINCREMENT, incident_id INTEGER NOT NULL, step_number INTEGER NOT NULL,
            step_name TEXT NOT NULL, status TEXT NOT NULL, details TEXT,
            FOREIGN KEY (incident_id) REFERENCES incidents (id)
        );""")
    print(f"[DB] Initialized database at {DB_PATH}")

def create_incident(inc_data: dict) -> int:
    with get_conn() as conn:
        sql = ''' INSERT INTO incidents(snow_sys_id, number, short_description, description, priority, priority_label, category, assignment_group, opened_at, created_at, state)
                  VALUES(?,?,?,?,?,?,?,?,?,?,?) '''
        cursor = conn.cursor()
        opened_at_str = inc_data.get('opened_at')
        opened_at_dt = datetime.fromisoformat(opened_at_str.replace('Z', '+00:00')) if opened_at_str else None
        cursor.execute(sql, (
            inc_data.get('sys_id'), inc_data.get('number'), inc_data.get('short_description'), inc_data.get('description'), 
            inc_data.get('priority'), inc_data.get('priority_label'), inc_data.get('category'), 
            inc_data.get('assignment_group'), opened_at_dt, datetime.now(timezone.utc), 'in_progress'
        ))
        incident_id = cursor.lastrowid
        steps = [(incident_id, i, STEP_DESCRIPTIONS[i], 'pending', None) for i in range(1, 7)]
        conn.executemany("INSERT INTO pipeline_steps(incident_id, step_number, step_name, status, details) VALUES(?,?,?,?,?)", steps)
    return incident_id

def get_all_incidents() -> list:
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM incidents ORDER BY created_at DESC").fetchall()
        incidents = []
        for row in rows:
            incident = dict(row)
            for key, value in incident.items():
                if isinstance(value, datetime):
                    incident[key] = value.isoformat()
            incidents.append(incident)
        return incidents

def get_incident(incident_id: int) -> dict:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM incidents WHERE id = ?", (incident_id,)).fetchone()
        if not row: return None
        incident = dict(row)
        for key, value in incident.items():
            if isinstance(value, datetime):
                incident[key] = value.isoformat()
        return incident

def get_incident_by_snow_id(snow_sys_id: str):
    with get_conn() as conn:
        return conn.execute("SELECT id FROM incidents WHERE snow_sys_id = ?", (snow_sys_id,)).fetchone()

def get_pipeline_steps(incident_id: int) -> list:
    with get_conn() as conn:
        return [dict(row) for row in conn.execute("SELECT * FROM pipeline_steps WHERE incident_id = ? ORDER BY step_number", (incident_id,)).fetchall()]

def update_step_status(incident_id: int, step_number: int, status: str, details: str = None):
    with get_conn() as conn:
        conn.execute("UPDATE pipeline_steps SET status = ?, details = ? WHERE incident_id = ? AND step_number = ?",
                     (status, details, incident_id, step_number))

def complete_incident(incident_id: int, ai_decision: str, response_json: dict):
    with get_conn() as conn:
        conn.execute("UPDATE incidents SET state = 'completed', ai_decision = ?, completed_at = ?, orchestrator_response = ? WHERE id = ?",
                     (ai_decision, datetime.now(timezone.utc), json.dumps(response_json), incident_id))

def fail_incident(incident_id: int, error_details: str):
    with get_conn() as conn:
        conn.execute("UPDATE incidents SET state = 'failed', ai_decision = 'Failed', completed_at = ?, orchestrator_response = ? WHERE id = ?",
                     (datetime.now(timezone.utc), json.dumps({'error': error_details}), incident_id))

def get_dashboard_stats() -> dict:
    with get_conn() as conn:
        c = conn.cursor()
        total = c.execute("SELECT COUNT(*) FROM incidents").fetchone()[0]
        investigating = c.execute("SELECT COUNT(*) FROM incidents WHERE state = 'in_progress'").fetchone()[0]
        completed = c.execute("SELECT COUNT(*) FROM incidents WHERE state = 'completed'").fetchone()[0]
        failed = c.execute("SELECT COUNT(*) FROM incidents WHERE state = 'failed'").fetchone()[0]
        c.execute("SELECT SUM((JULIANDAY(completed_at) - JULIANDAY(created_at)) * 86400) FROM incidents WHERE state = 'completed' AND completed_at IS NOT NULL")
        total_time_row = c.fetchone()
        total_time = total_time_row[0] if total_time_row and total_time_row[0] else 0
        avg_time = (total_time / completed) if completed > 0 else 0
    return {'total': total, 'investigating': investigating, 'completed': completed, 'failed': failed, 'avg_time': avg_time}