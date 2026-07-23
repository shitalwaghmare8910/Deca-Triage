# src/agents/anomaly-detection-agent/agent.py
# ─────────────────────────────────────────────────────────────────────────────
# Anomaly Detection Agent (port 8009)
#
# Turns the platform from *reactive* triage into *proactive* detection.
#
# What it does, on a timer:
#   1. Pulls recent + baseline metrics from Cloud SQL `xs2a_accounts_db.audit_log`
#      via the existing Postgres Agent (http://localhost:8003/execute-query),
#      so it reuses the safe SQL proxy and the single set of DB credentials.
#   2. Asks Vertex AI Gemini to reason over those metrics and decide whether the
#      recent window looks anomalous (error-rate spikes, surges of 5xx / CRITICAL
#      events, unusual event types, a dominant failing credit application, ...).
#   3. If an anomaly is found (and it isn't in cooldown), it synthesises an SRE
#      style alert and POSTs it to the backend `/api/ingest-alert`, which runs the
#      SAME dashboard pipeline (orchestrator → runbook → SQL → Gemini RCA →
#      critic / concept / jira / notification) — so the investigation appears on
#      the frontend automatically.
#
# A deterministic heuristic is used as a fallback so the agent still works if
# Gemini is unavailable.
# ─────────────────────────────────────────────────────────────────────────────

import os
import json
import time
import logging
import threading
import datetime
from typing import Any, Dict, List, Optional

import requests
from fastapi import FastAPI, HTTPException
from dotenv import load_dotenv

import vertexai
from vertexai.generative_models import GenerativeModel

load_dotenv()


# --- Color formatting for demo logs -----------------------------------------
class C:
    BLUE, CYAN, GREEN, YELLOW, RED, END, BOLD = (
        "\033[94m", "\033[96m", "\033[92m", "\033[93m", "\033[91m", "\033[0m", "\033[1m",
    )


logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(asctime)s - %(message)s")
log = logging.getLogger("anomaly-agent")


# --- Configuration -----------------------------------------------------------
PROJECT_ID = os.getenv("GOOGLE_CLOUD_PROJECT", "db-dev-a7km-mp-aiw-pb-tech")
LOCATION = os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1")
MODEL_NAME = os.getenv("ANOMALY_MODEL", "gemini-2.5-flash")

POSTGRES_API_URL = os.getenv("POSTGRES_API_URL", "http://localhost:8003")
BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:5000")

AUDIT_TABLE = os.getenv("AUDIT_TABLE", "xs2a_accounts_db.audit_log")

# Windows / cadence (all overridable via env for the demo).
RECENT_WINDOW_MINUTES = int(os.getenv("ANOMALY_RECENT_MINUTES", "60"))
BASELINE_WINDOW_HOURS = int(os.getenv("ANOMALY_BASELINE_HOURS", "24"))
POLL_INTERVAL_SECONDS = int(os.getenv("ANOMALY_POLL_SECONDS", "120"))
FIRST_SCAN_DELAY_SECONDS = int(os.getenv("ANOMALY_FIRST_SCAN_DELAY", "20"))
COOLDOWN_MINUTES = int(os.getenv("ANOMALY_COOLDOWN_MINUTES", "30"))

# Auto scanning + auto triage toggles. Set to "0" to run in manual mode
# (only /scan-now) or to detect-but-don't-triage.
AUTO_SCAN = os.getenv("ANOMALY_AUTO_SCAN", "1") == "1"
AUTO_TRIAGE = os.getenv("ANOMALY_AUTO_TRIAGE", "1") == "1"

# Minimum severity that is allowed to auto-trigger a full triage.
_SEVERITY_ORDER = {"LOW": 1, "MEDIUM": 2, "HIGH": 3, "CRITICAL": 4}
MIN_TRIAGE_SEVERITY = os.getenv("ANOMALY_MIN_SEVERITY", "MEDIUM").upper()

# Heuristic fallback thresholds.
HEURISTIC_MIN_RECENT_EVENTS = int(os.getenv("ANOMALY_MIN_RECENT_EVENTS", "5"))
HEURISTIC_ERROR_RATE = float(os.getenv("ANOMALY_ERROR_RATE_THRESHOLD", "0.4"))
HEURISTIC_RATE_MULTIPLIER = float(os.getenv("ANOMALY_RATE_MULTIPLIER", "2.0"))

