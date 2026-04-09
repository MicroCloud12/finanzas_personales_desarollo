// Plugin para texto central
const centerTextPlugin = {
    id: 'centerText',
    beforeDraw: function(chart) {
        if (chart.config.type !== 'doughnut') return;
        var width = chart.width,
            height = chart.height,
            ctx = chart.ctx;

        ctx.restore();
        
        // Título secundario
        ctx.font = '500 13px Outfit, sans-serif';
        ctx.textBaseline = 'middle';
        ctx.fillStyle = '#9CA3AF'; // text-gray-400
        var text1 = 'Gastos del mes',
            textX1 = Math.round((width - ctx.measureText(text1).width) / 2),
            textY1 = height / 2 - 15;
        ctx.fillText(text1, textX1, textY1);

        // Monto principal
        ctx.font = 'bold 28px Outfit, sans-serif';
        ctx.fillStyle = '#111827'; // text-gray-900
        let sum = 0;
        if (chart.data.datasets && chart.data.datasets[0] && chart.data.datasets[0].data) {
            sum = chart.data.datasets[0].data.reduce((a, b) => Number(a) + Number(b), 0);
        }
        
        // Format to split decimal like design: "$6,222.00"
        let formatter = new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' });
        let parts = formatter.formatToParts(sum);
        let integerPart = '';
        let decimalPart = '';
        parts.forEach(p => {
            if (p.type === 'decimal' || p.type === 'fraction') { decimalPart += p.value; }
            else { integerPart += p.value; }
        });
        
        let text2 = integerPart;
        let textX2 = Math.round((width - ctx.measureText(text2 + decimalPart).width) / 2);
        let textY2 = height / 2 + 20;
        ctx.fillText(text2, textX2, textY2);
        
        // Dibujamos la parte decimal más clara
        let intWidth = ctx.measureText(text2).width;
        ctx.fillStyle = '#D1D5DB'; // text-gray-300
        ctx.font = 'bold 24px Outfit, sans-serif';
        ctx.fillText(decimalPart, textX2 + intWidth, textY2 + 1); // ajustado 1px visual
        
        ctx.save();
    }
};

