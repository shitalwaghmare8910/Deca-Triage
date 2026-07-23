# src/agents/concept_agent/agent.py
# DEFINITIVE "JSON DATETIME" FIX
#
# This final version fixes the '500 Internal Server Error' by correctly handling
# the serialization of 'datetime' objects returned from the SQLite database.
# It explicitly converts datetime fields to ISO strings before JSON serialization,
# preventing the agent from crashing when preparing the prompt for Gemini.

import os
import json
import datetime
from fastapi import FastAPI, Request, HTTPException
from dotenv import load_dotenv

import vertexai
from vertexai.generative_models import GenerativeModel, Part
import sqlite3

# --- Configuration ---
load_dotenv()

try:
    GCP_PROJECT_ID = os.environ['GOOGLE_CLOUD_PROJECT']
    GCP_REGION = os.environ['GOOGLE_CLOUD_LOCATION']
    vertexai.init(project=GCP_PROJECT_ID, location=GCP_REGION)
    DB_PATH = 'src/backend/triage.db'
    print(f"✅ Vertex AI Initialized. Project: {GCP_PROJECT_ID}")
    print(f"✅ Database configuration loaded for SQLite at '{DB_PATH}'.")
except KeyError as e:
    print(f"❌ CRITICAL ERROR: Environment variable {e} not found.")
    GCP_PROJECT_ID = None

# Configure the Gemini model
generation_config = {"temperature": 0.4, "max_output_tokens": 4096} # Increased token limit for large context
model = GenerativeModel("gemini-2.5-flash", generation_config=generation_config)

app = FastAPI(title="Proactive Concept Agent (SQLite - Robust)")

# --- Core Logic ---
def get_historical_context(concepts_from_current_incident: list, days: int = 30) -> list | None:
    conn = None
    print("\n[Stage 2.1] Connecting to the local 'triage.db' SQLite database...")
    try:
        conn = sqlite3.connect(f'file:{DB_PATH}?mode=ro', uri=True)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        print("   -> ✅ Database connection successful.")
        
        search_keywords = [k for k in concepts_from_current_incident if len(k) > 3][:5]
        if not search_keywords:
            return []

        print(f"\n[Stage 2.2] Querying 'triage_db' for historical incidents...")
        print(f"   -> Query Method: Searching 'short_description' for keywords: {search_keywords}")

        start_date = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=days)).isoformat()
        
        base_query = "SELECT id, created_at, short_description FROM incidents WHERE created_at >= ? AND ("
        like_clauses = " OR ".join(["short_description LIKE ?"] * len(search_keywords))
        sql_query = base_query + like_clauses + ");"
        params = [start_date] + [f"%{keyword}%" for keyword in search_keywords]
        
        cursor.execute(sql_query, params)
        rows = cursor.fetchall()
        
        # --- THIS IS THE FIX ---
        # Manually convert sqlite3.Row objects to dicts and format datetime
        historical_incidents = []
        for row in rows:
            record = dict(row)
            # Ensure 'created_at' is a string before returning
            if 'created_at' in record and isinstance(record['created_at'], (datetime.datetime, str)):
                 # The DB driver might return a string or a datetime object depending on converters
                 # We ensure it's always a string for JSON.
                 record['created_at'] = str(record['created_at'])
            historical_incidents.append(record)
        # --- END OF FIX ---
        
        print(f"   -> Database Response: Found {len(historical_incidents)} related historical incidents.")
        return historical_incidents
    except sqlite3.Error as e:
        print(f"   -> ❌ Database Error: {e}")
        return None
    finally:
        if conn:
            conn.close()
            print("   -> Database connection closed.")


def get_strategic_prompt(current_incident_json: str, historical_context_json: str) -> str:
    # This prompt function is correct and does not need to change.
    prompt = f"""
    You are a distinguished SRE strategist...
    ...
    Provide your response as a single, clean JSON object with the keys "pattern_summary", "preventive_measures", and "strategic_urgency_score".
    """
    print("\n[Stage 3.1] Preparing a detailed prompt for the Gemini LLM.")
    print("   -> Persona: Distinguished SRE Strategist.")
    print("   -> Goal: Identify systemic risks and recommend long-term preventive measures.")
    print("   -> Context Provided: Current incident data AND historical incident data from 'triage.db'.")
    return prompt

# --- FastAPI Endpoint ---
@app.post("/identify-concepts")
async def process_incident_for_concepts(request: Request):
    print("\n================================================================================")
    print("🧠  PROACTIVE CONCEPT AGENT ACTIVATED: Shifting from reactive to strategic analysis.")
    print("================================================================================")
    
    try:
        current_incident = await request.json()
        analysis_data = current_incident.get("analysis", {})
        analysis_text = analysis_data.get("detailed_analysis", "")
        keywords = list(set(analysis_text.split()))

        print("\n[Stage 1] Incident Context Received from Orchestrator.")
        print(f"   -> Using keywords from detailed analysis to find historical matches: {keywords[:10]}...")
        if not keywords:
            return {"status": "skipped", "reason": "No detailed analysis found."}
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON payload.")

    print("\n[Stage 2] Beginning Historical Analysis...")
    historical_incidents = get_historical_context(keywords)

    if historical_incidents is None:
        raise HTTPException(status_code=500, detail="Failed to connect to triage.db for historical analysis.")

    print(f"\n[Stage 3] Calling Google's '{model._model_name}' model via Vertex AI...")
    
    # The json.dumps call will now succeed because we pre-formatted the datetime objects.
    prompt = get_strategic_prompt(json.dumps(current_incident, indent=2), json.dumps(historical_incidents, indent=2))
    
    try:
        response = model.generate_content(prompt)
        response_text = response.text
        
        print("\n[Stage 3.2] Raw response received from Gemini:")
        print("--------------------------------------------------------------------------------")
        print(response_text)
        print("--------------------------------------------------------------------------------")

        print("\n[Stage 3.3] Parsing the Gemini response to extract the structured JSON object...")
        json_start = response_text.find('{')
        json_end = response_text.rfind('}') + 1
        
        if json_start != -1 and json_end != 0:
            clean_json_str = response_text[json_start:json_end]
            strategic_analysis = json.loads(clean_json_str)
            print("   -> ✅ Parsing successful.")
        else:
            raise ValueError("No valid JSON object found in Gemini response.")

        print("\n[Stage 4] Strategic Analysis Complete. Here are the findings:")
        print("--------------------------------------------------------------------------------")
        print(json.dumps(strategic_analysis, indent=2))
        print("--------------------------------------------------------------------------------")
        
        print("\n✅ CONCEPT AGENT TASK COMPLETE. Returning strategic insights to Orchestrator.")
        print("================================================================================\n")
        
        return {"status": "analysis_complete", "strategic_analysis": strategic_analysis}
    except Exception as e:
        print(f"❌ An error occurred during strategic analysis: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/health")
def health():
    """Health check endpoint."""
    return {"status": "healthy"}