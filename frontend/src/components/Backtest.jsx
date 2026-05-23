import { useState } from 'react';
import { useApi } from '../hooks/useApi';
import {
  LineChart, Line, BarChart, Bar, XAxis, YAxis, CartesianGrid,
  Tooltip, ResponsiveContainer, Legend, ReferenceLine,
} from 'recharts';
import './Dashboard.css';

const ACTIVE_STRATEGIES = [
  { value: 'iron_condor', label: 'Iron Condor' },
  { value: 'short_put_spread', label: 'Credit Spread' },
  { value: 'long_call_spread', label: 'Debit Spread' },
  { value: 'butterfly', label: 'Butterfly' },
];

const COLORS = ['#3b82f6', '#10b981', '#f59e0b', '#ef4444'];

export default function Backtest() {
  const [showGuide, setShowGuide] = useState(false);
  const [strategy, setStrategy] = useState('iron_condor');
  const [symbol, setSymbol] = useState('SPY');
  const [start, setStart] = useState('2024-01-01');
  const [exitRule, setExitRule] = useState('50pct');
  const [regimeFilter, setRegimeFilter] = useState(false);
  const [biasFilter, setBiasFilter] = useState(false);
  const [dealerFilter, setDealerFilter] = useState(false);
  const [edgeThreshold, setEdgeThreshold] = useState(0);
  const [slippage, setSlippage] = useState(3);
  const [source, setSource] = useState('local');
  const [compareMode, setCompareMode] = useState(false);
  const [compareStrategies, setCompareStrategies] = useState(['iron_condor', 'butterfly']);
  const [showTrades, setShowTrades] = useState(false);
  const [sortCol, setSortCol] = useState('entry_date');
  const [sortAsc, setSortAsc] = useState(false);
  const [queryPath, setQueryPath] = useState(null);

  const { data, loading, error } = useApi(queryPath, { manual: !queryPath });

  function buildFilterParams() {
    const p = new URLSearchParams({ symbol, start, exit_rule: exitRule });
    if (regimeFilter) p.set('regime_filter', 'true');
    if (biasFilter) p.set('bias_filter', 'true');
    if (dealerFilter) p.set('dealer_filter', 'true');
    if (edgeThreshold > 0) p.set('edge_threshold', edgeThreshold);
    if (slippage > 0) p.set('slippage_pct', (slippage / 100).toFixed(4));
    if (source !== 'local') p.set('source', source);
    return p;
  }

  function handleRun() {
    const p = buildFilterParams();
    if (compareMode) {
      p.set('strategies', compareStrategies.join(','));
      setQueryPath(`/api/backtest/compare?${p}`);
    } else {
      setQueryPath(`/api/backtest/${strategy}?${p}`);
    }
  }

  function toggleCompareStrategy(s) {
    setCompareStrategies(prev =>
      prev.includes(s) ? prev.filter(x => x !== s) : [...prev, s].slice(0, 3)
    );
  }

  const isCompare = compareMode && data?.strategies;

  return (
    <div className="bt">
      {/* ── Guide ── */}
      <div className="bt-guide-bar">
        <button className="bt-guide-toggle" onClick={() => setShowGuide(!showGuide)}>
          {showGuide ? 'Hide' : 'How to use'}
        </button>
      </div>
      {showGuide && <Guide />}

      {/* ── Config Panel ── */}
      <div className="bt-config">
        <div className="bt-config-main">
          <div className="bt-field">
            <label className="bt-label">Strategy</label>
            {!compareMode ? (
              <select className="bt-select" value={strategy}
                onChange={e => setStrategy(e.target.value)}>
                {ACTIVE_STRATEGIES.map(s =>
                  <option key={s.value} value={s.value}>{s.label}</option>
                )}
              </select>
            ) : (
              <div className="bt-strategy-pills">
                {ACTIVE_STRATEGIES.map(s => (
                  <button key={s.value}
                    className={`bt-pill ${compareStrategies.includes(s.value) ? 'active' : ''}`}
                    onClick={() => toggleCompareStrategy(s.value)}>
                    {s.label}
                  </button>
                ))}
              </div>
            )}
          </div>

          <div className="bt-field">
            <label className="bt-label">Symbol</label>
            <input className="bt-input" value={symbol}
              onChange={e => setSymbol(e.target.value.toUpperCase())}
              style={{ width: 80 }} />
          </div>

          <div className="bt-field">
            <label className="bt-label">Start Date</label>
            <input className="bt-input" type="date" value={start}
              onChange={e => setStart(e.target.value)} />
          </div>

          <div className="bt-field">
            <label className="bt-label">Data Source</label>
            <div className="bt-toggle-group">
              <button className={`bt-toggle ${source === 'local' ? 'active' : ''}`}
                onClick={() => setSource('local')}>BS Model</button>
              <button className={`bt-toggle ${source === 'chain_replay' ? 'active' : ''}`}
                onClick={() => setSource('chain_replay')}>Real Data</button>
            </div>
          </div>

          <div className="bt-field">
            <label className="bt-label">Exit Rule</label>
            <div className="bt-toggle-group">
              {[
                ['50pct', '50% TP'],
                ['hold', 'Hold'],
                ['strategy', 'Auto'],
              ].map(([val, label]) => (
                <button key={val}
                  className={`bt-toggle ${exitRule === val ? 'active' : ''}`}
                  onClick={() => setExitRule(val)}>{label}</button>
              ))}
            </div>
          </div>

          <div className="bt-field bt-field-actions">
            <label className="bt-label">&nbsp;</label>
            <div className="bt-actions">
              <button className={`bt-mode-toggle ${compareMode ? 'active' : ''}`}
                onClick={() => setCompareMode(!compareMode)}>
                Compare
              </button>
              <button className="bt-run" onClick={handleRun} disabled={loading}>
                {loading ? 'Running...' : 'Run'}
              </button>
            </div>
          </div>
        </div>

        <div className="bt-filters">
          <span className="bt-filters-label">Signal Filters</span>
          <div className="bt-filter-chips">
            <button className={`bt-chip ${regimeFilter ? 'active' : ''}`}
              onClick={() => setRegimeFilter(!regimeFilter)}>Regime</button>
            <button className={`bt-chip ${biasFilter ? 'active' : ''}`}
              onClick={() => setBiasFilter(!biasFilter)}>Bias</button>
            <button className={`bt-chip ${dealerFilter ? 'active' : ''}`}
              onClick={() => setDealerFilter(!dealerFilter)}>Dealer</button>
          </div>
          <div className="bt-filter-inputs">
            <label className="bt-inline-label">
              Edge &gt;
              <input className="bt-input bt-input-sm" type="number" value={edgeThreshold}
                onChange={e => setEdgeThreshold(+e.target.value)} min={0} step={1} />
              <span className="bt-unit">%</span>
            </label>
            <label className="bt-inline-label">
              Slippage
              <input className="bt-input bt-input-sm" type="number" value={slippage}
                onChange={e => setSlippage(+e.target.value)} min={0} max={10} step={0.5} />
              <span className="bt-unit">%</span>
            </label>
          </div>
        </div>
      </div>

      {error && <div className="bt-error">Error: {error}</div>}

      {/* ── Results ── */}
      {isCompare && <CompareView data={data} />}
      {!isCompare && data && data.stats && (
        <SingleView data={data}
          showTrades={showTrades} setShowTrades={setShowTrades}
          sortCol={sortCol} setSortCol={setSortCol}
          sortAsc={sortAsc} setSortAsc={setSortAsc} />
      )}
    </div>
  );
}


