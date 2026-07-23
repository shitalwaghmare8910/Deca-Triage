# src/email_listener/email_listener.py
"""
Shared-Mailbox Email Alert Listener
===================================

Standalone service (does NOT modify any existing code). It polls a shared
mailbox via the Microsoft Graph API for UNREAD messages, treats each new
message as an alert (using the email Subject as the alert name), and forwards
it to the Root Orchestrator's /process-alert endpoint — the same contract the
ServiceNow poller in src/backend/server.py already uses.

Auth: OAuth2 client-credentials flow (Azure AD app registration with the
application permission `Mail.ReadWrite` on the shared mailbox).

All configuration is read from environment variables (see .env.example).
Secrets are NEVER hardcoded.
"""

import os
import sys
import time
import logging
import requests

try:
    import msal
except ImportError:  # msal is only required for real Graph (OAuth) mode.
    msal = None  # In mock mode this is fine; real mode validates below.

# --- Optional .env loading (no-op if python-dotenv isn't installed) ---
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# --- Logging ---
logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(asctime)s - %(message)s")
logger = logging.getLogger("email_listener")

# --- Configuration (all from environment) ---
TENANT_ID = os.getenv("GRAPH_TENANT_ID", "")
CLIENT_ID = os.getenv("GRAPH_CLIENT_ID", "")
CLIENT_SECRET = os.getenv("GRAPH_CLIENT_SECRET", "")
SHARED_MAILBOX = os.getenv("SHARED_MAILBOX", "")  # e.g. alerts@yourdomain.com

ORCHESTRATOR_URL = os.getenv("ORCHESTRATOR_URL", "http://localhost:8080")

# Where to send detected alerts:
#   FORWARD_MODE=orchestrator (default) -> POST {ORCHESTRATOR_URL}/process-alert
#                                          (original, unchanged behavior)
#   FORWARD_MODE=backend                -> POST {BACKEND_URL}/api/ingest-alert
#                                          so the alert shows on the dashboard
#                                          with a live investigation, exactly
#                                          like a ServiceNow incident.
FORWARD_MODE = os.getenv("FORWARD_MODE", "orchestrator").strip().lower()
BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:5000")
POLL_INTERVAL = int(os.getenv("POLL_INTERVAL", "30"))          # seconds
REQUEST_TIMEOUT = int(os.getenv("REQUEST_TIMEOUT", "120"))      # seconds
PAGE_SIZE = int(os.getenv("PAGE_SIZE", "25"))                   # messages per poll
SUBJECT_FILTER = os.getenv("SUBJECT_FILTER", "").strip()        # optional keyword
SENDER_FILTER = os.getenv("SENDER_FILTER", "").strip().lower()  # optional sender
MARK_AS_READ = os.getenv("MARK_AS_READ", "true").lower() in ("1", "true", "yes")

# --- Mock mode (default OFF) ---
# When EMAIL_LISTENER_MODE=mock the listener talks to the local Mock Outlook
# service (Graph-compatible) and SKIPS OAuth entirely. Any other value keeps the
# real Microsoft Graph + MSAL behavior exactly as before.
MODE = os.getenv("EMAIL_LISTENER_MODE", "graph").strip().lower()
MOCK_MODE = MODE == "mock"

# GRAPH_BASE is configurable so mock mode can point at the local mock. In real
# mode it defaults to the genuine Graph endpoint (unchanged behavior).
_DEFAULT_GRAPH_BASE = (
    "http://localhost:5002/v1.0" if MOCK_MODE else "https://graph.microsoft.com/v1.0"
)
GRAPH_BASE = os.getenv("GRAPH_BASE", _DEFAULT_GRAPH_BASE).rstrip("/")
GRAPH_SCOPE = ["https://graph.microsoft.com/.default"]


def _validate_config() -> None:
    """Fail fast at startup if required configuration is missing."""
    # In mock mode we only need a mailbox name for the URL path; OAuth vars are
    # not required because the mock does not authenticate.
    if MOCK_MODE:
        if not SHARED_MAILBOX:
            logger.error("Missing required environment variable: SHARED_MAILBOX")
            sys.exit(1)
        return

    missing = [
        name for name, val in (
            ("GRAPH_TENANT_ID", TENANT_ID),
            ("GRAPH_CLIENT_ID", CLIENT_ID),
            ("GRAPH_CLIENT_SECRET", CLIENT_SECRET),
            ("SHARED_MAILBOX", SHARED_MAILBOX),
        ) if not val
    ]
    if missing:
        logger.error("Missing required environment variables: %s", ", ".join(missing))
        logger.error("Copy .env.example to .env and fill in the values.")
        sys.exit(1)


def _build_msal_app() -> "msal.ConfidentialClientApplication":
    if msal is None:
        logger.error("Missing dependency 'msal'. Install with: pip install -r requirements.txt")
        sys.exit(1)
    authority = f"https://login.microsoftonline.com/{TENANT_ID}"
    return msal.ConfidentialClientApplication(
        client_id=CLIENT_ID,
        client_credential=CLIENT_SECRET,
        authority=authority,
    )


def _get_token(app) -> str:
    """Acquire a Graph access token. MSAL caches and reuses tokens internally."""
    # Mock mode: no auth server exists, return a placeholder the mock ignores.
    if MOCK_MODE:
        return "mock-token"
    result = app.acquire_token_silent(GRAPH_SCOPE, account=None)
    if not result:
        result = app.acquire_token_for_client(scopes=GRAPH_SCOPE)
    if "access_token" not in result:
        raise RuntimeError(
            f"Failed to acquire Graph token: "
            f"{result.get('error')} - {result.get('error_description')}"
        )
    return result["access_token"]


