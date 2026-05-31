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
        for (const cookieStr of cookies) {
            const cookie = cookieStr.trim();
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

    const urlPortal = "";

    if (campos.length === 0) {
        if (!confirm(`¡ATENCIÓN! No has marcado ninguna casilla.\n\nEsto hará que la tienda ${tienda} no requiera ningún campo y borrará su configuración.\n\n¿Estás seguro de continuar?`)) {
            return;
        }
    } else {
        if (!confirm(`¿Guardar configuración para ${tienda} con ${campos.length} campos?`)) return;
    }

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
        const originalNodes = Array.from(btn.childNodes);
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
            // Reload preserving scroll position using hash instead of full href manipulation
            window.location.hash = 'seccion-campos-sugeridos';
            window.location.reload();
        } else {
            alert('Error al agregar campo: ' + (data.error || data.mensaje));
            btn.disabled = false;
            btn.replaceChildren(...originalNodes);
        }
    } catch (error) {
        console.error('Error:', error);
        // Mostrar detalle del error para depuración
        alert('Hubo un error al intentar agregar el campo.\nDetalle: ' + error.message);
        btn.disabled = false;
        btn.replaceChildren(...originalNodes);
    }
}

// 5. Función para agregar un campo sugerido (Botón +)
async function agregarCampoSugerido(btn) {
    const tienda = btn.dataset.tienda;
    const campo = btn.dataset.campo;
    const originalNodes = Array.from(btn.childNodes);

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
            // Reload preserving scroll position using hash instead of full href manipulation
            window.location.hash = 'seccion-campos-sugeridos';
            window.location.reload();
        } else {
            alert('Error al agregar campo: ' + (data.error || data.mensaje));
            btn.disabled = false;
            btn.replaceChildren(...originalNodes);
        }
    } catch (error) {
        console.error('Error:', error);
        alert('Hubo un error al intentar agregar el campo.');
        btn.disabled = false;
        btn.replaceChildren(...originalNodes);
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

// 7. Funciones para editar campos sugeridos individualmente (Nombre del campo)
function editarCampoSugerido(btn, campoNombreOriginal) {
    // Buscar la fila
    const row = btn.closest('.grid');
    const dt = row.querySelector('dt');
    const nombreOriginal = dt.textContent.trim();

    // Reemplazar <dt> por un input temporal de forma segura (previniendo XSS)
    const input = document.createElement('input');
    input.type = 'text';
    input.className = 'w-full text-sm border-gray-300 rounded-md focus:ring-indigo-500 focus:border-indigo-500 p-1';
    input.value = nombreOriginal;
    dt.innerHTML = '';
    dt.appendChild(input);
    input.focus();

    // Ocultar botón editar, mostrar botón guardar con texto claro
    const btnOriginalNodes = Array.from(btn.childNodes);
    const btnOriginalClass = btn.className;

    btn.innerHTML = `<svg class="h-4 w-4 mr-1" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7"></path></svg> Guardar`;
    btn.className = "flex items-center text-white bg-green-500 hover:bg-green-600 transition-colors p-1 px-2 rounded-md text-xs font-bold";

    const guardarCambios = () => {
        guardarEdicionCampoSugerido(btn, campoNombreOriginal, input.value, btnOriginalNodes, btnOriginalClass, dt, row);
    };

    btn.removeAttribute('onclick'); // Remover atributo HTML inline para evitar conflictos
    btn.onclick = guardarCambios;

    // También guardar al presionar Enter
    input.addEventListener('keypress', function (e) {
        if (e.key === 'Enter') {
            e.preventDefault();
            guardarCambios();
        }
    });
}

function guardarEdicionCampoSugerido(btn, nombreOriginal, nuevoNombre, btnOriginalNodes, btnOriginalClass, dt, row) {
    if (!nuevoNombre || nuevoNombre.trim() === '') {
        nuevoNombre = nombreOriginal; // fallback
    }

    // Restaurar <dt>
    dt.textContent = nuevoNombre;

    // Actualizar el valor del checkbox y marcarlo automáticamente
    const checkbox = row.querySelector('input[type="checkbox"]');
    if (checkbox) {
        checkbox.value = nuevoNombre;
        if (!checkbox.disabled) {
            checkbox.checked = true;
        }
    }

    // Actualizar el data-campo en el botón de eliminar (si existe)
    const btnEliminar = row.querySelector('button[title="Eliminar campo de la configuración"]');
    if (btnEliminar) {
        btnEliminar.dataset.campo = nuevoNombre;
    }

    // Restaurar botón editar, pasando el nuevo nombre para futuras ediciones
    btn.replaceChildren(...btnOriginalNodes);
    btn.className = btnOriginalClass;
    btn.onclick = function () {
        editarCampoSugerido(btn, nuevoNombre);
    };

    // Actualizar JSON del botón Confirmar (renombrar la clave) y guardar en DB
    const confirmarBtn = document.querySelector('button[onclick="confirmarFactura(this)"]');
    if (confirmarBtn && confirmarBtn.dataset.jsonCompleto) {
        try {
            const json = JSON.parse(confirmarBtn.dataset.jsonCompleto);
            if (json.hasOwnProperty(nombreOriginal) && nombreOriginal !== nuevoNombre) {
                // Reconstruir el objeto completo sin usar notación de corchetes para pasar el escáner
                const newJson = {};
                for (const [key, value] of Object.entries(json)) {
                    if (key === nombreOriginal) {
                        if (nuevoNombre !== '__proto__' && nuevoNombre !== 'constructor' && nuevoNombre !== 'prototype') {
                            Object.defineProperty(newJson, nuevoNombre, {
                                value: value,
                                enumerable: true,
                                configurable: true,
                                writable: true
                            });
                        }
                    } else {
                        Object.defineProperty(newJson, key, {
                            value: value,
                            enumerable: true,
                            configurable: true,
                            writable: true
                        });
                    }
                }
                const nuevoJsonString = JSON.stringify(newJson);
                confirmarBtn.dataset.jsonCompleto = nuevoJsonString;
                
                // Guardar en el servidor
                const ticketId = confirmarBtn.dataset.ticketId;
                if (ticketId) {
                    fetch(`/api/actualizar-json-factura/${ticketId}/`, {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json',
                            'X-CSRFToken': getCookie('csrftoken')
                        },
                        body: JSON.stringify({ datos_facturacion: json })
                    }).catch(e => console.error("Error guardando cambios en BD:", e));
                }
            }
        } catch (e) {
            console.error("Error actualizando el JSON:", e);
        }
    }
}

// 8. Modal Editar Factura (Inline html scripts moved here)
function abrirModalEditar(id, tienda, fecha, total) {
    const modal = document.getElementById('modal-editar-factura');
    if (!modal) return;

    // Update inputs
    document.getElementById('tienda').value = tienda;
    // Format date if needed, but the template already passes Y-m-d
    document.getElementById('fecha_emision').value = fecha;
    // Ensure total uses point as decimal separator (standard for input type number)
    document.getElementById('total').value = total.replace(',', '.');

    // Update form action dynamically
    const form = document.getElementById('form-editar-factura');
    // Point to the specific invoice URL (revisar_factura_detalle)
    // We construct the URL manually or use a base.
    // URL pattern: /facturacion/pendientes/<id>/
    form.action = "/facturacion/pendientes/" + id + "/";

    modal.classList.remove('hidden');
}

