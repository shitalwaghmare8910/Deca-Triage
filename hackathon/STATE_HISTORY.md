# State Tracking — DECA — Decade of Autonomous Triage

This file tracks the saved restore points (git tags) for this project so any
change can be reverted safely. The project is under local git (branch `master`).

## How to use

```bash
cd /home/jovyan/work/gps-ai-telda-poc-final-copy

git tag                       # list all restore points
git diff <tag>                # see what changed since a restore point
git reset --hard <tag>        # revert tracked files to a restore point
git reset --hard <tag> && git clean -fd   # also delete files added after that tag
```

## Restore points (newest first)

| Tag | Description | What it contains |
|-----|-------------|------------------|
| `deca-rebrand-v3` | Rebrand to DECA | Renamed to "DECA — Decade of Autonomous Triage" (10th-anniversary "10" theme) across UI/docs/scripts. Backup: `../hackathon-before-deca-rebrand.tgz` |
| `rebrand-v2` | Rebrand + Confluence doc | Renamed to "GPS Octopus-AI-Powered Triage for Alerts" across UI/docs/scripts; added `docs/CONFLUENCE_PAGE.md` solution documentation; header title/subtitle spacing |
| `mock-outlook-pdf-v1` | Mock Outlook + email listener + PDF report | Mock Outlook inbox (port 5002, Graph-compatible), email listener mock mode → `/api/ingest-alert`, investigation report delivered to inbox as a downloadable PDF attachment |
| `before-mock-outlook` | Before Mock Outlook work | Baseline prior to the mock Outlook inbox / email-listener integration |
| `arch-diagram-v2` | Architecture diagram refresh | Rebrand + Email Listener ingress + Investigation Report flow + updated port map |
| `rebrand-v1` | Rebrand applied | "GCP AI Triage System" → "GPS OCTOPUS AI TRIAGE"; "Command Dashboard" → "Agentic SRE Intelligence" |
| `before-rebrand` | Before rename | Report feature + dynamic confidence, original branding |
| `report-feature-v1` | Report feature working | HTML investigation report + endpoint + UI button (static 72/90 confidence) |
| `pre-report-feature` | Baseline | Working state before any investigation-report work (agents, STIP, UI, Dockerfiles, requirements, start scripts) |

## Feature notes

- **Mock Outlook + PDF report** (`mock-outlook-pdf-v1`) — mock Outlook mailbox at
  `src/email_listener/mock_outlook/` (Flask, port 5002; Graph-compatible Inbox GET +
  PATCH, plus `/api/compose`, `/api/deliver-report`, `/api/messages`,
  `/api/messages/<id>/attachments/<idx>`). Email listener gained `EMAIL_LISTENER_MODE=mock`
  and `FORWARD_MODE=backend` (both default to the original real-Graph/orchestrator path).
  Backend `/api/ingest-alert` mirrors the ServiceNow poller; on completion
  `_deliver_report_email()` converts the report HTML to a PDF via `xhtml2pdf` and
  delivers it to the inbox as a downloadable attachment (delivered already-read, so no
  listener loop). All additive / default-off.
- **Investigation Report** — read-only endpoint `GET /api/incidents/<id>/report.html`
  in `src/backend/server.py`; renderer in `src/backend/report_template.py`
  (copy in `src/agents/notification-agent/report_template.py`). "View full report"
  button added in `src/backend/static/js/gps-pipeline.js`. All additive.
- **Dynamic confidence** — Gemini assigns `confidence_score` (0-100) via the
  orchestrator prompt; deterministic `_compute_confidence()` fallback in the
  orchestrator and both report templates when the model omits it.
- **Branding** — visible title in `src/backend/static/index.html`; header
  comments across `src/backend/static/js/gps-*.js` and `css/gps.css`.

## Adding a new restore point

```bash
git add -A
git -c user.email=snapshot@local -c user.name=snapshot commit -m "Snapshot: <description>"
git tag <short-tag-name>
```

Then add a row to the table above.
