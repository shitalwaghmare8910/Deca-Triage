# src/agents/root-orchestrator/agent.py
# DEFINITIVE "FULL DEMO MODE" VERSION - WITH RESILIENCE FIX

import os, json, logging, requests, re, time
from typing import Dict, Any, List, Optional # Import Optional for Pydantic
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
import vertexai
from vertexai.generative_models import GenerativeModel

class C:
    BLUE, CYAN, GREEN, YELLOW, RED, END, BOLD, UNDERLINE = '\033[94m', '\033[96m', '\033[92m', '\033[93m', '\033[91m', '\033[0m', '\033[1m', '\033[4m'

logging.basicConfig(level=logging.INFO) # Changed to INFO for better visibility
app = FastAPI(title="Root Orchestrator Agent (FULL DEMO MODE)")

PROJECT_ID = os.getenv("GOOGLE_CLOUD_PROJECT", "db-dev-a7km-mp-aiw-pb-tech") # Using your specific project ID
LOCATION = os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1")
MODEL_NAME = "gemini-2.5-flash" # Recommending a more capable model if available, otherwise "gemini-1.0-pro"

# Ensure these environment variables or direct URLs are correct for your setup
KNOWLEDGE_API_URL = os.getenv("KNOWLEDGE_API_URL", "http://localhost:8001")
POSTGRES_API_URL = os.getenv("POSTGRES_API_URL", "http://localhost:8003")
CRITIC_AGENT_URL = os.getenv("CRITIC_AGENT_URL", "http://localhost:8004")
CONCEPT_AGENT_URL = os.getenv("CONCEPT_AGENT_URL", "http://localhost:8005")
JIRA_AGENT_URL = os.getenv("JIRA_AGENT_URL", "http://localhost:8006")
NOTIFICATION_AGENT_URL = os.getenv("NOTIFICATION_AGENT_URL", "http://localhost:8008")
# Dedicated Root Cause Analysis agent. When reachable it performs the deep RCA;
# if it is down we transparently fall back to the built-in inline analysis so the
# pipeline never stalls.
RCA_AGENT_URL = os.getenv("RCA_AGENT_URL", "http://localhost:8011")

vertexai.init(project=PROJECT_ID, location=LOCATION)
# Initialize the Gemini model once
gemini_model = GenerativeModel(MODEL_NAME)

class Alert(BaseModel): alert_name: str
class KeyFinding(BaseModel): severity: str; finding: str
class Analysis(BaseModel):
    root_cause_summary: str = Field(..., description="Concise summary of the incident's root cause.")
    detailed_analysis: str = Field(..., description="In-depth explanation of the incident, including contributing factors.")
    affected_components: List[str] = Field(..., description="List of system components impacted by the incident.")
    key_findings: List[KeyFinding] = Field(..., description="List of critical observations and insights.")
    recommended_actions: List[str] = Field(..., description="Actionable steps to resolve or mitigate the incident.")
    # Optional fields for better reporting if you wish to expand the model
    escalation_needed: Optional[bool] = Field(False, description="True if manual escalation is required.")
    escalation_reason: Optional[str] = Field(None, description="Reason for manual escalation.")
    contacts: List[str] = Field([], description="List of teams/individuals to contact.")
    # Optional confidence score (0-100) surfaced in the investigation report. Defaulted so
    # existing behavior is unchanged when the model omits it.
    confidence_score: Optional[int] = Field(None, description="Analysis confidence 0-100.")
    # Deep-RCA enrichment produced by the dedicated RCA agent. All optional and
    # additive, so the built-in inline analysis (which omits them) still validates.
    root_cause_category: Optional[str] = Field(None, description="Category of the root cause, e.g. Configuration, Capacity, Dependency.")
    causal_chain: List[Dict[str, Any]] = Field([], description="5-Whys style causal chain from symptom to root cause.")
    contributing_factors: List[str] = Field([], description="Secondary factors that worsened the incident.")
    blast_radius: Optional[str] = Field(None, description="Estimated user/business impact and scope.")


# CAID prefix -> human label, used only to enrich the investigation report.
CAID_TYPE_MAP = {
    "MMDEOFRA": "MnM (Mortgage & More) Request",
    "MMDEOPRA": "MnM (Mortgage & More) Request",
    "PBDECOFI": "CoFi (Consumer Finance) Request",
}


