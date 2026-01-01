document.addEventListener('DOMContentLoaded', function () {
    const startBtn = document.getElementById('start-processing-btn');
    if (!startBtn) return;
    const progressContainer = document.getElementById('progress-container');
    const progressText = document.getElementById('progress-text');
    const progressPercent = document.getElementById('progress-percent');
    const progressBar = document.getElementById('progress-bar');
    let pollingInterval;

    startBtn.addEventListener('click', async function () {
        startBtn.disabled = true;
        progressContainer.classList.remove('hidden');
        updateProgress(0, "Iniciando...", 'bg-indigo-600');

        try {
            const startUrl = startBtn.dataset.startUrl;
            const redirectUrl = startBtn.dataset.redirectUrl;

            const initialResponse = await fetch(startUrl);
            const initialData = await initialResponse.json();
            const initialTaskId = initialData.task_id;

            updateProgress(15, "Buscando tickets...");
            const groupId = await waitForGroupId(initialTaskId);

            updateProgress(25, "Procesando tickets...");
            await monitorGroupProgress(groupId);

            updateProgress(100, "¡Proceso completado!", 'bg-green-500');
            setTimeout(() => {
                window.location.href = redirectUrl;
            }, 1500);

        } catch (error) {
            handleError(error.message);
        }
    });

    async function waitForGroupId(taskId) {
        while (true) {
            await sleep(2500);
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
    }

    async function monitorGroupProgress(groupId) {
        while (true) {
            await sleep(2500);
            const response = await fetch(`/estado-grupo/${groupId}/`);
            const data = await response.json();

            if (data.status === 'COMPLETED') {
                return;
            } else if (data.status === 'PROGRESS') {
                updateProgress(data.progress, `Procesando... ${data.completed} de ${data.total} lotes listos.`);
            } else if (data.status === 'FAILURE') {
                throw new Error(`El procesamiento del grupo falló: ${data.info}`);
            }
        }
    }

    function sleep(ms) { return new Promise(resolve => setTimeout(resolve, ms)); }

    function updateProgress(percentage, text, color = 'bg-indigo-600') {
        progressBar.style.width = `${percentage}%`;
        // Removed text injection into the bar itself to fix duplicate % and layout issues
        progressBar.textContent = '';
        // Update the external percentage text
        if (progressPercent) progressPercent.textContent = `${percentage}%`;

        // Preserve layout classes (h-2.5, rounded-full, transitions) and only switch color
        progressBar.className = `h-2.5 rounded-full transition-all duration-300 ease-out ${color}`;
        progressText.textContent = text;
    }

    function handleError(message) {
        if (pollingInterval) clearInterval(pollingInterval);
        console.error("Error:", message);
        updateProgress(100, `Error: ${message}`, 'bg-red-500');
        startBtn.disabled = false;
    }
});

// finanzas/static/js/procesamiento.js

// 1. Obtener el token CSRF (Necesario para seguridad en Django)
function getCookie(name) {
    let cookieValue = null;
    if (document.cookie && document.cookie !== '') {
        const cookies = document.cookie.split(';');
        for (let i = 0; i < cookies.length; i++) {
            const cookie = cookies[i].trim();
            if (cookie.substring(0, name.length + 1) === (name + '=')) {
                cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
                break;
            }
        }
    }
    return cookieValue;
}

// 2. Función para el botón "Guardar Configuración" (Disquete)
async function guardarConfiguracion(btn) {
    console.log("guardarConfiguracion function triggered");
    // Obtenemos los datos desde los atributos data- del botón HTML
    const tienda = btn.dataset.tienda;
    // Buscamos los checkboxes marcados dentro de la sección de campos sugeridos
    const container = document.getElementById('seccion-campos-sugeridos');
    if (!container) {
        alert("Error: No se encontró la sección de campos para guardar.");
        return;
    }
    const inputs = container.querySelectorAll('input[type="checkbox"]:checked');
    const campos = Array.from(inputs).map(input => input.value);

    // Removed prompt as requested
    const urlPortal = "";

    if (!confirm(`¿Guardar configuración para ${tienda} con ${campos.length} campos?`)) return;

    try {
        const response = await fetch('/api/guardar-config-tienda/', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': getCookie('csrftoken')
            },
            body: JSON.stringify({
                tienda: tienda,
                campos_seleccionados: campos,
                url_portal: urlPortal
            })
        });

        if (!response.ok) {
            const errorText = await response.text();
            throw new Error(`Server returned ${response.status}: ${errorText}`);
        }

        const data = await response.json();
        if (data.status === 'success') {
            alert(data.message);
            window.location.reload();
        } else {
            alert('Error del servidor: ' + data.message);
        }

    } catch (error) {
        console.error('Error al guardar configuración:', error);
        alert('Hubo un error al guardar la configuración. Revisa la consola para más detalles.');
    }
}

