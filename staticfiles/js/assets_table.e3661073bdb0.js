// Tabla "Mis Activos": sparklines, filtros (Todos/Ganadores/Perdedores) y orden por columna.
document.addEventListener('DOMContentLoaded', function () {
    const table = document.getElementById('assetsTable');
    if (!table) return;
    const body = document.getElementById('assetsBody');

    // --- Sparklines (tendencia por activo) ---
    // Nota: la dirección y el color reflejan la P/L real del activo. El zigzag es
    // estético (determinista por ticker) porque aún no guardamos precios diarios por activo.
    function seededRand(seed) {
        let s = 0;
        for (let i = 0; i < seed.length; i++) s = (s * 31 + seed.charCodeAt(i)) >>> 0;
        if (!s) s = 1;
        return function () { s = (s * 1664525 + 1013904223) >>> 0; return s / 4294967296; };
    }

    function drawSpark(el) {
        const trend = parseFloat(el.dataset.trend) || 0;
        const up = trend >= 0;
        const color = up ? '#22c55e' : '#ef4444';
        const rand = seededRand(el.dataset.seed || 'x');
        const n = 14, w = 96, h = 36, pad = 5;
        const startV = up ? 0.35 : 0.70;
        const endV = up ? 0.85 : 0.15;
        const pts = [];
        for (let i = 0; i < n; i++) {
            const t = i / (n - 1);
            const lin = startV + (endV - startV) * t;
            const v = Math.max(0.06, Math.min(0.94, lin + (rand() - 0.5) * 0.24));
            const x = pad + t * (w - 2 * pad);
            const y = pad + (1 - v) * (h - 2 * pad);
            pts.push([x, y]);
        }
        const d = pts.map((p, i) => (i ? 'L' : 'M') + p[0].toFixed(1) + ' ' + p[1].toFixed(1)).join(' ');
        const last = pts[pts.length - 1];
        el.innerHTML =
            '<svg width="' + w + '" height="' + h + '" viewBox="0 0 ' + w + ' ' + h + '" fill="none">' +
            '<path d="' + d + '" stroke="' + color + '" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>' +
            '<circle cx="' + last[0].toFixed(1) + '" cy="' + last[1].toFixed(1) + '" r="2.6" fill="' + color + '"/>' +
            '</svg>';
    }

    table.querySelectorAll('.spark').forEach(drawSpark);

    // --- Filtros (Todos / Ganadores / Perdedores) ---
    const filterBtns = document.querySelectorAll('#assetsFilter [data-filter]');
    filterBtns.forEach((btn) => {
        btn.addEventListener('click', () => {
            filterBtns.forEach((b) => {
                b.classList.remove('bg-blue-500', 'text-white');
                b.classList.add('border', 'border-white/15', 'text-gray-300');
            });
            btn.classList.add('bg-blue-500', 'text-white');
            btn.classList.remove('border', 'border-white/15', 'text-gray-300');

            const f = btn.dataset.filter;
            body.querySelectorAll('.asset-row').forEach((row) => {
                const pl = parseFloat(row.dataset.pl) || 0;
                const show = f === 'all' || (f === 'win' && pl >= 0) || (f === 'lose' && pl < 0);
                row.style.display = show ? '' : 'none';
            });
        });
    });

    // --- Orden por columna ---
    let sortDir = {};
    table.querySelectorAll('th[data-sort-index]').forEach((th) => {
        th.addEventListener('click', () => {
            const idx = parseInt(th.dataset.sortIndex, 10);
            const dir = sortDir[idx] === 'asc' ? 'desc' : 'asc';
            sortDir = { [idx]: dir };
            const rows = Array.from(body.querySelectorAll('.asset-row'));
            rows.sort((a, b) => {
                const av = parseFloat(a.children[idx] && a.children[idx].dataset.value) || 0;
                const bv = parseFloat(b.children[idx] && b.children[idx].dataset.value) || 0;
                return dir === 'asc' ? av - bv : bv - av;
            });
            rows.forEach((r) => body.appendChild(r));
        });
    });
});
