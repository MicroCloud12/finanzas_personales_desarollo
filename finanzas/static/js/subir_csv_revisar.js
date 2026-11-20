// Pantalla "Revisar antes de guardar" (subir_csv_revisar.html): contador de marcados y marcar/desmarcar todos.
(function () {
    const cajas = document.querySelectorAll('input.fila');
    const contador = document.getElementById('n-marcados');
    const todos = document.getElementById('marcar-todos');
    if (!contador || !todos) return;

    function actualizar() {
        contador.textContent = [...cajas].filter(c => c.checked).length;
    }
    cajas.forEach(c => c.addEventListener('change', actualizar));
    // "Convertir el que ya tienes": el movimiento ya existe, así que la fila no se guarda además.
    document.querySelectorAll('input[name="ajustar"]').forEach(a => a.addEventListener('change', e => {
        const fila = e.target.closest('tr').querySelector('input.fila');
        if (e.target.checked && fila) { fila.checked = false; actualizar(); }
    }));
    todos.addEventListener('change', e => {
        cajas.forEach(c => { c.checked = e.target.checked; });
        actualizar();
    });
})();
