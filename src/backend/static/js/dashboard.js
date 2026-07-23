/* Dashboard view: stats, charts, recent table */

async function refreshDashboard() {
    try {
        const [stats, incidents] = await Promise.all([
            fetchJSON(`${API}/api/dashboard/stats`),
            fetchJSON(`${API}/api/incidents`),
        ]);
        renderStats(stats);
        renderRecentTable(incidents.result || []);
        renderCharts(stats, incidents.result || []);
    } catch(e) { console.error('Dashboard refresh error:', e); }
}

function renderStats(s) {
    animateValue('stat-total-value', s.total);
    animateValue('stat-investigating-value', s.investigating);
    animateValue('stat-completed-value', s.completed);
    animateValue('stat-failed-value', s.failed);
    document.getElementById('stat-completion-rate').textContent = `${s.completion_rate}% rate`;
    const avg = s.avg_resolution_seconds;
    document.getElementById('stat-avg-value').textContent = avg < 60 ? `${avg}s` : avg < 3600 ? `${Math.round(avg/60)}m` : `${Math.round(avg/3600)}h`;
}

function animateValue(id, target) {
    const el = document.getElementById(id);
    const current = parseInt(el.textContent) || 0;
    if (current === target) return;
    const diff = target - current;
    const steps = Math.min(Math.abs(diff), 20);
    const step = diff / steps;
    let i = 0;
    const timer = setInterval(() => {
        i++;
        el.textContent = Math.round(current + step * i);
        if (i >= steps) { el.textContent = target; clearInterval(timer); }
    }, 40);
}

function renderRecentTable(incidents) {
    const tbody = document.getElementById('recent-tbody');
    document.getElementById('recent-count').textContent = `${incidents.length} incident${incidents.length!==1?'s':''}`;
    if (!incidents.length) {
        tbody.innerHTML = '<tr><td colspan="6" style="text-align:center;padding:32px;color:#999;">No incidents yet. Create one in ServiceNow!</td></tr>';
        return;
    }
    tbody.innerHTML = incidents.slice(0, 20).map(inc => {
        const p = inc.priority || 3;
        const pLabel = {1:'Critical',2:'High',3:'Medium',4:'Low',5:'Planning'}[p]||'Medium';
        const stateClass = inc.state === 'completed' ? 'completed' : inc.state === 'failed' ? 'failed' : inc.state === 'processing' ? 'processing' : 'new';
        const stateLabel = {completed:'Completed',failed:'Failed',processing:'Processing',new:'New'}[stateClass]||inc.state;
        const decision = inc.ai_decision || '—';
        const decClass = decision.toLowerCase().replace(/[- ]/g, '-');
        const time = inc.created_at ? timeAgo(inc.created_at) : '';
        return `<tr>
            <td><span style="font-family:var(--mono);font-weight:600;color:var(--blue);cursor:pointer" onclick="switchView('pipeline');setTimeout(()=>selectIncident(${inc.id}),100)">${esc(inc.number)}</span></td>
            <td><span class="priority-badge priority-${p}">${pLabel}</span></td>
            <td>${esc(inc.short_description)}</td>
            <td><span class="status-badge status-${stateClass}">${stateLabel}</span></td>
            <td>${decision!=='—'?`<span class="decision-badge decision-${decClass}">${decision}</span>`:'—'}</td>
            <td style="color:var(--text-muted);font-size:12px">${time}</td>
        </tr>`;
    }).join('');
}

function timeAgo(ts) {
    const d = new Date(ts);
    const diff = (Date.now() - d.getTime()) / 1000;
    if (diff < 60) return 'Just now';
    if (diff < 3600) return `${Math.floor(diff/60)}m ago`;
    if (diff < 86400) return `${Math.floor(diff/3600)}h ago`;
    return d.toLocaleDateString('en-GB',{day:'numeric',month:'short'});
}

function esc(s) {
    if (!s) return '';
    const d = document.createElement('div'); d.textContent = s; return d.innerHTML;
}