// 3. Función para el botón "Confirmar Factura" (Paloma)
async function confirmarFactura(btn) {
    // Leemos TODOS los datos que pusimos en el botón en el HTML
    const payload = {
        archivo_id: btn.dataset.archivoId,
        tienda: btn.dataset.tienda,
        total: btn.dataset.total,
        fecha: btn.dataset.fecha,
        // El JSON completo de datos extraídos lo pasamos como string en el HTML y aquí lo parseamos de vuelta
        datos_facturacion: JSON.parse(btn.dataset.jsonCompleto)
    };

    try {
        const response = await fetch('/api/confirmar-factura/', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': getCookie('csrftoken')
            },
            body: JSON.stringify(payload)
        });

        const data = await response.json();
        if (data.status === 'success') {
            alert("¡Factura guardada! Ya puedes verla en tu lista.");
            // Opcional: Ocultar la tarjeta del ticket procesado visualmente
            btn.closest('.card').remove();
        } else {
            alert("Error: " + data.message);
        }
    } catch (error) {
        console.error('Error:', error);
        alert('Error de conexión.');
    }
}

// 4. Función para agregar un nuevo campo a la tienda
// 4. Función para agregar un nuevo campo a la tienda (INLINE - Refined)
async function agregarCampoInline(btn) {
    const tienda = btn.dataset.tienda;

    // El input está en el contenedor hermano (col-span-11).
    // Modificación robusta: Usar ID directo en lugar de traversing relativo
    // El input tiene el ID "nuevo-campo-input"
    const inputField = document.getElementById('nuevo-campo-input');

    if (!inputField) {
        console.error("No se encontró el input con id: nuevo-campo-input");
        return;
    }

    const nombreCampo = inputField.value;

    if (!nombreCampo || nombreCampo.trim() === "") {
        // Visual cue for empty input error? For now, just focus it.
        inputField.focus();
        inputField.classList.add('ring-2', 'ring-red-300');
        setTimeout(() => inputField.classList.remove('ring-2', 'ring-red-300'), 1500);
        return;
    }

    try {
        // Disable button to prevent double submission
        btn.disabled = true;
        const originalIcon = btn.innerHTML;
        // Simple spinner or just opacity change
        btn.innerHTML = `<svg class="animate-spin h-5 w-5 text-indigo-600" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
          <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
          <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
        </svg>`;

        const response = await fetch('/api/agregar-campo-tienda/', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': getCookie('csrftoken')
            },
            body: JSON.stringify({
                tienda: tienda,
                campo: nombreCampo.trim()
            })
        });

        const data = await response.json();

        if (data.success) {
            // Reload preserving scroll position
            window.location.href = window.location.pathname + window.location.search + '#seccion-campos-sugeridos';
            window.location.reload();
        } else {
            alert('Error al agregar campo: ' + (data.error || data.mensaje));
            btn.disabled = false;
            btn.innerHTML = originalIcon;
        }
    } catch (error) {
        console.error('Error:', error);
        // Mostrar detalle del error para depuración
        alert('Hubo un error al intentar agregar el campo.\nDetalle: ' + error.message);
        btn.disabled = false;
    }
}

// 5. Función para agregar un campo sugerido (Botón +)
async function agregarCampoSugerido(btn) {
    const tienda = btn.dataset.tienda;
    const campo = btn.dataset.campo;
    const originalIcon = btn.innerHTML;

    try {
        btn.disabled = true;
        // Simple spinner
        btn.innerHTML = `<svg class="animate-spin h-3 w-3 text-indigo-500" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
          <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
          <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
        </svg>`;

        const response = await fetch('/api/agregar-campo-tienda/', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': getCookie('csrftoken')
            },
            body: JSON.stringify({
                tienda: tienda,
                campo: campo
            })
        });

        const data = await response.json();

        if (data.success) {
            // Reload preserving scroll position
            window.location.href = window.location.pathname + window.location.search + '#seccion-campos-sugeridos';
            window.location.reload();
        } else {
            alert('Error al agregar campo: ' + (data.error || data.mensaje));
            btn.disabled = false;
            btn.innerHTML = originalIcon;
        }
    } catch (error) {
        console.error('Error:', error);
        alert('Hubo un error al intentar agregar el campo.');
        btn.disabled = false;
        btn.innerHTML = originalIcon;
    }
}

// 6. Función para ELIMINAR un campo de la configuración (Trash Icon)
async function eliminarCampoConfigurado(btn) {
    const tienda = btn.dataset.tienda;
    const nombreCampo = btn.dataset.campo;

    if (!confirm(`¿Estás seguro de que quieres dejar de solicitar el campo "${nombreCampo}" para ${tienda}?`)) {
        return;
    }

    try {
        btn.disabled = true;
        // Optional spin processing styling if needed, but simple disable is likely enough for delete

        const response = await fetch('/api/eliminar-campo-tienda/', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': getCookie('csrftoken')
            },
            body: JSON.stringify({
                tienda: tienda,
                campo: nombreCampo
            })
        });

        const data = await response.json();

        if (data.success) {
            window.location.reload();
        } else {
            alert('Error al eliminar campo: ' + (data.error || data.mensaje));
            btn.disabled = false;
        }
    } catch (error) {
        console.error('Error:', error);
        alert('Hubo un error al intentar eliminar el campo.\nDetalle: ' + error.message);
        btn.disabled = false;
    }
}