// Gráfico de gastos por categoría
function initGastosChart() {
    const canvas = document.getElementById('gastosPorCategoriaChart');
    if (!canvas) return;
    const url = canvas.dataset.url;
    fetch(url)
        .then(resp => resp.json())
        .then(data => {

            const palette = [
                '#8B5CF6', // Purple base
                '#C4B5FD', // Light purple
                '#EDE9FE', // Very light
                '#4B5563', // Dark gray
                '#9CA3AF', // Medium gray
                '#E5E7EB', // Light gray
                '#6D28D9', // Deep purple
                '#A78BFA',
                '#374151',
                '#D1D5DB'
            ];

            const backgroundColors = data.labels.map((_, i) => palette[i % palette.length]);

            new Chart(canvas, {
                type: 'doughnut',
                plugins: [centerTextPlugin],
                data: {
                    labels: data.labels,
                    datasets: [{
                        data: data.data,
                        backgroundColor: backgroundColors,
                        borderWidth: 4, // create space between segments
                        borderColor: '#ffffff', // matching card background
                        borderRadius: 20, // Circular border ends!
                        hoverOffset: 6
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    layout: {
                        padding: 20
                    },
                    cutout: '80%', // Thinner ring
                    rotation: 180, // Start drawing angles nicely
                    plugins: {
                        legend: { display: false },
                        tooltip: {
                            backgroundColor: '#ffffff',
                            titleColor: '#1F2937',
                            bodyColor: '#4B5563',
                            borderColor: '#E5E7EB',
                            borderWidth: 1,
                            padding: 12,
                            titleFont: { family: 'Outfit', size: 14, weight: 'bold' },
                            bodyFont: { family: 'Outfit', size: 13, weight: 'bold' },
                            cornerRadius: 12,
                            displayColors: false,
                            yAlign: 'bottom',
                            callbacks: {
                                title: () => null, // Hide title to just show "40% $2,500"
                                label: function (context) {
                                    let sum = context.dataset.data.reduce((a,b)=> Number(a)+Number(b), 0);
                                    let percentage = Math.round((context.parsed * 100) / sum);
                                    let formattedVal = new Intl.NumberFormat('en-US', {style: 'currency', currency: 'USD', minimumFractionDigits: 0}).format(context.parsed);
                                    return [percentage + '%', formattedVal];
                                }
                            }
                        },
                        datalabels: {
                            display: false // Turn off old custom labels
                        }
                    }
                }
            });

            // Generar la leyenda HTML dinámica personalizada
            const legendContainer = document.getElementById('gastosLegend');
            if (legendContainer) {
                let html = '';
                data.labels.forEach((label, i) => {
                    const color = backgroundColors[i];
                    html += `
                        <div class="flex items-center gap-2 mb-2 w-auto min-w-[30%]">
                            <span class="w-2.5 h-2.5 rounded-full" style="background-color: ${color}"></span>
                            <span class="text-xs font-semibold text-gray-700">${label}</span>
                        </div>
                    `;
                });
                legendContainer.innerHTML = html;
            }
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
                        backgroundColor: ['#4F46E5', '#EF4444'], // Blue for Income, Red for Expenses
                        borderRadius: 6,
                        barThickness: 50, // Thicker bars
                        maxBarThickness: 80,
                        cornerRadius: 8,
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    scales: {
                        y: {
                            beginAtZero: true,
                            grid: { display: true, borderDash: [2, 2], drawBorder: false },
                            ticks: {
                                callback: value => '$' + value.toLocaleString(),
                                font: { family: 'Outfit', size: 11 },
                                color: '#6B7280'
                            }
                        },
                        x: {
                            grid: { display: false },
                            ticks: {
                                font: { family: 'Outfit', size: 11 },
                                color: '#6B7280'
                            }
                        }
                    },
                    plugins: {
                        legend: { display: false },
                        tooltip: {
                            backgroundColor: '#1F2937',
                            padding: 12,
                            titleFont: { family: 'Outfit', size: 13 },
                            bodyFont: { family: 'Outfit', size: 13 },
                            cornerRadius: 8,
                            displayColors: true,
                            callbacks: {
                                label: function (context) {
                                    let label = context.dataset.label || '';
                                    if (label) {
                                        label += ': ';
                                    }
                                    if (context.parsed.y !== null) {
                                        label += new Intl.NumberFormat('en-US', {
                                            style: 'currency',
                                            currency: 'USD'
                                        }).format(context.parsed.y);
                                    }
                                    return label;
                                }
                            }
                        }
                    }
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


// Gráfico de Crecimiento de Ahorro (Savings Growth - Purple Area)
function initSavingsGrowthChart() {
    const canvas = document.getElementById('savingsGrowthChart');
    if (!canvas) return;

    // Retrieve data securely from json_script tags
    const labelsScript = document.getElementById('savings-labels-data');
    const valuesScript = document.getElementById('savings-values-data');

    if (!labelsScript || !valuesScript) return;

    const labels = JSON.parse(labelsScript.textContent);
    const data = JSON.parse(valuesScript.textContent);

    const ctx = canvas.getContext('2d');

    // Create Purple Gradient
    const gradient = ctx.createLinearGradient(0, 0, 0, 300);
    gradient.addColorStop(0, 'rgba(139, 92, 246, 0.5)'); // Purple-500 @ 50%
    gradient.addColorStop(1, 'rgba(139, 92, 246, 0.0)'); // Transparent

    new Chart(canvas, {
        type: 'line',
        plugins: [ChartDataLabels],
        data: {
            labels: labels,
            datasets: [{
                label: 'Savings',
                data: data,
                borderColor: '#8B5CF6', // Purple-500
                backgroundColor: gradient,
                borderWidth: 3,
                fill: true,
                tension: 0.4, // Smooth curves
                pointBackgroundColor: '#ffffff',
                pointBorderColor: '#8B5CF6',
                pointBorderWidth: 2,
                pointRadius: 4,
                pointHoverRadius: 6,
                pointHoverBorderWidth: 3
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            layout: {
                padding: { top: 50, right: 20, left: 10, bottom: 10 }
            },
            scales: {
                y: {
                    beginAtZero: false,
                    grace: '10%', // Add breathing room at the top
                    grid: {
                        color: '#f3f4f6',
                        drawBorder: false,
                        borderDash: [5, 5]
                    },
                    ticks: {
                        callback: function (value) { return '$' + value.toLocaleString(); },
                        font: { family: 'Outfit', size: 11 },
                        color: '#9ca3af'
                    }
                },
                x: {
                    grid: { display: false },
                    ticks: {
                        font: { family: 'Outfit', size: 11 },
                        color: '#9ca3af'
                    }
                }
            },
            plugins: {
                legend: { display: false },
                tooltip: {
                    backgroundColor: '#1F2937',
                    padding: 12,
                    titleFont: { family: 'Outfit', size: 13 },
                    bodyFont: { family: 'Outfit', size: 13 },
                    cornerRadius: 8,
                    displayColors: false,
                    callbacks: {
                        label: function (context) {
                            return 'Saved: $' + Number(context.parsed.y).toLocaleString();
                        }
                    }
                },
                datalabels: {
                    align: 'top',
                    anchor: 'end',
                    offset: 4,
                    backgroundColor: '#1F2937', // Dark bg like tooltip for contrast
                    color: '#ffffff',
                    borderRadius: 4,
                    font: { family: 'Outfit', weight: 'bold', size: 10 },
                    formatter: function (value) {
                        // Shorten large numbers: 1.2k, 15k
                        if (value >= 1000) return (value / 1000).toFixed(1) + 'k';
                        return value;
                    },
                    display: function (context) {
                        // Logic to reduce clutter:
                        // 1. Always show the last point
                        let index = context.dataIndex;
                        let count = context.dataset.data.length;
                        if (index === count - 1) return true;

                        // 2. Always show the first point
                        if (index === 0) return true;

                        // 3. Show if value differs from the previous point (a "step" or change)
                        let current = Number(context.dataset.data[index]);
                        let prev = Number(context.dataset.data[index - 1]);
                        if (current !== prev) return 'auto';

                        // 4. Otherwise hide
                        return false;
                    }
                }
            }
        }
    });
}

document.addEventListener('DOMContentLoaded', () => {
    initGastosChart();
    initFlujoDineroChart();
    // initInversionesChart(); // Removed/Replaced
    initSavingsGrowthChart();
});
