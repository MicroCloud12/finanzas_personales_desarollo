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
            alert(data.error);
        } else if (data.cantidad !== undefined) {
            badge.textContent = data.cantidad;
            badge.classList.remove('hidden');
        }
    })
    .catch(error => {
        iconSpinner.classList.add('hidden');
        iconLupa.classList.remove('hidden');
        alert("Ocurrió un error al buscar recibos.");
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
            alert(data.error);
        } else if (data.success) {
            let mensaje = `¡Predicción generada!\n\nMonto estimado: $${data.monto_predicho}\n`;
            if (data.fecha_predicha) {
                mensaje += `Fecha estimada: ${data.fecha_predicha}\n`;
            }
            mensaje += `Razonamiento: ${data.razonamiento}`;
            alert(mensaje);
            // Recargar la página para que se vea el nuevo presupuesto
            window.location.reload();
        }
    })
    .catch(error => {
        iconSpinner.classList.add('hidden');
        iconMagia.classList.remove('hidden');
        alert("Ocurrió un error al predecir el recibo. Esto puede tardar si hay muchos recibos.");
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
            alert(data.error);
        } else if (data.task_id) {
            // Empezar a sondear la tarea inicial
            checkInitialTask(data.task_id);
        } else {
            iconSpinner.classList.add('hidden');
            iconProcesar.classList.remove('hidden');
            alert(data.mensaje || "Hecho");
        }
    })
    .catch(error => {
        iconSpinner.classList.add('hidden');
        iconProcesar.classList.remove('hidden');
        alert("Ocurrió un error al procesar los recibos.");
        console.error(error);
    });

    function checkInitialTask(taskId) {
        fetch(`/resultado-tarea-inicial/${taskId}/`)
        .then(res => res.json())
        .then(data => {
            if (data.status === 'SUCCESS') {
                const result = data.result;
                if (result.status === 'STARTED') {
                    // La tarea inicial preparó el grupo, ahora sondeamos el grupo
                    checkGroupTask(result.task_group_id, result.total_tasks);
                } else if (result.status === 'NO_FILES') {
                    iconSpinner.classList.add('hidden');
                    iconProcesar.classList.remove('hidden');
                    alert(result.message);
                } else {
                    iconSpinner.classList.add('hidden');
                    iconProcesar.classList.remove('hidden');
                    alert(result.message || 'Error en tarea');
                }
            } else if (data.status === 'FAILURE') {
                iconSpinner.classList.add('hidden');
                iconProcesar.classList.remove('hidden');
                alert("Hubo un error en el worker de Celery.");
            } else {
                // status === 'PENDING'
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
                alert(`¡Se procesaron ${totalTasks} recibos exitosamente!`);
                window.location.reload();
            } else {
                // status === 'PROGRESS' o 'PENDING'
                setTimeout(() => checkGroupTask(groupId, totalTasks), 2000);
            }
        }).catch(err => {
            console.error(err);
            setTimeout(() => checkGroupTask(groupId, totalTasks), 2000);
        });
    }
}
