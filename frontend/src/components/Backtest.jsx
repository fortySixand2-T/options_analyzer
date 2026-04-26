import { useState } from 'react';
import { useApi } from '../hooks/useApi';
import {
  LineChart, Line, BarChart, Bar, XAxis, YAxis, CartesianGrid,
  Tooltip, ResponsiveContainer, Legend,
} from 'recharts';
import './Dashboard.css';

const STRATEGIES = [
  'iron_condor', 'short_put_spread', 'short_call_spread',
  'long_call_spread', 'long_put_spread', 'butterfly',
];

const COLORS = ['var(--blue)', '#10b981', '#f59e0b', '#ef4444', '#8b5cf6', '#06b6d4'];

export default function Backtest() {
  const [strategy, setStrategy] = useState('iron_condor');
  const [symbol, setSymbol] = useState('SPY');
  const [start, setStart] = useState('2023-01-01');
  const [exitRule, setExitRule] = useState('50pct');
  const [regimeFilter, setRegimeFilter] = useState(false);
  const [biasFilter, setBiasFilter] = useState(false);
  const [dealerFilter, setDealerFilter] = useState(false);
  const [edgeThreshold, setEdgeThreshold] = useState(0);
  const [slippage, setSlippage] = useState(3);
  const [compareMode, setCompareMode] = useState(false);
  const [compareStrategies, setCompareStrategies] = useState(['iron_condor', 'long_call_spread']);
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
    <div className="dashboard">
      {/* Controls */}
      <div className="controls-row">
        {!compareMode ? (
          <select className="input" value={strategy} onChange={e => setStrategy(e.target.value)}>
            {STRATEGIES.map(s => <option key={s} value={s}>{s.replace(/_/g, ' ')}</option>)}
          </select>
        ) : (
          <div className="compare-picks">
            {STRATEGIES.map(s => (
              <label key={s} className="checkbox-label">
                <input type="checkbox" checked={compareStrategies.includes(s)}
                  onChange={() => toggleCompareStrategy(s)} />
                {s.replace(/_/g, ' ')}
              </label>
            ))}
          </div>
        )}
        <input className="input small" value={symbol}
          onChange={e => setSymbol(e.target.value.toUpperCase())} />
        <input className="input" type="date" value={start} onChange={e => setStart(e.target.value)} />
        <label className="checkbox-label">
          <input type="checkbox" checked={compareMode}
            onChange={e => setCompareMode(e.target.checked)} />
          Compare
        </label>
        <button className="btn-primary" onClick={handleRun} disabled={loading}>
          {loading ? 'Running...' : compareMode ? 'Compare' : 'Run Backtest'}
        </button>
      </div>

      {/* Signal Filters */}
      <div className="controls-row filters-row">
        <span className="filter-label">Filters:</span>
        <label className="checkbox-label">
          <input type="checkbox" checked={regimeFilter}
            onChange={e => setRegimeFilter(e.target.checked)} />
          Regime
        </label>
        <label className="checkbox-label">
          <input type="checkbox" checked={biasFilter}
            onChange={e => setBiasFilter(e.target.checked)} />
          Bias
        </label>
        <label className="checkbox-label">
          <input type="checkbox" checked={dealerFilter}
            onChange={e => setDealerFilter(e.target.checked)} />
          Dealer
        </label>
        <label className="input-label">
          Edge {'>'}
          <input className="input small" type="number" value={edgeThreshold}
            onChange={e => setEdgeThreshold(+e.target.value)} min={0} step={1} />
          %
        </label>
        <label className="input-label">
          Slippage
          <input className="input small" type="number" value={slippage}
            onChange={e => setSlippage(+e.target.value)} min={0} max={10} step={0.5} />
          %
        </label>
        <div className="toggle-group">
          <button className={`toggle ${exitRule === '50pct' ? 'active' : ''}`}
            onClick={() => setExitRule('50pct')}>50% Target</button>
          <button className={`toggle ${exitRule === 'hold' ? 'active' : ''}`}
            onClick={() => setExitRule('hold')}>Hold to Expiry</button>
          <button className={`toggle ${exitRule === 'strategy' ? 'active' : ''}`}
            onClick={() => setExitRule('strategy')}>Per-Strategy</button>
        </div>
      </div>

      {error && <div className="panel error">Error: {error}</div>}

      {/* Compare Mode */}
      {isCompare && <CompareView data={data} />}

      {/* Single Strategy Mode */}
      {!isCompare && data && data.stats && <SingleView data={data}
        showTrades={showTrades} setShowTrades={setShowTrades}
        sortCol={sortCol} setSortCol={setSortCol}
        sortAsc={sortAsc} setSortAsc={setSortAsc} />}
    </div>
  );
}

