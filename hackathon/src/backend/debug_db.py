
import sqlite3
import json

conn = sqlite3.connect('triage.db')
cursor = conn.cursor()

cursor.execute("SELECT id, number, state, ai_decision, orchestrator_response FROM incidents ORDER BY id DESC LIMIT 1;")
record = cursor.fetchone()
conn.close()

if record:
    id, number, state, ai_decision, response_str = record
    print("="*60)
    print("LATEST INCIDENT RECORD:")
    print("="*60)
    print(f"ID:          {id}")
    print(f"Number:      {number}")
    print(f"State:       {state}")
    print(f"AI Decision: {ai_decision}")
    
    # Try to format the JSON for readability
    try:
        parsed_json = json.loads(response_str)
        pretty_json = json.dumps(parsed_json, indent=2)
        print(f"Orchestrator Response:\n{pretty_json}")
    except (json.JSONDecodeError, TypeError):
        print(f"Orchestrator Response (raw): {response_str}")
    print("="*60)
else:
    print("No incidents found in the database.")
