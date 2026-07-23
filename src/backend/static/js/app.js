/* App core: tab routing, clock, polling, SSE */
const API = window.location.origin + window.location.pathname.replace(/\/$/, '');
let currentTab = 'dashboard';
let pollTimer = null;
let evtSource = null;

document.addEventListener('DOMContentLoaded', () => {
    initTabs();
    startClock();
    startPolling();
    connectSSE();
});

function initTabs() {
    document.querySelectorAll('.nav-tab').forEach(tab => {
        tab.addEventListener('click', () => {
            const view = tab.dataset.view;
            switchView(view);
        });
    });

    // Initialize the health tab logic.
    // This calls the initHealthTab() function, which should be defined in health.js.
    // We check if the function exists to prevent errors if health.js hasn't loaded.
    if (typeof initHealthTab === 'function') {
        initHealthTab();
    }
}

function switchView(view) {
    currentTab = view;

    // Toggle the 'active' class on all nav tabs based on the selected view.
    document.querySelectorAll('.nav-tab').forEach(t => t.classList.toggle('active', t.dataset.view === view));

    // Show or hide the main view sections based on the selected view.
    // This is updated to be generic and include the new 'agent-health' view.
    document.getElementById('view-dashboard').style.display = view === 'dashboard' ? '' : 'none';
    document.getElementById('view-pipeline').style.display = view === 'pipeline' ? '' : 'none';
    document.getElementById('view-agent-health').style.display = view === 'agent-health' ? '' : 'none';

    // Trigger data refresh for the newly activated view.
    if (view === 'dashboard') {
        refreshDashboard();
    } else if (view === 'pipeline') {
        refreshPipeline();
    }
    // The health tab has its own refresh logic inside health.js, triggered
    // by its refresh button or when it first becomes visible.
}

function startClock() {
    function tick() {
        const now = new Date();
        const t = now.toLocaleTimeString('en-GB');
        const el1 = document.getElementById('header-clock');
        const el2 = document.getElementById('pipeline-clock');
        if (el1) el1.textContent = t;
        if (el2) el2.textContent = t;
        const dateEl = document.getElementById('dashboard-date');
        if (dateEl) dateEl.textContent = now.toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' });
    }
    tick();
    setInterval(tick, 1000);
}

function startPolling() {
    async function poll() {
        // Only poll data for the currently active tab to save resources.
        if (currentTab === 'dashboard') await refreshDashboard();
        if (currentTab === 'pipeline') await refreshPipeline();
    }
    poll();
    pollTimer = setInterval(poll, 5000);
}

function connectSSE() {
    try {
        evtSource = new EventSource(`${API}/api/incidents/stream`);
        evtSource.addEventListener('new_incident', () => {
            if (currentTab === 'dashboard') refreshDashboard();
            if (currentTab === 'pipeline') refreshPipeline();
        });
        evtSource.addEventListener('step_update', (e) => {
            const data = JSON.parse(e.data);
            if (currentTab === 'pipeline') onStepUpdate(data);
        });
        evtSource.addEventListener('incident_completed', (e) => {
            const data = JSON.parse(e.data);
            if (currentTab === 'dashboard') refreshDashboard();
            if (currentTab === 'pipeline') onIncidentCompleted(data);
        });
        evtSource.onerror = () => { setTimeout(connectSSE, 5000); evtSource.close(); };
    } catch(e) {
        // If connection fails, retry after 5 seconds.
        setTimeout(connectSSE, 5000);
    }
}

async function fetchJSON(url) {
    const r = await fetch(url);
    if (!r.ok) {
        console.error(`Failed to fetch ${url}: ${r.statusText}`);
        return null;
    }
    return r.json();
}