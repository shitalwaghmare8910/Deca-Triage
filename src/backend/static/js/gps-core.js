/* ═══════════════════════════════════════════════════════════════════════════
   DECA — Decade of Autonomous Triage — Core module
   Shared state, API access, routing, SSE, polling, helpers.
   Binds ONLY to existing backend endpoints (no contract changes):
     GET /api/dashboard/stats, /api/incidents, /api/incidents/:id,
         /api/agent-health   |  SSE /api/incidents/stream
   ═══════════════════════════════════════════════════════════════════════════ */

const GPS = (function () {
    const API = window.location.origin + window.location.pathname.replace(/\/$/, '');

    // Display-only mapping of agent name -> port/endpoint (matches backend AGENT_ENDPOINTS)
    const AGENT_PORTS = {
        'Root Orchestrator': 8080,
        'Knowledge Ingestion': 8001,
        'Postgres Agent': 8003,
        'Critic Agent': 8004,
        'Concept Agent': 8005,
        'Jira Agent': 8006,
        'Incident Logger Agent': 8007,
        'Notification Agent': 8008,
        'Anomaly Detection Agent': 8009,
        'SRE Copilot Agent': 8010,
        'ServiceNow Mock': 5001,
    };
    const AGENT_TAGS = {
        'Root Orchestrator': 'RO', 'Knowledge Ingestion': 'KI', 'Postgres Agent': 'PG',
        'Critic Agent': 'CR', 'Concept Agent': 'CO', 'Jira Agent': 'JR',
        'Incident Logger Agent': 'IL', 'Notification Agent': 'NT',
        'Anomaly Detection Agent': 'AD', 'SRE Copilot Agent': 'CP', 'ServiceNow Mock': 'SN',
    };

    const SEV = {
        1: { label: 'CRITICAL', color: '#dc2626' },
        2: { label: 'HIGH',     color: '#f97316' },
        3: { label: 'MEDIUM',   color: '#eab308' },
        4: { label: 'LOW',      color: '#22c55e' },
        5: { label: 'INFO',     color: '#3b82f6' },
    };

    const state = {
        stats: { total: 0, investigating: 0, completed: 0, failed: 0, avg_time: 0 },
        incidents: [],
        agents: [],
        agentLatency: 0,
        activeView: 'dashboard',
        selectedIncidentId: null,
        loaded: false,
    };

    const views = {};
    function register(name, def) { views[name] = def; }

    /* ── helpers ─────────────────────────────────────────────────────────── */
    async function fetchJSON(url, opts) {
        try {
            const r = await fetch(url, opts);
            if (!r.ok) return null;
            return await r.json();
        } catch (e) { return null; }
    }
    function esc(s) {
        if (s === null || s === undefined) return '';
        const d = document.createElement('div'); d.textContent = String(s); return d.innerHTML;
    }
    function sev(priority) { return SEV[priority] || SEV[3]; }
    function statusOf(st) {
        if (st === 'completed') return { label: 'Resolved', cls: 'resolved' };
        if (st === 'failed')    return { label: 'Escalated', cls: 'escalated' };
        return { label: 'Investigating', cls: 'investigating' };
    }
    function timeAgo(ts) {
        if (!ts) return '';
        const d = new Date(ts); const diff = (Date.now() - d.getTime()) / 1000;
        if (isNaN(diff)) return '';
        if (diff < 60) return 'Just now';
        if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
        if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
        return d.toLocaleDateString('en-GB', { day: 'numeric', month: 'short' });
    }
    function fmtDur(sec) {
        if (sec === null || sec === undefined || isNaN(sec)) return '—';
        if (sec < 1) return `${Math.round(sec * 1000)}ms`;
        if (sec < 60) return `${sec.toFixed(1)}s`;
        if (sec < 3600) return `${Math.round(sec / 60)}m`;
        return `${(sec / 3600).toFixed(1)}h`;
    }
    function fmtSecValue(sec) {
        if (!sec || isNaN(sec)) return '0s';
        if (sec < 60) return `${Math.round(sec)}s`;
        if (sec < 3600) return `${Math.round(sec / 60)}m`;
        return `${(sec / 3600).toFixed(1)}h`;
    }
    function serviceOf(inc) {
        return inc.assignment_group || inc.category || 'service';
    }
    function toast(msg, type) {
        const wrap = document.getElementById('gps-toast');
        if (!wrap) return;
        const t = document.createElement('div');
        t.className = `toast ${type || ''}`; t.textContent = msg;
        wrap.appendChild(t);
        setTimeout(() => t.remove(), 3200);
    }

    /* ── derived analytics (client-side, from existing data only) ─────────── */
    function decisionCounts() {
        const inc = state.incidents;
        return {
            autoRemediated: inc.filter(i => i.state === 'completed').length,
            escalated:      inc.filter(i => i.state === 'failed').length,
            monitoring:     inc.filter(i => i.state === 'in_progress').length,
            noAction:       inc.filter(i => i.state === 'completed' && (i.ai_decision || '').toLowerCase().includes('no action')).length,
        };
    }
    function severitySplit() {
        const out = [];
        for (let p = 1; p <= 5; p++) {
            const count = state.incidents.filter(i => (i.priority || 3) === p).length;
            if (count > 0) out.push({ priority: p, count });
        }
        return out;
    }
    function byService() {
        const map = {};
        state.incidents.forEach(i => { const k = serviceOf(i); map[k] = (map[k] || 0) + 1; });
        return Object.entries(map).sort((a, b) => b[1] - a[1]);
    }
    function rootCauses() {
        const map = {};
        state.incidents.forEach(i => {
            const k = (i.short_description || 'Unknown').trim();
            map[k] = (map[k] || 0) + 1;
        });
        return Object.entries(map).sort((a, b) => b[1] - a[1]).slice(0, 6);
    }
    function hourlyVolume() {
        const now = new Date();
        const buckets = [];
        for (let h = 23; h >= 0; h--) {
            const ref = new Date(now - h * 3600000);
            const start = new Date(ref); start.setMinutes(0, 0, 0);
            const end = new Date(start.getTime() + 3600000);
            const inb = state.incidents.filter(i => {
                const t = new Date(i.created_at || i.opened_at); return t >= start && t < end;
            });
            buckets.push({
                label: String(start.getHours()).padStart(2, '0'),
                c: inb.filter(i => i.priority === 1).length,
                h: inb.filter(i => i.priority === 2).length,
                m: inb.filter(i => i.priority === 3).length,
                l: inb.filter(i => (i.priority || 3) >= 4).length,
            });
        }
        return buckets;
    }
    function avgResolutionSeconds() {
        if (state.stats && state.stats.avg_time) return state.stats.avg_time;
        const done = state.incidents.filter(i => i.state === 'completed' && i.completed_at && i.created_at);
        if (!done.length) return 0;
        const total = done.reduce((s, i) => s + Math.max(0, (new Date(i.completed_at) - new Date(i.created_at)) / 1000), 0);
        return total / done.length;
    }

    /* ── data loading ────────────────────────────────────────────────────── */
    async function loadAll() {
        const [s, inc] = await Promise.all([
            fetchJSON(`${API}/api/dashboard/stats`),
            fetchJSON(`${API}/api/incidents`),
        ]);
        if (s) state.stats = s;
        if (inc && inc.result) state.incidents = inc.result;
        state.loaded = true;
        updateNavBadge();
    }
    async function loadAgents() {
        const t0 = performance.now();
        const data = await fetchJSON(`${API}/api/agent-health`);
        state.agentLatency = Math.round(performance.now() - t0);
        if (Array.isArray(data)) state.agents = data;
        return state.agents;
    }
    async function loadIncidentDetail(id) {
        const data = await fetchJSON(`${API}/api/incidents/${id}`);
        return data && data.result ? data.result : null;
    }

    function updateNavBadge() {
        const b = document.getElementById('nav-inc-badge');
        if (b) b.textContent = state.incidents.length;
    }

    /* ── routing ─────────────────────────────────────────────────────────── */
    function switchView(name) {
        state.activeView = name;
        document.querySelectorAll('.gps-nav-tab').forEach(t =>
            t.classList.toggle('active', t.dataset.view === name));
        document.querySelectorAll('.gps-view').forEach(v =>
            v.classList.toggle('active', v.id === `view-${name}`));
        refreshActive(true);
    }
    function refreshActive(force) {
        const v = views[state.activeView];
        if (v && typeof v.refresh === 'function') v.refresh(force);
    }

    /* ── clock ───────────────────────────────────────────────────────────── */
    function startClock() {
        const tick = () => {
            const now = new Date();
            const c = document.getElementById('gps-clock');
            const d = document.getElementById('gps-date');
            if (c) c.textContent = now.toLocaleTimeString('en-GB');
            if (d) d.textContent = now.toLocaleDateString('en-GB', { day: '2-digit', month: 'short' }).toUpperCase();
        };
        tick(); setInterval(tick, 1000);
    }

    /* ── SSE ─────────────────────────────────────────────────────────────── */
    function connectSSE() {
        let evt;
        try { evt = new EventSource(`${API}/api/incidents/stream`); }
        catch (e) { setTimeout(connectSSE, 5000); return; }

        const onChange = async () => { await loadAll(); refreshActive(false); };
        evt.addEventListener('new_incident', onChange);
        evt.addEventListener('step_update', onChange);
        evt.addEventListener('incident_completed', onChange);
        evt.addEventListener('incident_failed', onChange);
        evt.onerror = () => { evt.close(); setTimeout(connectSSE, 5000); };
    }

    /* ── polling ─────────────────────────────────────────────────────────── */
    function startPolling() {
        const poll = async () => {
            await loadAll();
            if (state.activeView === 'agent-health') await loadAgents();
            refreshActive(false);
        };
        setInterval(poll, 6000);
    }

    /* ── init ────────────────────────────────────────────────────────────── */
    async function init() {
        document.querySelectorAll('.gps-nav-tab').forEach(tab =>
            tab.addEventListener('click', () => switchView(tab.dataset.view)));

        const rb = document.getElementById('gps-btn-refresh');
        if (rb) rb.addEventListener('click', async () => {
            await loadAll();
            if (state.activeView === 'agent-health') await loadAgents();
            refreshActive(true);
            toast('Refreshed', 'success');
        });
        const lo = document.getElementById('gps-btn-logout');
        if (lo) lo.addEventListener('click', () => toast('Demo session — logout disabled'));

        startClock();
        await loadAll();
        await loadAgents();
        switchView('dashboard');
        connectSSE();
        startPolling();
    }

    return {
        API, AGENT_PORTS, AGENT_TAGS, SEV, state, views, register,
        fetchJSON, esc, sev, statusOf, timeAgo, fmtDur, fmtSecValue, serviceOf, toast,
        decisionCounts, severitySplit, byService, rootCauses, hourlyVolume, avgResolutionSeconds,
        loadAll, loadAgents, loadIncidentDetail, switchView, refreshActive, init,
    };
})();

document.addEventListener('DOMContentLoaded', GPS.init);