# Predictive forecasting: project the error-rate trend and warn BEFORE an SLO
# breach actually happens. Uses a lightweight least-squares linear fit over
# recent time buckets (no ML deps).
FORECAST_ENABLED = os.getenv("ANOMALY_FORECAST_ENABLED", "1") == "1"
SLO_ERROR_RATE = float(os.getenv("ANOMALY_SLO_ERROR_RATE", "0.5"))        # breach threshold
FORECAST_HORIZON_MINUTES = int(os.getenv("ANOMALY_FORECAST_HORIZON", "30"))
FORECAST_BUCKET_MINUTES = int(os.getenv("ANOMALY_FORECAST_BUCKET", "10"))
FORECAST_LOOKBACK_MINUTES = int(os.getenv("ANOMALY_FORECAST_LOOKBACK", "120"))
FORECAST_MIN_BUCKETS = int(os.getenv("ANOMALY_FORECAST_MIN_BUCKETS", "3"))

vertexai.init(project=PROJECT_ID, location=LOCATION)
_model = GenerativeModel(MODEL_NAME, generation_config={"temperature": 0.2, "max_output_tokens": 2048})

app = FastAPI(title="Anomaly Detection Agent")


# --- In-memory state (for /status) ------------------------------------------
_STATE_LOCK = threading.Lock()
_LAST_SCAN: Optional[Dict[str, Any]] = None
_SCAN_HISTORY: List[Dict[str, Any]] = []          # most-recent-first, capped
_COOLDOWN: Dict[str, str] = {}                     # signature -> ISO timestamp last triggered
_HISTORY_LIMIT = 25


def _now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


# --- SQL helpers -------------------------------------------------------------
def _run_sql(query: str) -> List[Dict[str, Any]]:
    """Execute a read-only query through the Postgres Agent's safe proxy."""
    resp = requests.post(f"{POSTGRES_API_URL}/execute-query", json={"query": query}, timeout=30)
    resp.raise_for_status()
    payload = resp.json()
    data = payload.get("data")
    return data if isinstance(data, list) else []


def _collect_metrics() -> Dict[str, Any]:
    """Gather the metric snapshots the LLM (and heuristic) reason over.

    RECENT_WINDOW_MINUTES / BASELINE_WINDOW_HOURS are ints from config (never
    user input), so interpolating them into the SQL is safe.
    """
    recent = int(RECENT_WINDOW_MINUTES)
    baseline = int(BASELINE_WINDOW_HOURS)
    tbl = AUDIT_TABLE
    err_pred = "(code >= 400 OR severity IN ('ERROR', 'CRITICAL'))"

    # 1) Recent breakdown by event_type / severity / code.
    breakdown = _run_sql(
        f"""
        SELECT COALESCE(event_type, 'UNKNOWN') AS event_type,
               COALESCE(severity, 'UNKNOWN')   AS severity,
               COALESCE(code, 0)               AS code,
               COUNT(*)                        AS cnt
        FROM {tbl}
        WHERE created_date_time >= NOW() - INTERVAL '{recent} minutes'
        GROUP BY 1, 2, 3
        ORDER BY cnt DESC
        LIMIT 50;
        """
    )

    # 2) Recent vs baseline totals + error counts (for rate comparison).
    totals_rows = _run_sql(
        f"""
        SELECT
          SUM(CASE WHEN created_date_time >= NOW() - INTERVAL '{recent} minutes'
                   THEN 1 ELSE 0 END) AS recent_total,
          SUM(CASE WHEN created_date_time >= NOW() - INTERVAL '{recent} minutes'
                    AND {err_pred} THEN 1 ELSE 0 END) AS recent_errors,
          SUM(CASE WHEN created_date_time >= NOW() - INTERVAL '{baseline} hours'
                   THEN 1 ELSE 0 END) AS baseline_total,
          SUM(CASE WHEN created_date_time >= NOW() - INTERVAL '{baseline} hours'
                    AND {err_pred} THEN 1 ELSE 0 END) AS baseline_errors
        FROM {tbl}
        WHERE created_date_time >= NOW() - INTERVAL '{baseline} hours';
        """
    )
    totals = totals_rows[0] if totals_rows else {}

    # 3) Top offending credit applications in the recent window (gives the
    #    orchestrator a concrete CA_ID to investigate).
    offenders = _run_sql(
        f"""
        SELECT credit_application_id, COUNT(*) AS errors
        FROM {tbl}
        WHERE created_date_time >= NOW() - INTERVAL '{recent} minutes'
          AND {err_pred}
          AND credit_application_id IS NOT NULL
        GROUP BY credit_application_id
        ORDER BY errors DESC
        LIMIT 5;
        """
    )

    def _num(v: Any) -> float:
        try:
            return float(v)
        except (TypeError, ValueError):
            return 0.0

    recent_total = _num(totals.get("recent_total"))
    recent_errors = _num(totals.get("recent_errors"))
    baseline_total = _num(totals.get("baseline_total"))
    baseline_errors = _num(totals.get("baseline_errors"))

    recent_error_rate = recent_errors / recent_total if recent_total else 0.0
    baseline_error_rate = baseline_errors / baseline_total if baseline_total else 0.0

    return {
        "generated_at": _now_iso(),
        "windows": {
            "recent_minutes": recent,
            "baseline_hours": baseline,
        },
        "recent_breakdown": breakdown,
        "totals": {
            "recent_total": recent_total,
            "recent_errors": recent_errors,
            "recent_error_rate": round(recent_error_rate, 4),
            "baseline_total": baseline_total,
            "baseline_errors": baseline_errors,
            "baseline_error_rate": round(baseline_error_rate, 4),
        },
        "top_offending_applications": offenders,
    }


