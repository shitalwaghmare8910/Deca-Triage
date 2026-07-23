/* ═══════════════════════════════════════════════════════════════════════════
   Mock ServiceNow — Incident Management Portal JavaScript
   Handles list/form views, CRUD operations, routing, and UI interactions
   ═══════════════════════════════════════════════════════════════════════════ */

const API_BASE = window.location.origin + window.location.pathname.replace(/\/$/, '');

// ─── State ────────────────────────────────────────────────────────────────────

let currentView = 'list'; // 'list' or 'form'
let currentIncident = null; // sys_id of incident being edited
let incidents = [];

// ─── Priority helpers ─────────────────────────────────────────────────────────

const PRIORITY_MAP = {
    '1-1': 1, '1-2': 2, '1-3': 3,
    '2-1': 2, '2-2': 3, '2-3': 4,
    '3-1': 3, '3-2': 4, '3-3': 5,
};

const PRIORITY_LABELS = {
    1: '1 - Critical', 2: '2 - High', 3: '3 - Medium', 4: '4 - Low', 5: '5 - Planning'
};

const STATE_LABELS = {
    1: 'New', 2: 'In Progress', 3: 'On Hold', 6: 'Resolved', 7: 'Closed'
};

// ─── DOM Ready ────────────────────────────────────────────────────────────────

document.addEventListener('DOMContentLoaded', () => {
    initNavigation();
    initFormLogic();
    initTabs();
    showListView();
    loadIncidents();
});

// ─── Navigation ───────────────────────────────────────────────────────────────

function initNavigation() {
    // Sidebar toggle
    document.getElementById('sn-nav-toggle').addEventListener('click', () => {
        document.getElementById('sn-sidebar').classList.toggle('collapsed');
    });

    // Expandable nav sections
    document.querySelectorAll('.sn-nav-expandable').forEach(el => {
        el.addEventListener('click', () => {
            const targetId = el.getAttribute('data-target');
            const target = document.getElementById(targetId);
            if (target) {
                target.classList.toggle('collapsed');
                const arrow = el.querySelector('.sn-nav-arrow');
                if (arrow) {
                    arrow.style.transform = target.classList.contains('collapsed')
                        ? 'rotate(-90deg)' : '';
                }
            }
        });
    });

    // Nav items
    document.getElementById('nav-create-new').addEventListener('click', (e) => {
        e.preventDefault();
        setActiveNav(e.currentTarget);
        showFormView(null);
    });

    document.getElementById('nav-all-incidents').addEventListener('click', (e) => {
        e.preventDefault();
        setActiveNav(e.currentTarget);
        document.getElementById('filter-state').value = '';
        document.getElementById('filter-priority').value = '';
        showListView();
        loadIncidents();
    });

    document.getElementById('nav-my-incidents').addEventListener('click', (e) => {
        e.preventDefault();
        setActiveNav(e.currentTarget);
        showListView();
        loadIncidents();
    });

    document.getElementById('nav-open-incidents').addEventListener('click', (e) => {
        e.preventDefault();
        setActiveNav(e.currentTarget);
        document.getElementById('filter-state').value = '1';
        showListView();
        loadIncidents();
    });

    document.getElementById('nav-resolved-incidents').addEventListener('click', (e) => {
        e.preventDefault();
        setActiveNav(e.currentTarget);
        document.getElementById('filter-state').value = '6';
        showListView();
        loadIncidents();
    });

    // List toolbar buttons
    document.getElementById('btn-new-incident').addEventListener('click', () => {
        showFormView(null);
    });

    document.getElementById('btn-refresh-list').addEventListener('click', () => {
        loadIncidents();
    });

    // Filter change handlers
    document.getElementById('filter-state').addEventListener('change', loadIncidents);
    document.getElementById('filter-priority').addEventListener('change', loadIncidents);

    // Form buttons
    document.getElementById('btn-back-to-list').addEventListener('click', () => {
        showListView();
        loadIncidents();
    });

    document.getElementById('form-breadcrumb-back').addEventListener('click', () => {
        showListView();
        loadIncidents();
    });

    document.getElementById('btn-submit-incident').addEventListener('click', () => {
        submitIncident();
    });

    document.getElementById('btn-update-incident').addEventListener('click', () => {
        updateIncident();
    });
}

function setActiveNav(el) {
    document.querySelectorAll('.sn-nav-item').forEach(n => n.classList.remove('active'));
    el.classList.add('active');
}

// ─── View Switching ───────────────────────────────────────────────────────────

function showListView() {
    currentView = 'list';
    document.getElementById('view-list').style.display = 'block';
    document.getElementById('view-form').style.display = 'none';
}

function showFormView(sysId) {
    currentView = 'form';
    document.getElementById('view-list').style.display = 'none';
    document.getElementById('view-form').style.display = 'block';
    currentIncident = sysId;

    if (sysId) {
        loadIncidentForm(sysId);
    } else {
        clearForm();
    }
}

