import { useState } from 'react';
import { BarChart, Bar, LineChart, Line, XAxis, YAxis, Tooltip, Cell, ResponsiveContainer, ReferenceLine } from 'recharts';
import { useApi } from '../hooks/useApi';
import './Dashboard.css';

export default function SwingScanner() {
  const [symbols, setSymbols] = useState('SPY,QQQ,IWM');
  const [queryPath, setQueryPath] = useState(null);

  const { data, loading, error } = useApi(queryPath, { manual: !queryPath });

  function handleScan() {
    const params = new URLSearchParams({ symbols, top: 20 });
    setQueryPath(`/api/swing/scan?${params}`);
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
        <button className="btn-primary" onClick={handleScan} disabled={loading}>
          {loading ? 'Scanning...' : 'Swing Scan'}
        </button>
      </div>

      {error && <div className="panel error">Error: {error}</div>}

      {data && (
        <>
          {/* Regime + Swing Bias + Dealer */}
          <div className="regime-banner">
            Regime: <strong>{data.regime?.regime}</strong>
            {data.regime?.rationale && <span className="muted"> — {data.regime.rationale}</span>}
          </div>

          <div className="signal-context">
            {data.swing_bias && (
              <span className={`bias-badge ${data.swing_bias.label?.includes('BULLISH') ? 'green' : data.swing_bias.label?.includes('BEARISH') ? 'red' : 'muted'}`}>
                Swing Bias: {data.swing_bias.label?.replace(/_/g, ' ')} ({data.swing_bias.score > 0 ? '+' : ''}{data.swing_bias.score})
              </span>
            )}
            {data.dealer && (
              <span className={`dealer-badge ${data.dealer.regime === 'LONG_GAMMA' ? 'green' : 'red'}`}>
                Dealer: {data.dealer.regime?.replace(/_/g, ' ')}
              </span>
            )}
          </div>

          {/* Decision Matrix Result */}
          {data.decision && (
            <div className="panel" style={{ borderLeft: '3px solid var(--green)' }}>
              <div style={{ fontWeight: 600 }}>
                Decision: {data.decision.label}
              </div>
              <div className="muted" style={{ fontSize: '0.85rem', marginTop: 4 }}>
                {data.decision.rationale}
              </div>
              <div className="mono muted" style={{ fontSize: '0.8rem', marginTop: 4 }}>
                DTE: {data.decision.suggested_dte?.[0]}-{data.decision.suggested_dte?.[1]} | Edge: {data.decision.edge_source}
              </div>
            </div>
          )}

          {/* Edge Panels */}
          <div className="grid-3">
            <VRPPanel vrp={data.vrp} />
            <TermStructurePanel ts={data.term_structure} />
            <EarningsPanel earnings={data.earnings} />
          </div>

          {/* Strategy Results */}
          {data.strategies?.length > 0 && (
            <div className="strategies-list">
              <h3>Strategy Matches ({data.strategies.length})</h3>
              {data.strategies.map((s, i) => (
                <StrategyCard key={i} strategy={s} />
              ))}
            </div>
          )}

          {data.strategies?.length === 0 && (
            <div className="panel muted" style={{ textAlign: 'center', padding: 32 }}>
              No swing strategies match current conditions. {data.signals_count} signals scanned.
            </div>
          )}
        </>
      )}
    </div>
  );
}


