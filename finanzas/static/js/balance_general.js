// Gráfica de patrimonio mes a mes (balance_general.html). Los datos vienen en {{ grafica|json_script:"grafica-data" }}.
document.addEventListener('DOMContentLoaded', () => {
    const datos = document.getElementById('grafica-data');
    const canvas = document.getElementById('grafica-patrimonio');
    if (!datos || !canvas || typeof Chart === 'undefined') return;
    const d = JSON.parse(datos.textContent);
    const pesos = new Intl.NumberFormat('es-MX', { style: 'currency', currency: 'MXN' });
    const pesosEnteros = new Intl.NumberFormat('es-MX', { style: 'currency', currency: 'MXN', maximumFractionDigits: 0 });
    new Chart(canvas, {
        type: 'line',
        data: { labels: d.labels, datasets: [
            { label: 'Patrimonio', data: d.patrimonio, borderColor: '#4f46e5', backgroundColor: 'rgba(79,70,229,0.08)', fill: true, tension: 0.3, borderWidth: 2 },
            { label: 'Activos', data: d.activos, borderColor: '#059669', borderDash: [4, 4], borderWidth: 1.5, pointRadius: 2 },
            { label: 'Pasivos', data: d.pasivos, borderColor: '#dc2626', borderDash: [4, 4], borderWidth: 1.5, pointRadius: 2 },
        ] },
        options: { responsive: true, maintainAspectRatio: false,
            plugins: { legend: { position: 'bottom' }, tooltip: { callbacks: { label: ctx => ` ${ctx.dataset.label}: ${pesos.format(ctx.raw)}` } } },
            scales: { y: { ticks: { callback: v => pesosEnteros.format(v) } } } }
    });
});
