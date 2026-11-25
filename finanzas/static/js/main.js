function fadeFlashMessage() {
    const toasts = document.querySelectorAll('.toast-message');
    toasts.forEach((toast, index) => {
        // Mostrar los toasts escalonadamente
        setTimeout(() => {
            toast.classList.remove('translate-x-full', 'opacity-0');
        }, 100 * (index + 1));

        // Ocultarlos automáticamente después de 8 segundos
        setTimeout(() => {
            toast.classList.add('translate-x-full', 'opacity-0');
            setTimeout(() => toast.remove(), 300); // Dar tiempo a la animación para terminar
        }, 8000);
    });
}

function setupProfileMenu() {
    const menuButton = document.getElementById('profile-menu-button');
    const dropdownMenu = document.getElementById('profile-menu');

    if (menuButton && dropdownMenu) {
        menuButton.addEventListener('click', function(event) {
            event.stopPropagation();
            dropdownMenu.classList.toggle('hidden');
        });

        window.addEventListener('click', function(event) {
            if (!dropdownMenu.classList.contains('hidden') && !menuButton.contains(event.target)) {
                dropdownMenu.classList.add('hidden');
            }
        });

        document.addEventListener('keydown', function(event) {
            if (event.key === 'Escape' && !dropdownMenu.classList.contains('hidden')) {
                dropdownMenu.classList.add('hidden');
            }
        });
    }
}

function initScrollAnimations() {
    const scrollElements = document.querySelectorAll('.js-scroll');
    if (!scrollElements.length) return;

    const observer = new IntersectionObserver((entries) => {
        entries.forEach(entry => {
            if (entry.isIntersecting) {
                entry.target.classList.add('is-visible');
                observer.unobserve(entry.target);
            }
        });
    }, { threshold: 0.1 });

    scrollElements.forEach(el => observer.observe(el));
}

function setupMobileMenu() {
    const menuButton = document.getElementById('mobile-menu-button');
    const sidebar = document.getElementById('app-sidebar');
    const backdrop = document.getElementById('sidebar-backdrop');
    const closeBtn = document.getElementById('close-sidebar-btn');

    if (!menuButton || !sidebar) return;

    const abrir = () => {
        sidebar.classList.remove('-translate-x-full');
        if (backdrop) backdrop.classList.remove('hidden');
        menuButton.setAttribute('aria-expanded', 'true');
    };

    const cerrar = () => {
        sidebar.classList.add('-translate-x-full');
        if (backdrop) backdrop.classList.add('hidden');
        menuButton.setAttribute('aria-expanded', 'false');
    };

    menuButton.addEventListener('click', () => {
        const abierto = !sidebar.classList.contains('-translate-x-full');
        abierto ? cerrar() : abrir();
    });

    if (backdrop) backdrop.addEventListener('click', cerrar);
    if (closeBtn) closeBtn.addEventListener('click', cerrar);
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') cerrar();
    });
}

document.addEventListener('DOMContentLoaded', () => {
    fadeFlashMessage();
    setupProfileMenu();
    initScrollAnimations();
    setupMobileMenu();
});