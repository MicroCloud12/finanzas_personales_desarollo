(function () {
    const tipoSelect = document.getElementById('id_tipo');
    const divDestino = document.getElementById('div_cuenta_destino');
    const tiposConDestino = ['TRANSFERENCIA', 'PAGO_MENSUALIDAD', 'PAGO_CAPITAL'];

    function toggleDestino() {
        divDestino.style.display = tiposConDestino.includes(tipoSelect.value) ? 'block' : 'none';
    }

    tipoSelect.addEventListener('change', toggleDestino);
    toggleDestino();
})();
