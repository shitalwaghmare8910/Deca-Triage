/**
 * health.js
 * 
 * Handles all logic for the "Agent Health" tab.
 * - Defines the backend agents and their correct ports.
 * - Constructs correct proxy URLs for the JupyterHub environment.
 * - Fetches health status from each agent's /health endpoint.
 * - Renders and updates the health status cards in the UI.
 *
 * MODIFIED: June 29, 2026 - by dbLumina
 * REASON: Expanded the AGENTS constant to include all running agents (Critic,
 *         Concept, Jira, Incident Logger, Notification) to ensure they are
 *         monitored on the health dashboard.
 */

// This function will be called by app.js when the document is ready.
function initHealthTab() {
    
    // --- ACTION: Expanded the agent definitions list ---
    // *** MODIFICATION START ***
    const AGENTS = [
        { name: 'Orchestrator', port: 8080, purpose: 'Main entry point. Coordinates other agents.' },
        { name: 'Knowledge Agent', port: 8001, purpose: 'Handles knowledge ingestion and semantic search.' },
        { name: 'Postgres Agent', port: 8003, purpose: 'Executes SQL queries against the live database.' },
        { name: 'Critic Agent', port: 8004, purpose: 'Evaluates the AI-generated analysis for validity.' },
        { name: 'Concept Agent', port: 8005, purpose: 'Extracts key technical concepts from the incident.' },
        { name: 'Jira Agent', port: 8006, purpose: 'Simulates creating tickets in Jira.' },
        { name: 'Incident Logger Agent', port: 8007, purpose: 'Responsible for logging incident details.' },
        { name: 'Notification Agent', port: 8008, purpose: 'Sends notifications and recommended actions to SREs.' },
        { name: 'ServiceNow', port: 5001, purpose: 'Simulates the ServiceNow incident management UI and API.' }
    ];
    // *** MODIFICATION END ***


    // 2. DOM element references
    const healthGrid = document.getElementById('health-grid');
    const refreshButton = document.getElementById('btn-refresh-health');
    const healthView = document.getElementById('view-agent-health');

    /**
     * Constructs the correct base URL for an agent running on a specific port
     * within the JupyterHub proxy environment.
     * @param {number} port The agent's port number.
     * @returns {string} The full, proxied base URL for the agent.
     */
    function getAgentBaseUrl(port) {
        const pathParts = window.location.pathname.split('/');
        const proxyIndex = pathParts.indexOf('proxy');

        if (proxyIndex === -1) {
            console.warn('Proxy path not found, falling back to localhost.');
            return `${window.location.protocol}//${window.location.hostname}:${port}`;
        }

        // Reconstruct the path to point to the correct agent's proxy port
        const basePath = pathParts.slice(0, proxyIndex + 1).join('/');
        return `${window.location.origin}${basePath}/${port}`;
    }

    /**
     * Renders placeholder cards for each agent with a "Checking..." status.
     */
    function renderInitialAgentCards() {
        healthGrid.innerHTML = ''; // Clear any previous cards
        AGENTS.forEach(agent => {
            const card = document.createElement('div');
            card.className = 'health-card';
            card.id = `health-card-${agent.port}`;
            card.innerHTML = `
                <div class="health-card-header">
                    <h3 class="health-card-title">${agent.name}</h3>
                    <div class="health-status-badge status-checking" id="badge-${agent.port}">
                        <span class="material-icons-outlined">sync</span>
                        Checking...
                    </div>
                </div>
                <div class="health-card-body">
                    <p>Endpoint: <span class="endpoint">${getAgentBaseUrl(agent.port)}/health</span></p>
                </div>
                <div class="health-card-details" id="details-${agent.port}">
                    <p>${agent.purpose}</p>
                </div>
            `;
            healthGrid.appendChild(card);
        });
    }

    /**
     * Asynchronously fetches the health status of a single agent and updates its card.
     * @param {object} agent The agent object { name, port, purpose }.
     */
    async function checkAgentHealth(agent) {
        const card = document.getElementById(`health-card-${agent.port}`);
        const badge = document.getElementById(`badge-${agent.port}`);
        const details = document.getElementById(`details-${agent.port}`);
        const url = `${getAgentBaseUrl(agent.port)}/health`;

        try {
            const response = await fetch(url, { signal: AbortSignal.timeout(5000) });
            
            // Assume non-JSON response is also OK for simple health checks
            let data = {};
            if (response.headers.get("content-type")?.includes("application/json")) {
                data = await response.json();
            }

            if (!response.ok) throw new Error(data.detail || `HTTP error! Status: ${response.status}`);

            // SUCCESS CASE
            card.classList.remove('status-error');
            card.classList.add('status-ok');
            badge.className = 'health-status-badge status-ok';
            badge.innerHTML = `<span class="material-icons-outlined">check_circle</span> Online`;
            
            let detailsHtml = `<p>${agent.purpose}</p>`;
            if (data.status) detailsHtml += `<p><strong>Status:</strong> ${data.status}</p>`;
            details.innerHTML = detailsHtml;

        } catch (error) {
            // ERROR CASE
            card.classList.remove('status-ok');
            card.classList.add('status-error');
            badge.className = 'health-status-badge status-error';
            badge.innerHTML = `<span class="material-icons-outlined">error</span> Offline`;
            details.innerHTML = `<p class="error-msg">Failed to connect: ${error.message}</p>`;
        }
    }

    /**
     * Renders the initial cards and then triggers health checks for all agents.
     */
    function checkAllAgents() {
        renderInitialAgentCards();
        AGENTS.forEach(agent => checkAgentHealth(agent));
    }

    function checkOnFirstView() {
        if (!healthGrid.hasChildNodes()) {
            checkAllAgents();
        }
    }

    // 3. Event Listeners
    refreshButton.addEventListener('click', checkAllAgents);

    // This observer triggers the health check only when the tab becomes visible.
    const observer = new MutationObserver((mutations) => {
        mutations.forEach((mutation) => {
            if (mutation.attributeName === 'style' && healthView.style.display !== 'none') {
                checkOnFirstView();
            }
        });
    });
    observer.observe(healthView, { attributes: true });
}