function VRPPanel({ vrp }) {
  if (!vrp?.buckets?.length) {
    return (
      <div className="panel">
        <h4>VRP Curve</h4>
        <div className="muted">No VRP data available</div>
      </div>
    );
  }

  const chartData = vrp.buckets.map(b => ({
    name: b.label,
    vrp_pct: parseFloat(b.vrp_pct?.toFixed(1)),
  }));

  return (
    <div className="panel">
      <h4>Variance Risk Premium</h4>
      <div className="mono" style={{ marginBottom: 8 }}>
        Overall: <span className={vrp.overall_vrp_pct > 0 ? 'green' : 'red'}>
          {vrp.overall_vrp_pct?.toFixed(1)}%
        </span>
        {vrp.richest_bucket && (
          <span className="muted"> (richest: {vrp.richest_bucket})</span>
        )}
      </div>
      <ResponsiveContainer width="100%" height={140}>
        <BarChart data={chartData} margin={{ top: 5, right: 10, left: -10, bottom: 0 }}>
          <XAxis dataKey="name" tick={{ fill: '#9ca3af', fontSize: 11 }} />
          <YAxis tick={{ fill: '#9ca3af', fontSize: 11 }} tickFormatter={v => `${v}%`} />
          <Tooltip
            contentStyle={{ background: '#1f2937', border: '1px solid #374151', borderRadius: 6 }}
            labelStyle={{ color: '#d1d5db' }}
            formatter={v => [`${v}%`, 'VRP']}
          />
          <ReferenceLine y={0} stroke="#4b5563" />
          <Bar dataKey="vrp_pct" radius={[4, 4, 0, 0]}>
            {chartData.map((entry, i) => (
              <Cell key={i} fill={entry.vrp_pct >= 0 ? '#22c55e' : '#ef4444'} />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}


function TermStructurePanel({ ts }) {
  if (!ts?.expiries?.length) {
    return (
      <div className="panel">
        <h4>Term Structure</h4>
        <div className="muted">No term structure data available</div>
      </div>
    );
  }

  const chartData = ts.expiries.slice(0, 8).map(e => ({
    name: `${e.dte}d`,
    iv: parseFloat((e.atm_iv * 100).toFixed(1)),
    isKink: ts.kink_expiry === e.expiry,
  }));

  return (
    <div className="panel">
      <h4>IV Term Structure</h4>
      <div className="ts-meta mono" style={{ marginBottom: 8 }}>
        <span className={ts.contango ? 'green' : 'red'}>
          {ts.contango ? 'Contango' : 'Backwardation'}
        </span>
        <span className="muted"> | Slope: {ts.slope?.toFixed(1)}%</span>
        {ts.calendar_signal !== 0 && (
          <span className="muted"> | Calendar: {ts.calendar_signal?.toFixed(2)}</span>
        )}
      </div>
      {ts.kink_expiry && (
        <div className="kink-alert" style={{ color: 'var(--yellow)', fontSize: '0.85rem', marginBottom: 4 }}>
          Kink at {ts.kink_expiry} ({ts.kink_magnitude?.toFixed(1)} stdev)
        </div>
      )}
      <ResponsiveContainer width="100%" height={140}>
        <LineChart data={chartData} margin={{ top: 5, right: 10, left: -10, bottom: 0 }}>
          <XAxis dataKey="name" tick={{ fill: '#9ca3af', fontSize: 11 }} />
          <YAxis tick={{ fill: '#9ca3af', fontSize: 11 }} tickFormatter={v => `${v}%`} domain={['auto', 'auto']} />
          <Tooltip
            contentStyle={{ background: '#1f2937', border: '1px solid #374151', borderRadius: 6 }}
            labelStyle={{ color: '#d1d5db' }}
            formatter={v => [`${v}%`, 'IV']}
          />
          <Line
            type="monotone" dataKey="iv" stroke="#60a5fa" strokeWidth={2}
            dot={(props) => {
              const { cx, cy, payload } = props;
              if (payload.isKink) {
                return <circle cx={cx} cy={cy} r={5} fill="#ef4444" stroke="#ef4444" />;
              }
              return <circle cx={cx} cy={cy} r={3} fill="#60a5fa" stroke="#60a5fa" />;
            }}
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}


function EarningsPanel({ earnings }) {
  if (!earnings || earnings.earnings_days == null) {
    return (
      <div className="panel">
        <h4>Earnings</h4>
        <div className="muted">N/A (index or no data)</div>
      </div>
    );
  }

  return (
    <div className="panel">
      <h4>Earnings</h4>
      <div className="mono">
        Days to earnings: <strong>{earnings.earnings_days}</strong>
      </div>
      {earnings.in_earnings_window && (
        <div style={{ color: 'var(--yellow)', fontWeight: 600, marginTop: 4 }}>
          In earnings window
        </div>
      )}
      <div className="mono muted" style={{ marginTop: 4 }}>
        IV inflation: {(earnings.earnings_iv_inflation * 100)?.toFixed(0)}%
      </div>
      {earnings.expected_move_pct > 0 && (
        <div className="mono muted">
          Expected move: {earnings.expected_move_pct?.toFixed(1)}%
        </div>
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
                <span>{c.passed ? '✓' : '✗'}</span>
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
