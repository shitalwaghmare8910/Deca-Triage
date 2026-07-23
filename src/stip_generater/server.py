"""
Mock ServiceNow Incident Management Portal
Mimics ServiceNow's Table API for incidents + serves the portal UI.
"""

import uuid
import json
from datetime import datetime, timedelta
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import time # Make sure 'import time' is at the top of your file

app = Flask(__name__, static_folder='static', static_url_path='')
CORS(app)

# ─── In-Memory Incident Store ─────────────────────────────────────────────────

incidents = {}
incident_counter = 10001


def generate_sys_id():
    return str(uuid.uuid4()).replace('-', '')


def calculate_priority(impact, urgency):
    """ServiceNow priority matrix: Impact × Urgency"""
    matrix = {
        (1, 1): 1,  # Critical
        (1, 2): 2,  # High
        (1, 3): 3,  # Medium
        (2, 1): 2,  # High
        (2, 2): 3,  # Medium
        (2, 3): 4,  # Low
        (3, 1): 3,  # Medium
        (3, 2): 4,  # Low
        (3, 3): 5,  # Planning
    }
    return matrix.get((int(impact), int(urgency)), 4)


PRIORITY_LABELS = {1: 'Critical', 2: 'High', 3: 'Medium', 4: 'Low', 5: 'Planning'}
STATE_LABELS = {1: 'New', 2: 'In Progress', 3: 'On Hold', 6: 'Resolved', 7: 'Closed'}


def create_incident_record(data):
    # The global counter is no longer needed
    sys_id = generate_sys_id()
    now_dt = datetime.utcnow()
    now_iso = now_dt.isoformat() + 'Z'
    impact = int(data.get('impact', 2))
    urgency = int(data.get('urgency', 2))
    priority = calculate_priority(impact, urgency)
    state = int(data.get('state', 1))

    # --- THIS IS THE FIX ---
    # Generate a unique number based on the current time to avoid reset issues.
    # Format: INC + last 7 digits of the microsecond timestamp.
    timestamp_part = str(int(time.time() * 1_000_000))[-7:]
    incident_number = f'INC{timestamp_part}'
    # --- END OF FIX ---

    record = {
        'sys_id': sys_id,
        'number': incident_number, # Use the new, always-unique number
        'caller_id': data.get('caller_id', 'System'),
        'category': data.get('category', 'Software'),
        'subcategory': data.get('subcategory', ''),
        'short_description': data.get('short_description', ''),
        'description': data.get('description', ''),
        'impact': impact,
        'urgency': urgency,
        'priority': priority,
        'priority_label': PRIORITY_LABELS.get(priority, 'Low'),
        'state': state,
        'state_label': STATE_LABELS.get(state, 'New'),
        'assignment_group': data.get('assignment_group', ''),
        'assigned_to': data.get('assigned_to', ''),
        'contact_type': data.get('contact_type', 'Self-service'),
        'opened_at': data.get('opened_at', now_iso),
        'sys_created_on': now_iso,
        'sys_updated_on': now_iso,
        'resolved_at': '',
        'close_notes': '',
        'work_notes': '',
        'additional_comments': '',
    }
    incidents[sys_id] = record
    return record


def seed_data():
    """Pre-seed with realistic infrastructure incidents."""
    seeds = [
        {
            'short_description': 'HighDatabaseConnections',
            'description': 'The number of active database connections on payment-service has exceeded the configured threshold of 200. Current count: 347. This may lead to connection pool exhaustion and service degradation.',
            'category': 'Database',
            'subcategory': 'Performance',
            'impact': 1,
            'urgency': 1,
            'assignment_group': 'Database Operations',
            'assigned_to': 'DBA Team',
            'caller_id': 'Monitoring System',
            'contact_type': 'Monitoring',
            'state': 6,
            'opened_at': (datetime.utcnow() - timedelta(hours=3)).isoformat() + 'Z',
        },
        {
            'short_description': 'PSD2 Outbound Latency Alert',
            'description': 'PSD2 outbound API gateway is experiencing elevated latency. P99 response time has increased from 120ms to 2400ms. Multiple downstream bank connections returning 502 errors. GCO pathway affected.',
            'category': 'Network',
            'subcategory': 'Latency',
            'impact': 1,
            'urgency': 2,
            'assignment_group': 'API Gateway Team',
            'assigned_to': 'Platform Engineering',
            'caller_id': 'Grafana Alert',
            'contact_type': 'Monitoring',
            'state': 6,
            'opened_at': (datetime.utcnow() - timedelta(hours=5)).isoformat() + 'Z',
        },
        {
            'short_description': 'JAVANullPointerException',
            'description': 'Recurring NullPointerException in payment-service-1 pod. Stack trace points to TransactionProcessor.processPayment() line 247. Error rate: 15 occurrences in last 30 minutes. Affecting credit application flow.',
            'category': 'Application',
            'subcategory': 'Error',
            'impact': 2,
            'urgency': 2,
            'assignment_group': 'Application Support',
            'assigned_to': 'Java Dev Team',
            'caller_id': 'Splunk Alert',
            'contact_type': 'Monitoring',
            'state': 6,
            'opened_at': (datetime.utcnow() - timedelta(hours=8)).isoformat() + 'Z',
        },
        {
            'short_description': 'Istio 5xx Errors Spike',
            'description': 'Istio service mesh reporting 5xx error spike across payment-gateway namespace. Error rate increased from 0.1% to 4.7% in the last 15 minutes. Envoy proxy sidecar logs show upstream connection failures.',
            'category': 'Infrastructure',
            'subcategory': 'Service Mesh',
            'impact': 1,
            'urgency': 1,
            'assignment_group': 'Platform Engineering',
            'assigned_to': 'SRE Team',
            'caller_id': 'Prometheus Alert',
            'contact_type': 'Monitoring',
            'state': 6,
            'opened_at': (datetime.utcnow() - timedelta(hours=1)).isoformat() + 'Z',
        },
    ]
    for seed in seeds:
        create_incident_record(seed)