function SingleView({ data, showTrades, setShowTrades, sortCol, setSortCol, sortAsc, setSortAsc }) {
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
      {/* Source badge */}
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

      {/* Stats Row */}
      <div className="bt-stats">
        <Stat label="Win Rate" value={`${s.win_rate?.toFixed(1)}%`}
          positive={s.win_rate > 50} />
        <Stat label="Total P&L" value={`$${s.total_pnl?.toFixed(0)}`}
          positive={s.total_pnl > 0} />
        <Stat label="Trades" value={s.total_trades} neutral />
        <Stat label="Profit Factor" value={s.profit_factor?.toFixed(2)}
          positive={s.profit_factor > 1} />
        <Stat label="Sharpe" value={s.sharpe_ratio?.toFixed(2)}
          positive={s.sharpe_ratio > 0} />
        <Stat label="Max DD" value={`$${s.max_drawdown?.toFixed(0)}`}
          positive={false} />
        <Stat label="Avg Win" value={`$${s.avg_win?.toFixed(0)}`}
          positive={true} />
        <Stat label="Avg Loss" value={`$${s.avg_loss?.toFixed(0)}`}
          positive={false} />
      </div>

      {/* Charts Row */}
      <div className="bt-charts-row">
        {equityData.length > 1 && (
          <div className="bt-chart bt-chart-wide">
            <h3>Equity Curve</h3>
            <ResponsiveContainer width="100%" height={260}>
              <LineChart data={equityData}>
                <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
                <XAxis dataKey="trade" stroke="var(--text-muted)" fontSize={11}
                  tickLine={false} />
                <YAxis stroke="var(--text-muted)" fontSize={11}
                  tickFormatter={v => `$${v}`} tickLine={false} />
                <Tooltip contentStyle={tooltipStyle}
                  formatter={v => [`$${v.toFixed(0)}`, 'Equity']} />
                <ReferenceLine y={0} stroke="var(--text-muted)" strokeDasharray="3 3" />
                <Line type="monotone" dataKey="equity" stroke="#3b82f6"
                  dot={false} strokeWidth={2} />
              </LineChart>
            </ResponsiveContainer>
          </div>
        )}

        {data.pnl_distribution?.length > 0 && (
          <div className="bt-chart">
            <h3>P&L Distribution</h3>
            <ResponsiveContainer width="100%" height={260}>
              <BarChart data={data.pnl_distribution}>
                <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
                <XAxis dataKey="bin_start" stroke="var(--text-muted)" fontSize={10}
                  tickFormatter={v => `$${v}`} tickLine={false} />
                <YAxis stroke="var(--text-muted)" fontSize={11} tickLine={false} />
                <Tooltip contentStyle={tooltipStyle}
                  formatter={(v) => [v, 'Trades']}
                  labelFormatter={v => `$${v}`} />
                <Bar dataKey="count" fill="#3b82f6" radius={[2, 2, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        )}
      </div>

      {/* Breakdown Tables */}
      <div className="bt-breakdowns">
        {data.regime_breakdown && Object.keys(data.regime_breakdown).length > 0 && (
          <BreakdownTable title="By Regime" data={data.regime_breakdown} />
        )}
        {data.dte_breakdown && Object.keys(data.dte_breakdown).length > 0 && (
          <BreakdownTable title="By DTE" data={data.dte_breakdown} />
        )}
      </div>

      {/* Trade Log */}
      <div className="bt-trades-section">
        <button className="bt-trades-toggle" onClick={() => setShowTrades(!showTrades)}>
          {showTrades ? 'Hide' : 'Show'} Trade Log
          <span className="bt-trades-count">{data.trades_count || 0}</span>
        </button>
        {showTrades && sortedTrades.length > 0 && (
          <div className="bt-trades-wrap">
            <table className="bt-table">
              <thead>
                <tr>
                  {[
                    ['entry_date', 'Entry'],
                    ['exit_date', 'Exit'],
                    ['entry_price', 'Entry $'],
                    ['exit_price', 'Exit $'],
                    ['pnl', 'P&L'],
                    ['pnl_pct', 'P&L %'],
                    ['dte_at_entry', 'DTE'],
                    ['regime', 'Regime'],
                    ['exit_reason', 'Reason'],
                  ].map(([col, label]) => (
                    <th key={col} onClick={() => handleSort(col)}>
                      {label}
                      {sortCol === col && <span className="bt-sort-arrow">{sortAsc ? ' ▲' : ' ▼'}</span>}
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
                    <td className="muted">{t.exit_reason}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}


function CompareView({ data }) {
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
      {/* Comparison Stats */}
      <div className="bt-compare-table-wrap">
        <table className="bt-table bt-compare-table">
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

      {/* Combined Equity Curve */}
      {combinedEquity.length > 1 && (
        <div className="bt-chart">
          <h3>Equity Curves</h3>
          <ResponsiveContainer width="100%" height={320}>
            <LineChart data={combinedEquity}>
              <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
              <XAxis dataKey="trade" stroke="var(--text-muted)" fontSize={11} tickLine={false} />
              <YAxis stroke="var(--text-muted)" fontSize={11}
                tickFormatter={v => `$${v}`} tickLine={false} />
              <Tooltip contentStyle={tooltipStyle}
                formatter={v => [`$${v?.toFixed(0)}`, '']} />
              <ReferenceLine y={0} stroke="var(--text-muted)" strokeDasharray="3 3" />
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


function Stat({ label, value, positive, neutral }) {
  const cls = neutral ? '' : positive ? 'green' : 'red';
  return (
    <div className="bt-stat">
      <div className="bt-stat-label">{label}</div>
      <div className={`bt-stat-value ${cls}`}>{value}</div>
    </div>
  );
}


function BreakdownTable({ title, data }) {
  return (
    <div className="bt-breakdown">
      <h3>{title}</h3>
      <table className="bt-table">
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


function Guide() {
  return (
    <div className="bt-guide">
      <div className="bt-guide-cols">
        <div className="bt-guide-section">
          <h4>Data Source</h4>
          <p><strong>BS Model</strong> — Fast, synthetic prices from Black-Scholes. Good for quick iteration but can overestimate win rates since it assumes smooth pricing.</p>
          <p><strong>Real Data</strong> — Actual bid/ask/mid from collected chain snapshots. Slower, limited to dates with data, but trustworthy. Use this for final validation.</p>
        </div>
        <div className="bt-guide-section">
          <h4>Signal Filters</h4>
          <p>Toggle <strong>Regime</strong>, <strong>Bias</strong>, <strong>Dealer</strong> to only take trades when that signal layer agrees. Run with and without each filter to see if it improves results.</p>
          <p><strong>Edge &gt; N%</strong> — only trade when GARCH-estimated edge exceeds this threshold.</p>
        </div>
        <div className="bt-guide-section">
          <h4>Charts</h4>
          <p><strong>Equity Curve</strong> — X: trade number, Y: cumulative P&L ($). Tracks how your account grows or shrinks trade by trade.</p>
          <p><strong>P&L Distribution</strong> — X: dollar P&L buckets, Y: trade count. Shows where wins and losses cluster.</p>
        </div>
        <div className="bt-guide-section">
          <h4>Breakdowns</h4>
          <p><strong>By Regime</strong> — Performance in each vol regime. Find which regimes the strategy works in and which it doesn't.</p>
          <p><strong>By DTE</strong> — Performance by days-to-expiry at entry. Find the optimal DTE range for each strategy.</p>
        </div>
      </div>
    </div>
  );
}


const tooltipStyle = {
  background: 'var(--bg-card)',
  border: '1px solid var(--border)',
  borderRadius: 6,
  fontSize: 13,
};
