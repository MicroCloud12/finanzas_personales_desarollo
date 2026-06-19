document.addEventListener('DOMContentLoaded', function () {
    document.querySelectorAll('.debt-progress-bar').forEach(bar => {
        const tipo = bar.dataset.tipo;
        const saldo = parseFloat(bar.dataset.saldo) || 0;
        const monto = parseFloat(bar.dataset.monto) || 1;
        const pct = (saldo / monto) * 100;

        bar.classList.remove('bg-gray-300');
        if (tipo === 'TARJETA_CREDITO') {
            // Para tarjetas: saldo pendiente es el crédito disponible.
            // Más crédito disponible (100%) = Verde. Menos (0%) = Rojo.
            if (pct >= 85) bar.classList.add('bg-green-500');
            else if (pct >= 30) bar.classList.add('bg-yellow-500');
            else bar.classList.add('bg-red-500');
        } else {
            // Para préstamos: saldo pendiente es la deuda restante.
            // Menos deuda restante (0%) = Verde. Más deuda (100%) = Rojo.
            if (pct <= 15) bar.classList.add('bg-green-500');
            else if (pct <= 70) bar.classList.add('bg-yellow-500');
            else bar.classList.add('bg-red-500');
        }
    });
});
