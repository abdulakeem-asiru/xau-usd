let equityChart = null;
let currentMode = 'practice';
let currentlyPaused = false;

function fmt(n, decimals = 2) {
  if (n === null || n === undefined) return '—';
  return Number(n).toLocaleString(undefined, { minimumFractionDigits: decimals, maximumFractionDigits: decimals });
}

async function refreshStatus() {
  const res = await apiFetch('/api/config/bot-state');
  const s = await res.json();
  currentMode = s.mode;
  currentlyPaused = s.is_paused;

  const stateEl = document.getElementById('stat-state');
  stateEl.textContent = s.is_paused ? 'PAUSED' : (s.is_running ? 'RUNNING' : 'STOPPED');
  stateEl.className = 'text-lg font-semibold mt-1 ' + (s.is_paused ? 'text-yellow-400' : 'text-green-400');

  const modeEl = document.getElementById('stat-mode');
  modeEl.textContent = s.mode.toUpperCase();
  modeEl.className = 'text-lg font-semibold mt-1 ' + (s.mode === 'live' ? 'text-red-400' : 'text-neutral-200');

  document.getElementById('stat-equity').textContent = '$' + fmt(s.equity);
  const pnlEl = document.getElementById('stat-pnl');
  pnlEl.textContent = (s.today_realized_pnl >= 0 ? '+' : '') + fmt(s.today_realized_pnl) + (s.halted ? ' (HALTED)' : '');
  pnlEl.className = 'text-lg font-semibold mt-1 ' + (s.today_realized_pnl >= 0 ? 'text-green-400' : 'text-red-400');
  document.getElementById('stat-positions').textContent = s.open_positions_count;

  document.getElementById('live-banner').classList.toggle('hidden', s.mode !== 'live');
  document.getElementById('btn-live').classList.toggle('hidden', s.mode === 'live');
  document.getElementById('btn-revert').classList.toggle('hidden', s.mode !== 'live');

  const pauseBtn = document.getElementById('btn-pause');
  pauseBtn.textContent = s.is_paused ? '▶️ Resume' : '⏸ Pause';
}

async function toggleBotPause() {
  const endpoint = currentlyPaused ? '/api/bot/resume' : '/api/bot/pause';
  await apiFetch(endpoint, { method: 'POST' });
  await refreshStatus();
}

async function killSwitch() {
  if (!confirm('Close ALL open positions and halt the bot immediately?')) return;
  const res = await apiFetch('/api/kill-switch', { method: 'POST' });
  const data = await res.json();
  alert(`Closed ${data.closed_trade_ids.length} position(s).` + (data.failed_trade_ids.length ? ` FAILED to close: ${data.failed_trade_ids}` : ''));
  await refreshAll();
}

function openLiveModal() {
  document.getElementById('live-modal').classList.remove('hidden');
}
function closeLiveModal() {
  document.getElementById('live-modal').classList.add('hidden');
  document.getElementById('live-modal-error').classList.add('hidden');
}
async function confirmLive() {
  const phrase = document.getElementById('live-phrase').value;
  const password = document.getElementById('live-password').value;
  const res = await apiFetch('/api/mode/request-live', {
    method: 'POST', body: JSON.stringify({ confirmation_phrase: phrase, password }),
  });
  if (res.ok) {
    closeLiveModal();
    await refreshStatus();
  } else {
    const data = await res.json().catch(() => ({}));
    const errEl = document.getElementById('live-modal-error');
    errEl.textContent = data.detail || 'Failed to switch to live mode.';
    errEl.classList.remove('hidden');
  }
}
async function revertPractice() {
  if (!confirm('Revert to practice mode?')) return;
  await apiFetch('/api/mode/revert-practice', { method: 'POST' });
  await refreshStatus();
}

async function refreshPositions() {
  const res = await apiFetch('/api/positions');
  const positions = await res.json();
  const el = document.getElementById('positions-table');
  if (positions.length === 0) {
    el.innerHTML = '<p class="text-neutral-600">No open positions.</p>';
    return;
  }
  el.innerHTML = `<table class="w-full text-xs"><thead class="text-neutral-500"><tr>
      <th class="text-left py-1">Side</th><th class="text-right">Lots</th><th class="text-right">Entry</th>
      <th class="text-right">Current</th><th class="text-right">SL</th><th class="text-right">PnL</th></tr></thead><tbody>
    ${positions.map(p => `<tr class="border-t border-neutral-800">
      <td class="py-1 ${p.side === 'buy' ? 'text-green-400' : 'text-red-400'}">${p.side.toUpperCase()}</td>
      <td class="text-right">${fmt(p.volume, 2)}</td>
      <td class="text-right">${fmt(p.entry_price)}</td>
      <td class="text-right">${fmt(p.current_price)}</td>
      <td class="text-right">${fmt(p.stop_loss_price)}</td>
      <td class="text-right ${p.unrealized_pnl >= 0 ? 'text-green-400' : 'text-red-400'}">${fmt(p.unrealized_pnl)}</td>
    </tr>`).join('')}</tbody></table>`;
}

