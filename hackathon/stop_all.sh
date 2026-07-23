#!/usr/bin/env bash
# Stop every service started by start_all.sh.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PID_FILE="$ROOT/logs/all.pids"

if [[ ! -f "$PID_FILE" ]]; then
    echo "No PID file ($PID_FILE). Nothing to stop, or services were not started via start_all.sh."
    exit 0
fi

echo "Stopping all DECA — Decade of Autonomous Triage services…"
while read -r pid label; do
    [[ -n "${pid:-}" ]] || continue
    if kill -0 "$pid" 2>/dev/null; then
        kill "$pid" 2>/dev/null || true
        echo "  ✗ stopped $label (pid $pid)"
    else
        echo "  · already stopped $label (pid $pid)"
    fi
done < "$PID_FILE"

: > "$PID_FILE"
echo "Done."
