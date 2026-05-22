/* ═══════════════════════════════════════════════════════════════════
   TruckMind Frontend — main.js v3.0 (LangGraph)
   Auteure : AFFAKI Aya — EST Tétouan — IA DUT 2025-2026
═══════════════════════════════════════════════════════════════════ */

// ── State ────────────────────────────────────────────────────────
const STATE = { ready: false, loading: false, stats: null, alerts: [] };

// ── Utils ────────────────────────────────────────────────────────
const $ = id => document.getElementById(id);
const now = () => new Date().toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit' });

/**
 * Show a toast notification
 * @param {string} msg - Message text
 * @param {'ok'|'err'|'inf'} type - Toast style
 * @param {number} ms - Duration in ms
 */
function toast(msg, type = 'inf', ms = 3200) {
  const t = $('toast');
  t.className = `toast show ${type}`;
  t.textContent = msg;
  setTimeout(() => { t.className = 'toast'; }, ms);
}

/**
 * Update header status indicator
 * @param {'online'|'loading'|'error'} s
 */
function setStatus(s) {
  const labels = { online: 'SYSTÈME PRÊT', loading: 'CONNEXION', error: 'ERREUR' };
  $('status-dot').className = `status-dot ${s}`;
  $('status-lbl').textContent = labels[s] || 'HORS LIGNE';
}

// ── Tab switching ─────────────────────────────────────────────────
function switchTab(tab) {
  document.querySelectorAll('.tab-content').forEach(el => el.classList.remove('active'));
  document.querySelectorAll('.nav-tab').forEach(el => el.classList.remove('active'));
  $(`tab-${tab}`).classList.add('active');
  document.querySelector(`[data-tab="${tab}"]`).classList.add('active');
  if (tab === 'dashboard' && STATE.stats) renderDashboard(STATE.stats);
}

// ── Markdown renderer ─────────────────────────────────────────────
function md(text) {
  return text
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/```([\s\S]*?)```/g, '<pre>$1</pre>')
    .replace(/`([^`]+)`/g, '<code>$1</code>')
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(/^#{1,3} (.+)$/gm, '<strong>$1</strong>')
    .replace(/^[-•] (.+)$/gm, '<li>$1</li>')
    .replace(/^\d+\. (.+)$/gm, '<li>$1</li>')
    .replace(/---/g, '<hr>')
    .replace(/\n/g, '<br>');
}

// ── Add message to chat ───────────────────────────────────────────
function addMessage(role, html, meta = null) {
  $('welcome-screen')?.remove();
  const msgs = $('messages');
  const isUser = role === 'user';
  const row = document.createElement('div');
  row.className = `msg-row ${role}`;

  let footerHTML = '';
  if (meta) {
      footerHTML = `<div class="msg-footer">
        <span class="msg-badge sql">SQL: ${meta.sql_results || 0}</span>
        ${meta.vector_results !== undefined ? `<span class="msg-badge" style="color:var(--amber);border-color:rgba(245,158,11,.2)">VEC: ${meta.vector_results}</span>` : ''}
        <span class="msg-badge type">${meta.type_requete || '—'}</span>
        ${meta.total_ms ? `<span class="msg-badge ms">${meta.total_ms}ms</span>` : ''}
        ${meta.mode ? `<span class="msg-badge" style="color:var(--text-3)">${meta.mode}</span>` : ''}
      </div>`;
  }

  row.innerHTML = `
    <div class="msg-av ${isUser ? 'av-user' : 'av-bot'}">${isUser ? '👤' : '🚛'}</div>
    <div class="msg-body">
      <div class="msg-meta">
        <span class="msg-name">${isUser ? 'OPÉRATEUR' : 'TRUCKMIND'}</span>
        <span class="msg-time">${now()}</span>
      </div>
      <div class="msg-bubble">${html}</div>
      ${footerHTML}
    </div>`;

  msgs.appendChild(row);
  msgs.scrollTop = msgs.scrollHeight;
}

function addTyping() {
  $('welcome-screen')?.remove();
  const msgs = $('messages');
  const el = document.createElement('div');
  el.className = 'typing-row';
  el.id = 'typing';
  el.innerHTML = `
    <div class="typing-dots">
      <div class="td"></div>
      <div class="td"></div>
      <div class="td"></div>
    </div>`;
  msgs.appendChild(el);
  msgs.scrollTop = msgs.scrollHeight;
}

// ── Send message ──────────────────────────────────────────────────
async function sendMessage() {
  if (STATE.loading) return;
  const input = $('chat-input');
  const q = input.value.trim();
  if (!q) return;

  // Command shortcuts
  if (q.startsWith('/dtc ')) {
    const code = q.slice(5).trim().toUpperCase();
    input.value = '';
    input.style.height = 'auto';
    switchTab('search');
    $('dtc-search-input').value = code;
    searchDTC(code);
    return;
  }
  if (q.startsWith('/vehicle ') || q.startsWith('/v ')) {
    const vid = q.split(' ')[1];
    input.value = '';
    input.style.height = 'auto';
    $('chat-input').value = `Quel est l'état complet du véhicule ${vid} ?`;
    sendMessage();
    return;
  }

  input.value = '';
  input.style.height = 'auto';
  STATE.loading = true;
  $('send-btn').disabled = true;

  addMessage('user', md(q));
  addTyping();

  try {
    const res = await fetch('/api/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ question: q })
    });
    const data = await res.json();
    $('typing')?.remove();

    if (data.error) {
      addMessage('bot', `⚠️ <strong>Erreur :</strong> ${data.error}`);
    } else {
      addMessage('bot', md(data.answer), {
        sql_results: data.sources?.sql_results,
        vector_results: data.sources?.vector_results,
        type_requete: data.type_requete,
        total_ms: data.meta?.total_ms,
        mode: data.meta?.mode
      });
    }
  } catch (e) {
    $('typing')?.remove();
    addMessage('bot', `⚠️ Erreur de connexion : ${e.message}`);
    toast('Connexion perdue', 'err');
  }

  STATE.loading = false;
  $('send-btn').disabled = false;
  input.focus();
}

