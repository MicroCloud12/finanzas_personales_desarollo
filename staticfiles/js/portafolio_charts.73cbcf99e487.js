const CHART_COLORS = {
    primary: {
        solid: '#818cf8',      // Indigo-400
        gradientStart: 'rgba(99, 102, 241, 0.5)',
        gradientEnd: 'rgba(99, 102, 241, 0)'
    },
    tooltip: {
        bg: 'rgba(17, 24, 39, 0.9)',
        textMain: '#fff',
        textMuted: '#e5e7eb',
        border: 'rgba(255,255,255,0.1)'
    },
    allocation: ['#4F46E5', '#10B981', '#F59E0B', '#EF4444', '#8B5CF6']
};

const CHART_IDS = {
    MAIN: 'portfolioMainChart',
    ALLOCATION: 'allocationChart'
};

const DATA_IDS = {
    CHART_LABELS: 'chart-labels-data',
    CHART_DATA: 'chart-data-data',
    DIST_LABELS: 'dist-labels-data',
    DIST_DATA: 'dist-data-data'
};

function formatCurrency(value) {
    return new Intl.NumberFormat('en-US', {
        style: 'currency',
        currency: 'USD',
        minimumFractionDigits: 0
    }).format(value);
}

function getJsonData(elementId) {
    const element = document.getElementById(elementId);
    if (!element) {
        console.warn(`Element with id ${elementId} not found.`);
        return [];
    }

    try {
        const parsedContent = JSON.parse(element.textContent);
        // Sometimes Django json_script double encodes strings. This handles it safely.
        return typeof parsedContent === 'string' ? JSON.parse(parsedContent) : parsedContent;
    } catch (error) {
        console.error(`Error parsing JSON for element ${elementId}:`, error);
        return [];
    }
}

function getPortfolioData() {
    return {
        chartLabels: getJsonData(DATA_IDS.CHART_LABELS),
        chartData: getJsonData(DATA_IDS.CHART_DATA),
        distLabels: getJsonData(DATA_IDS.DIST_LABELS),
        distData: getJsonData(DATA_IDS.DIST_DATA)
    };
}

function initMainChart(labels, data) {
    const canvas = document.getElementById(CHART_IDS.MAIN);
    if (!canvas) return;

    const ctx = canvas.getContext('2d');
    const gradient = ctx.createLinearGradient(0, 0, 0, 400);
    gradient.addColorStop(0, CHART_COLORS.primary.gradientStart);
    gradient.addColorStop(1, CHART_COLORS.primary.gradientEnd);

    new Chart(ctx, {
        type: 'line',
        data: {
            labels,
            datasets: [{
                label: 'Valor Acumulado',
                data,
                borderColor: CHART_COLORS.primary.solid,
                backgroundColor: gradient,
                borderWidth: 3,
                pointRadius: 0,
                pointHoverRadius: 6,
                fill: true,
                tension: 0.4
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { display: false },
                tooltip: {
                    mode: 'index',
                    intersect: false,
                    backgroundColor: CHART_COLORS.tooltip.bg,
                    titleColor: CHART_COLORS.tooltip.textMuted,
                    bodyColor: CHART_COLORS.tooltip.textMain,
                    borderColor: CHART_COLORS.tooltip.border,
                    borderWidth: 1,
                    padding: 10,
                    callbacks: {
                        label: (context) => formatCurrency(context.parsed.y)
                    }
                }
            },
            scales: {
                x: { display: false },
                y: { display: false, beginAtZero: false }
            }
        }
    });
}

function initAllocationChart(labels, data) {
    const canvas = document.getElementById(CHART_IDS.ALLOCATION);
    if (!canvas) return;

    const ctx = canvas.getContext('2d');
    
    new Chart(ctx, {
        type: 'doughnut',
        data: {
            labels,
            datasets: [{
                data,
                backgroundColor: CHART_COLORS.allocation,
                borderWidth: 0,
                hoverOffset: 4
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            cutout: '75%',
            plugins: {
                legend: { display: false },
                tooltip: {
                    callbacks: {
                        label: (context) => {
                            const label = context.label ? `${context.label}: ` : '';
                            return `${label}${formatCurrency(context.parsed)}`;
                        }
                    }
                }
            }
        }
    });
}

document.addEventListener('DOMContentLoaded', () => {
    const data = getPortfolioData();
    initMainChart(data.chartLabels, data.chartData);
    initAllocationChart(data.distLabels, data.distData);
});
