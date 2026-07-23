/* ═══════════════════════════════════════════════════════════════════════════
   DECA — Decade of Autonomous Triage — Alert Pipeline Workflow view
   Binds to existing /api/incidents + /api/incidents/:id (steps + orchestrator_response).
   ═══════════════════════════════════════════════════════════════════════════ */

let PipeTab = 'timeline';
let PipeDetail = null;

/* ── Live execution-log buffers (client-side; no backend/contract change) ──
   LiveLogs:  incidentId -> [ { text } ]   accumulated console lines
   LiveSeen:  incidentId -> { steps:{num:status}, orch:bool, seeded:bool }
   Lines observed live (status transitions) get a clock timestamp; historical
   lines seeded on first view are shown untimed to avoid fabricating times.   */
const LiveLogs = {};
const LiveSeen = {};

function logNowTs() { return new Date().toLocaleTimeString('en-GB'); }

// D — surface orchestrator/agent internals as individual log lines.
function orchDetailLines(orch, inc) {
    const lines = [];
    if (!orch) return lines;
    if (orch.runbook_matched) lines.push(`[RUNBOOK] Matched: ${orch.runbook_matched}`);
    const qr = orch.query_results || orch.query_result || [];
    if (Array.isArray(qr) && qr.length >= 0) {
        lines.push(`[SQL] Executed ${qr.length} ${qr.length === 1 ? 'query' : 'queries'}`);
    }
    if (orch.sql_query_result) lines.push(`[SQL] Result: ${orch.sql_query_result}`);
    const decision = inc.ai_decision || orch.decision;
    if (decision) lines.push(`[DECISION] ${decision}`);
    const actions = orch.recommended_actions
        || (orch.detailed_analysis_report && orch.detailed_analysis_report.recommended_actions)
        || [];
    const actionCount = Array.isArray(actions) ? actions.length : actions;
    if (actionCount) lines.push(`[ACTIONS] ${actionCount} recommended action(s)`);
    if (orch.report_generated || inc.state === 'completed') lines.push('[REPORT] Final RCA report generated');
    if (orch.analysis_summary) lines.push('[ORCHESTRATOR] ' + orch.analysis_summary);
    return lines;
}

// A — accumulate log lines from step data, appending only what changed.
function accumulateLogs(inc) {
    const id = inc.id;
    if (!LiveLogs[id]) LiveLogs[id] = [];
    if (!LiveSeen[id]) LiveSeen[id] = { steps: {}, orch: false, seeded: false };
    const buf = LiveLogs[id];
    const seen = LiveSeen[id];
    const steps = (inc.steps || []).slice().sort((a, b) => a.step_number - b.step_number);
    const orch = parseOrch(inc);

    if (!seen.seeded) {
        // First view in this session: seed existing history without fake timestamps.
        steps.forEach(s => {
            buf.push({ text: `[STEP ${s.step_number}] ${s.step_name} → ${s.status}${s.details ? '  | ' + s.details : ''}` });
            seen.steps[s.step_number] = s.status;
        });
        if (orch) { orchDetailLines(orch, inc).forEach(l => buf.push({ text: l })); seen.orch = true; }
        seen.seeded = true;
        return;
    }

    // Subsequent SSE/poll refreshes: append only newly-changed steps, timestamped.
    steps.forEach(s => {
        if (seen.steps[s.step_number] !== s.status) {
            seen.steps[s.step_number] = s.status;
            buf.push({ text: `[${logNowTs()}] [STEP ${s.step_number}] ${s.step_name} → ${s.status}${s.details ? '  | ' + s.details : ''}` });
        }
    });
    if (orch && !seen.orch) {
        orchDetailLines(orch, inc).forEach(l => buf.push({ text: `[${logNowTs()}] ${l}` }));
        seen.orch = true;
    }
}

function scrollLogToBottom() {
    requestAnimationFrame(() => {
        const el = document.getElementById('pipe-log-out');
        if (el) el.scrollTop = el.scrollHeight;
    });
}

