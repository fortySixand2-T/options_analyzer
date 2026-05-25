import { useState } from 'react';
import { AreaChart, Area, BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell, CartesianGrid } from 'recharts';
import { useApi } from '../hooks/useApi';
import './Performance.css';

export default function Performance() {
  const { data: summary } = useApi('/api/performance/summary');
  const { data: equityData } = useApi('/api/performance/equity-curve');
  const { data: ddData } = useApi('/api/performance/drawdown');
  const { data: stratData } = useApi('/api/performance/by-strategy');
  const { data: regimeData } = useApi('/api/performance/by-regime');
  const { data: monthData } = useApi('/api/performance/by-month');

  const equity = equityData?.curve || [];
  const drawdown = ddData?.series || [];
  const strategies = stratData?.strategies || [];
  const regimes = regimeData?.regimes || [];
  const months = monthData?.months || [];

  if (!summary || summary.total_trades === 0) {
    return (
      <div className="performance">
        <div className="perf-empty">
          <p>No closed positions yet</p>
          <p className="perf-hint">Close positions in the Positions tab to see performance analytics</p>
        </div>
      </div>
    );
  }

  return (
    <div className="performance">
      {/* Stat strip */}
      <div className="perf-stat-strip">
        <StatBox label="Total P&L" value={`$${summary.total_pnl.toLocaleString()}`} positive={summary.total_pnl >= 0} />
        <StatBox label="Win Rate" value={`${summary.win_rate}%`} positive={summary.win_rate >= 50} />
        <StatBox label="Trades" value={summary.total_trades} />
        <StatBox label="Profit Factor" value={summary.profit_factor} positive={summary.profit_factor > 1} />
        <StatBox label="Avg Win" value={`$${summary.avg_win}`} positive />
        <StatBox label="Avg Loss" value={`$${summary.avg_loss}`} positive={false} />
        <StatBox label="Max DD" value={`$${ddData?.max_drawdown || 0}`} positive={false} />
      </div>

      {/* Equity curve */}
      {equity.length > 1 && (
        <div className="perf-chart-card">
          <h3>Equity Curve</h3>
          <ResponsiveContainer width="100%" height={200}>
            <AreaChart data={equity} margin={{ top: 10, right: 10, left: 0, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#2a2e39" />
              <XAxis dataKey="date" tick={{ fill: '#787b86', fontSize: 10 }} />
              <YAxis tick={{ fill: '#787b86', fontSize: 10 }} />
              <Tooltip contentStyle={{ background: '#1e222d', border: '1px solid #363c4e', borderRadius: 4 }} />
              <Area type="monotone" dataKey="cumulative" stroke="#2962ff" fill="rgba(41,98,255,0.15)" />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      )}

      {/* Drawdown chart */}
      {drawdown.length > 1 && (
        <div className="perf-chart-card">
          <h3>Drawdown</h3>
          <ResponsiveContainer width="100%" height={120}>
            <AreaChart data={drawdown} margin={{ top: 10, right: 10, left: 0, bottom: 0 }}>
              <XAxis dataKey="date" tick={{ fill: '#787b86', fontSize: 10 }} />
              <YAxis tick={{ fill: '#787b86', fontSize: 10 }} />
              <Tooltip contentStyle={{ background: '#1e222d', border: '1px solid #363c4e', borderRadius: 4 }} />
              <Area type="monotone" dataKey="drawdown" stroke="#ef5350" fill="rgba(239,83,80,0.15)" />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      )}

      {/* Breakdown grids */}
      <div className="perf-grid">
        {strategies.length > 0 && (
          <div className="perf-chart-card">
            <h3>By Strategy</h3>
            <ResponsiveContainer width="100%" height={160}>
              <BarChart data={strategies} margin={{ top: 10, right: 10, left: -10, bottom: 0 }}>
                <XAxis dataKey="strategy" tick={{ fill: '#787b86', fontSize: 10 }} />
                <YAxis tick={{ fill: '#787b86', fontSize: 10 }} />
                <Tooltip contentStyle={{ background: '#1e222d', border: '1px solid #363c4e', borderRadius: 4 }} />
                <Bar dataKey="total_pnl" radius={[3, 3, 0, 0]}>
                  {strategies.map((e, i) => (
                    <Cell key={i} fill={e.total_pnl >= 0 ? '#26a69a' : '#ef5350'} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        )}

        {regimes.length > 0 && (
          <div className="perf-chart-card">
            <h3>By Regime</h3>
            <ResponsiveContainer width="100%" height={160}>
              <BarChart data={regimes} margin={{ top: 10, right: 10, left: -10, bottom: 0 }}>
                <XAxis dataKey="regime" tick={{ fill: '#787b86', fontSize: 10 }} />
                <YAxis tick={{ fill: '#787b86', fontSize: 10 }} />
                <Tooltip contentStyle={{ background: '#1e222d', border: '1px solid #363c4e', borderRadius: 4 }} />
                <Bar dataKey="total_pnl" radius={[3, 3, 0, 0]}>
                  {regimes.map((e, i) => (
                    <Cell key={i} fill={e.total_pnl >= 0 ? '#26a69a' : '#ef5350'} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        )}
      </div>

      {/* Monthly heatmap */}
      {months.length > 0 && (
        <div className="perf-chart-card">
          <h3>Monthly P&L</h3>
          <div className="perf-month-grid">
            {months.map(m => (
              <div key={m.month} className={`perf-month-cell ${m.total_pnl >= 0 ? 'positive' : 'negative'}`}>
                <span className="perf-month-label">{m.month}</span>
                <span className="perf-month-val">${m.total_pnl.toLocaleString()}</span>
                <span className="perf-month-trades">{m.trades} trades</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}


function StatBox({ label, value, positive }) {
  const cls = positive === true ? 'text-green' : positive === false ? 'text-red' : '';
  return (
    <div className="perf-stat-box">
      <span className="perf-stat-label">{label}</span>
      <span className={`perf-stat-val ${cls}`}>{value}</span>
    </div>
  );
}
