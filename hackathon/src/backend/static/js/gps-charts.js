/* ═══════════════════════════════════════════════════════════════════════════
   DECA — Decade of Autonomous Triage — Chart helpers (Chart.js). Derived from existing data only.
   ═══════════════════════════════════════════════════════════════════════════ */

const GPSCharts = (function () {
    const store = {};
    function destroy(id) { if (store[id]) { store[id].destroy(); delete store[id]; } }
    const ready = () => typeof window.Chart !== 'undefined';

    function alertVolumeLine(canvasId) {
        if (!ready()) return;
        const ctx = document.getElementById(canvasId); if (!ctx) return;
        const buckets = GPS.hourlyVolume();
        destroy(canvasId);
        store[canvasId] = new Chart(ctx, {
            type: 'line',
            data: {
                labels: buckets.map(b => b.label + ':00'),
                datasets: [
                    { label: 'Critical', data: buckets.map(b => b.c), borderColor: '#dc2626', backgroundColor: 'transparent', tension: 0.4, pointRadius: 0, borderWidth: 2 },
                    { label: 'High',     data: buckets.map(b => b.h), borderColor: '#f97316', backgroundColor: 'transparent', tension: 0.4, pointRadius: 0, borderWidth: 2 },
                    { label: 'Medium',   data: buckets.map(b => b.m), borderColor: '#eab308', backgroundColor: 'transparent', tension: 0.4, pointRadius: 0, borderWidth: 2 },
                    { label: 'Low',      data: buckets.map(b => b.l), borderColor: '#3b82f6', backgroundColor: 'transparent', tension: 0.4, pointRadius: 0, borderWidth: 2 },
                ],
            },
            options: {
                responsive: true, maintainAspectRatio: false,
                plugins: { legend: { position: 'bottom', labels: { boxWidth: 10, padding: 14, font: { size: 10, family: 'Inter' } } } },
                scales: {
                    x: { grid: { display: false }, ticks: { font: { size: 9 }, maxRotation: 0, autoSkip: true, maxTicksLimit: 12 } },
                    y: { beginAtZero: true, grid: { color: '#f0f2f7' }, ticks: { font: { size: 9 }, precision: 0 } },
                },
            },
        });
    }

    function severityDonut(canvasId, legendId) {
        if (!ready()) return;
        const ctx = document.getElementById(canvasId); if (!ctx) return;
        const split = GPS.severitySplit();
        const labels = split.map(s => GPS.sev(s.priority).label);
        const data = split.map(s => s.count);
        const colors = split.map(s => GPS.sev(s.priority).color);
        destroy(canvasId);
        store[canvasId] = new Chart(ctx, {
            type: 'doughnut',
            data: { labels, datasets: [{ data, backgroundColor: colors, borderWidth: 2, borderColor: '#fff' }] },
            options: { responsive: true, maintainAspectRatio: false, cutout: '64%', plugins: { legend: { display: false } } },
        });
        const legend = document.getElementById(legendId);
        if (legend) legend.innerHTML = split.map(s =>
            `<span class="legend-item"><span class="legend-dot" style="background:${GPS.sev(s.priority).color}"></span>${GPS.sev(s.priority).label} ${s.count}</span>`).join('');
    }

    function hourlyStacked(canvasId) {
        if (!ready()) return;
        const ctx = document.getElementById(canvasId); if (!ctx) return;
        const buckets = GPS.hourlyVolume();
        destroy(canvasId);
        store[canvasId] = new Chart(ctx, {
            type: 'bar',
            data: {
                labels: buckets.map(b => b.label),
                datasets: [
                    { label: 'Critical', data: buckets.map(b => b.c), backgroundColor: '#dc2626' },
                    { label: 'High',     data: buckets.map(b => b.h), backgroundColor: '#f97316' },
                    { label: 'Medium',   data: buckets.map(b => b.m), backgroundColor: '#22c55e' },
                    { label: 'Low',      data: buckets.map(b => b.l), backgroundColor: '#3b82f6' },
                ],
            },
            options: {
                responsive: true, maintainAspectRatio: false,
                plugins: { legend: { position: 'bottom', labels: { boxWidth: 10, padding: 14, font: { size: 10 } } } },
                scales: {
                    x: { stacked: true, grid: { display: false }, ticks: { font: { size: 9 }, maxRotation: 0, autoSkip: true, maxTicksLimit: 14 } },
                    y: { stacked: true, beginAtZero: true, grid: { color: '#f0f2f7' }, ticks: { font: { size: 9 }, precision: 0 } },
                },
            },
        });
    }

    function byServiceBar(canvasId) {
        if (!ready()) return;
        const ctx = document.getElementById(canvasId); if (!ctx) return;
        const rows = GPS.byService();
        destroy(canvasId);
        store[canvasId] = new Chart(ctx, {
            type: 'bar',
            data: {
                labels: rows.map(r => r[0]),
                datasets: [{ data: rows.map(r => r[1]), backgroundColor: '#0a1f7a', borderRadius: 3, barThickness: 14 }],
            },
            options: {
                indexAxis: 'y', responsive: true, maintainAspectRatio: false,
                plugins: { legend: { display: false } },
                scales: {
                    x: { beginAtZero: true, grid: { color: '#f0f2f7' }, ticks: { font: { size: 9 }, precision: 0 } },
                    y: { grid: { display: false }, ticks: { font: { size: 10 } } },
                },
            },
        });
    }

    return { alertVolumeLine, severityDonut, hourlyStacked, byServiceBar };
})();