def _fetch_unread(token: str) -> list:
    """Return unread messages from the shared mailbox inbox, oldest first."""
    url = f"{GRAPH_BASE}/users/{SHARED_MAILBOX}/mailFolders/Inbox/messages"
    params = {
        "$filter": "isRead eq false",
        "$select": "id,subject,from,receivedDateTime",
        "$orderby": "receivedDateTime asc",
        "$top": str(PAGE_SIZE),
    }
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    resp = requests.get(url, headers=headers, params=params, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    return resp.json().get("value", [])


def _mark_read(token: str, message_id: str) -> None:
    url = f"{GRAPH_BASE}/users/{SHARED_MAILBOX}/messages/{message_id}"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    resp = requests.patch(url, headers=headers, json={"isRead": True}, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()


def _passes_filters(message: dict) -> bool:
    subject = (message.get("subject") or "")
    if SUBJECT_FILTER and SUBJECT_FILTER.lower() not in subject.lower():
        return False
    if SENDER_FILTER:
        sender = (
            message.get("from", {})
            .get("emailAddress", {})
            .get("address", "")
            .lower()
        )
        if SENDER_FILTER not in sender:
            return False
    return True


def _forward_to_orchestrator(alert_name: str) -> bool:
    """POST the alert to the Root Orchestrator (same contract as the ServiceNow poller)."""
    try:
        resp = requests.post(
            f"{ORCHESTRATOR_URL}/process-alert",
            json={"alert_name": alert_name},
            timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        logger.info("[FORWARD] Orchestrator accepted alert: '%s'", alert_name)
        return True
    except requests.exceptions.RequestException as e:
        logger.error("[FORWARD] Failed to forward alert '%s': %s", alert_name, e)
        return False


def _forward_to_backend(alert_name: str, sender: str) -> bool:
    """POST the alert to the backend ingest endpoint so it appears on the
    dashboard and runs the full investigation pipeline (like ServiceNow)."""
    try:
        resp = requests.post(
            f"{BACKEND_URL}/api/ingest-alert",
            json={"alert_name": alert_name, "sender": sender, "source": "Email"},
            timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        logger.info("[FORWARD] Backend accepted alert: '%s'", alert_name)
        return True
    except requests.exceptions.RequestException as e:
        logger.error("[FORWARD] Failed to forward alert '%s' to backend: %s", alert_name, e)
        return False


def _forward_alert(alert_name: str, sender: str) -> bool:
    """Dispatch the alert to the configured target."""
    if FORWARD_MODE == "backend":
        return _forward_to_backend(alert_name, sender)
    return _forward_to_orchestrator(alert_name)


def process_messages(token: str, messages: list) -> None:
    for msg in messages:
        subject = (msg.get("subject") or "").strip()
        message_id = msg.get("id")

        if not _passes_filters(msg):
            logger.debug("[SKIP] Filtered out message: '%s'", subject)
            # Mark as read so it isn't re-evaluated every poll.
            if MARK_AS_READ and message_id:
                try:
                    _mark_read(token, message_id)
                except requests.exceptions.RequestException:
                    pass
            continue

        alert_name = subject or "(no subject)"
        sender = msg.get("from", {}).get("emailAddress", {}).get("address", "unknown")
        logger.info("[NEW ALERT] From %s — '%s'", sender, alert_name)

        forwarded = _forward_alert(alert_name, sender)

        # Only mark as read if successfully forwarded, so failed alerts are retried.
        if forwarded and MARK_AS_READ and message_id:
            try:
                _mark_read(token, message_id)
            except requests.exceptions.RequestException as e:
                logger.warning("[MARK-READ] Could not mark message read: %s", e)


def run() -> None:
    _validate_config()
    # Only build the MSAL app when we actually need real OAuth.
    app = None if MOCK_MODE else _build_msal_app()

    logger.info("=" * 60)
    logger.info("  Shared-Mailbox Email Alert Listener")
    logger.info("  Mode         : %s", "MOCK (local Outlook)" if MOCK_MODE else "GRAPH (Microsoft 365)")
    logger.info("  Graph base   : %s", GRAPH_BASE)
    logger.info("  Mailbox      : %s", SHARED_MAILBOX)
    if FORWARD_MODE == "backend":
        logger.info("  Forward to   : %s/api/ingest-alert (dashboard pipeline)", BACKEND_URL)
    else:
        logger.info("  Forward to   : %s/process-alert (orchestrator)", ORCHESTRATOR_URL)
    logger.info("  Orchestrator : %s/process-alert", ORCHESTRATOR_URL)
    logger.info("  Poll interval: %ss", POLL_INTERVAL)
    if SUBJECT_FILTER:
        logger.info("  Subject filter: contains '%s'", SUBJECT_FILTER)
    if SENDER_FILTER:
        logger.info("  Sender filter : '%s'", SENDER_FILTER)
    logger.info("=" * 60)

    while True:
        try:
            token = _get_token(app)
            messages = _fetch_unread(token)
            if messages:
                logger.info("[POLL] %d unread message(s) found.", len(messages))
                process_messages(token, messages)
            else:
                logger.debug("[POLL] No unread messages.")
        except requests.exceptions.HTTPError as e:
            logger.error("[GRAPH] HTTP error: %s — %s", e, getattr(e.response, "text", ""))
        except requests.exceptions.RequestException as e:
            logger.error("[GRAPH] Network error: %s", e)
        except Exception as e:  # keep the loop alive on unexpected errors
            logger.error("[LOOP] Unexpected error: %s", e, exc_info=True)

        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    try:
        run()
    except KeyboardInterrupt:
        logger.info("Listener stopped.")