// ── Quick chip send ───────────────────────────────────────────────
function chipSend(el) {
  $('chat-input').value = el.textContent.replace(/^[^\w]+/, '').trim();
  sendMessage();
}

// ── Input behavior ─────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  const chatInput = $('chat-input');

  chatInput.addEventListener('keydown', e => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  });

  chatInput.addEventListener('input', function () {
    this.style.height = 'auto';
    this.style.height = Math.min(this.scrollHeight, 120) + 'px';
  });
});

// ── Load system status ─────────────────────────────────────────────
async function loadStatus() {
  try {
    const res = await fetch('/api/status');
    const data = await res.json();
    if (data.ready) {
      STATE.ready = true;
      setStatus('online');
      $('kpi-dtc').textContent = (data.stats?.dtc_codes || 0).toLocaleString();
      $('kpi-total').textContent = (data.stats?.maintenance_records || 0).toLocaleString();
      toast(`Système prêt · ${data.stats?.maintenance_records} enregistrements`, 'ok');
    } else {
      setStatus('error');
      toast('Base de données non initialisée', 'err', 5000);
    }
  } catch (e) {
    setStatus('error');
    toast('Serveur inaccessible', 'err');
  }
}

// ── Load fleet stats ───────────────────────────────────────────────
async function loadFleetStats() {
  try {
    const res = await fetch('/api/fleet/stats');
    const data = await res.json();
    STATE.stats = data;

    const g = data.global || {};
    const total = g.total || 1;

    // Sidebar KPIs
    $('kpi-critique').textContent = g.nb_critique || 0;
    $('kpi-anomalies').textContent = g.nb_anomalies || 0;

    // Risk distribution segments
    const nc = g.nb_critique || 0;
    const ne = g.nb_eleve || 0;
    const nm = g.nb_modere || 0;
    const nf = g.nb_faible || 0;
    const sum = (nc + ne + nm + nf) || 1;

    setTimeout(() => {
      $('seg-critique').style.width = (nc / sum * 100) + '%';
      $('seg-eleve').style.width    = (ne / sum * 100) + '%';
      $('seg-modere').style.width   = (nm / sum * 100) + '%';
      $('seg-faible').style.width   = (nf / sum * 100) + '%';
    }, 300);

    $('leg-c').textContent = Math.round(nc / sum * 100) + '% Critique';
    $('leg-e').textContent = Math.round(ne / sum * 100) + '% Élevé';
    $('leg-m').textContent = Math.round(nm / sum * 100) + '% Modéré';
    $('leg-f').textContent = Math.round(nf / sum * 100) + '% Faible';

    // If dashboard is active, render it
    if (document.querySelector('.tab-content.active')?.id === 'tab-dashboard') {
      renderDashboard(data);
    }
  } catch (e) {
    console.warn('Stats load failed', e);
  }
}

