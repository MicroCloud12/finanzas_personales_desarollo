document.addEventListener('DOMContentLoaded', function () {
    const startBtn = document.getElementById('start-processing-btn');
    if (!startBtn) return;
    const progressContainer = document.getElementById('progress-container');
    const progressText = document.getElementById('progress-text');
    const progressBar = document.getElementById('progress-bar');
    let pollingInterval;

    startBtn.addEventListener('click', async function() {
        startBtn.disabled = true;
        progressContainer.classList.remove('hidden');
        updateProgress(0, "Iniciando...", 'bg-blue-500');

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

    function updateProgress(percentage, text, color = 'bg-blue-500') {
        progressBar.style.width = `${percentage}%`;
        progressBar.textContent = `${percentage}%`;
        progressBar.className = `text-xs font-medium text-blue-100 text-center p-0.5 leading-none rounded-full ${color}`;
        progressText.textContent = text;
    }

    function handleError(message) {
        if (pollingInterval) clearInterval(pollingInterval);
        console.error("Error:", message);
        updateProgress(100, `Error: ${message}`, 'bg-red-500');
        startBtn.disabled = false;
    }
});