/* ── Clickable timeline + per-step output (auto-follow live; no backend change) ──
   PipeSelectedStep: currently selected step_number for the Step Output panel.
   PipeStepManual:   true once the user clicks a step (stops auto-follow).
   PipeStepIncident: incident the selection belongs to (reset on incident switch). */
let PipeSelectedStep = null;
let PipeStepManual = false;
let PipeStepIncident = null;

function activeStepNumber(inc) {
    const steps = (inc.steps || []).slice().sort((a, b) => a.step_number - b.step_number);
    if (!steps.length) return null;
    const running = steps.find(s => s.status === 'running');
    if (running) return running.step_number;
    const completed = steps.filter(s => s.status === 'completed');
    if (completed.length) return completed[completed.length - 1].step_number;
    return steps[0].step_number;
}

function ensureStepSelection(inc) {
    if (PipeStepIncident !== inc.id) {
        PipeStepIncident = inc.id;
        PipeStepManual = false;
        PipeSelectedStep = null;
    }
    const exists = (inc.steps || []).some(s => s.step_number === PipeSelectedStep);
    if (!PipeStepManual || !exists) {
        PipeSelectedStep = activeStepNumber(inc);
    }
}

function kvBlock(obj) {
    return '<div class="kv">' + Object.entries(obj)
        .map(([k, v]) => `<span class="k">${GPS.esc(k)}</span><span class="v">${GPS.esc(String(v))}</span>`)
        .join('') + '</div>';
}

// Build the right-side output for one step using data already in /api/incidents/:id.
function stepOutputHtml(inc, n) {
    const step = (inc.steps || []).find(s => s.step_number === n);
    if (!step) return '<p class="pdesc">No step selected.</p>';
    const orch = parseOrch(inc);

    let extra = '';
    switch (n) {
        case 1: // Alert Reception
            extra = kvBlock({
                'Incident': inc.number || '—',
                'Short description': inc.short_description || '—',
                'Source': 'Listener',
            });
            break;
        case 2: // Parameter Extraction
            extra = kvBlock({
                'Alert name': inc.short_description || '—',
                'Category': inc.category || '—',
                'Assignment group': inc.assignment_group || '—',
            });
            break;
        case 3: // Runbook Search
            extra = orch ? kvBlock({ 'Runbook matched': orch.runbook_matched || 'N/A' }) : '';
            break;
        case 4: { // Diagnostic Queries
            if (orch) {
                const qr = orch.query_results || [];
                extra = kvBlock({
                    'SQL status': orch.sql_query_result || 'N/A',
                    'Queries executed': Array.isArray(qr) ? qr.length : '—',
                });
                if (Array.isArray(qr) && qr.length) {
                    extra += `<div class="code-out">${GPS.esc(JSON.stringify(qr, null, 2))}</div>`;
                }
            }
            break;
        }
        case 5: // AI Root Cause Analysis
            if (orch) extra = `<div class="code-out">${GPS.esc(orch.analysis_summary || 'Analysis pending…')}</div>`;
            break;
        case 6: { // Post-Analysis Actions
            if (orch) {
                const actions = orch.recommended_actions
                    || (orch.detailed_analysis_report && orch.detailed_analysis_report.recommended_actions)
                    || [];
                const list = Array.isArray(actions) && actions.length
                    ? '<ul class="so-list">' + actions.map(a => `<li>${GPS.esc(a)}</li>`).join('') + '</ul>'
                    : '<p class="pdesc">No recommended actions.</p>';
                extra = kvBlock({ 'Report generated': inc.state === 'completed' ? 'Yes' : 'No' }) + list;
            }
            break;
        }
    }

    const detail = step.details ? `<p class="pdesc">${GPS.esc(step.details)}</p>` : '';
    const fallback = (!extra && step.status === 'pending') ? '<p class="pdesc">This step has not run yet.</p>' : '';
    return `<div class="so-head"><span class="so-name">${GPS.esc(step.step_name)}</span>
        <span class="tl-state ${step.status}">${step.status}</span></div>
        ${detail}${extra}${fallback}`;
}



