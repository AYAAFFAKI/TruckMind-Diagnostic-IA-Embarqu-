// ═══ SIMULATOR JS ═══

let simInterval = null;

function startJourney() {
    const city = document.getElementById('city').value;
    
    // Update destination label
    const destLabel = document.getElementById('sim-dest-label');
    if (destLabel) destLabel.textContent = city;
    
    fetch('/api/simulator/start', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({destination: city})
    }).then(r => r.json()).then(data => {
        const statusEl = document.getElementById('sim-status');
        if (statusEl) statusEl.textContent = '🚛 Trajet démarré vers ' + city;
        
        // ✅ Réinitialiser le compteur de notifications côté client
        // pour que les nouvelles notifications déclenchent le son correctement
        if (typeof notifLastCount !== 'undefined') {
            notifLastCount = 0;
        }
        
        // ✅ Vider l'affichage des notifications si la page est visible
        const notifContainer = document.getElementById('notifications-list');
        if (notifContainer) {
            notifContainer.innerHTML = '<div class="notif-empty">Nouveau trajet démarré. En attente d\'alertes...</div>';
        }
    }).catch(e => console.error('Erreur démarrage:', e));
}

function stopJourney() {
    fetch('/api/simulator/stop', { method: 'POST' })
        .then(r => r.json()).then(data => {
            const statusEl = document.getElementById('sim-status');
            if (statusEl) statusEl.textContent = '⛔ Trajet arrêté';
        }).catch(e => console.error('Erreur arrêt:', e));
}

function fetchSimStatus() {
    fetch('/api/simulator/status')
        .then(r => r.json())
        .then(data => {
            // Status text
            const statusEl = document.getElementById('sim-status');
            if (statusEl) statusEl.textContent = data.journey_status || "En attente...";
            
            // Speed
            const speedEl = document.getElementById('sim-speed');
            if (speedEl) speedEl.textContent = (data.current_speed_kmh || 0).toFixed(1);
            
            // Load with color coding
            const loadEl = document.getElementById('sim-load');
            if (loadEl) {
                loadEl.textContent = (data.load_tonnes || 0).toFixed(1);
                if (data.load_tonnes > 38) loadEl.className = 'sim-card-val danger';
                else if (data.load_tonnes > 30) loadEl.className = 'sim-card-val warn';
                else loadEl.className = 'sim-card-val';
            }
            
            // Distance
            const distEl = document.getElementById('sim-distance');
            if (distEl) {
                distEl.textContent = (data.distance_covered_km || 0).toFixed(1) + " / " + Math.round(data.total_distance_km || 0);
            }
            
            // Temperature
            const tempEl = document.getElementById('sim-temp');
            if (tempEl && data.temperature_moteur !== undefined) {
                tempEl.textContent = data.temperature_moteur.toFixed(1) + ' °C';
                if (data.temperature_moteur > 105) tempEl.className = 'sim-card-val danger';
                else if (data.temperature_moteur > 95) tempEl.className = 'sim-card-val warn';
                else tempEl.className = 'sim-card-val';
            }
            
            // Pneus
            const pressionEl = document.getElementById('sim-pression');
            if (pressionEl && data.pression_pneus !== undefined) {
                pressionEl.textContent = data.pression_pneus.toFixed(1);
                if (data.pression_pneus < 90 || data.pression_pneus > 130) pressionEl.className = 'sim-card-val danger';
                else if (data.pression_pneus < 100 || data.pression_pneus > 125) pressionEl.className = 'sim-card-val warn';
                else pressionEl.className = 'sim-card-val';
            }

            // Freins
            const freinsEl = document.getElementById('sim-freins');
            if (freinsEl && data.freins_usure_percent !== undefined) {
                freinsEl.textContent = data.freins_usure_percent.toFixed(1);
                if (data.freins_usure_percent > 85) freinsEl.className = 'sim-card-val danger';
                else if (data.freins_usure_percent > 70) freinsEl.className = 'sim-card-val warn';
                else freinsEl.className = 'sim-card-val';
            }
            
            // Batterie
            const battEl = document.getElementById('sim-batterie');
            if (battEl && data.etat_batterie !== undefined) {
                battEl.textContent = data.etat_batterie.toFixed(1);
                if (data.etat_batterie < 30) battEl.className = 'sim-card-val danger';
                else if (data.etat_batterie < 50) battEl.className = 'sim-card-val warn';
                else battEl.className = 'sim-card-val';
            }
            
            // Vibrations
            const vibEl = document.getElementById('sim-vibration');
            if (vibEl && data.niveaux_vibration !== undefined) {
                vibEl.textContent = data.niveaux_vibration.toFixed(2);
                if (data.niveaux_vibration > 1.8) vibEl.className = 'sim-card-val danger';
                else if (data.niveaux_vibration > 1.2) vibEl.className = 'sim-card-val warn';
                else vibEl.className = 'sim-card-val';
            }
            
            // Consommation
            const consoEl = document.getElementById('sim-conso');
            if (consoEl && data.consommation_carburant !== undefined) {
                consoEl.textContent = data.consommation_carburant.toFixed(1);
                if (data.consommation_carburant > 45) consoEl.className = 'sim-card-val danger';
                else if (data.consommation_carburant > 35) consoEl.className = 'sim-card-val warn';
                else consoEl.className = 'sim-card-val';
            }
            
            // Progress bar + truck icon movement
            const pct = data.progress_percent || 0;
            const progressFill = document.getElementById('sim-progress');
            if (progressFill) progressFill.style.width = pct + '%';
            
            const truckIcon = document.getElementById('sim-truck-icon');
            if (truckIcon) truckIcon.style.left = pct + '%';
        })
        .catch(e => console.error("Erreur status:", e));
}

// Poll every 5 seconds
setInterval(fetchSimStatus, 5000);