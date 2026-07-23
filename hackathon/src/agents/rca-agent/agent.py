# src/agents/rca-agent/agent.py
# RCA Agent — dedicated Root Cause Analysis microservice for DECA.
#
# Extracts the deep root-cause reasoning that previously lived inline inside the
# Root Orchestrator into a focused, independently-scalable agent. It performs a
# rigorous SRE-grade analysis (5-Whys causal chain, contributing factors,
# root-cause category, blast radius) while remaining a DROP-IN for the
# orchestrator: the JSON it returns is a superset of the fields the existing
# pipeline/report already consume, so nothing downstream breaks.

import os
import json
import logging
from typing import Any, Dict, List, Optional

from fastapi import FastAPI
from pydantic import BaseModel, Field
from dotenv import load_dotenv
import vertexai
from vertexai.generative_models import GenerativeModel

load_dotenv()
logging.basicConfig(level=logging.INFO)

PROJECT_ID = os.getenv("GOOGLE_CLOUD_PROJECT", "db-dev-a7km-mp-aiw-pb-tech")
LOCATION = os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1")
MODEL_NAME = os.getenv("RCA_MODEL_NAME", "gemini-2.5-flash")

try:
    vertexai.init(project=PROJECT_ID, location=LOCATION)
    gemini_model = GenerativeModel(MODEL_NAME)
    logging.info(f"✅ RCA Agent Vertex AI ready. Project={PROJECT_ID} Region={LOCATION} Model={MODEL_NAME}")
except Exception as e:  # pragma: no cover - startup diagnostic
    gemini_model = None
    logging.error(f"❌ RCA Agent failed to init Vertex AI: {e}")

app = FastAPI(title="RCA Agent (Root Cause Analysis)")


# ── Request / response contracts ─────────────────────────────────────────────
class RCARequest(BaseModel):
    alert_name: str
    runbook: Dict[str, Any] = Field(default_factory=dict)
    query_results: List[Dict[str, Any]] = Field(default_factory=list)


class CausalStep(BaseModel):
    why: str
    because: str


class KeyFinding(BaseModel):
    severity: str
    finding: str


def _summarize_evidence(alert_name: str, runbook: Dict[str, Any], query_results: List[Dict[str, Any]]) -> List[str]:
    """Turn raw evidence into compact, prompt-friendly bullet lines."""
    evidence = [
        f'Alert Name: "{alert_name}"',
        f'Matched Runbook: "{runbook.get("alert_name", "N/A")}"',
    ]
    if not query_results:
        evidence.append("No SQL diagnostic queries were executed (missing runbook definition or CA ID).")
        return evidence

    for q in query_results:
        purpose = q.get("purpose", "N/A")
        if "error" in q:
            msg = q.get("error", {})
            msg = msg.get("message", "Unknown error") if isinstance(msg, dict) else str(msg)
            evidence.append(f"Diagnostic Query (Purpose: {purpose}): FAILED with error: {msg}")
            continue
        data = q.get("result", {}).get("data")
        if isinstance(data, list):
            if len(data) == 0:
                evidence.append(f"Diagnostic Query (Purpose: {purpose}): Returned 0 rows — CRITICAL observability gap.")
            else:
                evidence.append(f"Diagnostic Query (Purpose: {purpose}): Returned {len(data)} rows. Sample: {json.dumps(data[:3])}")
        else:
            evidence.append(f"Diagnostic Query (Purpose: {purpose}): Completed but returned no usable data.")
    return evidence


def _compute_confidence(runbook: Dict[str, Any], query_results: List[Dict[str, Any]], escalation_needed: bool, has_findings: bool) -> int:
    """Deterministic, explainable confidence used when the model omits its own."""
    score = 100
    if not runbook or not runbook.get("alert_name"):
        score -= 30
    successful = [q for q in query_results if isinstance(q.get("result", {}).get("data"), list)]
    errored = [q for q in query_results if "error" in q]
    total_rows = sum(len(q["result"]["data"]) for q in successful)
    if query_results:
        if errored:
            score -= 20
        if total_rows == 0:
            score -= 25
    else:
        score -= 15
    if escalation_needed:
        score -= 15
    if not has_findings:
        score -= 10
    return max(5, min(100, score))


