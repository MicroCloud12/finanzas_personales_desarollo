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
        }, 150);
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
});
