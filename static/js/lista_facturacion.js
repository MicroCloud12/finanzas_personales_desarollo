function openModal(jsonData) {
    try {
        const scriptTag = document.getElementById(jsonData);
        let obj = null;
        if (scriptTag) {
            obj = JSON.parse(scriptTag.textContent);
        } else {
            console.error("No se encontró script con ID:", jsonData);
            return;
        }

        const container = document.getElementById('formattedContent');
        container.innerHTML = '';

        if (obj && typeof obj === 'object') {
            for (const [key, value] of Object.entries(obj)) {
                if (!value) continue;
                const div = document.createElement('div');
                div.className = "flex justify-between md:grid md:grid-cols-3 gap-4 pb-2";
                const dt = document.createElement('dt');
                dt.className = "text-sm font-medium text-gray-500 capitalize md:col-span-1";
                dt.textContent = key.replace(/_/g, ' ');
                const dd = document.createElement('dd');
                dd.className = "text-sm text-gray-900 font-semibold md:col-span-2 break-all text-right md:text-left";
                dd.textContent = value;
                div.appendChild(dt);
                div.appendChild(dd);
                container.appendChild(div);
            }
        } else {
            container.innerHTML = '<p class="text-sm text-gray-500">No hay datos estructurados disponibles.</p>';
        }
        document.getElementById('jsonModal').classList.remove('hidden');
    } catch (e) {
        console.error("Error modal:", e);
    }
}

function closeModal() {
    document.getElementById('jsonModal').classList.add('hidden');
}
