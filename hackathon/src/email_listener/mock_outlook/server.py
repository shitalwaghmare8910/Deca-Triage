"""
Mock Outlook / Microsoft Graph Mailbox
======================================

A standalone Flask app that mimics the *narrow* slice of the Microsoft Graph
mail API that ``email_listener.py`` actually calls, plus a small Outlook-style
web UI for composing "alert" emails into the inbox.

Design goals (do NOT change any existing functionality):
  * Brand-new, isolated service — mirrors the Mock ServiceNow portal
    (src/stip_generater/server.py) in spirit and structure.
  * Implements the exact Graph endpoints the listener uses so the listener can
    poll this mock unchanged when it is pointed at this base URL:
        GET   /v1.0/users/<mailbox>/mailFolders/Inbox/messages
        PATCH /v1.0/users/<mailbox>/messages/<id>
  * Extra UI-only endpoints for the mock inbox:
        POST  /api/compose     -> create a new alert email in the inbox
        GET   /api/messages    -> list all messages (for the UI)
        GET   /                -> serves the Outlook-like UI
        GET   /health          -> health probe

All state is in-memory. No secrets, no external calls.
"""

import os
import uuid
import base64
import binascii
from datetime import datetime, timezone

from flask import Flask, request, jsonify, send_from_directory, Response
from flask_cors import CORS

app = Flask(__name__, static_folder="static", static_url_path="")
CORS(app)

# ─── Config ─────────────────────────────────────────────────────────────────
PORT = int(os.getenv("MOCK_OUTLOOK_PORT", "5002"))
# The mailbox this mock "owns". The listener addresses the mailbox by name in
# the URL path; we accept ANY mailbox value so config never has to match.
DEFAULT_MAILBOX = os.getenv("SHARED_MAILBOX", "alerts@yourdomain.com")

# ─── In-Memory Mailbox Store ────────────────────────────────────────────────
# Each message mirrors the shape returned by Microsoft Graph for the fields the
# listener selects: id, subject, from.emailAddress.address, receivedDateTime,
# isRead. We also keep bodyPreview/body for a nicer UI.
messages: "dict[str, dict]" = {}


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _new_id() -> str:
    return uuid.uuid4().hex


def _attachment_meta(att: dict) -> dict:
    """Attachment metadata for the UI (no base64 bytes)."""
    return {
        "name": att.get("name", "attachment"),
        "contentType": att.get("contentType", "application/octet-stream"),
        "size": att.get("size") or 0,
    }


def create_message(subject: str, sender: str, body: str = "", *,
                   is_read: bool = False, is_report: bool = False,
                   body_html: str = "", attachments=None) -> dict:
    """Create a Graph-shaped message and store it in the inbox.

    Report emails are delivered already-read (is_read=True) so the email
    listener's ``isRead eq false`` filter ignores them and no loop occurs.
    ``attachments`` is a list of dicts: name, contentType, size, contentBytes(b64).
    """
    msg_id = _new_id()
    content_type = "html" if body_html else "text"
    record = {
        "id": msg_id,
        "subject": subject or "(no subject)",
        "from": {"emailAddress": {"address": sender or "monitoring@alerts.local"}},
        "receivedDateTime": _now_iso(),
        "isRead": bool(is_read),
        "isReport": bool(is_report),
        "bodyPreview": (body or "")[:255],
        "body": {"contentType": content_type, "content": body_html or body or ""},
        "attachments": attachments or [],
        "hasAttachments": bool(attachments),
    }
    messages[msg_id] = record
    return record


def _seed() -> None:
    """Pre-seed a couple of realistic alert emails (all start unread)."""
    seeds = [
        ("HighDatabaseConnections", "grafana@monitoring.local",
         "Active DB connections on payment-service exceeded threshold 200. Current: 347."),
        ("PSD2 Outbound Latency Alert", "prometheus@monitoring.local",
         "PSD2 outbound gateway P99 latency rose from 120ms to 2400ms. 502s on downstream banks."),
    ]
    for subject, sender, body in seeds:
        create_message(subject, sender, body)


# ─── Graph-compatible API (subset the listener uses) ────────────────────────

def _matches_filter(msg: dict, odata_filter: str) -> bool:
    """Support the single filter the listener sends: ``isRead eq false``."""
    if not odata_filter:
        return True
    f = odata_filter.replace(" ", "").lower()
    if f == "isreadeqfalse":
        return not msg.get("isRead", False)
    if f == "isreadeqtrue":
        return bool(msg.get("isRead", False))
    return True