def _compute_confidence(runbook: Dict[str, Any], query_results: List[Dict[str, Any]], analysis: "Analysis") -> int:
    """Deterministic, explainable confidence (0-100) derived from the evidence.

    Used only as a fallback when the model does not provide its own score, so
    every alert gets a value that reflects its actual diagnostic quality.
    """
    score = 100
    # No runbook matched -> weak grounding.
    if not runbook or not runbook.get("alert_name"):
        score -= 30
    # SQL evidence quality.
    successful = [q for q in query_results if isinstance(q.get("result", {}).get("data"), list)]
    errored = [q for q in query_results if "error" in q]
    total_rows = sum(len(q["result"]["data"]) for q in successful)
    if query_results:
        if errored:
            score -= 20
        if total_rows == 0:
            score -= 25  # observability gap
    else:
        score -= 15  # no queries executed at all
    # Escalation implies the system itself is not fully certain.
    if getattr(analysis, "escalation_needed", False):
        score -= 15
    # Thin analysis output.
    if not getattr(analysis, "key_findings", None):
        score -= 10
    return max(5, min(100, score))


def _build_report_context(alert_name: str, runbook: Dict[str, Any], query_results: List[Dict[str, Any]], analysis: "Analysis") -> Dict[str, Any]:
    """Assemble an enrichment block for the styled investigation report.

    Purely additive: consumed by the notification agent and the backend report
    endpoint. Never affects the core triage flow.
    """
    # Extract a display CAID (supports dash + space formats) from filled queries.
    caid = None
    for q in query_results:
        fq = str(q.get("filled_query", ""))
        m = re.search(r"((?:MMDEOFRA|MMDEOPRA|PBDECOFI)[-\s][\w\-]+)", fq)
        if m:
            caid = m.group(1).strip()
            break
    prefix = re.match(r"([A-Z]+)", caid).group(1) if caid else None
    filled_query = next((q.get("filled_query") for q in query_results if q.get("filled_query")), None)
    # Hybrid confidence: prefer the model's own score, fall back to a computed one.
    confidence = analysis.confidence_score
    if confidence is None:
        confidence = _compute_confidence(runbook, query_results, analysis)
    return {
        "alert_name": alert_name,
        "runbook_matched": runbook.get("alert_name", "No runbook found"),
        "extracted_caid": caid,
        "caid_prefix": prefix,
        "caid_type_label": CAID_TYPE_MAP.get((prefix or "").upper()),
        "filled_query": filled_query,
        "confidence_score": confidence,
        "escalation_needed": analysis.escalation_needed,
        "escalation_reason": analysis.escalation_reason,
    }


def find_runbook(alert_name: str) -> Dict[str, Any]:
    logging.info(f"{C.BLUE}>>> [Step 2] Searching for a runbook...{C.END}")
    try:
        response = requests.post(f"{KNOWLEDGE_API_URL}/search", json={"query": alert_name, "top_k": 1}, timeout=10)
        response.raise_for_status()
        runbook_data = response.json().get("runbook", {})
        if runbook_data:
            logging.info(f"{C.GREEN}✅ Runbook Found:{C.END} {C.BOLD}{runbook_data.get('alert_name')}{C.END}")
        else:
            logging.warning(f"{C.YELLOW}⚠️ No runbook found for '{alert_name}'.{C.END}")
        return runbook_data
    except requests.exceptions.RequestException as e:
        logging.error(f"{C.RED}❌ Failed to communicate with Knowledge Agent: {e}{C.END}"); return {}
    except Exception as e:
        logging.error(f"{C.RED}❌ Failed to find runbook: {e}{C.END}"); return {}

