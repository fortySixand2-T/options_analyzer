import { useState, useMemo } from 'react';
import { useApi } from '../hooks/useApi';
import './Scanner.css';

export default function Scanner() {
  const [symbols, setSymbols] = useState('SPY,QQQ,IWM');
  const [maxDte, setMaxDte] = useState(14);
  const [withStrategies, setWithStrategies] = useState(false);
  const [queryPath, setQueryPath] = useState(null);
  const [sortCol, setSortCol] = useState(null);
  const [sortAsc, setSortAsc] = useState(true);

  const { data, loading, error } = useApi(queryPath, { manual: !queryPath });

  function handleScan() {
    const params = new URLSearchParams({
      symbols, max_dte: maxDte, strategies: withStrategies, top: 20,
    });
    setQueryPath(`/api/scan?${params}`);
  }

  function toggleSort(col) {
    if (sortCol === col) setSortAsc(!sortAsc);
    else { setSortCol(col); setSortAsc(true); }
  }

  const sortedSignals = useMemo(() => {
    if (!data?.signals || !sortCol) return data?.signals || [];
    return [...data.signals].sort((a, b) => {
      const av = a[sortCol], bv = b[sortCol];
      if (av == null) return 1;
      if (bv == null) return -1;
      return sortAsc ? (av > bv ? 1 : -1) : (av < bv ? 1 : -1);
    });
  }, [data?.signals, sortCol, sortAsc]);

  const SortTh = ({ col, children }) => (
    <th onClick={() => toggleSort(col)}>
      {children}
      {sortCol === col && <span className="sort-arrow">{sortAsc ? ' ▲' : ' ▼'}</span>}
    </th>
  );

  return (
    <div className="scanner">
      <div className="tv-toolbar scanner-toolbar">
        <input className="tv-input" value={symbols}
          onChange={e => setSymbols(e.target.value)} placeholder="SPY,QQQ,IWM" />
        <div className="tv-field">
          <span className="tv-label">DTE</span>
          <input className="tv-input sm" type="number" value={maxDte}
            onChange={e => setMaxDte(+e.target.value)} />
        </div>
        <div className="tv-toggle-group">
          <button className={`tv-toggle ${!withStrategies ? 'active' : ''}`}
            onClick={() => setWithStrategies(false)}>Signals</button>
          <button className={`tv-toggle ${withStrategies ? 'active' : ''}`}
            onClick={() => setWithStrategies(true)}>Strategies</button>
        </div>
        <button className="tv-btn-primary" onClick={handleScan} disabled={loading}>
          {loading ? 'Scanning...' : 'Scan'}
        </button>
      </div>

      {error && <div className="tv-error">Error: {error}</div>}

      {data && !withStrategies && data.signals && (
        <div className="tv-panel" style={{ overflow: 'auto' }}>
          <table className="tv-table">
            <thead>
              <tr>
                <SortTh col="ticker">Ticker</SortTh>
                <SortTh col="strike">Strike</SortTh>
                <th>Type</th>
                <SortTh col="dte">DTE</SortTh>
                <SortTh col="mid">Mid</SortTh>
                <SortTh col="iv_rank">IV Rank</SortTh>
                <SortTh col="edge_pct">Edge%</SortTh>
                <th>Dir</th>
                <SortTh col="delta">Delta</SortTh>
                <SortTh col="theta">Theta</SortTh>
                <SortTh col="conviction">Score</SortTh>
              </tr>
            </thead>
            <tbody>
              {sortedSignals.map((s, i) => (
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
          {(data.regime || data.bias || data.dealer) && (
            <div className="scanner-context">
              {data.regime && (
                <span className="tv-badge muted">
                  {data.regime.regime?.replace(/_/g, ' ')}
                </span>
              )}
              {data.bias && (
                <span className={`tv-badge ${data.bias.label?.includes('BULLISH') ? 'green' : data.bias.label?.includes('BEARISH') ? 'red' : 'muted'}`}>
                  Bias: {data.bias.label?.replace(/_/g, ' ')} ({data.bias.score > 0 ? '+' : ''}{data.bias.score})
                </span>
              )}
              {data.dealer && (
                <span className={`tv-badge ${data.dealer.regime === 'LONG_GAMMA' ? 'green' : 'red'}`}>
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
          <div className="tv-panel" style={{ overflow: 'auto' }}>
            <table className="tv-table">
              <thead>
                <tr>
                  <th>Ticker</th><th>Strategy</th><th>Score</th>
                  <th>Checks</th><th>DTE</th><th>Entry</th><th>R:R</th>
                </tr>
              </thead>
              <tbody>
                {data.strategies.map((s, i) => (
                  <StrategyRow key={i} strategy={s} />
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  );
}

function StrategyRow({ strategy: s }) {
  const [open, setOpen] = useState(false);
  const scoreBg = s.score >= 70 ? 'var(--green)' : s.score >= 50 ? 'var(--amber)' : 'var(--red)';
  return (
    <>
      <tr className="strategy-row" onClick={() => setOpen(!open)}>
        <td className="mono">{s.ticker}</td>
        <td>{s.strategy_label}</td>
        <td>
          <span className="tv-score" style={{ background: scoreBg }}>
            {s.score?.toFixed(0)}
          </span>
        </td>
        <td className="muted">{s.checks_passed}/{s.checks_total}</td>
        <td className="mono">{s.suggested_dte}d</td>
        <td className="mono">{s.is_credit ? 'Cr' : 'Dr'} ${s.entry?.toFixed(2)}</td>
        <td className="mono">{s.risk_reward}</td>
      </tr>
      {open && (
        <tr className="strategy-detail-row">
          <td colSpan={7}>
            <div className="strategy-detail-content">
              <div className="strategy-checklist">
                {s.checklist?.map((c, j) => (
                  <div key={j} className={`strategy-check ${c.passed ? 'passed' : 'failed'}`}>
                    <span>{c.passed ? '✓' : '✗'}</span>
                    <span className="check-name">{c.name}</span>
                    {c.value && <span className="check-val">{c.value}</span>}
                  </div>
                ))}
              </div>
              <div className="strategy-meta">
                {s.max_profit != null && <span>Max profit: ${s.max_profit?.toFixed(0)}</span>}
                {s.max_loss != null && <span>Max loss: ${s.max_loss?.toFixed(0)}</span>}
              </div>
              {s.rationale && <div className="strategy-rationale">{s.rationale}</div>}
            </div>
          </td>
        </tr>
      )}
    </>
  );
}
