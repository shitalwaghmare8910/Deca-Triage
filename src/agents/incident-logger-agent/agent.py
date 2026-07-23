# src/agents/incident-logger-agent/agent.py
import uvicorn
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import requests

# --- Configuration ---
SERVICENOW_URL = "http://localhost:5001"

# --- API Models ---
class IncidentUpdate(BaseModel):
    incident_sys_id: str
    comment_text: str
    state: int = 6 # 6 = Resolved

# --- FastAPI App ---
app = FastAPI()

@app.post("/update-incident")
async def update_incident(update: IncidentUpdate):
    target_url = f"{SERVICENOW_URL}/api/now/table/incident/{update.incident_sys_id}"
    payload = {
        "work_notes": update.comment_text,
        "state": update.state # Mark as Resolved
    }
    
    try:
        print(f"--- [Incident Logger] Updating ServiceNow Incident {update.incident_sys_id} ---")
        response = requests.patch(target_url, json=payload, timeout=5)
        response.raise_for_status() # Raise an exception for non-2xx status codes
        print(f"Successfully updated incident. Status: {response.status_code}")
        return {"status": "incident_updated", "target": update.incident_sys_id}
    except requests.exceptions.RequestException as e:
        print(f"Error updating ServiceNow: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to connect to Mock ServiceNow API at {target_url}")

@app.get("/health")
def health():
    return {"status": "healthy", "service": "incident-logger-agent"}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8007)