# --- Predictive forecasting --------------------------------------------------
def _collect_timeseries() -> List[Dict[str, Any]]:
    """Bucketed error-rate time series over the forecast lookback window.

    Buckets are FORECAST_BUCKET_MINUTES wide; each row has the bucket start,
    total events, error events and the resulting error rate.
    """
    bucket_secs = int(FORECAST_BUCKET_MINUTES) * 60
    lookback = int(FORECAST_LOOKBACK_MINUTES)
    tbl = AUDIT_TABLE
    err_pred = "(code >= 400 OR severity IN ('ERROR', 'CRITICAL'))"

    rows = _run_sql(
        f"""
        SELECT to_timestamp(floor(extract(epoch FROM created_date_time) / {bucket_secs}) * {bucket_secs}) AS bucket_start,
               COUNT(*) AS total,
               COUNT(*) FILTER (WHERE {err_pred}) AS errors
        FROM {tbl}
        WHERE created_date_time >= NOW() - INTERVAL '{lookback} minutes'
        GROUP BY 1
        ORDER BY 1;
        """
    )

    series: List[Dict[str, Any]] = []
    for r in rows:
        total = float(r.get("total") or 0)
        errors = float(r.get("errors") or 0)
        series.append({
            "bucket_start": str(r.get("bucket_start")),
            "total": total,
            "errors": errors,
            "error_rate": round(errors / total, 4) if total else 0.0,
        })
    return series


