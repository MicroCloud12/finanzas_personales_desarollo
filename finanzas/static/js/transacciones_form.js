(function () {
    const tipoSelect = document.getElementById('id_tipo');
    const divOrigen = document.getElementById('div_origen');
    const divDestino = document.getElementById('div_destino');
    const divInteres = document.getElementById('div_monto_interes');
    const labelOrigen = document.getElementById('label_origen');
    const labelDestino = document.getElementById('label_destino');
    if (!tipoSelect) return;

    // Reglas del libro mayor: qué cuentas intervienen en cada tipo de movimiento
    const REGLAS = {
        INGRESO:          { origen: false, destino: true,  interes: false, labelDestino: 'Cuenta a la que entra el ingreso' },
        GASTO:            { origen: true,  destino: false, interes: false, labelOrigen: 'Cuenta o tarjeta con la que pagaste' },
        TRANSFERENCIA:    { origen: true,  destino: true,  interes: false, labelOrigen: 'Cuenta de la que sale', labelDestino: 'Cuenta, tarjeta o ahorro al que llega' },
        PAGO_MENSUALIDAD: { origen: true,  destino: true,  interes: true,  labelOrigen: 'Cuenta de la que sale el pago', labelDestino: 'Préstamo que estás pagando' },
        PAGO_CAPITAL:     { origen: true,  destino: true,  interes: false, labelOrigen: 'Cuenta de la que sale el abono', labelDestino: 'Préstamo al que abonas' },
    };

    function aplicar() {
        const regla = REGLAS[tipoSelect.value] || REGLAS.GASTO;
        if (divOrigen) divOrigen.style.display = regla.origen ? 'block' : 'none';
        if (divDestino) divDestino.style.display = regla.destino ? 'block' : 'none';
        if (divInteres) divInteres.style.display = regla.interes ? 'block' : 'none';
        if (labelOrigen && regla.labelOrigen) labelOrigen.textContent = regla.labelOrigen;
        if (labelDestino && regla.labelDestino) labelDestino.textContent = regla.labelDestino;
    }

    tipoSelect.addEventListener('change', aplicar);
    aplicar();
})();
