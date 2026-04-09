// Plugin para texto central
const centerTextPlugin = {
    id: 'centerText',
    beforeDraw: function (chart) {
        if (chart.config.type !== 'doughnut') return;
        var width = chart.width,
            height = chart.height,
            ctx = chart.ctx;

        ctx.restore();

        // Título secundario
        ctx.font = '500 13px Outfit, sans-serif';
        ctx.textBaseline = 'middle';
        ctx.fillStyle = '#9CA3AF'; // text-gray-400
        var text1 = 'This month expence',
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
                                    let sum = context.dataset.data.reduce((a, b) => Number(a) + Number(b), 0);
                                    let percentage = Math.round((context.parsed * 100) / sum);
                                    let formattedVal = new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', minimumFractionDigits: 0 }).format(context.parsed);
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

// Removed initFlujoDineroChart (Finance Overview removed from dashboard)

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


// Gráfico de Crecimiento de Ahorro (Total Balance Overview)
function initSavingsGrowthChart() {
    const canvas = document.getElementById('savingsGrowthChart');
    if (!canvas) return;

    // Retrieve data securely from json_script tags
    const labelsScript = document.getElementById('savings-labels-data');
    const valuesScript = document.getElementById('savings-values-data');

    let labels = [];
    let data = [];
    if (labelsScript && valuesScript) {
        labels = JSON.parse(labelsScript.textContent);
        data = JSON.parse(valuesScript.textContent);
    } else {
        // Fallback mock labels for redesign test
        labels = ['1 Jul', '3 Jul', '5 Jul', '7 Jul', '9 Jul', '11 Jul', '13 Jul', '15 Jul', '17 Jul'];
        data = [16000, 15000, 9500, 13000, 18500, 12500, 16000, 13000, 17500];
    }

    // Mock "Same period last month" data
    let data2 = data.map(v => Number(v) * (0.7 + Math.random() * 0.4));

    const ctx = canvas.getContext('2d');

    // Create Purple Gradient
    const gradient = ctx.createLinearGradient(0, 0, 0, 300);
    gradient.addColorStop(0, 'rgba(139, 92, 246, 0.4)'); // Purple-500 @ 40%
    gradient.addColorStop(1, 'rgba(139, 92, 246, 0.05)'); // Transparent

    new Chart(canvas, {
        type: 'line',
        data: {
            labels: labels,
            datasets: [
                {
                    label: 'This month',
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
                },
                {
                    label: 'Same period last month',
                    data: data2,
                    borderColor: '#C4B5FD', // Light purple
                    borderWidth: 2,
                    borderDash: [5, 5],
                    fill: false,
                    tension: 0.4, // Smooth curves
                    pointRadius: 0,
                    pointHoverRadius: 4
                }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            layout: {
                padding: { top: 20, right: 20, left: 10, bottom: 10 }
            },
            interaction: {
                mode: 'index',
                intersect: false,
            },
            scales: {
                y: {
                    beginAtZero: true,
                    suggestedMax: Math.max(...data) * 1.2,
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
                    backgroundColor: '#ffffff',
                    titleColor: '#1F2937',
                    bodyColor: '#4B5563',
                    borderColor: '#E5E7EB',
                    borderWidth: 1,
                    padding: 12,
                    titleFont: { family: 'Outfit', size: 13, weight: 'bold' },
                    bodyFont: { family: 'Outfit', size: 13, weight: 'bold' },
                    cornerRadius: 12,
                    displayColors: true,
                    callbacks: {
                        label: function (context) {
                            return context.dataset.label + ': $' + Number(context.parsed.y).toLocaleString();
                        }
                    }
                }
            }
        }
    });
}

// Gráfico de Comparing Budget and Expense
function initBudgetVsActualChart() {
    const canvas = document.getElementById('budgetVsActualChart');
    if (!canvas) return;

    // Mock data for Budget vs Actual (Comparing of budget and expence)
    const labels = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul'];
    const expenseData = [4000, 2800, 3500, 4800, 2500, 5000, 2200];
    const budgetData = [5000, 2800, 3800, 5500, 4000, 6800, 5000];

    new Chart(canvas, {
        type: 'bar',
        data: {
            labels: labels,
            datasets: [
                {
                    label: 'Expense',
                    data: expenseData,
                    backgroundColor: '#8B5CF6', // Solid purple
                    borderRadius: 20,
                    barPercentage: 0.6,
                    categoryPercentage: 0.7,
                    borderSkipped: false
                },
                {
                    label: 'Budget',
                    data: budgetData,
                    backgroundColor: '#EDE9FE', // Light transparent purple
                    borderRadius: 20,
                    barPercentage: 0.6,
                    categoryPercentage: 0.7,
                    borderSkipped: false
                }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            // Grouped: false allows bars to overlay each other on the same x category 
            // BUT ChartJS overlaid bars are drawn in order. Budget is drawn 2nd so it covers Expense? 
            // We want Expense ON TOP. So we place Expense FIRST in datasets? No, ChartJS draws datasets in index order.
            // Dataset 0 drawn first, then Dataset 1. So Dataset 1 is on top.
            // Wait, we want Expense on top. Let's make Budget Dataset 0, Expense Dataset 1.
            layout: { padding: { top: 20, right: 10, left: 10, bottom: 0 } },
            scales: {
                x: {
                    stacked: false,
                    grid: { display: false },
                    ticks: { font: { family: 'Outfit', size: 11 }, color: '#9ca3af' }
                },
                y: {
                    stacked: false,
                    beginAtZero: true,
                    grid: { color: '#f3f4f6', borderDash: [5, 5], drawBorder: false },
                    ticks: {
                        callback: function (value) { return '$' + value.toLocaleString(); },
                        font: { family: 'Outfit', size: 11 }, color: '#9ca3af'
                    }
                }
            },
            plugins: {
                legend: { display: false },
                tooltip: {
                    backgroundColor: '#ffffff',
                    titleColor: '#1F2937',
                    bodyColor: '#4B5563',
                    borderColor: '#E5E7EB',
                    borderWidth: 1,
                    padding: 12,
                    titleFont: { family: 'Outfit', size: 13, weight: 'bold' },
                    bodyFont: { family: 'Outfit', size: 13, weight: 'bold' },
                    cornerRadius: 12,
                    callbacks: {
                        label: function (context) {
                            return context.dataset.label + ': $' + Number(context.parsed.y).toLocaleString();
                        }
                    }
                }
            }
        }
    });

    // Fix overlaid z-index by re-ordering datasets array in data object config:
    const chartConfig = Chart.instances[Chart.instances.length - 1].config;
    const datasets = chartConfig._config.data.datasets;
    // Swap them so Budget is drawn first, Expense drawn second to overlay.
    // Wait, Dataset 0 is drawn first. Dataset 1 is drawn second.
    // So Expense is dataset 0, Budget is dataset 1. Budget is on top. This is inverse!
    datasets.reverse();
    Chart.instances[Chart.instances.length - 1].update();
}

document.addEventListener('DOMContentLoaded', () => {
    initGastosChart();
    initSavingsGrowthChart();
    initBudgetVsActualChart();
});
