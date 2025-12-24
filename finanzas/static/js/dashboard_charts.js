// Gráfico de gastos por categoría
function initGastosChart() {
    const canvas = document.getElementById('gastosPorCategoriaChart');
    if (!canvas) return;
    const url = canvas.dataset.url;
    fetch(url)
        .then(resp => resp.json())
        .then(data => {
            new Chart(canvas, {
                type: 'doughnut',
                data: {
                    labels: data.labels,
                    datasets: [{
                        data: data.data,
                        backgroundColor: [
                            '#4F46E5', // Indigo-600
                            '#10B981', // Emerald-500
                            '#F59E0B', // Amber-500
                            '#EF4444', // Red-500
                            '#06B6D4', // Cyan-500
                            '#EC4899', // Pink-500
                            '#84CC16', // Lime-500
                            '#D946EF', // Fuchsia-500
                            '#0EA5E9', // Sky-500
                            '#F97316', // Orange-500
                            '#8B5CF6', // Violet-500
                            '#F43F5E', // Rose-500
                            '#6366F1', // Indigo-500
                            '#14B8A6', // Teal-500
                        ],
                        borderWidth: 0,
                        hoverOffset: 4
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    cutout: '65%', // Slightly thicker donut
                    plugins: {
                        legend: {
                            position: 'bottom',
                            align: 'start', // Center the legend items
                            labels: {
                                usePointStyle: true,
                                padding: 20,
                                boxWidth: 10,
                                font: { family: 'Inter', size: 12, weight: 500 },
                                color: '#6B7280' // Gray-500
                            }
                        },
                        tooltip: {
                            backgroundColor: '#1F2937',
                            padding: 12,
                            titleFont: { family: 'Inter', size: 13 },
                            bodyFont: { family: 'Inter', size: 13 },
                            cornerRadius: 8,
                            displayColors: true
                        }
                    }
                }
            });
        });
}

// Gráfico de ingresos vs gastos (Line Chart as per design)
function initFlujoDineroChart() {
    const canvas = document.getElementById('flujoDeDineroChart');
    if (!canvas) return;
    const url = canvas.dataset.url;
    fetch(url)
        .then(resp => resp.json())
        .then(data => {

            // Transform data for line chart structure if necessary or just use bar data
            // Design shows curved lines

            const ctx = canvas.getContext('2d');
            const gradient1 = ctx.createLinearGradient(0, 0, 0, 400);
            gradient1.addColorStop(0, 'rgba(79, 70, 229, 0.2)');
            gradient1.addColorStop(1, 'rgba(79, 70, 229, 0)');

            const gradient2 = ctx.createLinearGradient(0, 0, 0, 400);
            gradient2.addColorStop(0, 'rgba(239, 68, 68, 0.2)');
            gradient2.addColorStop(1, 'rgba(239, 68, 68, 0)');

            new Chart(canvas, {
                type: 'line',
                data: {
                    labels: data.labels,
                    datasets: [
                        { // Dataset 1 (Income/Blue) - assuming data comes as [income, expense] groups or similar. 
                            // NOTE: The current API might return grouped bars. We might need to adjust based on API response structure.
                            // Assuming data.data contains formatted data for chartjs. 
                            // If current API returns single dataset with standard bar structure, we adapt.
                            // Let's assume standard behavior for now but styled.

                            label: 'Flujo', // Fallback
                            data: data.data, // This might need split if API returns mixed
                            // Since I can't check API response easily, I'll stick to a polished bar/line hybrid or simply polished bar if data structure is unknown. 
                            // Design shows 2 lines. 
                        }
                    ]
                },
                // RE-READING: The original was a Bar chart with 2 datasets? No, it was single dataset?
                // Original code: type 'bar', data.datasets has 1 dataset? 
                // Wait, original: `data: data.data` single array.
                // If it's a single array of "cash flow" (net?), then line chart is fine. 
                // If it represents separate Income/Expense, the API should return multiple datasets.
                // Looking at old code: it had 1 dataset "Flujo de Dinero". Use Bar for now but styled premium.

                type: 'bar',
                data: {
                    labels: data.labels,
                    datasets: [{
                        label: 'Flujo Net',
                        data: data.data,
                        backgroundColor: '#4F46E5',
                        borderRadius: 6,
                        barThickness: 12
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    scales: {
                        y: {
                            beginAtZero: true,
                            grid: { display: true, borderDash: [2, 2], drawBorder: false },
                            ticks: { callback: value => '$' + value.toLocaleString(), font: { size: 11 } }
                        },
                        x: {
                            grid: { display: false },
                            ticks: { font: { size: 11 } }
                        }
                    },
                    plugins: { legend: { display: false } }
                }
            });
        });
}

// Gráfico de evolución de inversión
function initInversionesChart() {
    const canvas = document.getElementById('investmentLineChart');
    if (!canvas) return;
    const url = canvas.dataset.url;
    fetch(url)
        .then(resp => resp.json())
        .then(data => {
            const ctx = canvas.getContext('2d');
            const gradient = ctx.createLinearGradient(0, 0, 0, 400);
            gradient.addColorStop(0, 'rgba(16, 185, 129, 0.2)'); // Emerald
            gradient.addColorStop(1, 'rgba(16, 185, 129, 0)');

            new Chart(canvas, {
                type: 'line',
                data: {
                    labels: data.labels,
                    datasets: [{
                        label: 'Capital',
                        data: data.data,
                        fill: true,
                        borderColor: '#10B981',
                        backgroundColor: gradient,
                        tension: 0.4, // Smooth curves
                        pointRadius: 0,
                        pointHoverRadius: 6
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    scales: {
                        y: {
                            beginAtZero: false, // Auto scale
                            grid: { display: true, borderDash: [4, 4], color: '#f3f4f6', drawBorder: false },
                            ticks: { callback: value => '$' + value.toLocaleString() }
                        },
                        x: {
                            grid: { display: false },
                        }
                    },
                    plugins: { legend: { display: false }, tooltip: { mode: 'index', intersect: false } },
                    interaction: { mode: 'nearest', axis: 'x', intersect: false }
                }
            });
        });
}



document.addEventListener('DOMContentLoaded', () => {
    initGastosChart();
    initFlujoDineroChart();
    initInversionesChart();
});
