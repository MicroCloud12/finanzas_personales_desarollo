// Acciones de la tabla de presupuesto (buscar recibos, procesarlos, predecir) vía fetch + JSON.
function showToast(message, type = 'info', duracion = 5000) {
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
    setTimeout(() => toast.remove(), duracion);
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

// Predice lo que toca pagar el mes que entra; el servidor guarda el siguiente pago en el concepto.
// El toast se deja leer unos segundos antes de recargar la tabla con la columna "Próximo mes" actualizada.
function predecirRecibo(btn) {
    conSpinner(btn, '.icon-magia', '.icon-spinner-magia', 'Ocurrió un error al predecir el recibo.', async () => {
        const data = await getJSON(btn.dataset.url);
        if (data.error) return showToast(data.error, 'error', 9000);
        if (data.success) {
            showToast(data.mensaje || `Predicción: $${data.monto_predicho}${data.fecha_predicha ? ' · ' + data.fecha_predicha : ''}`, 'success', 9000);
            await dormir(3500);
            window.location.reload();
        }
    });
}

// Segundo clic mientras corre = cancelar (revoca el lote en Celery y deja listo el botón para volver a empezar).
async function cancelarRecibos(btn) {
    if (!confirm('¿Cancelar el procesamiento de recibos?')) return;
    const csrf = document.querySelector('input[name="csrfmiddlewaretoken"]');
    await fetch('/api/cancelar-procesamiento/', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf ? csrf.value : '', 'X-Requested-With': 'XMLHttpRequest' },
        body: JSON.stringify({ task_id: btn.dataset.taskId, group_id: btn.dataset.groupId || null, cancel_type: 'recibos' }),
    });
    btn.dataset.cancelado = '1';
}

function procesarRecibosAnteriores(btn) {
    if (btn.dataset.taskId) return cancelarRecibos(btn);
    const badge = btn.querySelector('.progreso-badge');
    const progreso = texto => { badge.textContent = texto; badge.classList.toggle('hidden', !texto); };
    const cancelado = () => btn.dataset.cancelado === '1';
    conSpinner(btn, '.icon-procesar', '.icon-spinner-procesar', 'Ocurrió un error al procesar los recibos.', async () => {
        const data = await getJSON(btn.dataset.url);
        if (data.error) return showToast(data.error, 'error');
        if (!data.task_id) return showToast(data.mensaje || 'Hecho', 'info');
        btn.dataset.taskId = data.task_id;
        btn.title = 'Procesando... clic para cancelar';

        // 1) la tarea lanzadora devuelve el id del grupo; 2) se espera a que el grupo termine
        let inicial;
        do { await dormir(2000); inicial = await getJSON(`/resultado-tarea-inicial/${data.task_id}/`); }
        while (!cancelado() && inicial.status !== 'SUCCESS' && inicial.status !== 'FAILURE');
        if (cancelado()) return showToast('Procesamiento cancelado.', 'warning');
        if (inicial.status === 'FAILURE') return showToast('Hubo un error en el worker de Celery.', 'error');
        const r = inicial.result;
        if (r.status !== 'STARTED') return showToast(r.message || 'Error en tarea', r.status === 'NO_FILES' ? 'warning' : 'error');
        btn.dataset.groupId = r.task_group_id;
        showToast(`Procesando ${r.total_tasks} recibo(s): un PDF tarda unos segundos, una foto hasta medio minuto. Puedes seguir usando la app.`, 'info');

        // Cada recibo espera unos segundos (límite de la API) más la lectura de la IA: si tarda más de un
        // minuto por recibo, el lote se quedó colgado y no tiene caso seguir esperando aquí.
        const limite = Date.now() + Math.max(5, r.total_tasks) * 60 * 1000;
        let grupo;
        do {
            await dormir(2000);
            grupo = await getJSON(`/estado-grupo/${r.task_group_id}/`);
            if (grupo.status === 'PROGRESS') progreso(`${grupo.completed}/${grupo.total}`);
        } while (!cancelado() && grupo.status !== 'COMPLETED' && grupo.status !== 'FAILURE' && Date.now() < limite);
        if (cancelado()) return showToast('Procesamiento cancelado.', 'warning');
        if (grupo.status === 'FAILURE') return showToast('Falló el procesamiento de los recibos.', 'error');
        if (grupo.status !== 'COMPLETED') {
            return showToast('Esto está tardando demasiado. Revisa que el worker de Celery esté corriendo; ' +
                             'si estaba colgado, vuelve a dar clic y elige cancelar para empezar de nuevo.', 'warning');
        }
        const fallidos = grupo.fallidos || 0;
        showToast(fallidos ? `Se procesaron ${r.total_tasks - fallidos} recibo(s); ${fallidos} con error (revisa el worker).`
                           : `¡Se procesaron ${r.total_tasks} recibo(s) exitosamente!`, fallidos ? 'warning' : 'success');
        window.location.reload();
    }).finally(() => {
        delete btn.dataset.taskId; delete btn.dataset.groupId; delete btn.dataset.cancelado;
        btn.title = 'Procesar recibos de Drive';
        progreso('');
    });
}