function SingleView({ data, showTrades, setShowTrades, sortCol, setSortCol, sortAsc, setSortAsc }) {
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

  return (
    <>
      <div className="metrics-grid">
        <StatCard label="Win Rate" value={`${data.stats.win_rate?.toFixed(1)}%`}
          color={data.stats.win_rate > 50 ? 'green' : 'red'} />
        <StatCard label="Total P&L" value={`$${data.stats.total_pnl?.toFixed(0)}`}
          color={data.stats.total_pnl > 0 ? 'green' : 'red'} />
        <StatCard label="Trades" value={data.stats.total_trades} />
        <StatCard label="Profit Factor" value={data.stats.profit_factor?.toFixed(2)}
          color={data.stats.profit_factor > 1 ? 'green' : 'red'} />
        <StatCard label="Sharpe" value={data.stats.sharpe_ratio?.toFixed(2)}
          color={data.stats.sharpe_ratio > 0 ? 'green' : 'red'} />
        <StatCard label="Max DD" value={`$${data.stats.max_drawdown?.toFixed(0)}`} color="red" />
        <StatCard label="Avg Win" value={`$${data.stats.avg_win?.toFixed(0)}`} color="green" />
        <StatCard label="Avg Loss" value={`$${data.stats.avg_loss?.toFixed(0)}`} color="red" />
      </div>

      {/* Equity Curve */}
      {equityData.length > 1 && (
        <div className="chart-container">
          <h3>Equity Curve</h3>
          <ResponsiveContainer width="100%" height={300}>
            <LineChart data={equityData}>
              <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
              <XAxis dataKey="trade" stroke="var(--text-muted)" fontSize={12} />
              <YAxis stroke="var(--text-muted)" fontSize={12} tickFormatter={v => `$${v}`} />
              <Tooltip contentStyle={{ background: 'var(--bg-card)', border: '1px solid var(--border)' }}
                formatter={v => [`$${v.toFixed(0)}`, 'Equity']} />
              <Line type="monotone" dataKey="equity" stroke="var(--blue)" dot={false} strokeWidth={2} />
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}

      {/* P&L Distribution */}
      {data.pnl_distribution?.length > 0 && (
        <div className="chart-container">
          <h3>P&L Distribution</h3>
          <ResponsiveContainer width="100%" height={200}>
            <BarChart data={data.pnl_distribution}>
              <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
              <XAxis dataKey="bin_start" stroke="var(--text-muted)" fontSize={11}
                tickFormatter={v => `$${v}`} />
              <YAxis stroke="var(--text-muted)" fontSize={11} />
              <Tooltip contentStyle={{ background: 'var(--bg-card)', border: '1px solid var(--border)' }}
                formatter={(v, name) => [v, name === 'count' ? 'Trades' : name]}
                labelFormatter={v => `$${v}`} />
              <Bar dataKey="count" fill="var(--blue)" />
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}

      {/* Regime Breakdown */}
      {data.regime_breakdown && Object.keys(data.regime_breakdown).length > 0 && (
        <div className="table-wrap">
          <h3>Regime Breakdown</h3>
          <table className="data-table">
            <thead>
              <tr><th>Regime</th><th>Trades</th><th>Win Rate</th><th>Avg P&L</th><th>Total P&L</th></tr>
            </thead>
            <tbody>
              {Object.entries(data.regime_breakdown).map(([regime, d]) => (
                <tr key={regime}>
                  <td>{regime}</td>
                  <td className="mono">{d.count}</td>
                  <td className={`mono ${d.win_rate > 50 ? 'green' : 'red'}`}>{d.win_rate?.toFixed(1)}%</td>
                  <td className={`mono ${d.avg_pnl > 0 ? 'green' : 'red'}`}>${d.avg_pnl?.toFixed(0)}</td>
                  <td className={`mono ${d.total_pnl > 0 ? 'green' : 'red'}`}>${d.total_pnl?.toFixed(0)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* DTE Breakdown */}
      {data.dte_breakdown && Object.keys(data.dte_breakdown).length > 0 && (
        <div className="table-wrap">
          <h3>DTE Bucket Breakdown</h3>
          <table className="data-table">
            <thead>
              <tr><th>DTE</th><th>Trades</th><th>Win Rate</th><th>Avg P&L</th><th>Total P&L</th></tr>
            </thead>
            <tbody>
              {Object.entries(data.dte_breakdown).map(([bucket, d]) => (
                <tr key={bucket}>
                  <td>{bucket}</td>
                  <td className="mono">{d.count}</td>
                  <td className={`mono ${d.win_rate > 50 ? 'green' : 'red'}`}>{d.win_rate?.toFixed(1)}%</td>
                  <td className={`mono ${d.avg_pnl > 0 ? 'green' : 'red'}`}>${d.avg_pnl?.toFixed(0)}</td>
                  <td className={`mono ${d.total_pnl > 0 ? 'green' : 'red'}`}>${d.total_pnl?.toFixed(0)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Trade Table */}
      <div className="table-wrap">
        <h3>
          <button className="refresh-btn" onClick={() => setShowTrades(!showTrades)}>
            {showTrades ? 'Hide' : 'Show'} Trades ({data.trades_count || 0})
          </button>
        </h3>
        {showTrades && sortedTrades.length > 0 && (
          <table className="data-table">
            <thead>
              <tr>
                {['entry_date', 'exit_date', 'entry_price', 'exit_price', 'pnl', 'pnl_pct', 'dte_at_entry', 'regime', 'exit_reason'].map(col => (
                  <th key={col} onClick={() => handleSort(col)} style={{ cursor: 'pointer' }}>
                    {col.replace(/_/g, ' ')} {sortCol === col ? (sortAsc ? '\u25b2' : '\u25bc') : ''}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {sortedTrades.map((t, i) => (
                <tr key={i}>
                  <td className="mono">{t.entry_date}</td>
                  <td className="mono">{t.exit_date}</td>
                  <td className="mono">${t.entry_price?.toFixed(2)}</td>
                  <td className="mono">${t.exit_price?.toFixed(2)}</td>
                  <td className={`mono ${t.pnl > 0 ? 'green' : 'red'}`}>${t.pnl?.toFixed(0)}</td>
                  <td className={`mono ${t.pnl_pct > 0 ? 'green' : 'red'}`}>{t.pnl_pct?.toFixed(1)}%</td>
                  <td className="mono">{t.dte_at_entry}</td>
                  <td>{t.regime}</td>
                  <td>{t.exit_reason}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </>
  );
}

function CompareView({ data }) {
  const strategies = data.strategies || {};
  const names = Object.keys(strategies).filter(k => !strategies[k].error);

  // Build combined equity curves
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
    <>
      {/* Stat Comparison Table */}
      <div className="table-wrap">
        <h3>Strategy Comparison</h3>
        <table className="data-table">
          <thead>
            <tr>
              <th>Metric</th>
              {names.map(n => <th key={n}>{n.replace(/_/g, ' ')}</th>)}
            </tr>
          </thead>
          <tbody>
            {[
              ['Win Rate', s => `${s.win_rate?.toFixed(1)}%`, s => s.win_rate > 50],
              ['Total P&L', s => `$${s.total_pnl?.toFixed(0)}`, s => s.total_pnl > 0],
              ['Trades', s => s.total_trades],
              ['Profit Factor', s => s.profit_factor?.toFixed(2), s => s.profit_factor > 1],
              ['Sharpe', s => s.sharpe_ratio?.toFixed(2), s => s.sharpe_ratio > 0],
              ['Max DD', s => `$${s.max_drawdown?.toFixed(0)}`],
              ['Avg Win', s => `$${s.avg_win?.toFixed(0)}`],
              ['Avg Loss', s => `$${s.avg_loss?.toFixed(0)}`],
            ].map(([label, fmt, isGood]) => (
              <tr key={label}>
                <td>{label}</td>
                {names.map(n => {
                  const s = strategies[n]?.stats;
                  if (!s) return <td key={n}>--</td>;
                  const good = isGood ? isGood(s) : null;
                  return (
                    <td key={n} className={`mono ${good === true ? 'green' : good === false ? 'red' : ''}`}>
                      {fmt(s)}
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
        <div className="chart-container">
          <h3>Combined Equity Curves</h3>
          <ResponsiveContainer width="100%" height={350}>
            <LineChart data={combinedEquity}>
              <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
              <XAxis dataKey="trade" stroke="var(--text-muted)" fontSize={12} />
              <YAxis stroke="var(--text-muted)" fontSize={12} tickFormatter={v => `$${v}`} />
              <Tooltip contentStyle={{ background: 'var(--bg-card)', border: '1px solid var(--border)' }}
                formatter={v => [`$${v?.toFixed(0)}`, '']} />
              <Legend />
              {names.map((n, i) => (
                <Line key={n} type="monotone" dataKey={n} stroke={COLORS[i % COLORS.length]}
                  dot={false} strokeWidth={2} name={n.replace(/_/g, ' ')} />
              ))}
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}
    </>
  );
}

function StatCard({ label, value, color }) {
  return (
    <div className="metric-card">
      <div className="metric-label">{label}</div>
      <div className={`metric-value mono ${color || ''}`}>{value}</div>
    </div>
  );
}
