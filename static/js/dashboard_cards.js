document.addEventListener('DOMContentLoaded', function() {
    const dataEl = document.getElementById('tarjetas-data');
    if (!dataEl) return;
    
    const tarjetas = JSON.parse(dataEl.textContent);
    if (tarjetas.length === 0) return;

    let currentIndex = 0;
    
    const visualCardName = document.getElementById('visualCardName');
    const visualCardNumber = document.getElementById('visualCardNumber');
    const indexLabel = document.getElementById('visualCardIndexLabel');
    const widget = document.getElementById('myCardsWidget');
    
    const prevBtn = document.getElementById('prevCardBtn');
    const nextBtn = document.getElementById('nextCardBtn');
    
    // Arrays for random premium gradient variations for the Main Container
    const backgroundGradients = [
        'linear-gradient(135deg, #0f172a 0%, #172554 40%, #991b1b 100%)', // Original Red/Navy abstract look
        'linear-gradient(135deg, #020617 0%, #064e3b 40%, #10b981 100%)', // Emerald abstract
        'linear-gradient(135deg, #1e1b4b 0%, #4c1d95 40%, #f43f5e 100%)', // Purple/Rose abstract
        'linear-gradient(135deg, #0a0a0a 0%, #262626 50%, #ea580c 100%)'  // Ember/Slate abstract
    ];

    function updateCardDisplay(index) {
        const card = tarjetas[index];
        
        // Small fade animation
        widget.style.opacity = '0.7';
        
        setTimeout(() => {
            // Update content
            visualCardName.textContent = card.nombre;
            visualCardNumber.innerHTML = '<span class="inline-block relative top-[0.2em] transform translate-y-px">**** **** ****</span> <span class="ml-3">' + (card.terminacion || '0000') + '</span>';
            if(indexLabel) indexLabel.textContent = '( ' + (index + 1) + '/' + tarjetas.length + ' )';
            
            // Cycle gradients smoothly on the main block
            widget.style.background = backgroundGradients[index % backgroundGradients.length];
            
            // Restore animation
            widget.style.opacity = '1';
            
            // --- NEW: Trigger update for Income Card ---
            fetchIncomeMetrics(card.nombre);
        }, 150);
    }

    // Función para mandar a traer los ingresos cruzados con filtros
    function fetchIncomeMetrics(cuentaNombre) {
        const monthSelect = document.querySelector('select[name="month"]');
        const yearSelect = document.querySelector('select[name="year"]');
        if (!monthSelect || !yearSelect) return;
        
        const month = monthSelect.value;
        const year = yearSelect.value;
        
        const url = `/api/dashboard/ingresos-tarjeta/?cuenta_nombre=${encodeURIComponent(cuentaNombre)}&month=${month}&year=${year}`;
        
        fetch(url)
            .then(response => response.json())
            .then(data => {
                if (data.status === 'success') {
                    // Split integer and decimal parts
                    const parts = String(data.total_income).split('.');
                    document.getElementById('incomeTotalAmount').textContent = parts[0];
                    if (document.getElementById('incomeDecimalAmount')) {
                        document.getElementById('incomeDecimalAmount').textContent = parts[1] || '00';
                    }
                    
                    document.getElementById('incomePercentageText').textContent = data.porcentaje + '%';
                    
                    document.getElementById('incomeExtraAmount').textContent = '$' + data.diferencia_monto;
                    document.getElementById('incomeTxCount').textContent = data.transactions + ' transacciones';
                    document.getElementById('incomeCatCount').textContent = data.categories + ' categorías';
                    
                    const badge = document.getElementById('incomePercentageBadge');
                    const trendPath = document.getElementById('incomeTrendArrow');
                    const earnText = document.getElementById('incomeEarnText');
                    
                    if (data.es_positivo) {
                        badge.className = "inline-flex items-center gap-1 bg-green-50 text-green-600 px-2.5 py-1 rounded-lg text-xs font-bold transition-colors";
                        // Flecha hacia arriba
                        trendPath.setAttribute('d', 'M5 10l7-7m0 0l7 7m-7-7v18');
                        earnText.textContent = "extra";
                    } else {
                        badge.className = "inline-flex items-center gap-1 bg-red-50 text-red-600 px-2.5 py-1 rounded-lg text-xs font-bold transition-colors";
                        // Flecha hacia abajo
                        trendPath.setAttribute('d', 'M19 14l-7 7m0 0l-7-7m7 7V3');
                        earnText.textContent = "menos";
                    }
                }
            })
            .catch(error => console.error("Error al obtener las estadísticas de ingresos:", error));
    }

    if (prevBtn) {
        prevBtn.addEventListener('click', () => {
            currentIndex = (currentIndex === 0) ? tarjetas.length - 1 : currentIndex - 1;
            updateCardDisplay(currentIndex);
        });
    }

    if (nextBtn) {
        nextBtn.addEventListener('click', () => {
            currentIndex = (currentIndex === tarjetas.length - 1) ? 0 : currentIndex + 1;
            updateCardDisplay(currentIndex);
        });
    }

    // Initialize the real data for the first card on load
    fetchIncomeMetrics(tarjetas[currentIndex].nombre);
});
