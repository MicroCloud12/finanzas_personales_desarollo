// --- Constants ---
const UI_CLASSES = {
    HIDDEN: 'hidden',
    VISIBLE_SCROLL: 'is-visible',
    FLASH_MESSAGE: '.fixed.top-5.right-5'
};

const UI_IDS = {
    PROFILE_BTN: 'profile-menu-button',
    PROFILE_MENU: 'profile-menu',
    MOBILE_BTN: 'mobile-menu-button',
    MOBILE_MENU: 'mobile-menu',
    TRANS_TYPE: 'id_tipo',
    TRANS_DEST_DIV: 'div_cuenta_destino',
    TRANS_DEST_SELECT: 'id_cuenta_destino'
};

const TRANSFERS_TYPES = ['TRANSFERENCIA', 'PAGO_MENSUALIDAD', 'PAGO_CAPITAL'];

// --- Flash Messages ---
function initFlashMessages() {
    const messageWrapper = document.querySelector(UI_CLASSES.FLASH_MESSAGE);
    if (!messageWrapper) return;

    setTimeout(() => fadeOutElement(messageWrapper), 5000);
}

function fadeOutElement(element) {
    element.style.transition = 'opacity 0.5s ease';
    element.style.opacity = '0';
    setTimeout(() => element.remove(), 500);
}

// --- Navigation Menus ---
function initProfileMenu() {
    const menuButton = document.getElementById(UI_IDS.PROFILE_BTN);
    const dropdownMenu = document.getElementById(UI_IDS.PROFILE_MENU);

    if (!menuButton || !dropdownMenu) return;

    menuButton.addEventListener('click', (event) => {
        event.stopPropagation();
        dropdownMenu.classList.toggle(UI_CLASSES.HIDDEN);
    });

    window.addEventListener('click', (event) => {
        if (!dropdownMenu.classList.contains(UI_CLASSES.HIDDEN) && !menuButton.contains(event.target)) {
            dropdownMenu.classList.add(UI_CLASSES.HIDDEN);
        }
    });

    document.addEventListener('keydown', (event) => {
        if (event.key === 'Escape' && !dropdownMenu.classList.contains(UI_CLASSES.HIDDEN)) {
            dropdownMenu.classList.add(UI_CLASSES.HIDDEN);
        }
    });
}

function initMobileMenu() {
    const menuButton = document.getElementById(UI_IDS.MOBILE_BTN);
    const mobileMenu = document.getElementById(UI_IDS.MOBILE_MENU);

    if (!menuButton || !mobileMenu) return;

    menuButton.addEventListener('click', () => {
        const isExpanded = menuButton.getAttribute('aria-expanded') === 'true';
        menuButton.setAttribute('aria-expanded', String(!isExpanded));
        mobileMenu.classList.toggle(UI_CLASSES.HIDDEN);
    });
}

// --- Scroll Animations ---
function initScrollAnimations() {
    const scrollElements = document.querySelectorAll('.js-scroll');
    if (!scrollElements.length) return;

    const observer = new IntersectionObserver(handleScrollIntersect, { threshold: 0.1 });
    scrollElements.forEach(el => observer.observe(el));
}

function handleScrollIntersect(entries, observer) {
    entries.forEach(entry => {
        if (entry.isIntersecting) {
            entry.target.classList.add(UI_CLASSES.VISIBLE_SCROLL);
            observer.unobserve(entry.target);
        }
    });
}

// --- Transaction Form ---
function initTransactionForm() {
    const typeSelect = document.getElementById(UI_IDS.TRANS_TYPE);
    const destContainer = document.getElementById(UI_IDS.TRANS_DEST_DIV);
    const destSelect = document.getElementById(UI_IDS.TRANS_DEST_SELECT);

    if (!typeSelect || !destContainer) return;

    const toggleDestinationFields = () => {
        const isTransferType = TRANSFERS_TYPES.includes(typeSelect.value);
        
        destContainer.style.display = isTransferType ? 'block' : 'none';
        
        if (destSelect) {
            destSelect.required = isTransferType;
            if (!isTransferType) destSelect.value = '';
        }
    };

    toggleDestinationFields();
    typeSelect.addEventListener('change', toggleDestinationFields);
}

// --- Initialization ---
document.addEventListener('DOMContentLoaded', () => {
    initFlashMessages();
    initProfileMenu();
    initMobileMenu();
    initScrollAnimations();
    initTransactionForm();
});