GPS.register('pipeline', {
    async refresh(force) {
        populateSelector();
        const inc = GPS.state.incidents;
        const live = inc.filter(i => i.state === 'in_progress').length;
        const done = inc.filter(i => i.state === 'completed').length;
        setText('pipe-live', live);
        setText('pipe-complete', done);
        setText('pipe-pending', inc.filter(i => i.state === 'failed').length);
        setText('pipe-total', inc.length);

        if (!GPS.state.selectedIncidentId && inc.length) GPS.state.selectedIncidentId = inc[0].id;
        if (GPS.state.selectedIncidentId) await loadAndRender(GPS.state.selectedIncidentId, force);
        else showPipeEmpty();
    },
});

function showPipeEmpty() {
    const c = document.getElementById('pipe-content');
    const e = document.getElementById('pipe-empty');
    if (c) c.style.display = 'none';
    if (e) e.style.display = 'block';
}

function populateSelector() {
    const sel = document.getElementById('pipe-select');
    if (!sel) return;
    const cur = GPS.state.selectedIncidentId;
    sel.innerHTML = GPS.state.incidents.map(i =>
        `<option value="${i.id}" ${i.id === cur ? 'selected' : ''}>${GPS.esc(i.number)} — ${GPS.esc(i.short_description)}</option>`).join('');
}

async function loadAndRender(id, force) {
    const detail = (force || !PipeDetail || PipeDetail.id !== id)
        ? await GPS.loadIncidentDetail(id) : PipeDetail;
    if (!detail) { showPipeEmpty(); return; }
    PipeDetail = detail;
    document.getElementById('pipe-empty').style.display = 'none';
    document.getElementById('pipe-content').style.display = 'block';
    renderPipeHeader(detail);
    renderPipeTabs(detail);
}

function renderPipeHeader(inc) {
    const p = inc.priority || 3;
    const sev = GPS.sev(p);
    const badge = document.getElementById('pipe-inc-sev');
    if (badge) { badge.textContent = sev.label; badge.className = `sev-badge sev-${p}`; }
    setText('pipe-inc-name', inc.short_description || '');
    setText('pipe-inc-svc', GPS.serviceOf(inc));
    setText('pipe-inc-meta', `${inc.number || ''} · ${GPS.timeAgo(inc.created_at)}`);

    let totalSec = null;
    if (inc.completed_at && inc.created_at)
        totalSec = Math.max(0, (new Date(inc.completed_at) - new Date(inc.created_at)) / 1000);
    setText('pipe-total-time', totalSec !== null ? `Total: ${GPS.fmtDur(totalSec)}` : 'In progress');
}

function renderPipeTabs(inc) {
    document.querySelectorAll('.pipe-tab').forEach(t =>
        t.classList.toggle('active', t.dataset.tab === PipeTab));
    const body = document.getElementById('pipe-tab-body');
    if (!body) return;
    if (PipeTab === 'timeline') body.innerHTML = timelineHtml(inc);
    else if (PipeTab === 'logs') body.innerHTML = logsHtml(inc);
    else body.innerHTML = detailsHtml(inc);
}

function timelineHtml(inc) {
    ensureStepSelection(inc);
    const steps = (inc.steps || []).slice().sort((a, b) => a.step_number - b.step_number);
    const items = steps.map(s => {
        const icon = s.status === 'completed' ? '✓' : s.status === 'running' ? '⟳' : s.status === 'failed' ? '✗' : '○';
        const sel = s.step_number === PipeSelectedStep ? ' selected' : '';
        return `<div class="tl-item clickable${sel}" data-step="${s.step_number}">
            <span class="tl-icon ${s.status}">${icon}</span>
            <div class="tl-head">
                <span class="tl-name">${GPS.esc(s.step_name)}</span>
                <span class="tl-state ${s.status}">${s.status}</span>
            </div>
            ${s.details ? `<div class="tl-desc">${GPS.esc(s.details)}</div>` : ''}
        </div>`;
    }).join('');
    return `<div class="card"><h3 class="card-title" style="margin-bottom:14px">Workflow Execution Timeline</h3>
        <div class="timeline">${items || '<p class="tl-desc">No steps recorded yet.</p>'}</div></div>`;
}