// ── Load active alerts ─────────────────────────────────────────────
async function loadAlerts() {
  try {
    const res = await fetch('/api/fleet/alerts?lampe=ROUGE&limit=20');
    const data = await res.json();
    const list = $('alert-list');
    STATE.alerts = data.alerts || [];

    if (!STATE.alerts.length) {
      list.innerHTML = '<div style="font-family:var(--mono);font-size:10px;color:var(--text-3);padding:8px">Aucune alerte rouge</div>';
      return;
    }

    list.innerHTML = STATE.alerts.map(a => `
      <div class="alert-item rouge" onclick="askAboutVehicle('${a.vehicule_id}')">
        <div class="ai-lamp">🔴</div>
        <div class="ai-body">
          <div class="ai-vid">${a.vehicule_id}</div>
          <div class="ai-param">${a.parametre}</div>
          <div class="ai-val">${a.valeur_mesuree} ${a.unite || ''} (${a.depassement})</div>
        </div>
      </div>
    `).join('');
  } catch (e) {
    console.warn('Alerts load failed', e);
  }
}

function askAboutVehicle(vid) {
  switchTab('chat');
  $('chat-input').value = `Quel est l'état du véhicule ${vid} et quelles actions sont requises ?`;
  sendMessage();
}

// ── Dashboard rendering ────────────────────────────────────────────
function renderDashboard(data) {
  const g = data.global || {};

  // ── Gauge (score prédictif moyen) ──────────────────────────────
  const score = g.avg_score || 0;
  const dashLen = 204;
  const offset = dashLen - (score * dashLen);
  const gaugeArc = document.getElementById('gauge-arc');
  if (gaugeArc) {
    setTimeout(() => {
      gaugeArc.style.strokeDashoffset = offset;
      const col = score > 0.8 ? '#ef4444'
                : score > 0.5 ? '#f97316'
                : score > 0.2 ? '#eab308'
                : '#22c55e';
      gaugeArc.style.stroke = col;
    }, 200);
    const gv = $('gauge-val');
    if (gv) {
      gv.textContent = score.toFixed(3);
      gv.style.fill = score > 0.5 ? '#f97316' : '#f0f4f8';
    }
  }

  // ── Freins bar chart ────────────────────────────────────────────
  const freins = data.freins || {};
  const totalF = Object.values(freins).reduce((a, b) => a + b, 0) || 1;
  const freinsColors = {
    bon:     'var(--green)',
    moyen:   'var(--yellow)',
    mauvais: 'var(--red)',
    inconnu: 'var(--text-3)'
  };
  const fChart = $('freins-chart');
  if (fChart) {
    fChart.innerHTML = Object.entries(freins).map(([k, v]) => `
      <div class="bar-row">
        <div class="bar-label">${k}</div>
        <div class="bar-track">
          <div class="bar-fill"
               style="width:0%;background:${freinsColors[k] || 'var(--blue)'}"
               data-target="${(v / totalF * 100).toFixed(1)}">
          </div>
        </div>
        <div class="bar-val">${((v / totalF) * 100).toFixed(0)}%</div>
      </div>`).join('');
  }

  // ── Paramètres moyens ───────────────────────────────────────────
  const pList = $('params-list');
  if (pList) {
    pList.innerHTML = [
      { l: 'Temp. moteur moy.',   v: `${(g.avg_temp     || 0).toFixed(1)} °C`,     warn: (g.avg_temp || 0) > 100 },
      { l: 'Pression pneus moy.', v: `${(g.avg_pression || 0).toFixed(1)} PSI` },
      { l: 'Qualité huile moy.',  v: `${(g.avg_huile    || 0).toFixed(1)} %` },
      { l: 'Consommation moy.',   v: `${(g.avg_carburant|| 0).toFixed(1)} L/100km` },
      { l: 'Entretien nécessaire',v: `${g.nb_entretien  || 0} / ${g.total || 0}` }
    ].map(r => `
      <div class="stat-row">
        <div class="stat-label">${r.l}</div>
        <div class="stat-val" style="${r.warn ? 'color:var(--amber)' : ''}">${r.v}</div>
      </div>`).join('');
  }

  // ── Entretien bar chart ─────────────────────────────────────────
  const ents = data.entretiens || [];
  const maxEnt = Math.max(...ents.map(e => e.nb), 1);
  const entColors = ['var(--blue)', 'var(--cyan)', 'var(--purple)', 'var(--amber)', 'var(--green)'];
  const eChart = $('entretien-chart');
  if (eChart) {
    eChart.innerHTML = ents.map((e, i) => `
      <div class="bar-row">
        <div class="bar-label" title="${e.type}">${e.type.length > 12 ? e.type.slice(0, 12) + '…' : e.type}</div>
        <div class="bar-track">
          <div class="bar-fill"
               style="width:0%;background:${entColors[i % entColors.length]}"
               data-target="${(e.nb / maxEnt * 100).toFixed(1)}">
          </div>
        </div>
        <div class="bar-val">${e.nb}</div>
      </div>`).join('');
  }

  // ── Alertes par lampe ───────────────────────────────────────────
  const alertes = data.alertes || {};
  const aList = $('alertes-list');
  if (aList) {
    aList.innerHTML = Object.entries(alertes).map(([k, v]) => {
      const icon  = k === 'ROUGE' ? '🔴' : k === 'JAUNE' ? '🟡' : '🟢';
      const color = k === 'ROUGE' ? 'var(--red)' : k === 'JAUNE' ? 'var(--amber)' : 'var(--green)';
      return `
        <div class="stat-row">
          <div class="stat-label">${icon} ${k}</div>
          <div class="stat-val" style="color:${color}">${v.toLocaleString()}</div>
        </div>`;
    }).join('');
  }

  // ── Animate bars (wait for DOM) ─────────────────────────────────
  setTimeout(() => {
    document.querySelectorAll('.bar-fill[data-target]').forEach(el => {
      el.style.width = el.dataset.target + '%';
    });
  }, 100);

  // ── Load top risk table ─────────────────────────────────────────
  loadTopRisk();
}

