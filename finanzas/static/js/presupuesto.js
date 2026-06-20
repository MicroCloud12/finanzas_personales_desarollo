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
    toast.innerHTML = `<div class="pl-2 text-sm font-semibold">${message}</div>`;
    container.appendChild(toast);
    setTimeout(() => toast.remove(), 5000);
}

function buscarRecibos(btn, presupuestoId) {
    const url = btn.dataset.url;
    const iconLupa = btn.querySelector('.icon-lupa');
    const iconSpinner = btn.querySelector('.icon-spinner');
    const badge = btn.querySelector('.resultado-badge');

    iconLupa.classList.add('hidden');
    iconSpinner.classList.remove('hidden');
    badge.classList.add('hidden');

    fetch(url, {
        headers: {
            'X-Requested-With': 'XMLHttpRequest',
            'Accept': 'application/json'
        }
    })
    .then(response => response.json())
    .then(data => {
        iconSpinner.classList.add('hidden');
        iconLupa.classList.remove('hidden');

        if (data.error) {
            showToast(data.error, 'error');
        } else if (data.cantidad !== undefined) {
            badge.textContent = data.cantidad;
            badge.classList.remove('hidden');
        }
    })
    .catch(error => {
        iconSpinner.classList.add('hidden');
        iconLupa.classList.remove('hidden');
        showToast("Ocurrió un error al buscar recibos.", 'error');
        console.error(error);
    });
}

function predecirRecibo(btn, presupuestoId) {
    const url = btn.dataset.url;
    const iconMagia = btn.querySelector('.icon-magia');
    const iconSpinner = btn.querySelector('.icon-spinner-magia');

    iconMagia.classList.add('hidden');
    iconSpinner.classList.remove('hidden');

    fetch(url, {
        headers: {
            'X-Requested-With': 'XMLHttpRequest',
            'Accept': 'application/json'
        }
    })
    .then(response => response.json())
    .then(data => {
        iconSpinner.classList.add('hidden');
        iconMagia.classList.remove('hidden');

        if (data.error) {
            showToast(data.error, 'error');
        } else if (data.success) {
            showToast(`Predicción: $${data.monto_predicho}${data.fecha_predicha ? ' · ' + data.fecha_predicha : ''}`, 'success');
            window.location.reload();
        }
    })
    .catch(error => {
        iconSpinner.classList.add('hidden');
        iconMagia.classList.remove('hidden');
        showToast("Ocurrió un error al predecir el recibo.", 'error');
        console.error(error);
    });
}

function procesarRecibosAnteriores(btn, presupuestoId) {
    const url = btn.dataset.url;
    const iconProcesar = btn.querySelector('.icon-procesar');
    const iconSpinner = btn.querySelector('.icon-spinner-procesar');

    iconProcesar.classList.add('hidden');
    iconSpinner.classList.remove('hidden');

    fetch(url, {
        headers: {
            'X-Requested-With': 'XMLHttpRequest',
            'Accept': 'application/json'
        }
    })
    .then(response => response.json())
    .then(data => {
        if (data.error) {
            iconSpinner.classList.add('hidden');
            iconProcesar.classList.remove('hidden');
            showToast(data.error, 'error');
        } else if (data.task_id) {
            checkInitialTask(data.task_id);
        } else {
            iconSpinner.classList.add('hidden');
            iconProcesar.classList.remove('hidden');
            showToast(data.mensaje || "Hecho", 'info');
        }
    })
    .catch(error => {
        iconSpinner.classList.add('hidden');
        iconProcesar.classList.remove('hidden');
        showToast("Ocurrió un error al procesar los recibos.", 'error');
        console.error(error);
    });

    function checkInitialTask(taskId) {
        fetch(`/resultado-tarea-inicial/${taskId}/`)
        .then(res => res.json())
        .then(data => {
            if (data.status === 'SUCCESS') {
                const result = data.result;
                if (result.status === 'STARTED') {
                    checkGroupTask(result.task_group_id, result.total_tasks);
                } else if (result.status === 'NO_FILES') {
                    iconSpinner.classList.add('hidden');
                    iconProcesar.classList.remove('hidden');
                    showToast(result.message, 'warning');
                } else {
                    iconSpinner.classList.add('hidden');
                    iconProcesar.classList.remove('hidden');
                    showToast(result.message || 'Error en tarea', 'error');
                }
            } else if (data.status === 'FAILURE') {
                iconSpinner.classList.add('hidden');
                iconProcesar.classList.remove('hidden');
                showToast("Hubo un error en el worker de Celery.", 'error');
            } else {
                setTimeout(() => checkInitialTask(taskId), 2000);
            }
        }).catch(err => {
            console.error(err);
            setTimeout(() => checkInitialTask(taskId), 2000);
        });
    }

    function checkGroupTask(groupId, totalTasks) {
        fetch(`/estado-grupo/${groupId}/`)
        .then(res => res.json())
        .then(data => {
            if (data.status === 'COMPLETED') {
                iconSpinner.classList.add('hidden');
                iconProcesar.classList.remove('hidden');
                showToast(`¡Se procesaron ${totalTasks} recibos exitosamente!`, 'success');
                window.location.reload();
            } else {
                setTimeout(() => checkGroupTask(groupId, totalTasks), 2000);
            }
        }).catch(err => {
            console.error(err);
            setTimeout(() => checkGroupTask(groupId, totalTasks), 2000);
        });
    }
}