# ─── UI Routes ─────────────────────────────────────────────────────────────────

@app.route('/')
def serve_ui():
    return send_from_directory('static', 'index.html')


# ─── REST API (ServiceNow Table API style) ─────────────────────────────────────

@app.route('/api/now/table/incident', methods=['GET'])
def list_incidents():
    """List incidents with optional filtering via sysparm_query."""
    query = request.args.get('sysparm_query', '')
    limit = int(request.args.get('sysparm_limit', 100))

    results = list(incidents.values())

    # Parse simple ServiceNow query filters
    if query:
        filters = query.split('^')
        for f in filters:
            if '=' in f:
                key, val = f.split('=', 1)
                key = key.strip()
                val = val.strip()
                if key == 'state':
                    results = [r for r in results if str(r.get('state')) == val]
                elif key == 'priority':
                    results = [r for r in results if str(r.get('priority')) == val]
                elif key.endswith('>'):
                    # Handle sys_updated_on> type queries
                    actual_key = key.rstrip('>')
                    results = [r for r in results if r.get(actual_key, '') > val]
                else:
                    results = [r for r in results if str(r.get(key, '')) == val]

    # Sort by sys_updated_on descending (newest first)
    results.sort(key=lambda x: x.get('sys_updated_on', ''), reverse=True)
    results = results[:limit]

    return jsonify({'result': results})


@app.route('/api/now/table/incident/<sys_id>', methods=['GET'])
def get_incident(sys_id):
    """Get a single incident by sys_id."""
    record = incidents.get(sys_id)
    if not record:
        return jsonify({'error': {'message': 'Record not found'}}), 404
    return jsonify({'result': record})


@app.route('/api/now/table/incident', methods=['POST'])
def create_incident():
    """Create a new incident."""
    data = request.get_json(force=True)
    record = create_incident_record(data)
    return jsonify({'result': record}), 201


@app.route('/api/now/table/incident/<sys_id>', methods=['PATCH', 'PUT'])
def update_incident(sys_id):
    """Update an existing incident."""
    record = incidents.get(sys_id)
    if not record:
        return jsonify({'error': {'message': 'Record not found'}}), 404

    data = request.get_json(force=True)
    now = datetime.utcnow().isoformat() + 'Z'

    for key, val in data.items():
        if key in record and key not in ('sys_id', 'number', 'sys_created_on'):
            record[key] = val

    # Recalculate priority if impact or urgency changed
    if 'impact' in data or 'urgency' in data:
        record['priority'] = calculate_priority(record['impact'], record['urgency'])
        record['priority_label'] = PRIORITY_LABELS.get(record['priority'], 'Low')

    # Update state label
    if 'state' in data:
        record['state'] = int(data['state'])
        record['state_label'] = STATE_LABELS.get(record['state'], 'New')
        if record['state'] == 6:
            record['resolved_at'] = now

    record['sys_updated_on'] = now
    return jsonify({'result': record})


@app.route('/api/now/table/incident/<sys_id>', methods=['DELETE'])
def delete_incident(sys_id):
    """Delete an incident."""
    if sys_id in incidents:
        del incidents[sys_id]
        return '', 204
    return jsonify({'error': {'message': 'Record not found'}}), 404


# ─── Health ────────────────────────────────────────────────────────────────────

@app.route('/health')
def health():
    """Provides a standard health check endpoint."""
    return jsonify({"status": "healthy"})


# ─── Main ──────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    seed_data()
    print("=" * 60)
    print("  Mock ServiceNow Portal")
    print(f"  UI:  http://localhost:5001")
    print(f"  API: http://localhost:5001/api/now/table/incident")
    print(f"  Pre-seeded {len(incidents)} incidents")
    print("=" * 60)
    app.run(host='0.0.0.0', port=5001, debug=True)
