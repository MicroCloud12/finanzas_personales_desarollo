// --- Utils & Constants ---
const SPINNER_SVG = `<svg class="animate-spin h-4 w-4 text-current" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24"><circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle><path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path></svg>`;

function getCookie(name) {
    let cookieValue = null;
    if (document.cookie && document.cookie !== '') {
        const cookies = document.cookie.split(';');
        for (const cookieStr of cookies) {
            const cookie = cookieStr.trim();
            if (cookie.startsWith(name + '=')) {
                cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
                break;
            }
        }
    }
    return cookieValue;
}

async function apiFetch(url, payload) {
    const response = await fetch(url, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': getCookie('csrftoken')
        },
        body: JSON.stringify(payload)
    });
    
    if (!response.ok) {
        throw new Error(`Error en el servidor: ${response.status}`);
    }
    return response.json();
}

function showLoading(btn, spinnerSize = 'h-5 w-5') {
    const originalContent = Array.from(btn.childNodes);
    const originalClass = btn.className;
    btn.disabled = true;
    btn.innerHTML = SPINNER_SVG.replace('h-4 w-4', spinnerSize);
    return () => {
        btn.disabled = false;
        btn.replaceChildren(...originalContent);
        btn.className = originalClass;
    };
}

// --- Background Task Processor (DOMContentLoaded) ---
document.addEventListener('DOMContentLoaded', () => {
    initTaskProcessor();
});

function initTaskProcessor() {
    const startBtn = document.getElementById('start-processing-btn');
    const cancelBtn = document.getElementById('cancel-processing-btn');
    const progressContainer = document.getElementById('progress-container');
    const progressBar = document.getElementById('progress-bar');
    const progressText = document.getElementById('progress-text');
    const progressPercent = document.getElementById('progress-percent');
    
    if (!startBtn) return;

    let cancelRequested = false;
    let currentTaskId = null;
    let currentGroupId = null;
    let sleepResolver = null;
    let sleepTimer = null;

    const sleep = (ms) => new Promise(resolve => {
        sleepResolver = resolve;
        sleepTimer = setTimeout(() => {
            sleepResolver = null;
            resolve();
        }, ms);
    });

    const wakeUpEarly = () => {
        if (sleepTimer) clearTimeout(sleepTimer);
        if (sleepResolver) sleepResolver();
    };

    const updateUIProgress = (percentage, text, colorClass = 'bg-indigo-600') => {
        progressBar.style.width = `${percentage}%`;
        progressBar.className = `h-2.5 rounded-full transition-all duration-300 ease-out ${colorClass}`;
        progressText.textContent = text;
        if (progressPercent) progressPercent.textContent = `${percentage}%`;
    };

    const handleTaskError = (message) => {
        console.error("Task Error:", message);
        updateUIProgress(100, `Error: ${message}`, 'bg-red-500');
        startBtn.disabled = false;
        if (cancelBtn) cancelBtn.classList.add('hidden');
    };

    const waitForGroupId = async (taskId) => {
        while (true) {
            if (cancelRequested) throw new Error("UserCancelled");
            await sleep(2500);
            if (cancelRequested) throw new Error("UserCancelled");
            
            const response = await fetch(`/resultado-tarea-inicial/${taskId}/`);
            const data = await response.json();

            if (data.status === 'SUCCESS') {
                const result = data.result;
                if (result.status === 'STARTED') return result.task_group_id;
                if (result.status === 'NO_FILES') throw new Error("No se encontraron nuevos tickets.");
                throw new Error("Respuesta inesperada de la tarea inicial.");
            } else if (data.status === 'FAILURE') {
                throw new Error(`Tarea inicial falló: ${data.info}`);
            }
        }
    };

    const monitorGroupProgress = async (groupId) => {
        while (true) {
            if (cancelRequested) throw new Error("UserCancelled");
            await sleep(2500);
            if (cancelRequested) throw new Error("UserCancelled");
            
            const response = await fetch(`/estado-grupo/${groupId}/`);
            const data = await response.json();

            if (data.status === 'COMPLETED') return;
            if (data.status === 'PROGRESS') {
                updateUIProgress(data.progress, `Procesando... ${data.completed} de ${data.total} lotes listos.`);
            } else if (data.status === 'FAILURE') {
                throw new Error(`El procesamiento del grupo falló: ${data.info}`);
            }
        }
    };

    startBtn.addEventListener('click', async () => {
        startBtn.disabled = true;
        cancelRequested = false;
        currentTaskId = null;
        currentGroupId = null;
        
        progressContainer.classList.remove('hidden');
        if (cancelBtn) cancelBtn.classList.remove('hidden');
        
        updateUIProgress(0, "Iniciando...", 'bg-indigo-600');

        try {
            const initialResponse = await fetch(startBtn.dataset.startUrl);
            const initialData = await initialResponse.json();
            currentTaskId = initialData.task_id;

            updateUIProgress(15, "Buscando tickets...");
            currentGroupId = await waitForGroupId(currentTaskId);

            updateUIProgress(25, "Procesando tickets...");
            await monitorGroupProgress(currentGroupId);

            if (!cancelRequested) {
                updateUIProgress(100, "¡Proceso completado!", 'bg-green-500');
                if (cancelBtn) cancelBtn.classList.add('hidden');
                setTimeout(() => window.location.href = startBtn.dataset.redirectUrl, 1500);
            }
        } catch (error) {
            if (error.message === "UserCancelled") {
                updateUIProgress(100, "Proceso Cancelado", 'bg-yellow-500');
                startBtn.disabled = false;
                if (cancelBtn) {
                    cancelBtn.classList.add('hidden');
                    cancelBtn.innerText = "Cancelar Procesamiento";
                    cancelBtn.disabled = false;
                }
            } else {
                handleTaskError(error.message);
            }
        }
    });

    if (cancelBtn) {
        cancelBtn.addEventListener('click', () => {
            cancelRequested = true;
            cancelBtn.disabled = true;
            cancelBtn.innerText = "Cancelando...";
            wakeUpEarly();

            let cancelType = 'tickets';
            const startUrl = startBtn.dataset.startUrl || '';
            if (startUrl.includes('inversiones')) cancelType = 'inversiones';
            else if (startUrl.includes('deudas')) cancelType = 'deudas';
            else if (startUrl.includes('factura')) cancelType = 'facturas';

            apiFetch('/api/cancelar-procesamiento/', {
                task_id: currentTaskId,
                group_id: currentGroupId,
                cancel_type: cancelType
            }).catch(e => console.error("Error al cancelar en servidor", e));
        });
    }
}

