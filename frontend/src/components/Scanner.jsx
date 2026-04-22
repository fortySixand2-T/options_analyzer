import { useState } from 'react';
import { useApi } from '../hooks/useApi';
import './Dashboard.css';

export default function Scanner() {
  const [symbols, setSymbols] = useState('SPY,QQQ,IWM');
  const [maxDte, setMaxDte] = useState(14);
  const [withStrategies, setWithStrategies] = useState(false);
  const [queryPath, setQueryPath] = useState(null);

  const { data, loading, error, refetch } = useApi(queryPath, { manual: !queryPath });

  function handleScan() {
    const params = new URLSearchParams({
      symbols, max_dte: maxDte, strategies: withStrategies, top: 20,
    });
    setQueryPath(`/api/scan?${params}`);
  }

  return (
    <div className="dashboard">
      <div className="controls-row">
        <input
          className="input"
          value={symbols}
          onChange={e => setSymbols(e.target.value)}
          placeholder="SPY,QQQ,IWM"
        />
        <label className="input-label">
          Max DTE
          <input className="input small" type="number" value={maxDte}
            onChange={e => setMaxDte(+e.target.value)} />
        </label>
        <label className="checkbox-label">
          <input type="checkbox" checked={withStrategies}
            onChange={e => setWithStrategies(e.target.checked)} />
          Strategies
        </label>
        <button className="btn-primary" onClick={handleScan} disabled={loading}>
          {loading ? 'Scanning...' : 'Scan'}
        </button>
      </div>

      {error && <div className="panel error">Error: {error}</div>}

      {data && !withStrategies && data.signals && (
        <div className="table-wrap">
          <table className="data-table">
            <thead>
              <tr>
                <th>Ticker</th><th>Strike</th><th>Type</th><th>DTE</th>
                <th>Mid</th><th>IV Rank</th><th>Edge%</th><th>Dir</th>
                <th>Delta</th><th>Theta</th><th>Score</th>
              </tr>
            </thead>
            <tbody>
              {data.signals.map((s, i) => (
                <tr key={i}>
                  <td className="mono">{s.ticker}</td>
                  <td className="mono">{s.strike}</td>
                  <td>{s.option_type}</td>
                  <td className="mono">{s.dte}</td>
                  <td className="mono">${s.mid?.toFixed(2)}</td>
                  <td className="mono">{s.iv_rank?.toFixed(0)}%</td>
                  <td className={`mono ${s.edge_pct > 0 ? 'green' : 'red'}`}>
                    {s.edge_pct?.toFixed(1)}%
                  </td>
                  <td className={s.direction === 'BUY' ? 'green' : 'red'}>{s.direction}</td>
                  <td className="mono">{s.delta?.toFixed(3)}</td>
                  <td className="mono">{s.theta?.toFixed(3)}</td>
                  <td className="mono"><strong>{s.conviction?.toFixed(0)}</strong></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {data && withStrategies && data.strategies && (
        <>
          {data.regime && (
            <div className="regime-banner">
              Regime: <strong>{data.regime.regime}</strong> — {data.regime.rationale}
            </div>
          )}
          {(data.bias || data.dealer) && (
            <div className="signal-context">
              {data.bias && (
                <span className={`bias-badge ${data.bias.label?.includes('BULLISH') ? 'green' : data.bias.label?.includes('BEARISH') ? 'red' : 'muted'}`}>
                  Bias: {data.bias.label?.replace(/_/g, ' ')} ({data.bias.score > 0 ? '+' : ''}{data.bias.score})
                </span>
              )}
              {data.dealer && (
                <span className={`dealer-badge ${data.dealer.regime === 'LONG_GAMMA' ? 'green' : 'red'}`}>
                  Dealer: {data.dealer.regime?.replace(/_/g, ' ')}
                </span>
              )}
              {data.dealer?.max_pain && (
                <span className="mono muted">Max Pain: {data.dealer.max_pain?.toFixed(0)}</span>
              )}
              {data.dealer?.put_call_ratio && (
                <span className="mono muted">P/C: {data.dealer.put_call_ratio?.toFixed(2)}</span>
              )}
            </div>
          )}
          <div className="strategies-list">
            {data.strategies.map((s, i) => (
              <StrategyCard key={i} strategy={s} />
            ))}
          </div>
        </>
      )}
    </div>
  );
}

function StrategyCard({ strategy: s }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="strategy-card" onClick={() => setOpen(!open)}>
      <div className="strategy-header">
        <span className="strategy-name">{s.strategy_label}</span>
        <span className="mono">{s.ticker}</span>
        <span className="score-badge" style={{
          background: s.score >= 70 ? 'var(--green-dim)' : s.score >= 50 ? '#92400e' : 'var(--red-dim)',
        }}>
          {s.score?.toFixed(0)}
        </span>
        <span className="muted">{s.checks_passed}/{s.checks_total} checks</span>
        <span className="muted">{s.suggested_dte}d DTE</span>
      </div>
      {open && (
        <div className="strategy-detail">
          <div className="checklist">
            {s.checklist?.map((c, j) => (
              <div key={j} className={`check-item ${c.passed ? 'passed' : 'failed'}`}>
                <span>{c.passed ? '\u2713' : '\u2717'}</span>
                <span>{c.name}</span>
                {c.value && <span className="mono muted">{c.value}</span>}
              </div>
            ))}
          </div>
          <div className="strategy-meta">
            <span>{s.is_credit ? 'Credit' : 'Debit'}: ${s.entry?.toFixed(2)}</span>
            {s.max_profit != null && <span>Max profit: ${s.max_profit?.toFixed(0)}</span>}
            {s.max_loss != null && <span>Max loss: ${s.max_loss?.toFixed(0)}</span>}
            <span>R:R {s.risk_reward}</span>
          </div>
          <div className="rationale muted">{s.rationale}</div>
        </div>
      )}
    </div>
  );
}
