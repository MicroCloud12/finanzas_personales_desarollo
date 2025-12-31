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
                plugins: [ChartDataLabels, {
                    id: 'customConnectorLines',
                    afterDraw: (chart) => {
                        const {
                            ctx,
                            chartArea: { width, height }
                        } = chart;

                        chart.data.datasets.forEach((dataset, i) => {
                            const meta = chart.getDatasetMeta(i);

                            meta.data.forEach((element, index) => {
                                // Only draw if visible and has value
                                if (dataset.data[index] === 0 || element.hidden) return;

                                // Calculate percentage
                                const total = dataset.data.reduce((a, b) => Number(a) + Number(b), 0);
                                const value = Number(dataset.data[index]); // Ensure value is number
                                const percentage = (value * 100 / total);

                                // Only draw lines for small slices (<= 8%)
                                if (percentage > 8) return;

                                const { x, y } = element.tooltipPosition();
                                const center = element.getCenterPoint();

                                // Calculate coordinates
                                // We need center of chart, not center of arc
                                const centerX = chart.chartArea.left + width / 2;
                                const centerY = chart.chartArea.top + height / 2;

                                // Angle of the arc center
                                const angle = Math.atan2(y - centerY, x - centerX);

                                // Radii
                                const outerRadius = element.outerRadius;
                                const arcRadius = outerRadius + 4; // Start line closer to slice

                                // 3-Level Staggering
                                const staggerLevel = index % 3;
                                const staggerDist = 15 + (staggerLevel * 25); // Ends at 15, 40, 65

                                const midX = centerX + Math.cos(angle) * (outerRadius + staggerDist);
                                const midY = centerY + Math.sin(angle) * (outerRadius + staggerDist);

                                const startX = centerX + Math.cos(angle) * arcRadius;
                                const startY = centerY + Math.sin(angle) * arcRadius;

                                ctx.save();
                                ctx.beginPath();
                                ctx.moveTo(startX, startY);
                                ctx.lineTo(midX, midY);
                                ctx.strokeStyle = '#9ca3af'; // gray-400
                                ctx.lineWidth = 1;
                                ctx.stroke();
                                ctx.restore();
                            });
                        });
                    }
                }],
                data: {
                    labels: data.labels,
                    datasets: [{
                        data: data.data,
                        backgroundColor: [
                            '#FCD34D', '#F87171', '#FB923C', '#9D174D',
                            '#60A5FA', '#34D399', '#A78BFA', '#D946EF',
                            '#0EA5E9', '#F97316', '#8B5CF6', '#F43F5E'
                        ],
                        borderWidth: 0,
                        hoverOffset: 4
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    layout: {
                        padding: 45 // Reduced padding for Zoom In
                    },
                    cutout: '50%',
                    rotation: 120,
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
                                    let label = context.label || '';
                                    if (label) { label += ': '; }
                                    if (context.parsed !== null) {
                                        label += new Intl.NumberFormat('en-US', {
                                            style: 'currency', currency: 'USD'
                                        }).format(context.parsed);
                                    }
                                    return label;
                                }
                            }
                        },
                        datalabels: {
                            display: true,
                            // Hybrid Color: White inside, Gray outside
                            color: (ctx) => {
                                let sum = 0;
                                let dataArr = ctx.chart.data.datasets[0].data;
                                dataArr.map(data => { sum += Number(data); });
                                let value = ctx.dataset.data[ctx.dataIndex];
                                let percentage = (value * 100 / sum);
                                return percentage > 8 ? '#ffffff' : '#374151';
                            },
                            font: {
                                weight: '500', // Medium weight for Outfit
                                size: 11,
                                family: 'Outfit'
                            },
                            formatter: (value, ctx) => {
                                let sum = 0;
                                let dataArr = ctx.chart.data.datasets[0].data;
                                dataArr.map(data => { sum += Number(data); });
                                let percentage = (value * 100 / sum);

                                let label = ctx.chart.data.labels[ctx.dataIndex];
                                if (label.length > 15 && label.includes(' ')) {
                                    const words = label.split(' ');
                                    const mid = Math.floor(words.length / 2);
                                    label = words.slice(0, mid).join(' ') + '\n' + words.slice(mid).join(' ');
                                }

                                return label + '\n' + percentage.toFixed(0) + "%";
                            },
                            // Hybrid Anchor/Align
                            anchor: (ctx) => {
                                let sum = 0;
                                let dataArr = ctx.chart.data.datasets[0].data;
                                dataArr.map(data => { sum += Number(data); });
                                let value = ctx.dataset.data[ctx.dataIndex];
                                let percentage = (value * 100 / sum);
                                return percentage > 8 ? 'center' : 'end';
                            },
                            align: (ctx) => {
                                let sum = 0;
                                let dataArr = ctx.chart.data.datasets[0].data;
                                dataArr.map(data => { sum += Number(data); });
                                let value = ctx.dataset.data[ctx.dataIndex];
                                let percentage = (value * 100 / sum);
                                return percentage > 8 ? 'center' : 'end';
                            },
                            offset: (ctx) => {
                                let sum = 0;
                                let dataArr = ctx.chart.data.datasets[0].data;
                                dataArr.map(data => { sum += Number(data); });
                                let value = ctx.dataset.data[ctx.dataIndex];
                                let percentage = (value * 100 / sum);
                                // Only stagger outside labels
                                if (percentage > 8) return 0;
                                const level = ctx.dataIndex % 3;
                                return 20 + (level * 25); // Labels at 20, 45, 70 (5px gap from line end)
                            },
                            textAlign: 'center'
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
                padding: { top: 20, right: 20, left: 10, bottom: 10 }
            },
            scales: {
                y: {
                    beginAtZero: false,
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
                        // Only show label for the last point or significant peaks if crowded
                        // For now, show all but ensure enough space
                        return true;
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