function logsHtml(inc) {
    accumulateLogs(inc);
    const buf = LiveLogs[inc.id] || [];
    const text = buf.map(b => b.text).join('\n');
    const live = inc.state === 'in_progress';
    scrollLogToBottom();
    return `<div class="card"><h3 class="card-title" style="margin-bottom:12px">Execution Logs ${live ? '<span class="log-live">● LIVE</span>' : ''}</h3>
        <div class="code-out" id="pipe-log-out">${GPS.esc(text) || 'No logs available.'}${live ? '<span class="log-cursor">▋</span>' : ''}</div></div>`;
}

function detailsHtml(inc) {
    const orch = parseOrch(inc);
    const report = orch && orch.detailed_analysis_report ? orch.detailed_analysis_report : null;
    const reportBtn = orch
        ? `<a class="btn-report" href="${GPS.API}/api/incidents/${inc.id}/report.html" target="_blank" rel="noopener"
             style="float:right;font-size:11px;font-weight:600;text-decoration:none;color:#fff;
             background:#003087;padding:5px 11px;border-radius:3px;">↗ View full report</a>`
        : '';
    let html = `<div class="card"><h3 class="card-title" style="margin-bottom:12px">Investigation Report${reportBtn}</h3>`;
    if (!orch) {
        html += `<p class="tl-desc">Analysis not available yet for this incident.</p></div>`;
        return html;
    }
    html += `<div class="kv">
        <span class="k">Runbook matched</span><span class="v">${GPS.esc(orch.runbook_matched || 'N/A')}</span>
        <span class="k">SQL status</span><span class="v">${GPS.esc(orch.sql_query_result || 'N/A')}</span>
        <span class="k">Summary</span><span class="v">${GPS.esc(orch.analysis_summary || '—')}</span>
    </div>`;
    if (report && report.recommended_actions && report.recommended_actions.length) {
        html += `<div style="margin-top:12px"><div class="card-title" style="margin-bottom:6px">Recommended Actions</div>`;
        html += '<ul style="margin:0;padding-left:18px;font-size:12px;color:#16203a">' +
            report.recommended_actions.map(a => `<li>${GPS.esc(a)}</li>`).join('') + '</ul></div>';
    }
    html += `</div>`;
    return html;
}

function parseOrch(inc) {
    let orch = inc.orchestrator_response;
    if (!orch) return null;
    if (typeof orch === 'string') { try { orch = JSON.parse(orch); } catch (e) { return null; } }
    return orch;
}

function renderSidePanels(inc) {
    const orch = parseOrch(inc);
    // Step Output (driven by the selected/active timeline step)
    ensureStepSelection(inc);
    const stepBody = document.getElementById('pipe-step-body');
    if (stepBody) stepBody.innerHTML = stepOutputHtml(inc, PipeSelectedStep);
    const stepBadge = document.getElementById('pipe-step-badge');
    if (stepBadge) {
        const st = (inc.steps || []).find(s => s.step_number === PipeSelectedStep);
        stepBadge.textContent = st ? st.status : '—';
    }
    // Notification & Resolution
    const notif = document.getElementById('pipe-notif-body');
    if (notif) {
        const out = orch ? {
            runbook_matched: orch.runbook_matched,
            decision: inc.ai_decision || (inc.state === 'completed' ? 'Report Generated' : 'analysing…'),
            recommended_actions: (orch.recommended_actions || []).length,
            report_generated: inc.state === 'completed',
        } : { status: inc.state };
        notif.innerHTML = `<p class="pdesc">Generate final RCA report and notify stakeholders.</p>
            <div class="code-out">${GPS.esc(JSON.stringify(out, null, 2))}</div>`;
        const badge = document.getElementById('pipe-notif-badge');
        if (badge) badge.textContent = inc.state === 'completed' ? 'Completed' : inc.state === 'failed' ? 'Failed' : 'Running';
    }
    // ServiceNow Ticket
    const ticket = document.getElementById('pipe-ticket-body');
    if (ticket) {
        ticket.innerHTML = `<div class="kv">
            <span class="k">Number</span><span class="v mono">${GPS.esc(inc.number || '')}</span>
            <span class="k">State</span><span class="v">${GPS.esc(GPS.statusOf(inc.state).label)}</span>
            <span class="k">Priority</span><span class="v">${inc.priority || 3} - ${GPS.esc(inc.priority_label || GPS.sev(inc.priority || 3).label)}</span>
            <span class="k">Assignment Group</span><span class="v">${GPS.esc(inc.assignment_group || '—')}</span>
            <span class="k">Short Description</span><span class="v">${GPS.esc(inc.short_description || '')}</span>
            <span class="k">Category</span><span class="v">${GPS.esc(inc.category || '—')}</span>
            <span class="k">Instance</span><span class="v mono">dbunity.service-now.com</span>
            <span class="k">Port</span><span class="v mono">5001</span>
        </div>`;
    }
}

