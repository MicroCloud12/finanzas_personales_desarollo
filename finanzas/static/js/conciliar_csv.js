// Conciliación con el banco (conciliar_csv.html): la casilla del encabezado marca/desmarca todas las de su tabla.
(function () {
    document.querySelectorAll('input.marcar-todos').forEach(todos => {
        todos.addEventListener('change', () => {
            todos.closest('form').querySelectorAll('input[name="id"]').forEach(c => { c.checked = todos.checked; });
        });
    });
})();
