# src/agents/sre-copilot-agent/agent.py
# ─────────────────────────────────────────────────────────────────────────────
# "Ask the SRE" Copilot Agent (port 8010)
#
# A conversational assistant for on-call engineers. Given a natural-language
# question ("why did payments fail in the last hour?"), it:
#   1. PLANS — asks Gemini what evidence it needs (a read-only SQL query over the
#      audit_log, a runbook lookup, and/or recent incident history).
#   2. GATHERS — runs the plan safely:
#        • SQL goes through the existing Postgres Agent (:8003) and is guarded to
#          be strictly READ-ONLY (SELECT/WITH only, single statement, auto-LIMIT).
#        • Runbooks come from the Knowledge Ingestion RAG agent (:8001).
#        • Incident history comes from the backend (:5000).
#   3. ANSWERS — asks Gemini to compose a grounded answer from the evidence.
#
# It reuses the platform's existing services, so it adds no new DB credentials
# and no new data stores.
# ─────────────────────────────────────────────────────────────────────────────

import os
import re
import json
import logging
from typing import Any, Dict, List, Optional

import requests
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from dotenv import load_dotenv

import vertexai
from vertexai.generative_models import GenerativeModel

load_dotenv()

logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(asctime)s - %(message)s")
log = logging.getLogger("sre-copilot")

PROJECT_ID = os.getenv("GOOGLE_CLOUD_PROJECT", "db-dev-a7km-mp-aiw-pb-tech")
LOCATION = os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1")
MODEL_NAME = os.getenv("COPILOT_MODEL", "gemini-2.5-flash")

POSTGRES_API_URL = os.getenv("POSTGRES_API_URL", "http://localhost:8003")
KNOWLEDGE_API_URL = os.getenv("KNOWLEDGE_API_URL", "http://localhost:8001")
BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:5000")

AUDIT_TABLE = os.getenv("AUDIT_TABLE", "xs2a_accounts_db.audit_log")
MAX_SQL_ROWS = int(os.getenv("COPILOT_MAX_SQL_ROWS", "50"))

vertexai.init(project=PROJECT_ID, location=LOCATION)
_model = GenerativeModel(MODEL_NAME, generation_config={"temperature": 0.2, "max_output_tokens": 2048})

app = FastAPI(title="Ask-the-SRE Copilot Agent")

# Schema description the planner uses to write correct SQL.
SCHEMA_HINT = f"""Table: {AUDIT_TABLE}
Columns:
  - audit_id (uuid/text)
  - credit_application_id (text)   e.g. 'MMDEOPRA 12 3456 7890', 'PBDECOFI 98 7654 3210'
  - event_type (text)             e.g. CONSENT_CREATION, ACCOUNT_LIST_FETCH, TRANSACTION_FETCH, PAYMENT_INITIATION
  - code (numeric)                HTTP-style status code (200 ok; 4xx/5xx errors)
  - description (text)
  - severity (text)               one of INFO, WARN, ERROR, CRITICAL
  - created_date_time (timestamp)
An event is an ERROR when code >= 400 OR severity IN ('ERROR','CRITICAL')."""


# --- Read-only SQL guard -----------------------------------------------------
_FORBIDDEN = re.compile(
    r"\b(insert|update|delete|drop|alter|create|truncate|grant|revoke|"
    r"merge|copy|call|do|vacuum|comment|reindex|refresh|attach|"
    r"replace|upsert)\b",
    re.IGNORECASE,
)


def _sanitize_sql(sql: str) -> str:
    """Allow only a single read-only SELECT/WITH statement. Raise otherwise.

    This is the security boundary: the query text is model-generated from
    untrusted user input, and the Postgres Agent will execute it with real DB
    credentials, so we must reject anything that could mutate data.
    """
    if not sql or not sql.strip():
        raise ValueError("Empty SQL.")
    cleaned = sql.strip().rstrip(";").strip()

    # Single statement only.
    if ";" in cleaned:
        raise ValueError("Only a single SQL statement is allowed.")
    # No SQL comments (a common injection-hiding trick).
    if "--" in cleaned or "/*" in cleaned:
        raise ValueError("SQL comments are not allowed.")
    # Must start with SELECT or WITH.
    if not re.match(r"^\s*(select|with)\b", cleaned, re.IGNORECASE):
        raise ValueError("Only SELECT/WITH queries are allowed.")
    # No mutating keywords anywhere.
    if _FORBIDDEN.search(cleaned):
        raise ValueError("Query contains a forbidden (write) keyword.")

    # Enforce a row cap so we never pull the whole table into a prompt.
    if not re.search(r"\blimit\b", cleaned, re.IGNORECASE):
        cleaned = f"{cleaned} LIMIT {MAX_SQL_ROWS}"
    return cleaned


# --- Evidence gatherers ------------------------------------------------------
def _run_sql(sql: str) -> Dict[str, Any]:
    safe = _sanitize_sql(sql)
    resp = requests.post(f"{POSTGRES_API_URL}/execute-query", json={"query": safe}, timeout=30)
    resp.raise_for_status()
    data = resp.json().get("data")
    rows = data if isinstance(data, list) else []
    return {"query": safe, "row_count": len(rows), "rows": rows[:MAX_SQL_ROWS]}


def _get_runbook(query: str) -> Dict[str, Any]:
    resp = requests.post(f"{KNOWLEDGE_API_URL}/search", json={"query": query, "top_k": 1}, timeout=15)
    resp.raise_for_status()
    return resp.json().get("runbook", {}) or {}