def execute_queries(runbook: Dict[str, Any], alert_string: str) -> List[Dict[str, Any]]:
    logging.info(f"{C.BLUE}>>> [Step 3] Extracting and executing SQL...{C.END}")
    sql_queries_templates = runbook.get("sql_queries")
    if not isinstance(sql_queries_templates, list) or not sql_queries_templates:
        logging.warning(f"{C.YELLOW}⚠️ No SQL queries defined in runbook. Skipping.{C.END}"); return []

    ca_id_match = re.search(r'((?:MMDEOPRA|PBDECOFI) \S+ \S+ \S+)', alert_string)
    caid_full = ca_id_match.group(1).strip() if ca_id_match else None

    if not caid_full:
        logging.warning(f"{C.YELLOW}⚠️ Could not extract CA ID from alert string. Skipping SQL queries.{C.END}"); return []
    
    logging.info(f"{C.CYAN}    -> Extracted dynamic parameter (CA ID): {caid_full}{C.END}")
    
    query_results = []
    for i, query_obj in enumerate(sql_queries_templates):
        query_template = query_obj.get("query", "")
        # Safely replace the placeholder if it exists
        filled_query = query_template.replace("'<CA_ID>'", f"'{caid_full}'")
        
        logging.info(f"{C.CYAN}    -> Sending Query #{i+1} to Postgres Agent: {query_obj.get('purpose', 'N/A')}{C.END}")
        try:
            resp = requests.post(f"{POSTGRES_API_URL}/execute-query", json={"query": filled_query}, timeout=30)
            resp.raise_for_status()
            result_data = resp.json()
            # Ensure 'data' key exists and is a list
            if 'data' in result_data and isinstance(result_data['data'], list):
                logging.info(f"{C.GREEN}    ✅ Query #{i+1} Succeeded. Rows returned: {len(result_data['data'])}{C.END}")
            else:
                logging.warning(f"{C.YELLOW}    ⚠️ Query #{i+1} Succeeded, but 'data' key missing or not a list. Result: {result_data}{C.END}")
            query_results.append({"purpose": query_obj.get("purpose", ""), "result": result_data, "filled_query": filled_query})
        except requests.exceptions.RequestException as e:
            error_result = {"error": str(e), "message": "Failed to communicate with Postgres Agent or query timed out."}
            query_results.append({"purpose": query_obj.get("purpose", ""), "error": error_result, "filled_query": filled_query})
            logging.error(f"{C.RED}    ❌ Query #{i+1} Failed to communicate: {e}{C.END}")
        except Exception as e:
            error_result = {"error": str(e), "message": "An unexpected error occurred during query execution."}
            query_results.append({"purpose": query_obj.get("purpose", ""), "error": error_result, "filled_query": filled_query})
            logging.error(f"{C.RED}    ❌ Query #{i+1} Failed: {e}{C.END}")
    return query_results

