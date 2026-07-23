/* ═══════════════════════════════════════════════════════════════════════════
   DECA — Decade of Autonomous Triage — Analytics & Reporting view (client-side derived)
   ═══════════════════════════════════════════════════════════════════════════ */

GPS.register('analytics', {
    refresh() {
        GPSCharts.byServiceBar('chart-by-service');
        GPSCharts.hourlyStacked('chart-hourly');
        renderDecisionBreakdown();
        renderResolutionRate();
        renderRootCauses();
    },
});

function renderDecisionBreakdown() {
    const wrap = document.getElementById('analytics-decisions');
    if (!wrap) return;
    const d = GPS.decisionCounts();
    const total = GPS.state.incidents.length || 1;
    const rows = [
        { label: 'Auto-Remediated', value: d.autoRemediated, color: '#0a1f7a' },
        { label: 'Escalated', value: d.escalated, color: '#dc2626' },
        { label: 'Monitoring', value: d.monitoring, color: '#3b82f6' },
        { label: 'No Action', value: d.noAction, color: '#9aa3b5' },
    ];
    wrap.innerHTML = rows.map(r => {
        const pct = Math.round((r.value / total) * 100);
        return `<div class="bar-row">
            <span class="bl">${r.label}</span>
            <span class="bar-track"><span class="bar-fill" style="width:${Math.max(pct, 2)}%;background:${r.color}"></span></span>
            <span class="bv">${pct}%</span>
        </div>`;
    }).join('');
}

function renderResolutionRate() {
    const total = GPS.state.incidents.length;
    const completed = GPS.state.incidents.filter(i => i.state === 'completed').length;
    const failed = GPS.state.incidents.filter(i => i.state === 'failed').length;
    const rate = total ? Math.round((completed / total) * 100) : 0;
    setText('res-rate-num', rate);
    setText('res-rate-auto', completed);
    setText('res-rate-esc', failed);
}

function renderRootCauses() {
    const wrap = document.getElementById('root-causes');
    if (!wrap) return;
    const causes = GPS.rootCauses();
    if (!causes.length) { wrap.innerHTML = `<div style="color:#9aa3b5;font-size:12px">No data yet.</div>`; return; }
    const max = causes[0][1] || 1;
    wrap.innerHTML = causes.map((c, i) =>
        `<div class="rc-row">
            <span class="rc-i">${i + 1}</span>
            <span class="rc-name">${GPS.esc(c[0])}</span>
            <span class="rc-bar"><span style="width:${Math.round((c[1] / max) * 100)}%"></span></span>
        </div>`).join('');
}
