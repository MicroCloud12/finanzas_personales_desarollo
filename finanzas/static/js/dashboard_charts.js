// Gráfico de gastos/ingresos por categoría o descripción (con filtros)
let gastosChart = null;
function initGastosChart() {
    const canvas = document.getElementById('gastosPorCategoriaChart');
    if (!canvas) return;
    const tipoSel = document.getElementById('gastosTipoFilter');
    const agruparSel = document.getElementById('gastosAgruparFilter');

    function render() {
        // data-url ya trae ?year=...&month=...; añadimos los filtros
        let url = canvas.dataset.url;
        if (tipoSel) url += '&tipo=' + tipoSel.value;
        if (agruparSel) url += '&agrupar=' + agruparSel.value;
        fetch(url)
            .then(resp => resp.json())
            .then(data => {
                if (gastosChart) gastosChart.destroy();
                gastosChart = new Chart(canvas, {
                    type: 'doughnut',
                    data: {
                        labels: data.labels,
                        datasets: [{
                            data: data.data,
                            backgroundColor: [
                                '#FF6384', '#36A2EB', '#FFCE56',
                                '#4BC0C0', '#9966FF', '#FF9F40'
                            ]
                        }]
                    },
                    options: {
                        responsive: true,
                        maintainAspectRatio: false,
                        plugins: {
                            legend: {
                                position: 'bottom',
                                labels: { boxWidth: 12, padding: 10, font: { size: 11 } }
                            }
                        }
                    }
                });
            });
    }

    if (tipoSel) tipoSel.addEventListener('change', render);
    if (agruparSel) agruparSel.addEventListener('change', render);
    render();
}

function initBudgetVsActualChart() {
    const canvas = document.getElementById('budgetVsActualChart');
    if (!canvas || !canvas.dataset.url) return;
    const url = canvas.dataset.url;

    fetch(url)
        .then(resp => resp.json())
        .then(data => {
            new Chart(canvas, {
                type: 'bar',
                data: {
                    labels: data.labels,
                    datasets: [
                        {
                            label: 'Gasto Real',
                            data: data.real,
                            backgroundColor: '#4F46E5', // Indigo-600
                            borderRadius: 4
                        },
                        {
                            label: 'Presupuesto',
                            data: data.presupuestado,
                            backgroundColor: '#C7D2FE', // Indigo-200
                            borderRadius: 4
                        }
                    ]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    scales: {
                        y: {
                            beginAtZero: true,
                            grid: {
                                borderDash: [2, 4],
                                color: '#f3f4f6'
                            },
                            ticks: {
                                callback: value => '$' + value.toLocaleString()
                            }
                        },
                        x: {
                            grid: { display: false }
                        }
                    },
                    plugins: {
                        legend: { display: false }
                    }
                }
            });
        });
}

document.addEventListener('DOMContentLoaded', () => {
    initGastosChart();
    initBudgetVsActualChart();
});