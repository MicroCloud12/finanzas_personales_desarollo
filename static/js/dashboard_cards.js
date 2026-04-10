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
                    // --- UPDATE INGRESOS ---
                    const ing = data.ingresos;
                    const partsIng = String(ing.total).split('.');
                    document.getElementById('incomeTotalAmount').textContent = partsIng[0];
                    if (document.getElementById('incomeDecimalAmount')) {
                        document.getElementById('incomeDecimalAmount').textContent = partsIng[1] || '00';
                    }
                    
                    document.getElementById('incomePercentageText').textContent = ing.porcentaje + '%';
                    document.getElementById('incomeExtraAmount').textContent = '$' + ing.diferencia_monto;
                    document.getElementById('incomeTxCount').textContent = ing.transactions + ' transacciones';
                    document.getElementById('incomeCatCount').textContent = ing.categories + ' categorías';
                    
                    const badgeIng = document.getElementById('incomePercentageBadge');
                    const trendPathIng = document.getElementById('incomeTrendArrow');
                    const earnTextIng = document.getElementById('incomeEarnText');
                    
                    if (ing.es_positivo) {
                        badgeIng.className = "inline-flex items-center gap-1 bg-green-50 text-green-600 px-2.5 py-1 rounded-lg text-xs font-bold transition-colors";
                        trendPathIng.setAttribute('d', 'M5 10l7-7m0 0l7 7m-7-7v18');
                        earnTextIng.textContent = "extra";
                    } else {
                        badgeIng.className = "inline-flex items-center gap-1 bg-red-50 text-red-600 px-2.5 py-1 rounded-lg text-xs font-bold transition-colors";
                        trendPathIng.setAttribute('d', 'M19 14l-7 7m0 0l-7-7m7 7V3');
                        earnTextIng.textContent = "menos";
                    }

                    // --- UPDATE GASTOS ---
                    const gas = data.gastos;
                    const partsGas = String(gas.total).split('.');
                    document.getElementById('expenseTotalAmount').textContent = partsGas[0];
                    if (document.getElementById('expenseDecimalAmount')) {
                        document.getElementById('expenseDecimalAmount').textContent = partsGas[1] || '00';
                    }
                    
                    document.getElementById('expensePercentageText').textContent = gas.porcentaje + '%';
                    document.getElementById('expenseExtraAmount').textContent = '$' + gas.diferencia_monto;
                    document.getElementById('expenseTxCount').textContent = gas.transactions + ' transacciones';
                    document.getElementById('expenseCatCount').textContent = gas.categories + ' categorías';
                    
                    const badgeGas = document.getElementById('expensePercentageBadge');
                    const trendPathGas = document.getElementById('expenseTrendArrow');
                    const earnTextGas = document.getElementById('expenseEarnText');
                    
                    // In expenses, going up (es_positivo = true) is visually "bad/red" 
                    // Going down (es_positivo = false) is visually "good/green"
                    if (gas.es_positivo) {
                        badgeGas.className = "inline-flex items-center gap-1 bg-red-50 text-red-500 px-2.5 py-1 rounded-lg text-xs font-bold transition-colors";
                        trendPathGas.setAttribute('d', 'M5 10l7-7m0 0l7 7m-7-7v18');
                        earnTextGas.textContent = "extra";
                    } else {
                        badgeGas.className = "inline-flex items-center gap-1 bg-green-50 text-green-500 px-2.5 py-1 rounded-lg text-xs font-bold transition-colors";
                        trendPathGas.setAttribute('d', 'M19 14l-7 7m0 0l-7-7m7 7V3');
                        earnTextGas.textContent = "menos";
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
