#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════════════
# DECA — Decade of Autonomous Triage — start every service with one command.
#
#   ./start_all.sh           # start everything, stream a combined status
#   ./start_all.sh --foreground / -f   # same, but keep attached and Ctrl+C
#                                          stops all services
#
# Logs:  ./logs/<service>.log
# PIDs:  ./logs/<service>.pid   (also ./logs/all.pids)
# Stop:  ./stop_all.sh
# ═══════════════════════════════════════════════════════════════════════════
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

VENV="$ROOT/venv"
LOG_DIR="$ROOT/logs"
PID_FILE="$LOG_DIR/all.pids"
mkdir -p "$LOG_DIR"
: > "$PID_FILE"

# Make `src` importable (agents do `from src.common...`).
export PYTHONPATH="$ROOT${PYTHONPATH:+:$PYTHONPATH}"

# Deliver the Post-Analysis Investigation Report back to the Mock Outlook inbox
# after each investigation completes. (Backend reads this; other services ignore it.)
export OUTLOOK_DELIVERY_URL="${OUTLOOK_DELIVERY_URL:-http://localhost:5002/api/deliver-report}"

# ── Anomaly Detection auto-generation control (demo safety) ──────────────────
# The Anomaly agent can auto-generate incidents on a timer and can flood the
# (serial) orchestrator during a live demo. Choose a mode via ANOMALY_DEMO:
#   throttle (DEFAULT) — auto-scan on, but slow cadence, long cooldown, and only
#                        CRITICAL anomalies auto-triage. Keeps the "proactive"
#                        story without swamping the dashboard.
#   detect             — keep scanning/detecting, but NEVER auto-triage
#                        (use POST :8009/scan-now or the UI to trigger on demand).
#   off                — no background scanning at all (fully manual /scan-now).
#   full               — original aggressive behavior (no throttling).
# Any explicit ANOMALY_* env var you set yourself always wins over these defaults.
case "${ANOMALY_DEMO:-throttle}" in
    throttle)
        export ANOMALY_AUTO_SCAN="${ANOMALY_AUTO_SCAN:-1}"
        export ANOMALY_AUTO_TRIAGE="${ANOMALY_AUTO_TRIAGE:-1}"
        export ANOMALY_POLL_SECONDS="${ANOMALY_POLL_SECONDS:-600}"
        export ANOMALY_COOLDOWN_MINUTES="${ANOMALY_COOLDOWN_MINUTES:-60}"
        export ANOMALY_MIN_SEVERITY="${ANOMALY_MIN_SEVERITY:-CRITICAL}"
        export ANOMALY_FIRST_SCAN_DELAY="${ANOMALY_FIRST_SCAN_DELAY:-90}"
        ;;
    detect)
        export ANOMALY_AUTO_SCAN="${ANOMALY_AUTO_SCAN:-1}"
        export ANOMALY_AUTO_TRIAGE="${ANOMALY_AUTO_TRIAGE:-0}"
        export ANOMALY_POLL_SECONDS="${ANOMALY_POLL_SECONDS:-600}"
        ;;
    off)
        export ANOMALY_AUTO_SCAN="${ANOMALY_AUTO_SCAN:-0}"
        ;;
    full)
        : # leave every ANOMALY_* default to the agent's own aggressive values
        ;;
esac
echo "Anomaly mode: ANOMALY_DEMO=${ANOMALY_DEMO:-throttle} (auto_scan=${ANOMALY_AUTO_SCAN:-1} auto_triage=${ANOMALY_AUTO_TRIAGE:-1} poll=${ANOMALY_POLL_SECONDS:-agent-default}s min_sev=${ANOMALY_MIN_SEVERITY:-agent-default})"

if [[ ! -x "$VENV/bin/python" ]]; then
    echo "ERROR: virtualenv not found at $VENV. Create it first (python -m venv venv)." >&2
    exit 1
fi
PY="$VENV/bin/python"

