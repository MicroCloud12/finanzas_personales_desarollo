// Mi perfil (mi_perfil.html): modal para eliminar la cuenta; solo se habilita al escribir la palabra de confirmación,
// que llega en el atributo data-palabra del campo de texto.
(function () {
    const modal = document.getElementById('modal-eliminar');
    const abrir = document.getElementById('btn-abrir-eliminar');
    const cerrar = document.getElementById('btn-cerrar-eliminar');
    const input = document.getElementById('confirmacion-eliminar');
    const confirmar = document.getElementById('btn-confirmar-eliminar');
    const form = document.getElementById('form-eliminar');
    if (!modal || !abrir || !cerrar || !input || !confirmar || !form) return;
    const palabra = (input.dataset.palabra || '').toUpperCase();

    function mostrar(visible) {
        modal.classList.toggle('hidden', !visible);
        if (visible) { input.value = ''; confirmar.disabled = true; input.focus(); }
    }
    abrir.addEventListener('click', () => mostrar(true));
    cerrar.addEventListener('click', () => mostrar(false));
    modal.addEventListener('click', (e) => { if (e.target === modal) mostrar(false); });
    document.addEventListener('keydown', (e) => { if (e.key === 'Escape') mostrar(false); });
    input.addEventListener('input', () => { confirmar.disabled = input.value.trim().toUpperCase() !== palabra; });
    form.addEventListener('submit', () => {
        // Evita doble envío mientras el servidor borra la cuenta
        confirmar.disabled = true;
        confirmar.textContent = 'Eliminando…';
    });
})();
