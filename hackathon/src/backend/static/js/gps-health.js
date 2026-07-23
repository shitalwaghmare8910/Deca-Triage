/* ═══════════════════════════════════════════════════════════════════════════
   DECA — Decade of Autonomous Triage — Agent Health Monitor view
   Uses existing GET /api/agent-health (server-side checks).
   ═══════════════════════════════════════════════════════════════════════════ */

GPS.register('agent-health', {
    async refresh(force) {
        if (force) await GPS.loadAgents();
        renderAgentHealth();
    },
});

function renderAgentHealth() {
    const agents = GPS.state.agents;
    const grid = document.getElementById('agent-grid');
    const online = agents.filter(a => a.status === 'online').length;
    const total = agents.length;

    setText('ah-online', `${online}/${total || 0}`);
    setText('ah-online-sub', online === total && total ? 'All agents healthy' : `${total - online} need attention`);
    setText('ah-latency', `${GPS.state.agentLatency || 0}ms`);
    setText('ah-lastcheck', new Date().toLocaleTimeString('en-GB'));

    if (grid) {
        if (!agents.length) {
            grid.innerHTML = `<div class="empty-state"><span class="material-icons-outlined">sync</span><h3>Checking agents…</h3></div>`;
        } else {
            grid.innerHTML = agents.map(agentCard).join('');
        }
    }
    renderInvestigationFlow();
}

function agentCard(a) {
    const up = a.status === 'online';
    const port = GPS.AGENT_PORTS[a.name] || '—';
    const latency = up ? (GPS.state.agentLatency || 0) : 0;
    const tag = GPS.AGENT_TAGS[a.name] || a.name.slice(0, 2).toUpperCase();
    return `<div class="agent-card ${up ? 'is-up' : 'is-down'}">
        <div class="agent-card-head">
            <div class="agent-card-id">
                <div class="agent-avatar">${GPS.esc(tag)}</div>
                <div><div class="name">${GPS.esc(a.name)}</div><div class="port">:${port}</div></div>
            </div>
            <span class="agent-badge ${up ? 'up' : 'down'}"><span class="agent-badge-dot"></span>${up ? 'ACTIVE' : 'DOWN'}</span>
        </div>
        <div class="agent-card-body">
            <div class="agent-metric"><div class="k">Status</div><div class="v ${up ? 'healthy' : 'down'}">${up ? 'Healthy' : 'Offline'}</div></div>
            <div class="agent-metric"><div class="k">Latency</div><div class="v mono">${up ? latency + 'ms' : '—'}</div></div>
            <div class="agent-metric"><div class="k">Port</div><div class="v mono">${port}</div></div>
            <div class="agent-metric"><div class="k">Endpoint</div><div class="v mono">/health</div></div>
            <div class="agent-health-bar-wrap">
                <div class="k"><span>Health</span><span>${up ? '100%' : '0%'}</span></div>
                <div class="agent-health-bar ${up ? '' : 'down'}"><span style="width:${up ? 100 : 0}%"></span></div>
            </div>
        </div>
    </div>`;
}

function renderInvestigationFlow() {
    const flow = document.getElementById('agent-pipeline-flow');
    if (!flow) return;
    const chain = [
        { name: 'Root Orchestrator', color: '#0a1f7a' },
        { name: 'ServiceNow Mock', color: '#f97316' },
        { name: 'Knowledge Ingestion', color: '#16a34a' },
        { name: 'Postgres Agent', color: '#7c3aed' },
        { name: 'Critic Agent', color: '#0ea5e9' },
        { name: 'Notification Agent', color: '#dc2626' },
    ];
    const byName = {};
    GPS.state.agents.forEach(a => { byName[a.name] = a.status; });
    flow.innerHTML = chain.map((n, i) => {
        const tag = GPS.AGENT_TAGS[n.name] || n.name.slice(0, 2).toUpperCase();
        const port = GPS.AGENT_PORTS[n.name] || '';
        const node = `<div class="flow-node" style="background:${n.color}">
            <div class="fn-port">:${port}</div>
            <div class="fn-tag">${tag}</div>
            <div class="fn-name">${GPS.esc(n.name)}</div>
        </div>`;
        return i < chain.length - 1 ? node + `<span class="flow-arrow">→</span>` : node;
    }).join('');
}