// ─── API Calls ────────────────────────────────────────────────────────────────

async function loadIncidents() {
    const stateFilter = document.getElementById('filter-state').value;
    const priorityFilter = document.getElementById('filter-priority').value;

    let queryParts = [];
    if (stateFilter) queryParts.push(`state=${stateFilter}`);
    if (priorityFilter) queryParts.push(`priority=${priorityFilter}`);
    const query = queryParts.join('^');

    try {
        const url = `${API_BASE}/api/now/table/incident${query ? `?sysparm_query=${query}` : ''}`;
        const resp = await fetch(url);
        const data = await resp.json();
        incidents = data.result || [];
        renderIncidentList();
    } catch (err) {
        console.error('Failed to load incidents:', err);
        showToast('Failed to load incidents', 'error');
    }
}

async function loadIncidentForm(sysId) {
    try {
        const resp = await fetch(`${API_BASE}/api/now/table/incident/${sysId}`);
        const data = await resp.json();
        const inc = data.result;
        populateForm(inc);
    } catch (err) {
        console.error('Failed to load incident:', err);
        showToast('Failed to load incident', 'error');
    }
}

async function submitIncident() {
    const shortDesc = document.getElementById('field-short-description').value.trim();
    if (!shortDesc) {
        showToast('Short description is required', 'error');
        document.getElementById('field-short-description').focus();
        return;
    }

    const payload = gatherFormData();

    try {
        const resp = await fetch(`${API_BASE}/api/now/table/incident`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
        });
        const data = await resp.json();
        const inc = data.result;

        showToast(`Incident ${inc.number} created successfully`, 'success');

        // Show the created incident in the form
        currentIncident = inc.sys_id;
        populateForm(inc);
    } catch (err) {
        console.error('Failed to create incident:', err);
        showToast('Failed to create incident', 'error');
    }
}

async function updateIncident() {
    if (!currentIncident) return;

    const payload = gatherFormData();

    try {
        const resp = await fetch(`${API_BASE}/api/now/table/incident/${currentIncident}`, {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
        });
        const data = await resp.json();
        const inc = data.result;

        showToast(`Incident ${inc.number} updated`, 'success');
        populateForm(inc);
    } catch (err) {
        console.error('Failed to update incident:', err);
        showToast('Failed to update incident', 'error');
    }
}

// ─── Form Logic ───────────────────────────────────────────────────────────────

function initFormLogic() {
    const impactEl = document.getElementById('field-impact');
    const urgencyEl = document.getElementById('field-urgency');

    function recalcPriority() {
        const key = `${impactEl.value}-${urgencyEl.value}`;
        const p = PRIORITY_MAP[key] || 4;
        document.getElementById('field-priority').value = PRIORITY_LABELS[p] || '4 - Low';
    }

    impactEl.addEventListener('change', recalcPriority);
    urgencyEl.addEventListener('change', recalcPriority);
}

function initTabs() {
    document.querySelectorAll('.sn-tab').forEach(tab => {
        tab.addEventListener('click', (e) => {
            e.preventDefault();
            const tabId = tab.getAttribute('data-tab');
            document.querySelectorAll('.sn-tab').forEach(t => t.classList.remove('active'));
            document.querySelectorAll('.sn-tab-content').forEach(c => c.classList.remove('active'));
            tab.classList.add('active');
            document.getElementById(`tab-${tabId}`).classList.add('active');
        });
    });
}

function gatherFormData() {
    return {
        caller_id: document.getElementById('field-caller').value,
        category: document.getElementById('field-category').value,
        subcategory: document.getElementById('field-subcategory').value,
        short_description: document.getElementById('field-short-description').value.trim(),
        description: document.getElementById('field-description').value,
        state: parseInt(document.getElementById('field-state').value),
        impact: parseInt(document.getElementById('field-impact').value),
        urgency: parseInt(document.getElementById('field-urgency').value),
        assignment_group: document.getElementById('field-assignment-group').value,
        assigned_to: document.getElementById('field-assigned-to').value,
        work_notes: document.getElementById('field-work-notes').value,
        additional_comments: document.getElementById('field-additional-comments').value,
        close_notes: document.getElementById('field-close-notes').value,
        contact_type: 'Self-service',
    };
}

