import {
  LineChart, Line, BarChart, Bar, XAxis, YAxis, CartesianGrid,
  Tooltip, ResponsiveContainer, Legend, ReferenceLine,
} from 'recharts';

const COLORS = ['#2962ff', '#26a69a', '#ff9800', '#ef5350'];

const tooltipStyle = {
  background: '#1e222d',
  border: '1px solid #363c4e',
  borderRadius: 4,
  fontSize: 13,
};


export function SingleView({ data, sortCol, setSortCol, sortAsc, setSortAsc }) {
  const s = data.stats;
  const equityData = data.equity_curve?.map((v, i) => ({ trade: i, equity: v })) || [];

  function handleSort(col) {
    if (sortCol === col) setSortAsc(!sortAsc);
    else { setSortCol(col); setSortAsc(true); }
  }

  const sortedTrades = [...(data.trades || [])].sort((a, b) => {
    const va = a[sortCol], vb = b[sortCol];
    if (va < vb) return sortAsc ? -1 : 1;
    if (va > vb) return sortAsc ? 1 : -1;
    return 0;
  });

  const isReal = data.source === 'chain_replay';

  return (
    <div className="bt-results">
      <div className="bt-source-bar">
        <span className={`bt-source-badge ${isReal ? 'real' : 'sim'}`}>
          {isReal ? 'Real Market Data' : 'BS Simulated'}
        </span>
        {data.data_issues?.length > 0 && (
          <span className="bt-data-warn">
            {data.data_issues.length} data issue{data.data_issues.length > 1 ? 's' : ''} detected
          </span>
        )}
      </div>

      <div className="bt-stat-strip">
        <StatCell label="Win Rate" value={`${s.win_rate?.toFixed(1)}%`} positive={s.win_rate > 50} />
        <StatCell label="Total P&L" value={`$${s.total_pnl?.toFixed(0)}`} positive={s.total_pnl > 0} />
        <StatCell label="Trades" value={s.total_trades} neutral />
        <StatCell label="Profit Factor" value={s.profit_factor?.toFixed(2)} positive={s.profit_factor > 1} />
        <StatCell label="Sharpe" value={s.sharpe_ratio?.toFixed(2)} positive={s.sharpe_ratio > 0} />
        <StatCell label="Max DD" value={`$${s.max_drawdown?.toFixed(0)}`} positive={false} />
        <StatCell label="Avg Win" value={`$${s.avg_win?.toFixed(0)}`} positive={true} />
        <StatCell label="Avg Loss" value={`$${s.avg_loss?.toFixed(0)}`} positive={false} />
      </div>

      <div className="bt-charts-row">
        {equityData.length > 1 && (
          <div className="tv-chart">
            <h3>Equity Curve</h3>
            <ResponsiveContainer width="100%" height={340}>
              <LineChart data={equityData}>
                <CartesianGrid strokeDasharray="3 3" stroke="#363c4e" />
                <XAxis dataKey="trade" stroke="#545862" fontSize={11} tickLine={false} />
                <YAxis stroke="#545862" fontSize={11} tickFormatter={v => `$${v}`} tickLine={false} />
                <Tooltip contentStyle={tooltipStyle} formatter={v => [`$${v.toFixed(0)}`, 'Equity']} />
                <ReferenceLine y={0} stroke="#545862" strokeDasharray="3 3" />
                <Line type="monotone" dataKey="equity" stroke="#2962ff" dot={false} strokeWidth={2} />
              </LineChart>
            </ResponsiveContainer>
          </div>
        )}

        {data.pnl_distribution?.length > 0 && (
          <div className="tv-chart">
            <h3>P&L Distribution</h3>
            <ResponsiveContainer width="100%" height={340}>
              <BarChart data={data.pnl_distribution}>
                <CartesianGrid strokeDasharray="3 3" stroke="#363c4e" />
                <XAxis dataKey="bin_start" stroke="#545862" fontSize={10} tickFormatter={v => `$${v}`} tickLine={false} />
                <YAxis stroke="#545862" fontSize={11} tickLine={false} />
                <Tooltip contentStyle={tooltipStyle} formatter={v => [v, 'Trades']} labelFormatter={v => `$${v}`} />
                <Bar dataKey="count" fill="#2962ff" radius={[2, 2, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        )}
      </div>

      <div className="bt-breakdowns">
        {data.regime_breakdown && Object.keys(data.regime_breakdown).length > 0 && (
          <BreakdownTable title="By Regime" data={data.regime_breakdown} />
        )}
        {data.dte_breakdown && Object.keys(data.dte_breakdown).length > 0 && (
          <BreakdownTable title="By DTE" data={data.dte_breakdown} />
        )}
      </div>

      {sortedTrades.length > 0 && (
        <div className="bt-trades-section">
          <div className="bt-trades-header">
            <h3>Trade Log</h3>
            <span className="bt-trades-count">{data.trades_count || sortedTrades.length}</span>
          </div>
          <table className="tv-table">
            <thead>
              <tr>
                {[
                  ['entry_date', 'Entry'], ['exit_date', 'Exit'],
                  ['entry_price', 'Entry $'], ['exit_price', 'Exit $'],
                  ['pnl', 'P&L'], ['pnl_pct', 'P&L %'], ['dte_at_entry', 'DTE'],
                  ['regime', 'Regime'], ['bias_label', 'Bias'],
                  ['dealer_regime', 'Dealer'], ['exit_reason', 'Reason'],
                ].map(([col, label]) => (
                  <th key={col} onClick={() => handleSort(col)}>
                    {label}
                    {sortCol === col && <span className="sort-arrow">{sortAsc ? ' ▲' : ' ▼'}</span>}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {sortedTrades.map((t, i) => (
                <tr key={i}>
                  <td>{t.entry_date}</td>
                  <td>{t.exit_date}</td>
                  <td>${t.entry_price?.toFixed(2)}</td>
                  <td>${t.exit_price?.toFixed(2)}</td>
                  <td className={t.pnl > 0 ? 'green' : 'red'}>${t.pnl?.toFixed(0)}</td>
                  <td className={t.pnl_pct > 0 ? 'green' : 'red'}>{t.pnl_pct?.toFixed(1)}%</td>
                  <td>{t.dte_at_entry}</td>
                  <td><span className="bt-regime-tag">{t.regime}</span></td>
                  <td>{t.bias_label || '--'}</td>
                  <td>{t.dealer_regime || '--'}</td>
                  <td className="muted">{t.exit_reason}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}


export function CompareView({ data }) {
  const strategies = data.strategies || {};
  const names = Object.keys(strategies).filter(k => !strategies[k].error);

  const maxLen = Math.max(...names.map(n => strategies[n].equity_curve?.length || 0));
  const combinedEquity = [];
  for (let i = 0; i < maxLen; i++) {
    const point = { trade: i };
    names.forEach(n => {
      const curve = strategies[n].equity_curve || [];
      point[n] = i < curve.length ? curve[i] : curve[curve.length - 1] || 0;
    });
    combinedEquity.push(point);
  }

  return (
    <div className="bt-results">
      <div className="bt-compare-table-wrap">
        <table className="tv-table bt-compare-table">
          <thead>
            <tr>
              <th>Metric</th>
              {names.map((n, i) => (
                <th key={n}>
                  <span className="bt-compare-dot" style={{ background: COLORS[i % COLORS.length] }} />
                  {n.replace(/_/g, ' ')}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {[
              ['Win Rate', s => `${s.win_rate?.toFixed(1)}%`, s => s.win_rate > 50],
              ['Total P&L', s => `$${s.total_pnl?.toFixed(0)}`, s => s.total_pnl > 0],
              ['Trades', s => s.total_trades, () => null],
              ['Profit Factor', s => s.profit_factor?.toFixed(2), s => s.profit_factor > 1],
              ['Sharpe', s => s.sharpe_ratio?.toFixed(2), s => s.sharpe_ratio > 0],
              ['Max DD', s => `$${s.max_drawdown?.toFixed(0)}`, () => null],
              ['Avg Win', s => `$${s.avg_win?.toFixed(0)}`, () => null],
              ['Avg Loss', s => `$${s.avg_loss?.toFixed(0)}`, () => null],
            ].map(([label, fmt, isGood]) => (
              <tr key={label}>
                <td className="bt-compare-label">{label}</td>
                {names.map(n => {
                  const st = strategies[n]?.stats;
                  if (!st) return <td key={n}>--</td>;
                  const g = isGood(st);
                  return (
                    <td key={n} className={g === true ? 'green' : g === false ? 'red' : ''}>
                      {fmt(st)}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {combinedEquity.length > 1 && (
        <div className="tv-chart">
          <h3>Equity Curves</h3>
          <ResponsiveContainer width="100%" height={340}>
            <LineChart data={combinedEquity}>
              <CartesianGrid strokeDasharray="3 3" stroke="#363c4e" />
              <XAxis dataKey="trade" stroke="#545862" fontSize={11} tickLine={false} />
              <YAxis stroke="#545862" fontSize={11} tickFormatter={v => `$${v}`} tickLine={false} />
              <Tooltip contentStyle={tooltipStyle} formatter={v => [`$${v?.toFixed(0)}`, '']} />
              <ReferenceLine y={0} stroke="#545862" strokeDasharray="3 3" />
              <Legend wrapperStyle={{ fontSize: 13, paddingTop: 8 }} />
              {names.map((n, i) => (
                <Line key={n} type="monotone" dataKey={n}
                  stroke={COLORS[i % COLORS.length]}
                  dot={false} strokeWidth={2}
                  name={n.replace(/_/g, ' ')} />
              ))}
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}
    </div>
  );
}


function StatCell({ label, value, positive, neutral }) {
  const cls = neutral ? '' : positive ? 'green' : 'red';
  return (
    <div className="stat">
      <div className="stat-label">{label}</div>
      <div className={`stat-value ${cls}`}>{value}</div>
    </div>
  );
}


function BreakdownTable({ title, data }) {
  return (
    <div className="tv-panel">
      <div className="tv-panel-header">
        <span className="tv-panel-title">{title}</span>
      </div>
      <table className="tv-table">
        <thead>
          <tr>
            <th>{title.replace('By ', '')}</th>
            <th>Trades</th>
            <th>Win Rate</th>
            <th>Avg P&L</th>
            <th>Total P&L</th>
          </tr>
        </thead>
        <tbody>
          {Object.entries(data).map(([key, d]) => (
            <tr key={key}>
              <td><span className="bt-regime-tag">{key}</span></td>
              <td>{d.count}</td>
              <td className={d.win_rate > 50 ? 'green' : 'red'}>{d.win_rate?.toFixed(1)}%</td>
              <td className={d.avg_pnl > 0 ? 'green' : 'red'}>${d.avg_pnl?.toFixed(0)}</td>
              <td className={d.total_pnl > 0 ? 'green' : 'red'}>${d.total_pnl?.toFixed(0)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}


export function Guide({ onClose }) {
  return (
    <div className="bt-guide-backdrop" onClick={onClose}>
      <div className="bt-guide" onClick={e => e.stopPropagation()}>
        <div className="bt-guide-header">
          <h3>Backtest Guide</h3>
          <button className="bt-guide-close" onClick={onClose}>✕</button>
        </div>
        <div className="bt-guide-cols">
          <div className="bt-guide-section">
            <h4>Data Source</h4>
            <p><strong>BS Model</strong> — Fast, synthetic prices from Black-Scholes. Good for quick iteration but can overestimate win rates.</p>
            <p><strong>Real Data</strong> — Actual bid/ask/mid from collected chain snapshots. Slower, limited to dates with data, but trustworthy.</p>
          </div>
          <div className="bt-guide-section">
            <h4>Signal Filters</h4>
            <p>Toggle <strong>Regime</strong>, <strong>Bias</strong>, <strong>Dealer</strong> to only take trades when that signal layer agrees.</p>
            <p><strong>Edge &gt; N%</strong> — only trade when GARCH-estimated edge exceeds this threshold.</p>
          </div>
          <div className="bt-guide-section">
            <h4>Charts</h4>
            <p><strong>Equity Curve</strong> — Cumulative P&L trade by trade.</p>
            <p><strong>P&L Distribution</strong> — Where wins and losses cluster.</p>
          </div>
          <div className="bt-guide-section">
            <h4>Breakdowns</h4>
            <p><strong>By Regime</strong> — Performance in each vol regime.</p>
            <p><strong>By DTE</strong> — Performance by days-to-expiry at entry.</p>
          </div>
        </div>
      </div>
    </div>
  );
}
