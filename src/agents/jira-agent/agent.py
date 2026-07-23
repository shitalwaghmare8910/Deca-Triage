# src/agents/jira_agent/agent.py
# DEFINITIVE "DEMO-READY JIRA AGENT" VERSION (NO SECRETS)
#
# This version is designed for a seamless demonstration in AI Workbench.
# It REMOVES all Google Secret Manager dependencies and operates in a permanent
# "Mock Mode". It still uses Gemini to intelligently map incident data to a
# complex Jira template and creates a realistic-looking fake ticket.

import os
import json
from fastapi import FastAPI, Request, HTTPException
from dotenv import load_dotenv

# Gemini/Vertex AI imports
import vertexai
from vertexai.generative_models import GenerativeModel

# --- Configuration ---
load_dotenv()

try:
    GCP_PROJECT_ID = os.environ['GOOGLE_CLOUD_PROJECT']
    GCP_REGION = os.environ['GOOGLE_CLOUD_LOCATION']
    
    # Jira specific configuration
    JIRA_SERVER = os.environ.get("JIRA_SERVER", "https://deutschebank.atlassian.net")
    JIRA_PROJECT_KEY = os.environ.get("JIRA_PROJECT_KEY", "ADENG")

    vertexai.init(project=GCP_PROJECT_ID, location=GCP_REGION)
    
    print(f"✅ Vertex AI Initialized. Project: {GCP_PROJECT_ID}")
    print(f"✅ Jira configuration loaded for Server: {JIRA_SERVER}, Project: {JIRA_PROJECT_KEY}")
    
    # --- THIS IS THE FIX: Defaulting to Mock Mode for Demo ---
    print("\n[Auth] Jira credentials not configured for this demo environment.")
    print("   -> ✅ Agent will run in permanent 'Mock Mode' as designed.")
    MOCK_MODE = True
    # --- END OF FIX ---

except KeyError as e:
    print(f"❌ CRITICAL ERROR: Environment variable {e} not found.")
    GCP_PROJECT_ID = None
    MOCK_MODE = True # Also enter mock mode if GCP config is missing

# Configure the Gemini model
generation_config = {"temperature": 0.2, "max_output_tokens": 4096}
model = GenerativeModel("gemini-2.5-flash", generation_config=generation_config)

app = FastAPI(title="Jira Agent (Demo Mode)")

# --- Core Logic with Detailed Logging ---

def get_jira_mapper_prompt(incident_data_json: str) -> str:
    """Creates a prompt for Gemini to map incident data to the complex Jira format."""
    prompt = f"""
    You are a Jira expert specializing in SRE workflows at Deutsche Bank. Your task is to take a raw incident analysis
    and map it perfectly into the required JSON format for creating a "Story" in the "{JIRA_PROJECT_KEY}" project.

    Use the following incident data:
    ```json
    {incident_data_json}
    ```

    Now, create the JSON payload for the Jira API. Follow these rules precisely:
    1.  **Project and Issue Type:** The project key is "{JIRA_PROJECT_KEY}" and the issue type is "Story".
    2.  **Summary:** Create a concise, descriptive summary like "SRE | Investigate | <Original Incident Summary>".
    3.  **Description:** Format a detailed, well-structured description using Jira's markup. Include sections for "Root Cause Analysis", "Key Findings", and "Recommended Actions" based on the input data.
    4.  **Priority:** Map the incident priority. If the analysis contains "CRITICAL" findings, set the priority to "High". Otherwise, use "Medium".
    5.  **Labels:** Extract key technical terms from the 'affected_components' and 'detailed_analysis' to use as labels (e.g., "PSD2", "Observability-Gap", "XS2A").
    6.  **Custom Fields:** You MUST populate the required custom fields.
        - `customfield_xxxxx` (for 'Activity Type'): Set this to "Other".
        - `customfield_yyyyy` (for 'Security Level'): Set this to "Internal".
    7.  **Do not invent data** for fields not present in the input (like Due Date, Sponsors, etc.). Only map the provided incident analysis.

    Provide ONLY the final, clean JSON object for the Jira API `create_issue` call. Do not include any other text.
    Your output must start with `{{` and end with `}}`.
    """
    print("\n[Stage 2.1] Preparing a detailed prompt for the Gemini LLM.")
    print("   -> Persona: Jira Expert / SRE Specialist.")
    print("   -> Goal: Map the simple incident analysis to the complex enterprise Jira ticket format.")
    print("   -> Context Provided: Full incident analysis from the Orchestrator.")
    return prompt

# --- FastAPI Endpoint ---

@app.post("/create-ticket")
async def create_jira_ticket(request: Request):
    """
    Receives incident data, uses Gemini to format it, and creates a mock Jira ticket.
    """
    print("\n================================================================================")
    print("🎫  JIRA AGENT ACTIVATED: Bridging automated analysis with project management.")
    print("================================================================================")
    
    try:
        incident_data = await request.json()
        print("\n[Stage 1] Incident Context Received from Orchestrator.")
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON payload.")

    # Stage 2: Use Gemini to map data to the complex Jira format
    print(f"\n[Stage 2] Calling Google's '{model._model_name}' model via Vertex AI...")
    prompt = get_jira_mapper_prompt(json.dumps(incident_data, indent=2))
    
    try:
        response = model.generate_content(prompt)
        response_text = response.text
        
        print("\n[Stage 2.2] Raw response from Gemini (Simulated Jira JSON payload):")
        print("--------------------------------------------------------------------------------")
        print(response_text)
        print("--------------------------------------------------------------------------------")

        print("\n[Stage 2.3] Parsing the Gemini response to get the Jira API payload...")
        json_start = response_text.find('{')
        json_end = response_text.rfind('}') + 1
        
        if json_start != -1 and json_end != 0:
            jira_payload_str = response_text[json_start:json_end]
            jira_payload = json.loads(jira_payload_str)
            print("   -> ✅ Parsing successful. Simulated Jira payload is ready.")
        else:
            raise ValueError("No valid JSON object found in Gemini response.")

    except Exception as e:
        print(f"❌ An error occurred during Gemini mapping: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to generate Jira payload: {e}")

    # Stage 3: Create the Mock Jira Ticket
    print("\n[Stage 3] Simulating interaction with Jira API...")

    if MOCK_MODE:
        mock_key = f"{JIRA_PROJECT_KEY}-DEMO{os.urandom(2).hex().upper()}"
        print(f"   -> ✅ Successfully created  Jira ticket: {mock_key}")
        print("\n✅ JIRA AGENT TASK COMPLETE.  Ticket details returned to Orchestrator.")
        print("================================================================================\n")
        return {"status": "success_mock", "ticket_key": mock_key, "ticket_url": f"{JIRA_SERVER}/browse/{mock_key}"}
    else:
        # This block will not be reached in this demo version, but is kept for completeness.
        print("   -> ERROR: Real Jira connection was attempted in a demo-only agent.")
        raise HTTPException(status_code=500, detail="Agent is configured for Mock Mode only.")

@app.get("/health")
def health():
    return {"status": "healthy"}