def analyze_with_gemini(alert_name: str, runbook: Dict[str, Any], query_results: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Root Cause Analysis dispatcher.

    Delegates to the dedicated RCA agent (deep 5-Whys analysis). If that agent is
    unreachable or errors, transparently falls back to the built-in inline Gemini
    analysis so the pipeline is never blocked.
    """
    logging.info(f"{C.BLUE}>>> [Step 4] Delegating Root Cause Analysis to RCA Agent...{C.END}")
    try:
        resp = requests.post(
            f"{RCA_AGENT_URL}/analyze",
            json={"alert_name": alert_name, "runbook": runbook, "query_results": query_results},
            timeout=90,
        )
        resp.raise_for_status()
        analysis = resp.json()
        if isinstance(analysis, dict) and analysis.get("root_cause_summary"):
            logging.info(f"{C.GREEN}✅ RCA Agent analysis received.{C.END} {C.BOLD}{analysis.get('root_cause_summary')}{C.END}")
            return analysis
        logging.warning(f"{C.YELLOW}⚠️ RCA Agent returned unusable payload; falling back to inline analysis.{C.END}")
    except requests.exceptions.RequestException as e:
        logging.warning(f"{C.YELLOW}⚠️ RCA Agent unreachable ({e}); falling back to inline analysis.{C.END}")
    except Exception as e:
        logging.warning(f"{C.YELLOW}⚠️ RCA Agent error ({e}); falling back to inline analysis.{C.END}")
    return _analyze_inline(alert_name, runbook, query_results)


def _analyze_inline(alert_name: str, runbook: Dict[str, Any], query_results: List[Dict[str, Any]]) -> Dict[str, Any]:
    logging.info(f"{C.BLUE}>>> [Step 4] Calling Gemini for Root Cause Analysis (inline fallback)...{C.END}")

    # Prepare evidence for Gemini
    evidence_text = [
        f"Alert Name: \"{alert_name}\"",
        f"Matched Runbook: \"{runbook.get('alert_name', 'N/A')}\"",
    ]
    
    # --- MODIFICATION START: Safely process query results and append to evidence ---
    sql_status = "SQL queries were not executed."
    if query_results:
        successful_queries = [res for res in query_results if 'result' in res and 'data' in res['result']]
        failed_queries = [res for res in query_results if 'error' in res]

        if successful_queries:
            for s_query in successful_queries:
                num_rows = len(s_query['result']['data'])
                if num_rows == 0:
                    evidence_text.append(f"Diagnostic Database Query (Purpose: {s_query['purpose']}): Returned 0 rows for the correlation ID. This is a critical observability gap.")
                else:
                    evidence_text.append(f"Diagnostic Database Query (Purpose: {s_query['purpose']}): Returned {num_rows} rows. First few records: {json.dumps(s_query['result']['data'][:3])}") # Limit for prompt length
            sql_status = "SQL queries executed."
        else:
            sql_status = "All SQL queries failed or returned no usable data."
        
        if failed_queries:
            for f_query in failed_queries:
                evidence_text.append(f"Diagnostic Database Query (Purpose: {f_query['purpose']}): Failed with error: {f_query.get('error', {}).get('message', 'Unknown error')}")
    else:
        evidence_text.append("No SQL queries were executed due to missing runbook definition or missing CA ID.")
    # --- MODIFICATION END ---


    prompt = f"""As an expert SRE, analyze the incident below and generate a structured JSON report. You MUST output a valid JSON object.
    
    **Incident Evidence:**
    {'- '.join(evidence_text)}

    **Analysis Instructions:**
    1.  Based ONLY on the provided evidence, generate a JSON object with the following keys. Ensure all fields are populated, even if with 'N/A' or empty lists if data is insufficient.
        -   `root_cause_summary` (string): Concise summary of the root cause.
        -   `detailed_analysis` (string): In-depth explanation. Emphasize any data gaps (like 0 SQL rows).
        -   `affected_components` (list of strings): System components impacted.
        -   `key_findings` (list of objects: `severity` [CRITICAL, HIGH, MEDIUM, LOW], `finding` [string]): Critical observations. If the SQL query returned 0 rows, include a 'CRITICAL' finding about the observability gap.
        -   `recommended_actions` (list of strings): Actionable steps.
        -   `escalation_needed` (boolean): True if manual intervention is likely needed.
        -   `escalation_reason` (string, optional): Why escalation is needed.
        -   `contacts` (list of strings): Teams/individuals to contact (e.g., "SRE Team", "External XS2A Support").
        -   `confidence_score` (integer 0-100): Your confidence in this root-cause analysis, based ONLY on how complete and conclusive the evidence is. Use HIGH (85-100) when a runbook matched and SQL evidence clearly explains the failure; MEDIUM (60-84) when evidence is partial or requires human confirmation; LOW (0-59) when there is an observability gap (0 rows, missing runbook, query errors). Escalated incidents should generally score below 80.

    2.  If the evidence indicates an observability gap (e.g., 0 rows from SQL, missing runbook), make sure this is prominently featured in `detailed_analysis` and `key_findings`.
    3.  DO NOT include any conversational text outside the JSON.
    """
    
    try:
        logging.info(f"{C.CYAN}    -> Sending evidence to Vertex AI...{C.END}")
        # Use the pre-initialized gemini_model
        response = gemini_model.generate_content(prompt, generation_config={"response_mime_type": "application/json"})
        
        # Directly get the text from the response, assuming it's already JSON thanks to mime_type
        raw_json_text = response.text.strip()
        analysis = json.loads(raw_json_text)
        
        logging.info(f"{C.GREEN}✅ Gemini analysis successful. Summary:{C.END} {C.BOLD}{analysis.get('root_cause_summary', 'No summary available.')}{C.END}")
        return analysis
    except Exception as e:
        logging.error(f"{C.RED}❌ Gemini analysis failed: {e}. Raw response (if any): {response.text if 'response' in locals() else 'N/A'}{C.END}")
        return {
            "root_cause_summary": "AI analysis failed due to internal error.",
            "detailed_analysis": f"Error: {e}. Check orchestrator logs for full details. Original evidence: {evidence_text}",
            "affected_components": ["AI System"],
            "key_findings": [{"severity": "CRITICAL", "finding": "AI analysis could not be completed."}],
            "recommended_actions": ["Manually investigate orchestrator logs and re-run analysis."],
            "escalation_needed": True,
            "escalation_reason": "Automated analysis failed."
        }

@app.post("/process-alert")
async def process_alert_pipeline(alert: Alert):
    print("\n" + "="*80 + f"\n{C.BOLD}🎬 NEW INCIDENT: {alert.alert_name}{C.END}\n" + "="*80)
    logging.info(f"{C.BLUE}>>> [Step 1] Starting Phase 1: Triage & Analysis...{C.END}")
    
    runbook = find_runbook(alert.alert_name)
    query_results = execute_queries(runbook, alert.alert_name)
    analysis_json = analyze_with_gemini(alert.alert_name, runbook, query_results)
    
    try:
        # Pydantic validation: Ensure the AI's output conforms to our expected structure
        full_analysis_payload = Analysis(**analysis_json)
    except Exception as e:
        logging.error(f"{C.RED}❌ Pydantic Validation Error after Gemini analysis: {e}. Gemini's output: {analysis_json}{C.END}")
        # Construct a fallback payload for error reporting
        full_analysis_payload = Analysis(
            root_cause_summary="AI output validation failed.",
            detailed_analysis=f"The AI generated a response that did not conform to the expected JSON structure. Error: {e}. Original AI output: {json.dumps(analysis_json)}",
            affected_components=["AI System", "Orchestrator"],
            key_findings=[{"severity": "CRITICAL", "finding": "AI output invalid, manual review needed."}],
            recommended_actions=["Review AI prompt and model output for structural consistency.", "Manually analyze incident."],
            escalation_needed=True,
            escalation_reason="AI output is malformed or incomplete."
        )

    logging.info(f"\n{C.BLUE}>>> [Step 5] Starting Phase 2: Post-Analysis & Action...{C.END}")
    
    # Additive enrichment for the styled investigation report (does not affect triage).
    report_context = _build_report_context(alert.alert_name, runbook, query_results, full_analysis_payload)

    # Store aggregated results to send back to the main Flask app
    orchestrator_final_response_data = {
        "alert_name": alert.alert_name,
        "runbook_matched": runbook.get('alert_name', 'No runbook found'),
        "query_results": query_results,
        "analysis_summary": full_analysis_payload.root_cause_summary, # Use summary for easy display
        "detailed_analysis_report": full_analysis_payload.model_dump(), # Full payload for detailed report
        "recommended_actions": full_analysis_payload.recommended_actions,
        "key_concepts": [f.finding for f in full_analysis_payload.key_findings], # Simplified for concept agent or display
        "sql_query_result": "No SQL queries defined" if not runbook.get("sql_queries") else ("SQL queries executed successfully" if not [res for res in query_results if 'error' in res or (res.get('result', {}).get('data') is not None and len(res['result']['data']) == 0)] else "SQL queries encountered issues (0 rows or error)"),
        "report_context": report_context,
    }

    agent_calls = {
        "Critic Agent": (CRITIC_AGENT_URL, "/evaluate-analysis", {"analysis": full_analysis_payload.model_dump()}),
        "Concept Agent": (CONCEPT_AGENT_URL, "/identify-concepts", {"analysis": full_analysis_payload.model_dump()}),
        "Jira Agent": (JIRA_AGENT_URL, "/create-ticket", {"summary": full_analysis_payload.root_cause_summary, "description": full_analysis_payload.detailed_analysis, "incident_id": alert.alert_name}), # Pass more context
        "Notification Agent": (NOTIFICATION_AGENT_URL, "/send-notification", {"incident_id": alert.alert_name, "actions": full_analysis_payload.recommended_actions, "summary": full_analysis_payload.root_cause_summary, "report_context": report_context, "detailed_analysis_report": full_analysis_payload.model_dump(), "query_results": query_results}), # Pass actions
    }
    
    post_analysis_results = {}
    for name, (url, endpoint, payload) in agent_calls.items():
        try:
            logging.info(f"{C.CYAN}    -> Calling {name}...{C.END}")
            # Use the specific payload for each agent call
            response = requests.post(f"{url}{endpoint}", json=payload, timeout=30)
            response.raise_for_status()
            post_analysis_results[name] = {"status": "success", "response": response.json()}
            logging.info(f"{C.GREEN}    ✅ {name} call successful.{C.END}")
        except requests.exceptions.RequestException as e:
            post_analysis_results[name] = {"status": "failed", "error": str(e), "message": "Failed to communicate with agent."}
            logging.error(f"{C.RED}    ❌ {name} call failed to communicate: {e}{C.END}")
        except Exception as e:
            post_analysis_results[name] = {"status": "failed", "error": str(e), "message": "An unexpected error occurred during agent call."}
            logging.error(f"{C.RED}    ❌ {name} call failed: {e}{C.END}")

    # Add post-analysis results to the final response
    orchestrator_final_response_data["post_analysis_results"] = post_analysis_results
    
    logging.info(f"\n{C.BOLD}🏁 ORCHESTRATION COMPLETE. Returning final report.{C.END}\n")
    
    # Return the full detailed report under 'analysis' key
    return orchestrator_final_response_data

@app.get("/health")
def health(): return {"status": "healthy"}