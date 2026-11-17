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
    todos.addEventListener('change', e => {
        cajas.forEach(c => { c.checked = e.target.checked; });
        actualizar();
    });
})();
