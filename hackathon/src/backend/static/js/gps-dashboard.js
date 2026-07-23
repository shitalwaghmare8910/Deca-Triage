/* ═══════════════════════════════════════════════════════════════════════════
   DECA — Decade of Autonomous Triage — Agentic SRE Intelligence view
   ═══════════════════════════════════════════════════════════════════════════ */

GPS.register('dashboard', {
    refresh() {
        const s = GPS.state.stats;
        const inc = GPS.state.incidents;
        const total = s.total || inc.length;
        const completed = s.completed || 0;
        const failed = s.failed || 0;
        const investigating = s.investigating || 0;
        const rate = total ? Math.round((completed / total) * 100) : 0;
        const escRate = total ? Math.round((failed / total) * 100) : 0;

        setText('dash-total', total);
        setText('dash-investigating', investigating);
        setText('dash-resolved', completed);
        setText('dash-resolved-sub', `${rate}% rate`);
        setText('dash-escalated', failed);
        setText('dash-escalated-sub', `${escRate}% esc`);
        setText('dash-auto', completed);
        setText('dash-avg', GPS.fmtSecValue(GPS.avgResolutionSeconds()));

        GPSCharts.alertVolumeLine('chart-alert-volume');
        GPSCharts.severityDonut('chart-severity', 'severity-legend');

        renderRecent(inc);
        renderAgentStatus();
        renderDecisionCards(total);
    },
});

function setText(id, v) { const el = document.getElementById(id); if (el) el.textContent = v; }

function renderRecent(incidents) {
    const tbody = document.getElementById('dash-recent-tbody');
    const count = document.getElementById('dash-recent-count');
    if (count) count.textContent = `Showing latest ${Math.min(incidents.length, 8)}`;
    if (!tbody) return;
    if (!incidents.length) {
        tbody.innerHTML = `<tr><td colspan="7" style="text-align:center;padding:28px;color:#9aa3b5">No incidents yet. Create one in ServiceNow.</td></tr>`;
        return;
    }
    tbody.innerHTML = incidents.slice(0, 8).map(rowHtml).join('');
}

function rowHtml(inc) {
    const p = inc.priority || 3;
    const sev = GPS.sev(p);
    const st = GPS.statusOf(inc.state);
    const decision = inc.state === 'in_progress' ? 'analysing…'
        : (inc.ai_decision || (inc.state === 'completed' ? 'Report Generated' : '—'));
    const decCls = inc.state === 'in_progress' ? '' : 'done';
    return `<tr>
        <td><span class="t-id" onclick="openIncident(${inc.id})">${GPS.esc(inc.number)}</span></td>
        <td><div class="t-main">${GPS.esc(inc.short_description)}</div><div class="t-sub">${GPS.esc(GPS.serviceOf(inc))}</div></td>
        <td><span class="sev-badge sev-${p} sev-outline">${sev.label}</span></td>
        <td><span class="status-chip status-${st.cls}"><span class="dot"></span>${st.label}</span></td>
        <td><span class="ai-decision ${decCls}">${GPS.esc(decision)}</span></td>
        <td><span class="src-cell"><span class="material-icons-outlined">dns</span>${GPS.esc((GPS.serviceOf(inc) || 'svc').split(' ')[0].toLowerCase())}</span></td>
        <td class="t-time">${GPS.timeAgo(inc.created_at)}</td>
    </tr>`;
}

function openIncident(id) {
    GPS.state.selectedIncidentId = id;
    GPS.switchView('pipeline');
}

function renderAgentStatus() {
    const wrap = document.getElementById('dash-agent-status');
    if (!wrap) return;
    const agents = GPS.state.agents;
    if (!agents.length) { wrap.innerHTML = `<div style="color:#9aa3b5;font-size:12px">Checking agents…</div>`; return; }
    wrap.innerHTML = agents.slice(0, 8).map(a => {
        const tag = GPS.AGENT_TAGS[a.name] || a.name.slice(0, 2).toUpperCase();
        const online = a.status === 'online';
        return `<div class="agent-status-row">
            <span class="agent-status-tag">${tag}</span>
            <span class="agent-status-name">${GPS.esc(a.name)}</span>
            <span class="agent-status-line"></span>
            <span class="agent-status-dot ${online ? 'online' : 'offline'}"></span>
        </div>`;
    }).join('');
}

function renderDecisionCards(total) {
    const d = GPS.decisionCounts();
    const pct = n => total ? Math.round((n / total) * 100) : 0;
    setDecision('dec-auto', d.autoRemediated, pct(d.autoRemediated), '#16a34a');
    setDecision('dec-esc', d.escalated, pct(d.escalated), '#dc2626');
    setDecision('dec-mon', d.monitoring, pct(d.monitoring), '#3b82f6');
    setDecision('dec-noaction', d.noAction, pct(d.noAction), '#9aa3b5');
}

function setDecision(id, value, pct, color) {
    setText(`${id}-value`, value);
    setText(`${id}-sub`, `${pct}% of total`);
    const bar = document.getElementById(`${id}-bar`);
    if (bar) bar.innerHTML = `<span style="width:${Math.max(pct, 3)}%;background:${color}"></span>`;
}