@app.route("/v1.0/users/<mailbox>/mailFolders/Inbox/messages", methods=["GET"])
@app.route("/v1.0/users/<mailbox>/mailFolders/inbox/messages", methods=["GET"])
def graph_list_messages(mailbox):
    """Mimic GET .../mailFolders/Inbox/messages with $filter/$orderby/$top."""
    odata_filter = request.args.get("$filter", "")
    orderby = request.args.get("$orderby", "receivedDateTime asc")
    try:
        top = int(request.args.get("$top", "25"))
    except ValueError:
        top = 25

    results = [m for m in messages.values() if _matches_filter(m, odata_filter)]

    reverse = "desc" in orderby.lower()
    results.sort(key=lambda m: m.get("receivedDateTime", ""), reverse=reverse)
    results = results[:top]

    return jsonify({"value": results})


@app.route("/v1.0/users/<mailbox>/messages/<message_id>", methods=["PATCH"])
def graph_patch_message(mailbox, message_id):
    """Mimic PATCH .../messages/<id> — the listener uses this to mark read."""
    record = messages.get(message_id)
    if not record:
        return jsonify({"error": {"message": "Message not found"}}), 404
    data = request.get_json(force=True, silent=True) or {}
    if "isRead" in data:
        record["isRead"] = bool(data["isRead"])
    return jsonify(record)


# ─── UI-only helpers ────────────────────────────────────────────────────────

@app.route("/api/compose", methods=["POST"])
def compose():
    """Create a new alert email into the inbox (used by the mock UI)."""
    data = request.get_json(force=True, silent=True) or {}
    subject = (data.get("subject") or "").strip()
    sender = (data.get("from") or "monitoring@alerts.local").strip()
    body = (data.get("body") or "").strip()
    if not subject:
        return jsonify({"error": "subject is required"}), 400
    record = create_message(subject, sender, body)
    return jsonify({"result": record}), 201


@app.route("/api/deliver-report", methods=["POST"])
def deliver_report():
    """Deliver a Post-Analysis Investigation Report back into the inbox.

    The report is delivered ALREADY-READ and flagged (isReport=true) so the
    email listener (which only picks up unread mail) never treats it as a new
    alert — this prevents any processing loop.
    """
    data = request.get_json(force=True, silent=True) or {}
    subject = (data.get("subject") or "Investigation Report").strip()
    sender = (data.get("from") or "ai-triage@octopus.local").strip()
    body = (data.get("body") or "").strip()
    body_html = data.get("body_html") or ""
    attachments = data.get("attachments") or []
    record = create_message(
        subject, sender, body,
        is_read=True, is_report=True, body_html=body_html,
        attachments=attachments,
    )
    # Don't echo the (potentially large) base64 bytes back in the response.
    safe = dict(record)
    safe["attachments"] = [_attachment_meta(a) for a in record["attachments"]]
    return jsonify({"result": safe}), 201


@app.route("/api/messages", methods=["GET"])
def list_messages():
    """List all messages (read + unread) for the UI, newest first.
    Attachment bytes are stripped to keep the payload small."""
    results = []
    for m in sorted(messages.values(), key=lambda m: m.get("receivedDateTime", ""), reverse=True):
        item = dict(m)
        item["attachments"] = [_attachment_meta(a) for a in m.get("attachments", [])]
        results.append(item)
    return jsonify({"result": results, "mailbox": DEFAULT_MAILBOX})


@app.route("/api/messages/<message_id>/attachments/<int:idx>", methods=["GET"])
def download_attachment(message_id, idx):
    """Serve a message attachment (e.g. the investigation report PDF)."""
    record = messages.get(message_id)
    if not record:
        return jsonify({"error": "not found"}), 404
    atts = record.get("attachments", [])
    if idx < 0 or idx >= len(atts):
        return jsonify({"error": "attachment not found"}), 404
    att = atts[idx]
    try:
        raw = base64.b64decode(att.get("contentBytes", ""))
    except (binascii.Error, ValueError):
        return jsonify({"error": "invalid attachment"}), 500
    return Response(
        raw,
        mimetype=att.get("contentType", "application/octet-stream"),
        headers={"Content-Disposition": f'attachment; filename="{att.get("name", "attachment")}"'},
    )


@app.route("/api/messages/<message_id>", methods=["DELETE"])
def delete_message(message_id):
    """Delete a message (UI convenience)."""
    if message_id in messages:
        del messages[message_id]
        return "", 204
    return jsonify({"error": "not found"}), 404


# ─── UI + Health ────────────────────────────────────────────────────────────

@app.route("/")
def serve_ui():
    return send_from_directory("static", "index.html")


@app.route("/health")
def health():
    return jsonify({"status": "healthy", "unread": sum(1 for m in messages.values() if not m["isRead"])})


# ─── Main ───────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    _seed()
    print("=" * 60)
    print("  Mock Outlook Mailbox")
    print(f"  UI:    http://localhost:{PORT}")
    print(f"  Graph: http://localhost:{PORT}/v1.0/users/{DEFAULT_MAILBOX}/mailFolders/Inbox/messages")
    print(f"  Pre-seeded {len(messages)} messages")
    print("=" * 60)
    app.run(host="0.0.0.0", port=PORT, debug=True)
