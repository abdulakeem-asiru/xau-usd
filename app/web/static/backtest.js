let btChart = null;

function fmt(n, decimals = 2) {
  if (n === null || n === undefined) return '—';
  return Number(n).toLocaleString(undefined, { minimumFractionDigits: decimals, maximumFractionDigits: decimals });
}

async function loadStrategies() {
  const res = await apiFetch('/api/config/strategy');
  const cfg = await res.json();
  document.getElementById('bt-strategy').innerHTML = cfg.available_strategies
    .map(name => `<option value="${name}">${name}</option>`).join('');

  const end = new Date();
  const start = new Date();
  start.setMonth(start.getMonth() - 6);
  document.getElementById('bt-end').value = end.toISOString().slice(0, 10);
  document.getElementById('bt-start').value = start.toISOString().slice(0, 10);
}

async function runBacktest() {
  const statusEl = document.getElementById('bt-status');
  let params;
  try {
    params = JSON.parse(document.getElementById('bt-params').value || '{}');
  } catch (e) {
    statusEl.textContent = 'Invalid JSON in strategy params.';
    return;
  }
  const payload = {
    strategy_name: document.getElementById('bt-strategy').value,
    strategy_params: params,
    instrument: document.getElementById('bt-instrument').value,
    timeframe: document.getElementById('bt-timeframe').value,
    start_date: document.getElementById('bt-start').value,
    end_date: document.getElementById('bt-end').value,
    initial_balance: parseFloat(document.getElementById('bt-balance').value),
    risk_pct_per_trade: parseFloat(document.getElementById('bt-risk').value),
    max_daily_loss_pct: parseFloat(document.getElementById('bt-daily-loss').value),
    max_concurrent_positions: parseInt(document.getElementById('bt-max-positions').value, 10),
    contract_size: parseFloat(document.getElementById('bt-contract-size').value),
    min_volume: parseFloat(document.getElementById('bt-min-volume').value),
    max_volume: parseFloat(document.getElementById('bt-max-volume').value),
    volume_step: parseFloat(document.getElementById('bt-volume-step').value),
  };
  statusEl.textContent = 'Starting backtest…';
  const res = await apiFetch('/api/backtest/run', { method: 'POST', body: JSON.stringify(payload) });
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    statusEl.textContent = 'Failed to start: ' + (data.detail || res.status);
    return;
  }
  const { backtest_run_id } = await res.json();
  statusEl.textContent = `Running (id ${backtest_run_id})… this can take a while for long date ranges.`;
  pollBacktest(backtest_run_id);
}

async function pollBacktest(id) {
  const statusEl = document.getElementById('bt-status');
  const res = await apiFetch(`/api/backtest/${id}`);
  const run = await res.json();
  if (run.status === 'running') {
    setTimeout(() => pollBacktest(id), 3000);
    return;
  }
  if (run.status === 'failed') {
    statusEl.textContent = 'Backtest failed: ' + (run.error_message || 'unknown error');
    return;
  }
  statusEl.textContent = 'Complete.';
  await renderResults(run);
}

async function renderResults(run) {
  document.getElementById('bt-results').classList.remove('hidden');
  document.getElementById('res-trades').textContent = run.total_trades ?? 0;
  document.getElementById('res-winrate').textContent = run.win_rate !== null ? fmt(run.win_rate, 1) + '%' : '—';
  document.getElementById('res-drawdown').textContent = run.max_drawdown_pct !== null ? fmt(run.max_drawdown_pct, 1) + '%' : '—';
  document.getElementById('res-sharpe').textContent = run.sharpe_ratio !== null ? fmt(run.sharpe_ratio, 2) : '—';
  document.getElementById('res-pf').textContent = run.profit_factor !== null ? fmt(run.profit_factor, 2) : '∞';

  const tradesRes = await apiFetch(`/api/backtest/${run.id}/trades`);
  const trades = await tradesRes.json();

  let cumulative = 0;
  const labels = [];
  const data = [];
  for (const t of trades) {
    cumulative += t.pnl || 0;
    labels.push(new Date(t.exit_time || t.entry_time).toLocaleDateString());
    data.push(cumulative);
  }
  const ctx = document.getElementById('bt-chart').getContext('2d');
  if (btChart) btChart.destroy();
  btChart = new Chart(ctx, {
    type: 'line',
    data: { labels, datasets: [{ label: 'Cumulative PnL', data, borderColor: '#f59e0b', backgroundColor: 'rgba(245,158,11,0.1)', tension: 0.15, pointRadius: 0, fill: true }] },
    options: { responsive: true, plugins: { legend: { display: false } }, scales: { x: { display: false }, y: { ticks: { color: '#8b93a3' }, grid: { color: '#1f2530' } } } },
  });

  const tableEl = document.getElementById('bt-trades-table');
  if (trades.length === 0) {
    tableEl.innerHTML = '<p class="text-neutral-600">No trades in this period.</p>';
    return;
  }
  tableEl.innerHTML = `<table class="w-full text-xs"><thead class="text-neutral-500 sticky top-0 bg-[#141922]"><tr>
      <th class="text-left py-1">Entry time</th><th class="text-left">Side</th><th class="text-right">Entry</th>
      <th class="text-right">Exit</th><th class="text-left">Reason</th><th class="text-right">PnL</th></tr></thead><tbody>
    ${trades.map(t => `<tr class="border-t border-neutral-800">
      <td class="py-1">${new Date(t.entry_time).toLocaleString()}</td>
      <td class="${t.side === 'buy' ? 'text-green-400' : 'text-red-400'}">${t.side.toUpperCase()}</td>
      <td class="text-right">${fmt(t.entry_price)}</td>
      <td class="text-right">${t.exit_price ? fmt(t.exit_price) : '—'}</td>
      <td>${t.exit_reason || '—'}</td>
      <td class="text-right ${t.pnl >= 0 ? 'text-green-400' : 'text-red-400'}">${fmt(t.pnl)}</td>
    </tr>`).join('')}</tbody></table>`;
}

loadStrategies();