def _forecast(series: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Least-squares linear projection of the error-rate trend.

    Returns the trend direction, slope per minute, the current fitted rate, the
    projected rate at the forecast horizon and an estimated minutes-to-breach of
    the SLO error-rate threshold.
    """
    points = [p for p in series if p["total"] > 0]
    if len(points) < FORECAST_MIN_BUCKETS:
        return {
            "status": "insufficient_data",
            "buckets_used": len(points),
            "slo_error_rate": SLO_ERROR_RATE,
            "will_breach": False,
        }

    bucket = int(FORECAST_BUCKET_MINUTES)
    # x in minutes relative to the first usable bucket.
    xs = [i * bucket for i in range(len(points))]
    ys = [p["error_rate"] for p in points]
    n = len(points)
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n
    denom = sum((x - mean_x) ** 2 for x in xs)
    slope = (sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys)) / denom) if denom else 0.0
    intercept = mean_y - slope * mean_x

    last_x = xs[-1]
    current_fitted = max(0.0, intercept + slope * last_x)
    horizon = int(FORECAST_HORIZON_MINUTES)
    projected = max(0.0, min(1.0, intercept + slope * (last_x + horizon)))

    minutes_to_breach: Optional[float] = None
    if slope > 1e-9 and current_fitted < SLO_ERROR_RATE:
        minutes_to_breach = (SLO_ERROR_RATE - current_fitted) / slope

    already_breaching = current_fitted >= SLO_ERROR_RATE
    will_breach = already_breaching or (
        minutes_to_breach is not None and minutes_to_breach <= horizon
    )

    if slope > 1e-4:
        trend = "rising"
    elif slope < -1e-4:
        trend = "falling"
    else:
        trend = "flat"

    return {
        "status": "ok",
        "buckets_used": n,
        "trend": trend,
        "slope_per_min": round(slope, 6),
        "current_rate": round(current_fitted, 4),
        "projected_rate_at_horizon": round(projected, 4),
        "horizon_minutes": horizon,
        "slo_error_rate": SLO_ERROR_RATE,
        "minutes_to_breach": round(minutes_to_breach, 1) if minutes_to_breach is not None else None,
        "already_breaching": already_breaching,
        "will_breach": bool(will_breach),
    }


def _gather() -> Dict[str, Any]:
    """Collect point-in-time metrics plus (optionally) the predictive forecast."""
    metrics = _collect_metrics()
    if FORECAST_ENABLED:
        try:
            series = _collect_timeseries()
            metrics["timeseries"] = series
            metrics["forecast"] = _forecast(series)
        except Exception as e:
            log.warning(f"{C.YELLOW}    ⚠️ Forecast step failed ({e}); continuing without it.{C.END}")
            metrics["forecast"] = {"status": "error", "error": str(e), "will_breach": False}
    return metrics


# --- Detection ---------------------------------------------------------------
def _build_prompt(metrics: Dict[str, Any]) -> str:
    return f"""You are an expert SRE monitoring the audit log of a PSD2 / XS2A open-banking
platform. You are given aggregated metrics comparing a RECENT time window
against a longer BASELINE window, plus a bucketed error-rate time series and a
PREDICTIVE forecast of where the error rate is trending. Decide whether the
recent window shows an operational ANOMALY worth investigating (for example: a
spike in error rate, a surge of HTTP 5xx or CRITICAL-severity events, an unusual
event type, a single credit application generating disproportionate failures, or
a clearly rising error-rate trend that is forecast to breach the SLO).

Metrics (JSON):
{json.dumps(metrics, indent=2, default=str)}

Respond with ONLY a valid JSON object with these exact keys:
- "anomaly_detected" (boolean)
- "severity" (one of "LOW", "MEDIUM", "HIGH", "CRITICAL")
- "confidence" (integer 0-100)
- "alert_name" (string): a concise, SRE-style alert title suitable for triage.
  If a single credit_application_id dominates the failures, INCLUDE it verbatim
  in the alert title. Example: "Elevated 503 error rate on TRANSACTION_FETCH for
  PBDECOFI 12 3456 7890".
- "summary" (string): 1-2 sentences explaining what looks abnormal.
- "evidence" (array of short strings): the specific numbers that justify the call.
- "affected_event_types" (array of strings)
- "affected_codes" (array of integers)
- "signature" (string): a short, STABLE key describing the anomaly class, used
  for de-duplication (e.g. "TRANSACTION_FETCH:503").

If nothing is abnormal, return anomaly_detected=false with severity "LOW".
Do not include any text outside the JSON object."""


def _parse_json(text: str) -> Dict[str, Any]:
    start, end = text.find("{"), text.rfind("}") + 1
    if start == -1 or end <= start:
        raise ValueError("No JSON object found in model response.")
    return json.loads(text[start:end])


def _heuristic_fallback(metrics: Dict[str, Any]) -> Dict[str, Any]:
    """Deterministic detector used when Gemini is unavailable or errors out."""
    t = metrics["totals"]
    recent_total = t["recent_total"]
    recent_rate = t["recent_error_rate"]
    baseline_rate = t["baseline_error_rate"]

    offenders = metrics.get("top_offending_applications") or []
    top_ca = offenders[0].get("credit_application_id") if offenders else None

    # Identify the dominant failing (event_type, code) pair for the signature.
    worst = None
    for row in metrics.get("recent_breakdown", []):
        try:
            code = int(float(row.get("code") or 0))
        except (TypeError, ValueError):
            code = 0
        sev = str(row.get("severity", "")).upper()
        if code >= 400 or sev in ("ERROR", "CRITICAL"):
            worst = row
            break

    spike = baseline_rate > 0 and recent_rate >= baseline_rate * HEURISTIC_RATE_MULTIPLIER
    high_abs = recent_rate >= HEURISTIC_ERROR_RATE
    detected = recent_total >= HEURISTIC_MIN_RECENT_EVENTS and (spike or high_abs)

    if not detected:
        return {
            "anomaly_detected": False,
            "severity": "LOW",
            "confidence": 60,
            "alert_name": "No anomaly detected",
            "summary": "Recent audit-log error rate is within normal bounds.",
            "evidence": [
                f"recent_error_rate={recent_rate}",
                f"baseline_error_rate={baseline_rate}",
            ],
            "affected_event_types": [],
            "affected_codes": [],
            "signature": "none",
            "source": "heuristic",
        }

    event_type = str(worst.get("event_type", "UNKNOWN")) if worst else "UNKNOWN"
    code = int(float(worst.get("code") or 0)) if worst else 0
    severity = "HIGH" if recent_rate >= 0.6 else "MEDIUM"
    title = f"Elevated error rate on {event_type}"
    if code >= 400:
        title = f"Elevated HTTP {code} error rate on {event_type}"
    if top_ca:
        title += f" for {top_ca}"

    return {
        "anomaly_detected": True,
        "severity": severity,
        "confidence": 70,
        "alert_name": title,
        "summary": (
            f"Recent error rate {recent_rate:.0%} over {int(recent_total)} events "
            f"exceeds baseline {baseline_rate:.0%}."
        ),
        "evidence": [
            f"recent_error_rate={recent_rate}",
            f"baseline_error_rate={baseline_rate}",
            f"recent_total={int(recent_total)}",
        ],
        "affected_event_types": [event_type] if event_type != "UNKNOWN" else [],
        "affected_codes": [code] if code >= 400 else [],
        "signature": f"{event_type}:{code}",
        "source": "heuristic",
    }


def _detect(metrics: Dict[str, Any]) -> Dict[str, Any]:
    """Run Gemini detection, falling back to the heuristic on any failure."""
    try:
        log.info(f"{C.CYAN}    -> Asking Gemini to reason over recent metrics...{C.END}")
        resp = _model.generate_content(
            _build_prompt(metrics),
            generation_config={"response_mime_type": "application/json"},
        )
        result = _parse_json(resp.text)
        result.setdefault("source", "gemini")
        # Normalise required fields.
        result["anomaly_detected"] = bool(result.get("anomaly_detected"))
        result["severity"] = str(result.get("severity", "LOW")).upper()
        result.setdefault("signature", result.get("severity", "unknown"))
        return result
    except Exception as e:
        log.warning(f"{C.YELLOW}    ⚠️ Gemini detection failed ({e}); using heuristic fallback.{C.END}")
        return _heuristic_fallback(metrics)


# --- Triage triggering -------------------------------------------------------
def _in_cooldown(signature: str) -> bool:
    ts = _COOLDOWN.get(signature)
    if not ts:
        return False
    last = datetime.datetime.fromisoformat(ts)
    age = datetime.datetime.now(datetime.timezone.utc) - last
    return age < datetime.timedelta(minutes=COOLDOWN_MINUTES)


def _trigger_triage(detection: Dict[str, Any], metrics: Dict[str, Any]) -> Dict[str, Any]:
    """POST the synthesised alert to the backend so it runs the dashboard pipeline."""
    alert_name = detection.get("alert_name") or "Audit-log anomaly detected"
    body = (
        f"{detection.get('summary', '')}\n\n"
        f"Evidence: {', '.join(str(e) for e in detection.get('evidence', []))}\n"
        f"Detected by: Anomaly Detection Agent ({detection.get('source', 'gemini')}), "
        f"severity={detection.get('severity')}, confidence={detection.get('confidence')}."
    )
    payload = {
        "alert_name": alert_name,
        "body": body,
        "source": "Anomaly Detection",
        "sender": "anomaly-agent@platform.local",
    }
    resp = requests.post(f"{BACKEND_URL}/api/ingest-alert", json=payload, timeout=15)
    resp.raise_for_status()
    return resp.json().get("result", {})


def _maybe_trigger_forecast(metrics: Dict[str, Any], force: bool = False) -> Optional[Dict[str, Any]]:
    """Raise a *predictive* alert if the error rate is trending toward the SLO.

    Fires before an anomaly is actually observed, so the team can act early.
    Returns the created incident dict, or None if nothing was raised.
    """
    fc = metrics.get("forecast") or {}
    if fc.get("status") != "ok" or not fc.get("will_breach"):
        return None
    if not (force or AUTO_TRIAGE):
        return None

    signature = "PREDICTIVE_SLO_BREACH"
    if _in_cooldown(signature):
        return None

    proj = fc.get("projected_rate_at_horizon", 0.0)
    mtb = fc.get("minutes_to_breach")
    slo = fc.get("slo_error_rate", SLO_ERROR_RATE)
    if fc.get("already_breaching"):
        title = f"SLO breach in progress: audit_log error rate {fc.get('current_rate', 0):.0%} (threshold {slo:.0%})"
        when = "already exceeding the SLO threshold"
    else:
        eta = f"~{int(mtb)} min" if mtb is not None else "soon"
        title = f"Predicted SLO breach: audit_log error rate trending to {proj:.0%} in {eta}"
        when = f"forecast to cross the {slo:.0%} SLO threshold in {eta}"

    body = (
        f"Predictive early-warning from the Anomaly Detection Agent. The audit_log "
        f"error rate is {fc.get('trend', 'rising')} (slope {fc.get('slope_per_min')}/min) and is {when}. "
        f"Current fitted rate {fc.get('current_rate', 0):.0%}, projected {proj:.0%} at a "
        f"{fc.get('horizon_minutes')}-minute horizon over {fc.get('buckets_used')} buckets."
    )
    payload = {
        "alert_name": title,
        "body": body,
        "source": "Predictive Anomaly",
        "sender": "anomaly-agent@platform.local",
    }
    resp = requests.post(f"{BACKEND_URL}/api/ingest-alert", json=payload, timeout=15)
    resp.raise_for_status()
    _COOLDOWN[signature] = _now_iso()
    incident = resp.json().get("result", {})
    log.info(
        f"{C.GREEN}🔮 Predictive alert raised: '{title}' -> incident "
        f"{incident.get('incident_id')}{C.END}"
    )
    return incident


def run_scan(force_triage: bool = False) -> Dict[str, Any]:
    """One full detection cycle. Returns a record describing what happened."""
    started = _now_iso()
    log.info(f"{C.BLUE}>>> Anomaly scan started ({started}){C.END}")

    try:
        metrics = _gather()
    except Exception as e:
        log.error(f"{C.RED}❌ Failed to collect metrics: {e}{C.END}")
        record = {
            "scanned_at": started,
            "status": "error",
            "error": str(e),
            "triggered": False,
        }
        _record(record)
        return record

    detection = _detect(metrics)
    triggered = False
    incident: Optional[Dict[str, Any]] = None
    skip_reason: Optional[str] = None

    if detection.get("anomaly_detected"):
        severity = detection.get("severity", "LOW")
        signature = str(detection.get("signature", "unknown"))
        meets_severity = _SEVERITY_ORDER.get(severity, 0) >= _SEVERITY_ORDER.get(MIN_TRIAGE_SEVERITY, 2)
        may_triage = force_triage or (AUTO_TRIAGE and meets_severity)

        if not may_triage:
            skip_reason = f"severity {severity} below threshold {MIN_TRIAGE_SEVERITY}" if not meets_severity else "auto-triage disabled"
        elif _in_cooldown(signature):
            skip_reason = f"signature '{signature}' in cooldown ({COOLDOWN_MINUTES}m)"
        else:
            try:
                incident = _trigger_triage(detection, metrics)
                triggered = True
                _COOLDOWN[signature] = _now_iso()
                log.info(
                    f"{C.GREEN}🚨 Anomaly triaged: '{detection.get('alert_name')}' "
                    f"-> incident {incident.get('incident_id')}{C.END}"
                )
            except Exception as e:
                skip_reason = f"failed to trigger triage: {e}"
                log.error(f"{C.RED}❌ {skip_reason}{C.END}")
    else:
        log.info(f"{C.GREEN}✅ No anomaly detected.{C.END}")

    # Predictive early-warning is independent of the point-in-time anomaly check.
    forecast_incident: Optional[Dict[str, Any]] = None
    try:
        forecast_incident = _maybe_trigger_forecast(metrics, force=force_triage)
    except Exception as e:
        log.error(f"{C.RED}❌ Predictive trigger failed: {e}{C.END}")

    record = {
        "scanned_at": started,
        "status": "ok",
        "detection": detection,
        "metrics_summary": metrics.get("totals"),
        "forecast": metrics.get("forecast"),
        "windows": metrics.get("windows"),
        "triggered": triggered,
        "incident": incident,
        "forecast_incident": forecast_incident,
        "skip_reason": skip_reason,
    }
    _record(record)
    return record


def _record(record: Dict[str, Any]) -> None:
    global _LAST_SCAN
    with _STATE_LOCK:
        _LAST_SCAN = record
        _SCAN_HISTORY.insert(0, record)
        del _SCAN_HISTORY[_HISTORY_LIMIT:]


# --- Background poller -------------------------------------------------------
def _poll_loop() -> None:
    log.info(
        f"{C.BOLD}Anomaly poller starting: first scan in {FIRST_SCAN_DELAY_SECONDS}s, "
        f"then every {POLL_INTERVAL_SECONDS}s.{C.END}"
    )
    time.sleep(FIRST_SCAN_DELAY_SECONDS)
    while True:
        try:
            run_scan()
        except Exception as e:  # never let the loop die
            log.error(f"{C.RED}❌ Unhandled error in scan loop: {e}{C.END}")
        time.sleep(POLL_INTERVAL_SECONDS)


@app.on_event("startup")
def _startup() -> None:
    log.info(f"{C.GREEN}Anomaly Detection Agent ready (model={MODEL_NAME}).{C.END}")
    log.info(
        f"   Windows: recent={RECENT_WINDOW_MINUTES}m baseline={BASELINE_WINDOW_HOURS}h | "
        f"auto_scan={AUTO_SCAN} auto_triage={AUTO_TRIAGE} min_severity={MIN_TRIAGE_SEVERITY}"
    )
    if AUTO_SCAN:
        threading.Thread(target=_poll_loop, daemon=True).start()
    else:
        log.info(f"{C.YELLOW}   Auto-scan disabled; use POST /scan-now to run manually.{C.END}")


# --- API ---------------------------------------------------------------------
@app.post("/scan-now")
def scan_now(force_triage: bool = False):
    """Run one detection cycle immediately and return the result.

    ?force_triage=true triggers the triage pipeline even below the severity
    threshold (handy for demos), but cooldown is still respected.
    """
    return run_scan(force_triage=force_triage)


@app.get("/status")
def status():
    with _STATE_LOCK:
        return {
            "last_scan": _LAST_SCAN,
            "history": _SCAN_HISTORY,
            "cooldown": _COOLDOWN,
        }


@app.get("/forecast")
def forecast():
    """Read-only: return the bucketed error-rate time series and its projection."""
    series = _collect_timeseries()
    return {
        "generated_at": _now_iso(),
        "timeseries": series,
        "forecast": _forecast(series),
    }


@app.get("/config")
def config():
    return {
        "model": MODEL_NAME,
        "postgres_api_url": POSTGRES_API_URL,
        "backend_url": BACKEND_URL,
        "audit_table": AUDIT_TABLE,
        "recent_window_minutes": RECENT_WINDOW_MINUTES,
        "baseline_window_hours": BASELINE_WINDOW_HOURS,
        "poll_interval_seconds": POLL_INTERVAL_SECONDS,
        "cooldown_minutes": COOLDOWN_MINUTES,
        "auto_scan": AUTO_SCAN,
        "auto_triage": AUTO_TRIAGE,
        "min_triage_severity": MIN_TRIAGE_SEVERITY,
        "forecast_enabled": FORECAST_ENABLED,
        "slo_error_rate": SLO_ERROR_RATE,
        "forecast_horizon_minutes": FORECAST_HORIZON_MINUTES,
        "forecast_bucket_minutes": FORECAST_BUCKET_MINUTES,
        "forecast_lookback_minutes": FORECAST_LOOKBACK_MINUTES,
    }


@app.get("/health")
def health():
    return {"status": "healthy"}