// --- Global UI Actions ---

async function guardarConfiguracion(btn) {
    const tienda = btn.dataset.tienda;
    const container = document.getElementById('seccion-campos-sugeridos');
    
    if (!container) {
        alert("Error: No se encontró la sección de campos para guardar.");
        return;
    }

    const selectedInputs = container.querySelectorAll('input[type="checkbox"]:checked');
    const campos = Array.from(selectedInputs).map(input => input.value);

    if (campos.length === 0) {
        if (!confirm(`¡ATENCIÓN! No has marcado ninguna casilla.\nEsto hará que la tienda ${tienda} no requiera ningún campo y borrará su configuración.\n¿Estás seguro?`)) return;
    } else {
        if (!confirm(`¿Guardar configuración para ${tienda} con ${campos.length} campos?`)) return;
    }

    try {
        const data = await apiFetch('/api/guardar-config-tienda/', {
            tienda,
            campos_seleccionados: campos,
            url_portal: ""
        });

        if (data.status === 'success') {
            alert(data.message);
            window.location.reload();
        } else {
            alert('Error del servidor: ' + data.message);
        }
    } catch (error) {
        console.error('Error:', error);
        alert('Hubo un error al guardar la configuración.');
    }
}

async function confirmarFactura(btn) {
    const payload = {
        archivo_id: btn.dataset.archivoId,
        tienda: btn.dataset.tienda,
        total: btn.dataset.total,
        fecha: btn.dataset.fecha,
        datos_facturacion: JSON.parse(btn.dataset.jsonCompleto)
    };

    try {
        const data = await apiFetch('/api/confirmar-factura/', payload);
        if (data.status === 'success') {
            alert("¡Factura guardada! Ya puedes verla en tu lista.");
            const card = btn.closest('.card');
            if (card) card.remove();
        } else {
            alert("Error: " + data.message);
        }
    } catch (error) {
        console.error('Error:', error);
        alert('Error de conexión.');
    }
}

async function agregarCampoInline(btn) {
    const inputField = document.getElementById('nuevo-campo-input');
    if (!inputField) return;

    const nombreCampo = inputField.value.trim();
    if (!nombreCampo) {
        inputField.focus();
        inputField.classList.add('ring-2', 'ring-red-300');
        setTimeout(() => inputField.classList.remove('ring-2', 'ring-red-300'), 1500);
        return;
    }

    const restoreBtn = showLoading(btn, 'h-5 w-5');
    
    try {
        const data = await apiFetch('/api/agregar-campo-tienda/', {
            tienda: btn.dataset.tienda,
            campo: nombreCampo
        });

        if (data.success) {
            window.location.hash = 'seccion-campos-sugeridos';
            window.location.reload();
        } else {
            alert('Error al agregar campo: ' + (data.error || data.mensaje));
            restoreBtn();
        }
    } catch (error) {
        console.error('Error:', error);
        alert('Hubo un error al intentar agregar el campo.');
        restoreBtn();
    }
}