# ── service registry ────────────────────────────────────────────────────────
# Each entry:  "Label|kind|target|port"
#   kind=agent    -> uvicorn agent:app --app-dir <target> --port <port>
#   kind=flask    -> python <target>/server.py          (port baked into server.py)
#   kind=listener -> python <target>/email_listener.py  (mock mode; no port)
SERVICES=(
    "Root Orchestrator|agent|src/agents/root-orchestrator|8080"
    "Knowledge Ingestion|agent|src/agents/knowledge_ingestion|8001"
    "Postgres Agent|agent|src/agents/postgres-agent|8003"
    "Critic Agent|agent|src/agents/critic-agent|8004"
    "Concept Agent|agent|src/agents/concept-agent|8005"
    "Jira Agent|agent|src/agents/jira-agent|8006"
    "Incident Logger Agent|agent|src/agents/incident-logger-agent|8007"
    "Notification Agent|agent|src/agents/notification-agent|8008"
    "Anomaly Detection Agent|agent|src/agents/anomaly-detection-agent|8009"
    "SRE Copilot Agent|agent|src/agents/sre-copilot-agent|8010"
    "RCA Agent|agent|src/agents/rca-agent|8011"
    "STIP Generator|flask|src/stip_generater|5001"
    "Mock Outlook|flask|src/email_listener/mock_outlook|5002"
    "Backend + Frontend|flask|src/backend|5000"
    "Email Listener|listener|src/email_listener|-"
)

slug() { echo "$1" | tr '[:upper:] ' '[:lower:]_' | tr -cd '[:alnum:]_'; }

start_one() {
    local label="$1" kind="$2" target="$3" port="$4"
    local name; name="$(slug "$label")"
    local log="$LOG_DIR/$name.log"
    local pidf="$LOG_DIR/$name.pid"

    case "$kind" in
        agent)
            "$VENV/bin/uvicorn" agent:app --app-dir "$target" \
                --host 0.0.0.0 --port "$port" >"$log" 2>&1 &
            ;;
        flask)
            ( cd "$target" && PYTHONPATH="$ROOT" "$PY" server.py ) >"$log" 2>&1 &
            ;;
        listener)
            # Standalone email listener in MOCK mode -> polls the local Mock
            # Outlook (port 5002) and forwards alerts to the backend dashboard
            # (/api/ingest-alert) so investigations appear on the frontend.
            # Real-Graph behavior is unchanged when run directly with
            # EMAIL_LISTENER_MODE unset.
            ( cd "$target" \
                && EMAIL_LISTENER_MODE=mock \
                   FORWARD_MODE=backend \
                   BACKEND_URL="${BACKEND_URL:-http://localhost:5000}" \
                   SHARED_MAILBOX="${SHARED_MAILBOX:-alerts@demo.local}" \
                   PYTHONPATH="$ROOT" "$PY" email_listener.py ) >"$log" 2>&1 &
            ;;
        *)
            echo "Unknown kind '$kind' for $label" >&2; return 1 ;;
    esac

    local pid=$!
    echo "$pid" > "$pidf"
    printf '%s %s\n' "$pid" "$label" >> "$PID_FILE"
    printf '  ✓ %-24s pid=%-6s port=%-5s log=logs/%s.log\n' "$label" "$pid" "$port" "$name"
}

stop_all() {
    echo
    echo "Stopping all services…"
    if [[ -f "$PID_FILE" ]]; then
        while read -r pid label; do
            [[ -n "${pid:-}" ]] || continue
            if kill -0 "$pid" 2>/dev/null; then
                kill "$pid" 2>/dev/null || true
                echo "  ✗ stopped $label (pid $pid)"
            fi
        done < "$PID_FILE"
    fi
    : > "$PID_FILE"
}

FOREGROUND=0
[[ "${1:-}" == "-f" || "${1:-}" == "--foreground" ]] && FOREGROUND=1

echo "Starting DECA — Decade of Autonomous Triage (project: $ROOT)"
echo "──────────────────────────────────────────────────────────────"
for entry in "${SERVICES[@]}"; do
    IFS='|' read -r label kind target port <<< "$entry"
    start_one "$label" "$kind" "$target" "$port"
    sleep 0.4
done
echo "──────────────────────────────────────────────────────────────"
echo "All services launched. Dashboard: http://localhost:5000"
echo "STIP Generator:                   http://localhost:5001"
echo "Mock Outlook:                     http://localhost:5002"
echo "Tail logs:  tail -f logs/*.log"
echo "Stop all:   ./stop_all.sh   (or Ctrl+C if started with -f)"

if [[ "$FOREGROUND" -eq 1 ]]; then
    trap stop_all INT TERM
    echo
    echo "Running in foreground — press Ctrl+C to stop everything."
    wait
fi
