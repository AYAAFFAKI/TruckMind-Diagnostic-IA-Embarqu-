// ═══ NOTIFICATIONS JS (version corrigée - évite les doublons) ═══

let notifLastCount = 0;
let lastPlayedNotificationId = null;   // ID du dernier cycle joué
let lastNotificationKey = null;        // Clé unique (titre + sévérité) pour détecter les répétitions
let lastNotificationTime = 0;          // Timestamp du dernier son joué

// ─── Joue le son uniquement pour les alertes critiques ou attention ───
function playNotificationSound(severite) {
    if (severite !== 'CRITIQUE' && severite !== 'ATTENTION') {
        console.log(" Son ignoré : sévérité =", severite);
        return;
    }
    const audio = document.getElementById('notification-audio');
    if (!audio) return;
    audio.currentTime = 0;
    audio.play().catch(e => console.warn('Autoplay empêché:', e));
    // Arrêt après 5 secondes
    setTimeout(() => {
        audio.pause();
        audio.currentTime = 0;
    }, 5000);
}

// ─── Récupère et affiche les notifications depuis l'API ───
function fetchNotifications() {
    fetch('/api/notifications')
        .then(r => r.json())
        .then(data => {
            const container = document.getElementById('notifications-list');
            if (!container) return;

            // Cas où il n'y a aucune notification
            if (!data || data.length === 0) {
                notifLastCount = 0;
                lastPlayedNotificationId = null;
                lastNotificationKey = null;
                container.innerHTML = '<div class="notif-empty">Aucune notification pour le moment. Démarrez un trajet pour recevoir des alertes.</div>';
                return;
            }

            // Dernière notification reçue (la plus récente)
            const latestNotification = data[data.length - 1];
            const latestId = latestNotification?.cycle || null;
            const now = Date.now();

            // Clé unique basée sur le titre et la sévérité (pour ignorer les doublons proches)
            const currentKey = `${latestNotification.titre}|${latestNotification.severite}`;

            // Vérification : nouvelle notification (taille augmentée) et ID différent
            if (data.length > notifLastCount && latestId !== lastPlayedNotificationId) {
                // Ignorer si la même clé est revenue dans les 5 dernières secondes (évite les doublons)
                if (currentKey === lastNotificationKey && (now - lastNotificationTime) < 5000) {
                    console.log(" Notification ignorée (répétition rapide)");
                } else {
                    playNotificationSound(latestNotification.severite);
                    lastPlayedNotificationId = latestId;
                    lastNotificationKey = currentKey;
                    lastNotificationTime = now;
                }
            }

            notifLastCount = data.length;

            // Construction de l'affichage HTML (ordre inverse : plus récent en premier)
            let html = '';
            data.slice().reverse().forEach(notif => {
                let sevClass = notif.severite === 'CRITIQUE' ? 'critique' : notif.severite === 'ATTENTION' ? 'attention' : '';
                let actionClass = notif.statut_final === 'ARRET IMMEDIAT' ? 'notif-action arret' : 'notif-action';

                let timeStr = "";
                if (notif.timestamp) {
                    try {
                        timeStr = notif.timestamp.split('T')[1].substring(0, 8);
                    } catch(e) {}
                }
                
                let rawText = notif.notification || "";
                // Supprime la ligne "**Titre** : ..." (déjà dans l'en-tête)
                rawText = rawText.replace(/\*\*Titre\*\*\s*:\s*.*?(?:\n|$)/i, '');
                // Supprime la ligne "**Statut final** : ..." (on garde seulement notre STATUT RECOMMANDÉ)
                rawText = rawText.replace(/^\*\*Statut final\*\*\s*:\s*.*$/gim, '');
                // Nettoie les lignes vides résiduelles
                rawText = rawText.replace(/^\s*[\r\n]/gm, '');
                
                let formattedText = rawText.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>');
                formattedText = formattedText.replace(/\n/g, '<br>');

                html += `
                <div class="notification-card ${sevClass}">
                    <div class="notif-header">
                        <div class="notif-title">${notif.titre || 'Notification Système'}</div>
                        <div class="notif-time">Cycle #${notif.cycle} • ${timeStr}</div>
                    </div>
                    <div class="notif-body">${formattedText}</div>
                    <div class="${actionClass}">STATUT RECOMMANDÉ : ${notif.statut_final}</div>
                </div>
                `;
            });
            container.innerHTML = html;
        })
        .catch(e => console.error("Erreur notifications:", e));
}

// Vérification toutes les 5 secondes
setInterval(fetchNotifications, 5000);  