async function agregarCampoSugerido(btn) {
    const restoreBtn = showLoading(btn, 'h-3 w-3');

    try {
        const data = await apiFetch('/api/agregar-campo-tienda/', {
            tienda: btn.dataset.tienda,
            campo: btn.dataset.campo
        });

        if (data.success) {
            window.location.hash = 'seccion-campos-sugeridos';
            window.location.reload();
        } else {
            alert('Error al agregar campo: ' + (data.error || data.mensaje));
            restoreBtn();
        }
    } catch (error) {
        console.error('Error:', error);
        alert('Hubo un error al intentar agregar el campo.');
        restoreBtn();
    }
}

async function eliminarCampoConfigurado(btn) {
    const { tienda, campo } = btn.dataset;

    if (!confirm(`¿Estás seguro de que quieres eliminar el campo "${campo}" de ${tienda}?`)) return;

    btn.disabled = true;

    try {
        const data = await apiFetch('/api/eliminar-campo-tienda/', { tienda, campo });
        if (data.success) {
            window.location.reload();
        } else {
            alert('Error al eliminar campo: ' + (data.error || data.mensaje));
            btn.disabled = false;
        }
    } catch (error) {
        console.error('Error:', error);
        alert('Hubo un error al intentar eliminar el campo.');
        btn.disabled = false;
    }
}

function editarCampoSugerido(btn, nombreOriginal) {
    const row = btn.closest('.grid');
    const dt = row.querySelector('dt');
    
    const input = document.createElement('input');
    input.type = 'text';
    input.className = 'w-full text-sm border-gray-300 rounded-md focus:ring-indigo-500 focus:border-indigo-500 p-1';
    input.value = dt.textContent.trim();
    
    dt.replaceChildren(input);
    input.focus();

    const originalHTML = btn.innerHTML;
    const originalClass = btn.className;

    btn.innerHTML = `<svg class="h-4 w-4 mr-1" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7"></path></svg> Guardar`;
    btn.className = "flex items-center text-white bg-green-500 hover:bg-green-600 transition-colors p-1 px-2 rounded-md text-xs font-bold";

    const triggerSave = () => {
        guardarEdicionCampoSugerido(btn, nombreOriginal, input.value, originalHTML, originalClass, dt, row);
    };

    btn.removeAttribute('onclick');
    btn.onclick = triggerSave;

    input.addEventListener('keypress', (e) => {
        if (e.key === 'Enter') {
            e.preventDefault();
            triggerSave();
        }
    });
}

function guardarEdicionCampoSugerido(btn, nombreOriginal, nuevoNombre, originalHTML, originalClass, dt, row) {
    const nombreFinal = (nuevoNombre || '').trim() || nombreOriginal;
    dt.textContent = nombreFinal;

    const checkbox = row.querySelector('input[type="checkbox"]');
    if (checkbox) {
        checkbox.value = nombreFinal;
        if (!checkbox.disabled) checkbox.checked = true;
    }

    const btnEliminar = row.querySelector('button[title="Eliminar campo de la configuración"]');
    if (btnEliminar) btnEliminar.dataset.campo = nombreFinal;

    btn.innerHTML = originalHTML;
    btn.className = originalClass;
    btn.onclick = () => editarCampoSugerido(btn, nombreFinal);

    actualizarJsonConfirmarFactura(nombreOriginal, nombreFinal);
}

function actualizarJsonConfirmarFactura(nombreOriginal, nombreNuevo) {
    const confirmarBtn = document.querySelector('button[onclick*="confirmarFactura"]');
    if (!confirmarBtn || !confirmarBtn.dataset.jsonCompleto) return;

    try {
        const json = JSON.parse(confirmarBtn.dataset.jsonCompleto);
        if (json.hasOwnProperty(nombreOriginal) && nombreOriginal !== nombreNuevo) {
            
            const newJson = {};
            for (const [key, value] of Object.entries(json)) {
                const targetKey = (key === nombreOriginal) ? nombreNuevo : key;
                if (!['__proto__', 'constructor', 'prototype'].includes(targetKey)) {
                    Object.defineProperty(newJson, targetKey, {
                        value, enumerable: true, configurable: true, writable: true
                    });
                }
            }

            confirmarBtn.dataset.jsonCompleto = JSON.stringify(newJson);

            const ticketId = confirmarBtn.dataset.ticketId;
            if (ticketId) {
                apiFetch(`/api/actualizar-json-factura/${ticketId}/`, { datos_facturacion: newJson })
                    .catch(e => console.error("Error guardando cambios en BD:", e));
            }
        }
    } catch (e) {
        console.error("Error actualizando el JSON:", e);
    }
}

function abrirModalEditar(id, tienda, fecha, total) {
    const modal = document.getElementById('modal-editar-factura');
    if (!modal) return;

    document.getElementById('tienda').value = tienda;
    document.getElementById('fecha_emision').value = fecha;
    document.getElementById('total').value = String(total).replace(',', '.');

    const form = document.getElementById('form-editar-factura');
    if (form) form.action = `/facturacion/pendientes/${id}/`;

    modal.classList.remove('hidden');
}