async function loadTopRisk() {
  try {
    const res = await fetch('/api/fleet/top-risk?limit=10');
    const data = await res.json();
    const tbody = $('risk-table-body');
    if (!tbody) return;

    tbody.innerHTML = (data.vehicles || []).map(v => `
      <tr>
        <td><a class="vid-link" onclick="askAboutVehicle('${v.vehicule_id}')">${v.vehicule_id}</a></td>
        <td style="font-family:var(--mono);font-size:11px;color:var(--text-0)">${(v.score_max || 0).toFixed(4)}</td>
        <td><span class="risk-pill ${v.niveau_risque}">${v.niveau_risque}</span></td>
        <td style="font-family:var(--mono);font-size:11px;color:var(--text-2)">${v.nb_interventions || 0}</td>
        <td style="font-family:var(--mono);font-size:11px;color:${(v.nb_anomalies || 0) > 0 ? 'var(--amber)' : 'var(--text-3)'}">${v.nb_anomalies || 0}</td>
        <td style="font-family:var(--mono);font-size:11px;color:var(--text-2)">${(v.avg_huile || 0).toFixed(1)}%</td>
        <td style="font-size:11px;color:var(--text-3)">${v.derniere_intervention || '—'}</td>
      </tr>`).join('');
  } catch (e) {
    console.warn('Top risk load failed', e);
  }
}

// ── DTC Search ─────────────────────────────────────────────────────
async function searchDTC(queryOverride) {
  const q = queryOverride || $('dtc-search-input')?.value?.trim();
  if (!q) return;

  const container = $('dtc-results');
  container.innerHTML = '<div style="font-family:var(--mono);font-size:10px;color:var(--text-3);text-align:center;padding:30px">Recherche en cours...</div>';

  try {
    const res = await fetch(`/api/knowledge/search?q=${encodeURIComponent(q)}&limit=10`);
    const data = await res.json();
    const results = data.results || [];

    if (!results.length) {
      container.innerHTML = `
        <div class="empty-state">
          <div class="empty-icon">🔍</div>
          <div class="empty-text">Aucun résultat pour "${q}"</div>
        </div>`;
      return;
    }

    container.innerHTML = results.map(r => {
      const gravClass = r.gravite || 'faible';
      return `
        <div class="dtc-result">
          <div class="dtc-header">
            <div class="dtc-code">${r.dtc}</div>
            <div>
              <div class="dtc-system">${r.systeme}</div>
            </div>
            <div style="margin-left:auto">
              <span class="dtc-gravity ${gravClass}">${r.gravite ? r.gravite.toUpperCase() : '—'}</span>
            </div>
          </div>
          <div class="dtc-symptome">${r.symptome}</div>
          <div class="dtc-piece">🔩 Pièce concernée : ${r.piece}</div>
          <div style="margin-top:12px">
            <button class="dtc-analyze-btn" onclick="chatFromDTC('${r.dtc}')">
              💬 Analyser ce code
            </button>
          </div>
        </div>`;
    }).join('');
  } catch (e) {
    container.innerHTML = `
      <div class="empty-state">
        <div class="empty-icon">⚠️</div>
        <div class="empty-text">Erreur : ${e.message}</div>
      </div>`;
  }
}

function chatFromDTC(code) {
  switchTab('chat');
  $('chat-input').value = `Explique le code DTC ${code} et donne les actions de diagnostic recommandées.`;
  sendMessage();
}

// ── Initialization ─────────────────────────────────────────────────
async function init() {
  setStatus('loading');
  await loadStatus();
  await Promise.all([loadFleetStats(), loadAlerts()]);
}

// Start
init();

// Refresh alerts every 60 seconds
setInterval(loadAlerts, 60000);