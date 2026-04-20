import { useState } from 'react';
import { useApi } from '../hooks/useApi';
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from 'recharts';
import './Dashboard.css';

export default function Backtest() {
  const [strategy, setStrategy] = useState('iron_condor');
  const [symbol, setSymbol] = useState('SPY');
  const [start, setStart] = useState('2022-01-01');
  const [queryPath, setQueryPath] = useState(null);

  const { data, loading, error } = useApi(queryPath, { manual: !queryPath });

  function handleRun() {
    const params = new URLSearchParams({ symbol, start });
    setQueryPath(`/api/backtest/${strategy}?${params}`);
  }

  const strategies = [
    'iron_condor', 'short_put_spread', 'short_call_spread',
    'short_strangle', 'long_call_spread', 'long_put_spread',
    'long_straddle', 'butterfly', 'naked_put_1dte',
  ];

  const equityData = data?.equity_curve?.map((v, i) => ({ trade: i, equity: v })) || [];

  return (
    <div className="dashboard">
      <div className="controls-row">
        <select className="input" value={strategy} onChange={e => setStrategy(e.target.value)}>
          {strategies.map(s => <option key={s} value={s}>{s.replace(/_/g, ' ')}</option>)}
        </select>
        <input className="input small" value={symbol} onChange={e => setSymbol(e.target.value.toUpperCase())} />
        <input className="input" type="date" value={start} onChange={e => setStart(e.target.value)} />
        <button className="btn-primary" onClick={handleRun} disabled={loading}>
          {loading ? 'Running...' : 'Run Backtest'}
        </button>
      </div>

      {error && <div className="panel error">Error: {error}</div>}

      {data && data.stats && (
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

          {equityData.length > 1 && (
            <div className="chart-container">
              <h3>Equity Curve</h3>
              <ResponsiveContainer width="100%" height={300}>
                <LineChart data={equityData}>
                  <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
                  <XAxis dataKey="trade" stroke="var(--text-muted)" fontSize={12} />
                  <YAxis stroke="var(--text-muted)" fontSize={12}
                    tickFormatter={v => `$${v}`} />
                  <Tooltip
                    contentStyle={{ background: 'var(--bg-card)', border: '1px solid var(--border)' }}
                    labelStyle={{ color: 'var(--text-secondary)' }}
                    formatter={v => [`$${v.toFixed(0)}`, 'Equity']}
                  />
                  <Line type="monotone" dataKey="equity" stroke="var(--blue)" dot={false} strokeWidth={2} />
                </LineChart>
              </ResponsiveContainer>
            </div>
          )}

          {data.regime_breakdown && Object.keys(data.regime_breakdown).length > 0 && (
            <div className="table-wrap">
              <h3>Regime Breakdown</h3>
              <table className="data-table">
                <thead>
                  <tr><th>Regime</th><th>Trades</th><th>Win Rate</th><th>Avg P&L</th></tr>
                </thead>
                <tbody>
                  {Object.entries(data.regime_breakdown).map(([regime, d]) => (
                    <tr key={regime}>
                      <td>{regime}</td>
                      <td className="mono">{d.count}</td>
                      <td className={`mono ${d.win_rate > 50 ? 'green' : 'red'}`}>{d.win_rate?.toFixed(1)}%</td>
                      <td className={`mono ${d.avg_pnl > 0 ? 'green' : 'red'}`}>${d.avg_pnl?.toFixed(0)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
    </div>
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
