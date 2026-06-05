// ═══ NOTIFICATIONS JS ═══

let notifLastCount = 0;

// ✅ تشغيل الصوت دائماً لمدة 5 ثواني عند أي إشعار جديد
function playNotificationSound() {
    const audio = document.getElementById('notification-audio');
    if (!audio) return;
    audio.currentTime = 0;
    audio.play().catch(e => console.warn('Autoplay prevented:', e));
    setTimeout(() => {
        audio.pause();
        audio.currentTime = 0;
    }, 5000);
}

function fetchNotifications() {
    fetch('/api/notifications')
        .then(r => r.json())
        .then(data => {
            const container = document.getElementById('notifications-list');
            if (!container) return;

            if (!data || data.length === 0) {
                notifLastCount = 0;
                container.innerHTML = '<div class="notif-empty">Aucune notification pour le moment. Démarrez un trajet pour recevoir des alertes.</div>';
                return;
            }

            // ✅ تشغيل الصوت عند وصول إشعارات جديدة — بدون أي شرط
            if (data.length > notifLastCount) {
                playNotificationSound();
            }

            // لا تعيد رسم البطاقات إذا لم يتغير العدد
            if (data.length === notifLastCount) return;

            notifLastCount = data.length;

            let html = '';
            // Reverse to show newest first
            data.slice().reverse().forEach(notif => {
                let sevClass = notif.severite === 'CRITIQUE' ? 'critique' : notif.severite === 'ATTENTION' ? 'attention' : '';
                let actionClass = notif.statut_final === 'ARRET IMMEDIAT' ? 'notif-action arret' : 'notif-action';

                let timeStr = "";
                if (notif.timestamp) {
                    try {
                        timeStr = notif.timestamp.split('T')[1].substring(0, 8);
                    } catch(e) {}
                }

                // ✅ تنظيف النص وتنسيقه
                let rawText = notif.notification || "";
                
                // إزالة سطر العنوان من الوصف حتى لا يتكرر (لأنه موجود بالفعل في notif-header)
                rawText = rawText.replace(/\*\*Titre\*\*\s*:\s*.*?(?:\n|$)/i, '');

                // تحويل **نص** إلى عريض، و \n إلى سطر جديد
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

// Poll every 2 seconds for faster sync
setInterval(fetchNotifications, 2000);