def _get_incidents(limit: int = 15) -> List[Dict[str, Any]]:
    resp = requests.get(f"{BACKEND_URL}/api/incidents", timeout=15)
    resp.raise_for_status()
    result = resp.json().get("result", [])
    slim = []
    for inc in result[:limit]:
        slim.append({
            "number": inc.get("number"),
            "short_description": inc.get("short_description"),
            "state": inc.get("state"),
            "priority_label": inc.get("priority_label"),
            "created_at": inc.get("created_at"),
        })
    return slim


# --- Gemini steps ------------------------------------------------------------
def _parse_json(text: str) -> Dict[str, Any]:
    start, end = text.find("{"), text.rfind("}") + 1
    if start == -1 or end <= start:
        raise ValueError("No JSON object found in model response.")
    return json.loads(text[start:end])


def _plan(question: str, history: List[Dict[str, str]]) -> Dict[str, Any]:
    convo = ""
    if history:
        convo = "\nConversation so far:\n" + "\n".join(
            f"{m.get('role', 'user')}: {m.get('content', '')}" for m in history[-6:]
        )

    prompt = f"""You are the planning step of an SRE assistant for a PSD2 / XS2A open-banking
platform. Decide what evidence is needed to answer the user's question, then
output a plan as a JSON object. You may query the audit log, look up a runbook,
and/or review recent incidents.

{SCHEMA_HINT}
{convo}

User question: "{question}"

Return ONLY a JSON object with these keys:
- "needs_sql" (boolean)
- "sql" (string): a SINGLE read-only PostgreSQL SELECT query (no semicolons, no
  comments, no writes) against {AUDIT_TABLE}. Use NOW() - INTERVAL '...' for time
  ranges. Empty string if needs_sql is false.
- "needs_runbook" (boolean)
- "runbook_query" (string): search text for the runbook, else "".
- "needs_incidents" (boolean): true if recent incident history is relevant.
- "reasoning" (string): one sentence on why this evidence is needed.
Only include SQL you are confident is valid. Do not answer the question here."""

    resp = _model.generate_content(prompt, generation_config={"response_mime_type": "application/json"})
    plan = _parse_json(resp.text)
    plan.setdefault("needs_sql", False)
    plan.setdefault("needs_runbook", False)
    plan.setdefault("needs_incidents", False)
    return plan


def _answer(question: str, history: List[Dict[str, str]], evidence: Dict[str, Any]) -> str:
    convo = ""
    if history:
        convo = "\nConversation so far:\n" + "\n".join(
            f"{m.get('role', 'user')}: {m.get('content', '')}" for m in history[-6:]
        )

    prompt = f"""You are an expert SRE assistant for a PSD2 / XS2A open-banking platform.
Answer the user's question using ONLY the evidence provided. Be concise and
practical: state what the data shows, the likely cause, and a recommended next
step. If the evidence is empty or inconclusive, say so plainly and suggest what
to check next. Do not invent numbers that are not in the evidence.
{convo}

User question: "{question}"

Evidence (JSON):
{json.dumps(evidence, indent=2, default=str)}

Write the answer in clear plain text (short paragraphs or bullet points)."""
    resp = _model.generate_content(prompt)
    return resp.text.strip()


# --- API ---------------------------------------------------------------------
class AskRequest(BaseModel):
    question: str = Field(..., min_length=1)
    history: List[Dict[str, str]] = Field(default_factory=list)


@app.post("/ask")
def ask(req: AskRequest):
    question = req.question.strip()
    if not question:
        raise HTTPException(status_code=400, detail="question is required")

    log.info(f"[COPILOT] Q: {question}")

    # 1) Plan
    try:
        plan = _plan(question, req.history)
    except Exception as e:
        log.error(f"[COPILOT] Planning failed: {e}")
        raise HTTPException(status_code=500, detail=f"Planning failed: {e}")

    # 2) Gather evidence
    evidence: Dict[str, Any] = {"schema": SCHEMA_HINT}
    sources: List[str] = []
    sql_used: Optional[str] = None

    if plan.get("needs_sql") and plan.get("sql"):
        try:
            sql_result = _run_sql(plan["sql"])
            evidence["sql_result"] = sql_result
            sql_used = sql_result["query"]
            sources.append("audit_log")
        except ValueError as e:
            # Rejected by the read-only guard — surface it, don't execute.
            evidence["sql_error"] = f"Query rejected by safety guard: {e}"
            log.warning(f"[COPILOT] SQL rejected: {e}")
        except Exception as e:
            evidence["sql_error"] = str(e)
            log.warning(f"[COPILOT] SQL failed: {e}")

    if plan.get("needs_runbook") and plan.get("runbook_query"):
        try:
            rb = _get_runbook(plan["runbook_query"])
            if rb:
                evidence["runbook"] = rb
                sources.append("runbook")
        except Exception as e:
            log.warning(f"[COPILOT] Runbook lookup failed: {e}")

    if plan.get("needs_incidents"):
        try:
            evidence["recent_incidents"] = _get_incidents()
            sources.append("incidents")
        except Exception as e:
            log.warning(f"[COPILOT] Incident lookup failed: {e}")

    # 3) Answer
    try:
        answer = _answer(question, req.history, evidence)
    except Exception as e:
        log.error(f"[COPILOT] Answer generation failed: {e}")
        raise HTTPException(status_code=500, detail=f"Answer generation failed: {e}")

    return {
        "answer": answer,
        "sources": sources,
        "sql_used": sql_used,
        "reasoning": plan.get("reasoning"),
    }


@app.get("/health")
def health():
    return {"status": "healthy"}
