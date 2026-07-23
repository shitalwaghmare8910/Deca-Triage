/* Chart.js integration for dashboard */
let alertVolumeChart = null;
let severityChart = null;

function renderCharts(stats, incidents) {
    renderAlertVolumeChart(incidents);
    renderSeverityChart(stats.severity_split || []);
}

function renderAlertVolumeChart(incidents) {
    const ctx = document.getElementById('chart-alert-volume');
    if (!ctx) return;

    // Group by hour buckets for last 24 hours
    const now = new Date();
    const hours = [];
    const critData = [], highData = [], medData = [], lowData = [];

    for (let i = 23; i >= 0; i--) {
        const h = new Date(now - i * 3600000);
        hours.push(h.getHours() + ':00');
        const hourStart = new Date(h); hourStart.setMinutes(0, 0, 0);
        const hourEnd = new Date(hourStart.getTime() + 3600000);
        const bucket = incidents.filter(inc => {
            const t = new Date(inc.created_at || inc.opened_at);
            return t >= hourStart && t < hourEnd;
        });
        critData.push(bucket.filter(i => i.priority === 1).length);
        highData.push(bucket.filter(i => i.priority === 2).length);
        medData.push(bucket.filter(i => i.priority === 3).length);
        lowData.push(bucket.filter(i => i.priority >= 4).length);
    }

    if (alertVolumeChart) alertVolumeChart.destroy();
    alertVolumeChart = new Chart(ctx, {
        type: 'bar',
        data: {
            labels: hours,
            datasets: [
                { label: 'Critical', data: critData, backgroundColor: '#ef4444', borderRadius: 2 },
                { label: 'High', data: highData, backgroundColor: '#f97316', borderRadius: 2 },
                { label: 'Medium', data: medData, backgroundColor: '#eab308', borderRadius: 2 },
                { label: 'Low', data: lowData, backgroundColor: '#10b981', borderRadius: 2 },
            ]
        },
        options: {
            responsive: true, maintainAspectRatio: false,
            plugins: { legend: { position: 'bottom', labels: { boxWidth: 12, padding: 16, font: { size: 11, family: 'Inter' } } } },
            scales: {
                x: { stacked: true, grid: { display: false }, ticks: { font: { size: 10 }, maxRotation: 0, autoSkip: true, maxTicksLimit: 12 } },
                y: { stacked: true, beginAtZero: true, grid: { color: '#f0f0f0' }, ticks: { font: { size: 10 }, stepSize: 1 } }
            }
        }
    });
}

function renderSeverityChart(split) {
    const ctx = document.getElementById('chart-severity');
    if (!ctx) return;

    const colorMap = { 1: '#ef4444', 2: '#f97316', 3: '#eab308', 4: '#10b981', 5: '#3b82f6' };
    const labelMap = { 1: 'CRITICAL', 2: 'HIGH', 3: 'MEDIUM', 4: 'LOW', 5: 'INFO' };

    const labels = split.map(s => labelMap[s.priority] || `P${s.priority}`);
    const data = split.map(s => s.count);
    const colors = split.map(s => colorMap[s.priority] || '#999');

    if (severityChart) severityChart.destroy();
    severityChart = new Chart(ctx, {
        type: 'doughnut',
        data: {
            labels: labels,
            datasets: [{ data: data, backgroundColor: colors, borderWidth: 2, borderColor: '#fff' }]
        },
        options: {
            responsive: true, maintainAspectRatio: false,
            cutout: '65%',
            plugins: { legend: { display: false } }
        }
    });

    // Custom legend
    const legend = document.getElementById('severity-legend');
    legend.innerHTML = split.map(s => `
        <span class="legend-item">
            <span class="legend-dot" style="background:${colorMap[s.priority]||'#999'}"></span>
            ${labelMap[s.priority]||'P'+s.priority} ${s.count}
        </span>
    `).join('');
}