def _build_prompt(evidence: List[str]) -> str:
    joined = "\n- ".join(evidence)
    return f"""You are a Principal Site Reliability Engineer performing a rigorous
root cause analysis (RCA) for a banking payments platform. Reason strictly from
the evidence — never invent facts. You MUST return a single valid JSON object.

**Incident Evidence:**
- {joined}

**Produce a JSON object with EXACTLY these keys:**
- "root_cause_summary" (string): One or two crisp sentences naming the most likely root cause.
- "root_cause_category" (string): ONE of ["Code Defect","Configuration","Capacity/Resource","Dependency/Upstream","Data/Integrity","Observability Gap","Unknown"].
- "detailed_analysis" (string): In-depth reasoning. Emphasize data gaps (e.g. 0 SQL rows) if present.
- "causal_chain" (list of objects with keys "why" and "because"): A 3-5 step "5 Whys" chain from the observed symptom down to the underlying root cause.
- "contributing_factors" (list of strings): Secondary factors that made the incident more likely or more severe.
- "affected_components" (list of strings): System components impacted.
- "blast_radius" (string): Concise estimate of user/business impact and scope.
- "key_findings" (list of objects with keys "severity" [CRITICAL|HIGH|MEDIUM|LOW] and "finding" [string]). If a query returned 0 rows, include a CRITICAL observability-gap finding.
- "recommended_actions" (list of strings): Prioritized, specific, actionable remediation steps.
- "escalation_needed" (boolean): True if manual intervention is likely required.
- "escalation_reason" (string): Why escalation is needed (empty string if not).
- "contacts" (list of strings): Teams/individuals to engage (e.g. "SRE Team", "XS2A Support").
- "confidence_score" (integer 0-100): Confidence based ONLY on evidence completeness. HIGH (85-100) when a runbook matched and SQL clearly explains the failure; MEDIUM (60-84) when partial; LOW (0-59) on observability gaps/missing runbook/query errors. Escalated incidents should generally score below 80.

Return ONLY the JSON object, with no surrounding prose or markdown fences."""


def _fallback_analysis(evidence: List[str], reason: str) -> Dict[str, Any]:
    return {
        "root_cause_summary": "RCA could not be completed automatically.",
        "root_cause_category": "Unknown",
        "detailed_analysis": f"Automated RCA failed: {reason}. Evidence considered: {evidence}",
        "causal_chain": [],
        "contributing_factors": [],
        "affected_components": ["AI System"],
        "blast_radius": "Undetermined — automated analysis failed.",
        "key_findings": [{"severity": "CRITICAL", "finding": "RCA agent could not complete the analysis."}],
        "recommended_actions": ["Manually investigate RCA agent logs and re-run analysis."],
        "escalation_needed": True,
        "escalation_reason": "Automated RCA failed.",
        "contacts": ["SRE Team"],
        "confidence_score": 5,
    }


@app.post("/analyze")
def analyze(req: RCARequest) -> Dict[str, Any]:
    """Perform a deep root cause analysis over the provided incident evidence."""
    logging.info(f">>> RCA requested for alert: {req.alert_name!r}")
    evidence = _summarize_evidence(req.alert_name, req.runbook, req.query_results)

    if gemini_model is None:
        return _fallback_analysis(evidence, "Vertex AI not initialized")

    try:
        response = gemini_model.generate_content(
            _build_prompt(evidence),
            generation_config={"response_mime_type": "application/json", "temperature": 0.2},
        )
        analysis = json.loads(response.text.strip())
    except Exception as e:  # broad on purpose: never crash the pipeline
        logging.error(f"❌ RCA generation failed: {e}")
        return _fallback_analysis(evidence, str(e))

    # Ensure confidence is always present and explainable.
    if not isinstance(analysis.get("confidence_score"), int):
        analysis["confidence_score"] = _compute_confidence(
            req.runbook,
            req.query_results,
            bool(analysis.get("escalation_needed")),
            bool(analysis.get("key_findings")),
        )
    logging.info(f"✅ RCA complete: {analysis.get('root_cause_summary', 'N/A')}")
    return analysis


@app.get("/health")
def health() -> Dict[str, str]:
    return {"status": "healthy"}
