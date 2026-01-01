document.addEventListener('DOMContentLoaded', function () {
    // Helper function to safely parse JSON from script tags
    function getJsonData(id) {
        const element = document.getElementById(id);
        if (element) {
            return JSON.parse(element.textContent);
        }
        console.warn(`Element with id ${id} not found.`);
        return [];
    }

    // Retrieve data from json_script tags
    // Note: The data from Django is already a JSON string (via json.dumps), 
    // so json_script adds another layer of quotes? 
    // Let's verify: In views.py: 'chart_labels': json.dumps(chart_labels)
    // So {{ chart_labels }} is "[ '2023-01', ... ]" string.
    // {{ chart_labels|json_script }} makes <script type="application/json">"[ '2023-01', ... ]"</script>
    // So JSON.parse(textContent) returns the string "[ '2023-01' ... ]"
    // We need to parse THAT string again to get the array.

    const rawChartLabels = getJsonData('chart-labels-data');
    const rawChartData = getJsonData('chart-data-data');
    const rawDistLabels = getJsonData('dist-labels-data');
    const rawDistData = getJsonData('dist-data-data');

    // Parse the inner JSON strings if they are strings
    const chartLabels = typeof rawChartLabels === 'string' ? JSON.parse(rawChartLabels) : rawChartLabels;
    const chartData = typeof rawChartData === 'string' ? JSON.parse(rawChartData) : rawChartData;
    const distLabels = typeof rawDistLabels === 'string' ? JSON.parse(rawDistLabels) : rawDistLabels;
    const distData = typeof rawDistData === 'string' ? JSON.parse(rawDistData) : rawDistData;

    // --- MAIN PORTFOLIO LINE CHART ---
    const ctxMainElement = document.getElementById('portfolioMainChart');
    if (ctxMainElement) {
        const ctxMain = ctxMainElement.getContext('2d');

        // Create gradient
        let gradient = ctxMain.createLinearGradient(0, 0, 0, 400);
        gradient.addColorStop(0, 'rgba(99, 102, 241, 0.5)'); // Indigo
        gradient.addColorStop(1, 'rgba(99, 102, 241, 0)');

        new Chart(ctxMain, {
            type: 'line',
            data: {
                labels: chartLabels,
                datasets: [{
                    label: 'Valor Acumulado',
                    data: chartData,
                    borderColor: '#818cf8', // Indigo-400
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
                        backgroundColor: 'rgba(17, 24, 39, 0.9)',
                        titleColor: '#e5e7eb',
                        bodyColor: '#fff',
                        borderColor: 'rgba(255,255,255,0.1)',
                        borderWidth: 1,
                        padding: 10,
                        callbacks: {
                            label: function (context) {
                                return '$' + Number(context.parsed.y).toLocaleString();
                            }
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

    // --- ALLOCATION DOUGHNUT CHART ---
    const ctxAllocElement = document.getElementById('allocationChart');
    if (ctxAllocElement) {
        const ctxAlloc = ctxAllocElement.getContext('2d');
        new Chart(ctxAlloc, {
            type: 'doughnut',
            data: {
                labels: distLabels,
                datasets: [{
                    data: distData,
                    backgroundColor: [
                        '#4F46E5', '#10B981', '#F59E0B', '#EF4444', '#8B5CF6'
                    ],
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
                            label: function (context) {
                                let label = context.label || '';
                                if (label) {
                                    label += ': ';
                                }
                                label += '$' + Number(context.parsed).toLocaleString();
                                return label;
                            }
                        }
                    }
                }
            }
        });
    }
});
