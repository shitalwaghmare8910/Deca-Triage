/* ═══════════════════════════════════════════════════════════════════════════
   DECA — Decade of Autonomous Triage — Incident Feed view
   ═══════════════════════════════════════════════════════════════════════════ */

const IncidentFilters = { severity: 'all', status: 'all', search: '' };

GPS.register('incidents', {
    refresh() {
        const inc = GPS.state.incidents;
        const critical = inc.filter(i => (i.priority || 3) === 1).length;
        setText('inc-total', inc.length);
        setText('inc-critical', critical);
        setText('inc-investigating', inc.filter(i => i.state === 'in_progress').length);
        setText('inc-escalated', inc.filter(i => i.state === 'failed').length);
        setText('inc-resolved', inc.filter(i => i.state === 'completed').length);
        renderIncidentTable();
    },
});

function initIncidentFilters() {
    document.querySelectorAll('#inc-sev-filters .filter-btn').forEach(b =>
        b.addEventListener('click', () => {
            IncidentFilters.severity = b.dataset.sev;
            setActive('#inc-sev-filters', b);
            renderIncidentTable();
        }));
    document.querySelectorAll('#inc-status-filters .filter-btn').forEach(b =>
        b.addEventListener('click', () => {
            IncidentFilters.status = b.dataset.status;
            setActive('#inc-status-filters', b);
            renderIncidentTable();
        }));
    const search = document.getElementById('inc-search');
    if (search) search.addEventListener('input', () => {
        IncidentFilters.search = search.value.toLowerCase().trim();
        renderIncidentTable();
    });
}

function setActive(scope, btn) {
    document.querySelectorAll(`${scope} .filter-btn`).forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
}

function renderIncidentTable() {
    const tbody = document.getElementById('inc-tbody');
    if (!tbody) return;
    let rows = GPS.state.incidents.slice();

    if (IncidentFilters.severity !== 'all')
        rows = rows.filter(i => String(i.priority || 3) === IncidentFilters.severity);
    if (IncidentFilters.status === 'active')
        rows = rows.filter(i => i.state === 'in_progress');
    else if (IncidentFilters.status === 'escalated')
        rows = rows.filter(i => i.state === 'failed');
    if (IncidentFilters.search) {
        const q = IncidentFilters.search;
        rows = rows.filter(i =>
            (i.number || '').toLowerCase().includes(q) ||
            (i.short_description || '').toLowerCase().includes(q) ||
            (GPS.serviceOf(i) || '').toLowerCase().includes(q));
    }

    if (!rows.length) {
        tbody.innerHTML = `<tr><td colspan="7" style="text-align:center;padding:28px;color:#9aa3b5">No matching incidents.</td></tr>`;
        return;
    }
    tbody.innerHTML = rows.map(rowHtml).join('');
}
