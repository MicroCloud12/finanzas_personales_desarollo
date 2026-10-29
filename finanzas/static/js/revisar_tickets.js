(function () {
    // Destino solo aplica a transferencias y pagos de préstamo.
    const CON_DESTINO = ['TRANSFERENCIA', 'PAGO_MENSUALIDAD', 'PAGO_CAPITAL'];

    function ajustarFila(fila) {
        const tipo = fila.querySelector('[data-rol="tipo"]');
        const destino = fila.querySelector('[data-rol="destino"]');
        if (!tipo || !destino) return;
        const aplica = CON_DESTINO.includes(tipo.value);
        destino.style.visibility = aplica ? 'visible' : 'hidden';
        if (!aplica) destino.value = 'N/A';
    }

    document.querySelectorAll('tr[data-ticket]').forEach(fila => {
        ajustarFila(fila);
        const tipo = fila.querySelector('[data-rol="tipo"]');
        if (tipo) tipo.addEventListener('change', () => ajustarFila(fila));
    });

    function aplicarATodos(selectorBarra, rol) {
        const barra = document.getElementById(selectorBarra);
        if (!barra) return;
        barra.addEventListener('change', () => {
            if (!barra.value) return;
            document.querySelectorAll('tr[data-ticket] [data-rol="' + rol + '"]').forEach(sel => {
                sel.value = barra.value;
            });
        });
    }
    aplicarATodos('aplicar_cuenta', 'cuenta');
    aplicarATodos('aplicar_categoria', 'categoria');
})();