/* hook side panels into header render */
const _renderPipeHeader = renderPipeHeader;
renderPipeHeader = function (inc) { _renderPipeHeader(inc); renderSidePanels(inc); };

function initPipelineControls() {
    const sel = document.getElementById('pipe-select');
    if (sel) sel.addEventListener('change', () => {
        GPS.state.selectedIncidentId = parseInt(sel.value, 10);
        loadAndRender(GPS.state.selectedIncidentId, true);
    });
    document.querySelectorAll('.pipe-tab').forEach(t =>
        t.addEventListener('click', () => { PipeTab = t.dataset.tab; if (PipeDetail) renderPipeTabs(PipeDetail); }));
    // Clickable timeline steps → show that step's output on the right (stops auto-follow).
    const tabBody = document.getElementById('pipe-tab-body');
    if (tabBody) tabBody.addEventListener('click', (e) => {
        const item = e.target.closest('.tl-item[data-step]');
        if (!item || !PipeDetail) return;
        PipeStepManual = true;
        PipeSelectedStep = parseInt(item.dataset.step, 10);
        renderPipeTabs(PipeDetail);
        renderSidePanels(PipeDetail);
    });
    const rnd = document.getElementById('btn-pipe-random');
    if (rnd) rnd.addEventListener('click', () => {
        const inc = GPS.state.incidents;
        if (!inc.length) { GPS.toast('No incidents available'); return; }
        const pick = inc[Math.floor(Math.random() * inc.length)];
        GPS.state.selectedIncidentId = pick.id;
        populateSelector();
        loadAndRender(pick.id, true);
    });
    const trig = document.getElementById('btn-pipe-trigger');
    if (trig) trig.addEventListener('click', triggerAlert);
}

async function triggerAlert() {
    // Best-effort: create an incident via the existing Mock ServiceNow API (no backend change).
    const base = serviceNowBaseUrl();
    const samples = [
        { short_description: 'HighDatabaseConnections', category: 'Database', impact: 1, urgency: 1, assignment_group: 'Database Operations' },
        { short_description: 'QueueBacklog', category: 'Infrastructure', impact: 2, urgency: 2, assignment_group: 'Platform Engineering' },
        { short_description: 'ResponseTimeHigh', category: 'Application', impact: 2, urgency: 1, assignment_group: 'Application Support' },
    ];
    const payload = { ...samples[Math.floor(Math.random() * samples.length)], description: 'Synthetic alert triggered from dashboard for demo.', state: 1 };
    try {
        const r = await fetch(`${base}/api/now/table/incident`, {
            method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload),
        });
        if (r.ok) GPS.toast('Alert triggered in ServiceNow', 'success');
        else GPS.toast('Trigger failed — open ServiceNow portal to create one', 'error');
    } catch (e) {
        GPS.toast('ServiceNow not reachable from dashboard — create incident in the portal', 'error');
    }
}

function serviceNowBaseUrl() {
    // Mirror health.js proxy logic so the same Jupyter proxy host can reach port 5001.
    const parts = window.location.pathname.split('/');
    const pi = parts.indexOf('proxy');
    if (pi === -1) return `${window.location.protocol}//${window.location.hostname}:5001`;
    const basePath = parts.slice(0, pi + 1).join('/');
    return `${window.location.origin}${basePath}/5001`;
}