function populateForm(inc) {
    document.getElementById('form-sys-id').value = inc.sys_id;
    document.getElementById('field-number').value = inc.number;
    document.getElementById('field-caller').value = inc.caller_id || '';
    document.getElementById('field-category').value = inc.category || '';
    document.getElementById('field-subcategory').value = inc.subcategory || '';
    document.getElementById('field-short-description').value = inc.short_description || '';
    document.getElementById('field-description').value = inc.description || '';
    document.getElementById('field-state').value = inc.state;
    document.getElementById('field-impact').value = inc.impact;
    document.getElementById('field-urgency').value = inc.urgency;
    document.getElementById('field-priority').value = PRIORITY_LABELS[inc.priority] || '3 - Medium';
    document.getElementById('field-assignment-group').value = inc.assignment_group || '';
    document.getElementById('field-assigned-to').value = inc.assigned_to || '';
    document.getElementById('field-work-notes').value = inc.work_notes || '';
    document.getElementById('field-additional-comments').value = inc.additional_comments || '';
    document.getElementById('field-close-notes').value = inc.close_notes || '';

    // Update header
    document.getElementById('form-title').textContent = inc.number;
    document.getElementById('form-breadcrumb-number').textContent = inc.number;

    // Show Update button, hide Submit
    document.getElementById('btn-submit-incident').style.display = 'none';
    document.getElementById('btn-update-incident').style.display = '';
}

function clearForm() {
    document.getElementById('form-sys-id').value = '';
    document.getElementById('field-number').value = '';
    document.getElementById('field-number').placeholder = 'Auto-generated';
    document.getElementById('field-caller').value = 'System';
    document.getElementById('field-category').value = '';
    document.getElementById('field-subcategory').value = '';
    document.getElementById('field-short-description').value = '';
    document.getElementById('field-description').value = '';
    document.getElementById('field-state').value = '1';
    document.getElementById('field-impact').value = '2';
    document.getElementById('field-urgency').value = '2';
    document.getElementById('field-priority').value = '3 - Medium';
    document.getElementById('field-assignment-group').value = '';
    document.getElementById('field-assigned-to').value = '';
    document.getElementById('field-work-notes').value = '';
    document.getElementById('field-additional-comments').value = '';
    document.getElementById('field-close-notes').value = '';
    document.getElementById('field-service').value = '';

    // Update header
    document.getElementById('form-title').textContent = 'New Incident';
    document.getElementById('form-breadcrumb-number').textContent = 'New record';

    // Show Submit button, hide Update
    document.getElementById('btn-submit-incident').style.display = '';
    document.getElementById('btn-update-incident').style.display = 'none';
}

// ─── List Rendering ───────────────────────────────────────────────────────────

function renderIncidentList() {
    const tbody = document.getElementById('incident-tbody');
    tbody.innerHTML = '';

    if (incidents.length === 0) {
        tbody.innerHTML = `
            <tr>
                <td colspan="8" style="text-align:center; padding:40px; color:#999;">
                    No incidents found
                </td>
            </tr>`;
    } else {
        incidents.forEach(inc => {
            const tr = document.createElement('tr');
            tr.innerHTML = `
                <td><input type="checkbox" class="sn-row-check"></td>
                <td><span class="sn-table-link" data-sysid="${inc.sys_id}">${inc.number}</span></td>
                <td><span class="sn-priority-badge sn-priority-${inc.priority}">${inc.priority_label}</span></td>
                <td>${escapeHtml(inc.short_description)}</td>
                <td><span class="sn-state-badge sn-state-${inc.state}">${inc.state_label}</span></td>
                <td>${escapeHtml(inc.category)}</td>
                <td>${escapeHtml(inc.assignment_group)}</td>
                <td>${formatTimestamp(inc.sys_updated_on)}</td>
            `;
            tr.addEventListener('click', (e) => {
                if (e.target.type === 'checkbox') return;
                showFormView(inc.sys_id);
            });
            tbody.appendChild(tr);
        });
    }

    document.getElementById('list-count').textContent = `${incidents.length} record${incidents.length !== 1 ? 's' : ''}`;
    document.getElementById('list-footer-count').textContent = `Showing ${incidents.length} of ${incidents.length}`;
}

// ─── Utility ──────────────────────────────────────────────────────────────────

function escapeHtml(str) {
    if (!str) return '';
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
}

function formatTimestamp(ts) {
    if (!ts) return '';
    const d = new Date(ts);
    const now = new Date();
    const diffMs = now - d;
    const diffMins = Math.floor(diffMs / 60000);
    const diffHours = Math.floor(diffMs / 3600000);

    if (diffMins < 1) return 'Just now';
    if (diffMins < 60) return `${diffMins}m ago`;
    if (diffHours < 24) return `${diffHours}h ago`;
    return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
}

function showToast(message, type = 'success') {
    const container = document.getElementById('toast-container');
    const toast = document.createElement('div');
    toast.className = `sn-toast sn-toast-${type}`;
    toast.innerHTML = `
        <span class="material-icons-outlined">${type === 'success' ? 'check_circle' : 'error'}</span>
        ${escapeHtml(message)}
    `;
    container.appendChild(toast);
    setTimeout(() => {
        if (toast.parentNode) toast.parentNode.removeChild(toast);
    }, 4000);
}
