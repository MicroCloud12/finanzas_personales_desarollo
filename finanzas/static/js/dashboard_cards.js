const TREND_ARROW_UP = 'M5 10l7-7m0 0l7 7m-7-7v18';
const TREND_ARROW_DOWN = 'M19 14l-7 7m0 0l-7-7m7 7V3';

const BADGE_BASE = 'inline-flex items-center gap-1 px-2.5 py-1 rounded-lg text-xs font-bold transition-colors';
const BADGE_POSITIVE = `bg-green-50 text-green-600 ${BADGE_BASE}`;
const BADGE_NEGATIVE = `bg-red-50 text-red-600 ${BADGE_BASE}`;
const BADGE_EXPENSE_UP = `bg-red-50 text-red-500 ${BADGE_BASE}`;     // gasto que sube = malo
const BADGE_EXPENSE_DOWN = `bg-green-50 text-green-500 ${BADGE_BASE}`; // gasto que baja = bueno

const BACKGROUND_GRADIENTS = [
    'linear-gradient(135deg, #0f172a 0%, #172554 40%, #991b1b 100%)',
    'linear-gradient(135deg, #020617 0%, #064e3b 40%, #10b981 100%)',
    'linear-gradient(135deg, #1e1b4b 0%, #4c1d95 40%, #f43f5e 100%)',
    'linear-gradient(135deg, #0a0a0a 0%, #262626 50%, #ea580c 100%)'
];

document.addEventListener('DOMContentLoaded', function() {
    function setText(id, text) {
        const el = document.getElementById(id);
        if (el) el.textContent = text;
    }

    function splitAmount(total) {
        const raw = String(total);
        const isNegative = raw.startsWith('-');
        const [whole, decimal] = (isNegative ? raw.slice(1) : raw).split('.');
        return { whole: (isNegative ? '-' : '') + whole, decimal: decimal || '00' };
    }

    // positiveBadge/negativeBadge = clases aplicadas según metric.es_positivo (true/false).
    function updateMetricCard(prefix, metric, positiveBadge, negativeBadge) {
        const amount = splitAmount(metric.total);
        setText(`${prefix}TotalAmount`, amount.whole);
        setText(`${prefix}DecimalAmount`, amount.decimal);
        setText(`${prefix}PercentageText`, `${metric.porcentaje}%`);
        setText(`${prefix}ExtraAmount`, `$${metric.diferencia_monto}`);
        setText(`${prefix}TxCount`, `${metric.transactions} transacciones`);
        setText(`${prefix}CatCount`, `${metric.categories} categorías`);

        const badge = document.getElementById(`${prefix}PercentageBadge`);
        const arrow = document.getElementById(`${prefix}TrendArrow`);
        const earnText = document.getElementById(`${prefix}EarnText`);
        if (badge) badge.className = metric.es_positivo ? positiveBadge : negativeBadge;
        if (arrow) arrow.setAttribute('d', metric.es_positivo ? TREND_ARROW_UP : TREND_ARROW_DOWN);
        if (earnText) earnText.textContent = metric.es_positivo ? 'extra' : 'menos';
    }

    // Tarjetas de arriba: cifras GLOBALES del mes vs. el mes anterior (las calcula la vista)
    const metricasEl = document.getElementById('metricas-data');
    if (metricasEl) {
        const m = JSON.parse(metricasEl.textContent);
        updateMetricCard('income', m.ingresos, BADGE_POSITIVE, BADGE_NEGATIVE);
        updateMetricCard('expense', m.gastos, BADGE_EXPENSE_UP, BADGE_EXPENSE_DOWN);
        updateMetricCard('balance', m.balance, BADGE_POSITIVE, BADGE_NEGATIVE);
    }

    // Widget "Mis tarjetas": solo cambia la tarjeta visual y su saldo
    const dataEl = document.getElementById('tarjetas-data');
    if (!dataEl) return;
    const tarjetas = JSON.parse(dataEl.textContent);
    if (tarjetas.length === 0) return;

    const widget = document.getElementById('myCardsWidget');
    const visualCardName = document.getElementById('visualCardName');
    const visualCardNumber = document.getElementById('visualCardNumber');
    const indexLabel = document.getElementById('visualCardIndexLabel');
    let currentIndex = 0;

    function showCard(index) {
        const card = tarjetas[index];
        widget.style.opacity = '0.7';
        setTimeout(() => {
            visualCardName.textContent = card.nombre;
            visualCardNumber.innerHTML = `<span class="inline-block relative top-[0.2em] transform translate-y-px">**** **** ****</span> <span class="ml-3">${card.terminacion || '0000'}</span>`;
            setText('visualCardSaldo', card.saldo);
            if (indexLabel) indexLabel.textContent = `( ${index + 1}/${tarjetas.length} )`;
            widget.style.background = BACKGROUND_GRADIENTS[index % BACKGROUND_GRADIENTS.length];
            widget.style.opacity = '1';
        }, 150);
    }

    document.getElementById('prevCardBtn')?.addEventListener('click', () => {
        currentIndex = (currentIndex === 0) ? tarjetas.length - 1 : currentIndex - 1;
        showCard(currentIndex);
    });

    document.getElementById('nextCardBtn')?.addEventListener('click', () => {
        currentIndex = (currentIndex === tarjetas.length - 1) ? 0 : currentIndex + 1;
        showCard(currentIndex);
    });
});
