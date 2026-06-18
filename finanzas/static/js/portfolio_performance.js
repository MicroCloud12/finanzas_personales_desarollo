// Gráfica de rendimiento del portafolio (evolución diaria del valor + G/P)
document.addEventListener('DOMContentLoaded', function () {
    const canvas = document.getElementById('portfolioPerformanceChart');
    if (!canvas || typeof Chart === 'undefined') return;

    const parseJson = (id) => {
        const el = document.getElementById(id);
        if (!el) return [];
        try { return JSON.parse(el.textContent); } catch (e) { return []; }
    };

    const allLabels = parseJson('perf-labels-data');
    const allValues = parseJson('perf-valores-data');
    const allGains = parseJson('perf-ganancias-data');

    if (!allLabels.length) return; // El estado vacío se maneja en la plantilla

    const ctx = canvas.getContext('2d');

    // Helpers de formato
    const formatK = (v) => {
        const abs = Math.abs(v);
        if (abs >= 1000) return (v / 1000).toFixed(abs % 1000 === 0 ? 0 : 1) + 'k';
        return String(Math.round(v));
    };
    const money = (v) => '$' + Number(v).toLocaleString('en-US', { maximumFractionDigits: 0 });
    const formatDate = (iso) => {
        const d = new Date(iso + 'T00:00:00');
        if (isNaN(d)) return iso;
        return d.toLocaleDateString('es-MX', { day: 'numeric', month: 'short', year: 'numeric' });
    };

    // Degradado índigo → transparente (paleta del dashboard)
    const gradient = ctx.createLinearGradient(0, 0, 0, canvas.clientHeight || 320);
    gradient.addColorStop(0, 'rgba(79, 70, 229, 0.22)');
    gradient.addColorStop(1, 'rgba(79, 70, 229, 0)');

    // Las ganancias visibles según el rango activo (las usa el tooltip)
    let currentGains = allGains;

    // Plugin: línea vertical punteada en el punto bajo el cursor
    const hoverLine = {
        id: 'hoverLine',
        afterDatasetsDraw(chart) {
            const active = chart.tooltip && chart.tooltip.getActiveElements
                ? chart.tooltip.getActiveElements() : [];
            if (!active.length) return;
            const x = active[0].element.x;
            const { top, bottom } = chart.chartArea;
            const c = chart.ctx;
            c.save();
            c.beginPath();
            c.setLineDash([4, 4]);
            c.moveTo(x, top);
            c.lineTo(x, bottom);
            c.lineWidth = 1;
            c.strokeStyle = 'rgba(79, 70, 229, 0.35)';
            c.stroke();
            c.restore();
        }
    };

    const chart = new Chart(ctx, {
        type: 'line',
        data: {
            labels: allLabels,
            datasets: [{
                data: allValues,
                borderColor: '#4F46E5',
                backgroundColor: gradient,
                borderWidth: 2,
                fill: true,
                tension: 0.35,
                pointRadius: 0,
                pointHoverRadius: 5,
                pointHoverBackgroundColor: '#4F46E5',
                pointHoverBorderColor: '#ffffff',
                pointHoverBorderWidth: 2
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            interaction: { mode: 'index', intersect: false },
            plugins: {
                legend: { display: false },
                tooltip: {
                    backgroundColor: '#ffffff',
                    borderColor: '#e5e7eb',
                    borderWidth: 1,
                    padding: 12,
                    displayColors: false,
                    titleColor: '#6b7280',
                    titleFont: { size: 11, weight: '500' },
                    bodyColor: '#111827',
                    bodyFont: { size: 15, weight: '700' },
                    callbacks: {
                        title: (items) => formatDate(items[0].label),
                        label: (item) => money(item.parsed.y),
                        afterLabel: (item) => {
                            const g = currentGains[item.dataIndex];
                            if (g == null) return '';
                            const sign = g >= 0 ? '+' : '-';
                            return (g >= 0 ? '▲ ' : '▼ ') + sign + money(Math.abs(g)) + ' G/P';
                        }
                    }
                }
            },
            scales: {
                x: {
                    grid: { display: false },
                    border: { display: false },
                    ticks: { color: '#9ca3af', font: { size: 11 }, maxRotation: 0, autoSkip: true, maxTicksLimit: 8 }
                },
                y: {
                    grid: { color: '#f3f4f6' },
                    border: { display: false },
                    ticks: { color: '#9ca3af', font: { size: 11 }, callback: (v) => formatK(v) }
                }
            }
        },
        plugins: [hoverLine]
    });

    // --- Filtrado por rango (1D / 1W / 1M / 6M / 1Y) ---
    function applyRange(days) {
        let labels = allLabels, values = allValues, gains = allGains;
        if (days && allLabels.length > days) {
            labels = allLabels.slice(-days);
            values = allValues.slice(-days);
            gains = allGains.slice(-days);
        }
        currentGains = gains;
        chart.data.labels = labels;
        chart.data.datasets[0].data = values;
        chart.update();
    }

    const buttons = document.querySelectorAll('#perfRangeButtons [data-range]');
    buttons.forEach((btn) => {
        btn.addEventListener('click', () => {
            buttons.forEach((b) => {
                b.classList.remove('bg-indigo-600', 'text-white');
                b.classList.add('text-gray-500');
            });
            btn.classList.add('bg-indigo-600', 'text-white');
            btn.classList.remove('text-gray-500');
            applyRange(parseInt(btn.dataset.range, 10));
        });
    });

    // Rango por defecto: 6M
    const defaultBtn = document.querySelector('#perfRangeButtons [data-range="180"]');
    if (defaultBtn) defaultBtn.click();
    else applyRange(180);
});