async function refreshTrades() {
  const res = await apiFetch('/api/trades?limit=15');
  const trades = await res.json();
  const el = document.getElementById('trades-table');
  if (trades.length === 0) {
    el.innerHTML = '<p class="text-neutral-600">No trades yet.</p>';
    return;
  }
  el.innerHTML = `<table class="w-full text-xs"><thead class="text-neutral-500"><tr>
      <th class="text-left py-1">Side</th><th class="text-left">Status</th><th class="text-right">Entry</th>
      <th class="text-right">Exit</th><th class="text-right">PnL</th></tr></thead><tbody>
    ${trades.map(t => `<tr class="border-t border-neutral-800">
      <td class="py-1 ${t.side === 'buy' ? 'text-green-400' : 'text-red-400'}">${t.side.toUpperCase()}</td>
      <td class="text-neutral-400">${t.status}${t.close_reason ? ' (' + t.close_reason + ')' : ''}</td>
      <td class="text-right">${fmt(t.entry_price)}</td>
      <td class="text-right">${t.exit_price ? fmt(t.exit_price) : '—'}</td>
      <td class="text-right ${t.pnl >= 0 ? 'text-green-400' : (t.pnl < 0 ? 'text-red-400' : '')}">${t.pnl !== null ? fmt(t.pnl) : '—'}</td>
    </tr>`).join('')}</tbody></table>`;
}

async function refreshEquityChart() {
  const res = await apiFetch('/api/equity-curve?limit=500');
  const points = await res.json();
  const labels = points.map(p => new Date(p.ts).toLocaleString());
  const data = points.map(p => p.equity);

  if (equityChart) {
    equityChart.data.labels = labels;
    equityChart.data.datasets[0].data = data;
    equityChart.update();
    return;
  }
  const ctx = document.getElementById('equity-chart').getContext('2d');
  equityChart = new Chart(ctx, {
    type: 'line',
    data: { labels, datasets: [{ label: 'Equity', data, borderColor: '#f59e0b', backgroundColor: 'rgba(245,158,11,0.1)', tension: 0.15, pointRadius: 0, fill: true }] },
    options: {
      responsive: true,
      plugins: { legend: { display: false } },
      scales: {
        x: { display: false },
        y: { ticks: { color: '#8b93a3' }, grid: { color: '#1f2530' } },
      },
    },
  });
}

async function loadStrategyConfig() {
  const res = await apiFetch('/api/config/strategy');
  const cfg = await res.json();
  const select = document.getElementById('strategy-select');
  select.innerHTML = cfg.available_strategies.map(name =>
    `<option value="${name}" ${name === cfg.strategy_name ? 'selected' : ''}>${name}</option>`).join('');
  document.getElementById('strategy-params').value = JSON.stringify(cfg.strategy_params, null, 2);
}
async function saveStrategyConfig() {
  const msg = document.getElementById('strategy-save-msg');
  let params;
  try {
    params = JSON.parse(document.getElementById('strategy-params').value || '{}');
  } catch (e) {
    msg.textContent = 'Invalid JSON in params.';
    msg.className = 'text-xs text-red-400';
    return;
  }
  const res = await apiFetch('/api/config/strategy', {
    method: 'PUT', body: JSON.stringify({ strategy_name: document.getElementById('strategy-select').value, strategy_params: params }),
  });
  if (res.ok) {
    msg.textContent = 'Saved.';
    msg.className = 'text-xs text-green-400';
  } else {
    const data = await res.json().catch(() => ({}));
    msg.textContent = data.detail || 'Failed to save.';
    msg.className = 'text-xs text-red-400';
  }
}

async function loadRiskConfig() {
  const res = await apiFetch('/api/config/risk');
  const cfg = await res.json();
  document.getElementById('risk-pct').value = cfg.risk_pct_per_trade;
  document.getElementById('max-daily-loss').value = cfg.max_daily_loss_pct;
  document.getElementById('max-positions').value = cfg.max_concurrent_positions;
}
async function saveRiskConfig() {
  const msg = document.getElementById('risk-save-msg');
  const payload = {
    risk_pct_per_trade: parseFloat(document.getElementById('risk-pct').value),
    max_daily_loss_pct: parseFloat(document.getElementById('max-daily-loss').value),
    max_concurrent_positions: parseInt(document.getElementById('max-positions').value, 10),
  };
  const res = await apiFetch('/api/config/risk', { method: 'PUT', body: JSON.stringify(payload) });
  if (res.ok) {
    msg.textContent = 'Saved.';
    msg.className = 'text-xs text-green-400';
  } else {
    const data = await res.json().catch(() => ({}));
    msg.textContent = (data.detail && JSON.stringify(data.detail)) || 'Failed to save.';
    msg.className = 'text-xs text-red-400';
  }
}

async function refreshAll() {
  await Promise.all([refreshStatus(), refreshPositions(), refreshTrades(), refreshEquityChart()]);
}

refreshAll();
loadStrategyConfig();
loadRiskConfig();
setInterval(refreshAll, 5000);
