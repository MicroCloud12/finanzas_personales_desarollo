// Acciones de la tabla de presupuesto (buscar recibos, procesarlos, predecir) vía fetch + JSON.
function showToast(message, type = 'info') {
    let container = document.getElementById('toast-container');
    if (!container) {
        container = document.createElement('div');
        container.id = 'toast-container';
        container.className = 'fixed top-20 right-5 z-50 flex flex-col gap-3 pointer-events-none';
        document.body.appendChild(container);
    }
    const colors = { success: 'border-green-500 text-green-700', error: 'border-red-500 text-red-700', warning: 'border-yellow-500 text-yellow-700', info: 'border-blue-500 text-blue-700' };
    const toast = document.createElement('div');
    toast.className = `pointer-events-auto flex items-center w-full max-w-xs p-4 bg-white/90 backdrop-blur-md rounded-lg shadow-2xl border-l-4 ${colors[type] || colors.info}`;
    const texto = document.createElement('div');
    texto.className = 'pl-2 text-sm font-semibold';
    texto.textContent = message;  // texto plano: un error del servidor nunca se interpreta como HTML
    toast.appendChild(texto);
    container.appendChild(toast);
    setTimeout(() => toast.remove(), 5000);
}

const getJSON = url => fetch(url, { headers: { 'X-Requested-With': 'XMLHttpRequest', 'Accept': 'application/json' } }).then(r => r.json());
const dormir = ms => new Promise(resolve => setTimeout(resolve, ms));

// Muestra el spinner del botón mientras corre `trabajo` y siempre restaura el ícono.
async function conSpinner(btn, icono, spinner, mensajeError, trabajo) {
    const i = btn.querySelector(icono), s = btn.querySelector(spinner);
    i.classList.add('hidden');
    s.classList.remove('hidden');
    try {
        await trabajo();
    } catch (error) {
        console.error(error);
        showToast(mensajeError, 'error');
    } finally {
        s.classList.add('hidden');
        i.classList.remove('hidden');
    }
}

function buscarRecibos(btn) {
    const badge = btn.querySelector('.resultado-badge');
    badge.classList.add('hidden');
    conSpinner(btn, '.icon-lupa', '.icon-spinner', 'Ocurrió un error al buscar recibos.', async () => {
        const data = await getJSON(btn.dataset.url);
        if (data.error) return showToast(data.error, 'error');
        if (data.cantidad !== undefined) {
            badge.textContent = data.cantidad;
            badge.classList.remove('hidden');
        }
    });
}

function predecirRecibo(btn) {
    conSpinner(btn, '.icon-magia', '.icon-spinner-magia', 'Ocurrió un error al predecir el recibo.', async () => {
        const data = await getJSON(btn.dataset.url);
        if (data.error) return showToast(data.error, 'error');
        if (data.success) {
            showToast(`Predicción: $${data.monto_predicho}${data.fecha_predicha ? ' · ' + data.fecha_predicha : ''}`, 'success');
            window.location.reload();
        }
    });
}

function procesarRecibosAnteriores(btn) {
    conSpinner(btn, '.icon-procesar', '.icon-spinner-procesar', 'Ocurrió un error al procesar los recibos.', async () => {
        const data = await getJSON(btn.dataset.url);
        if (data.error) return showToast(data.error, 'error');
        if (!data.task_id) return showToast(data.mensaje || 'Hecho', 'info');

        // 1) la tarea lanzadora devuelve el id del grupo; 2) se espera a que el grupo termine
        let inicial;
        do { await dormir(2000); inicial = await getJSON(`/resultado-tarea-inicial/${data.task_id}/`); }
        while (inicial.status !== 'SUCCESS' && inicial.status !== 'FAILURE');
        if (inicial.status === 'FAILURE') return showToast('Hubo un error en el worker de Celery.', 'error');
        const r = inicial.result;
        if (r.status !== 'STARTED') return showToast(r.message || 'Error en tarea', r.status === 'NO_FILES' ? 'warning' : 'error');

        let grupo;
        do { await dormir(2000); grupo = await getJSON(`/estado-grupo/${r.task_group_id}/`); }
        while (grupo.status !== 'COMPLETED' && grupo.status !== 'FAILURE');
        if (grupo.status === 'FAILURE') return showToast('Falló el procesamiento de los recibos.', 'error');
        showToast(`¡Se procesaron ${r.total_tasks} recibos exitosamente!`, 'success');
        window.location.reload();
    });
}
