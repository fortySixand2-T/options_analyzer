import { useApi } from '../hooks/useApi';
import './Dashboard.css';

function VixGauge({ value, label }) {
  const pct = Math.min(value / 50 * 100, 100);
  const color = value > 30 ? 'var(--red)' : value > 18 ? 'var(--amber)' : 'var(--green)';
  return (
    <div className="gauge">
      <div className="gauge-label">{label}</div>
      <div className="gauge-bar">
        <div className="gauge-fill" style={{ width: `${pct}%`, background: color }} />
      </div>
      <div className="gauge-value mono" style={{ color }}>{value?.toFixed(1) ?? '—'}</div>
    </div>
  );
}

function DealerRegimeBadge({ dealer }) {
  if (!dealer) return <span className="muted">N/A</span>;
  const isLong = dealer.regime === 'LONG_GAMMA';
  const color = isLong ? 'var(--green)' : 'var(--red)';
  return (
    <span className="dealer-badge" style={{ borderColor: color, color }}>
      {dealer.regime?.replace(/_/g, ' ')}
    </span>
  );
}

export default function RegimeDashboard() {
  const { data, loading, error, refetch } = useApi('/api/regime');

  if (loading) return <div className="panel loading">Loading regime data...</div>;
  if (error) return <div className="panel error">Error: {error} <button onClick={refetch}>Retry</button></div>;
  if (!data) return null;

  const v = data.vix || {};
  const d = data.dealer;
  const regimeColor = {
    HIGH_IV: 'var(--amber)',
    MODERATE_IV: 'var(--text)',
    LOW_IV: 'var(--green)',
    SPIKE: 'var(--red)',
  }[data.regime] || 'var(--text-muted)';

  return (
    <div className="dashboard">
      <div className="regime-header">
        <div className="regime-badge" style={{ borderColor: regimeColor, color: regimeColor }}>
          {data.regime?.replace(/_/g, ' ')}
        </div>
        <div className="regime-rationale">{data.rationale}</div>
        {data.event_active && (
          <div className="event-tag amber">
            {data.event_type} in {data.event_days}d
          </div>
        )}
        <button className="refresh-btn" onClick={refetch}>Refresh</button>
      </div>

      <div className="metrics-grid">
        <div className="metric-card">
          <VixGauge value={v.vix} label="VIX" />
        </div>
        <div className="metric-card">
          <VixGauge value={v.vix9d} label="VIX9D" />
        </div>
        <div className="metric-card">
          <VixGauge value={v.vix3m} label="VIX3M" />
        </div>
        <div className="metric-card">
          <VixGauge value={v.vix6m} label="VIX6M" />
        </div>
      </div>

      <div className="metrics-grid">
        <div className="metric-card">
          <div className="metric-label">Term Structure</div>
          <div className="metric-value mono">
            {v.contango && <span className="green">Contango</span>}
            {v.backwardation && <span className="red">Backwardation</span>}
            {!v.contango && !v.backwardation && <span className="muted">Flat</span>}
          </div>
          <div className="metric-sub">Slope: {v.term_structure_slope?.toFixed(3) ?? '—'}</div>
        </div>
        <div className="metric-card">
          <div className="metric-label">VIX Percentile (1Y)</div>
          <div className="metric-value mono">{v.vix_percentile_1y?.toFixed(0) ?? '—'}%</div>
        </div>
        <div className="metric-card">
          <div className="metric-label">Event Window</div>
          <div className="metric-value">
            {data.event_active
              ? <span className="amber">{data.event_type} — {data.event_days}d</span>
              : <span className="green">Clear</span>
            }
          </div>
        </div>
      </div>

      {/* Dealer Positioning (GEX) */}
      <div className="section-header">Dealer Positioning</div>
      {d ? (
        <div className="metrics-grid">
          <div className="metric-card">
            <div className="metric-label">Dealer Regime</div>
            <div className="metric-value"><DealerRegimeBadge dealer={d} /></div>
            <div className="metric-sub">{d.implication?.slice(0, 60)}...</div>
          </div>
          <div className="metric-card">
            <div className="metric-label">Net GEX</div>
            <div className="metric-value mono">{d.net_gex?.toLocaleString() ?? '—'}</div>
          </div>
          <div className="metric-card">
            <div className="metric-label">Gamma Flip</div>
            <div className="metric-value mono">{d.gamma_flip?.toFixed(1) ?? '—'}</div>
          </div>
          <div className="metric-card">
            <div className="metric-label">Walls</div>
            <div className="metric-value mono">
              <span className="red">C: {d.call_wall?.toFixed(0) ?? '—'}</span>
              {' / '}
              <span className="green">P: {d.put_wall?.toFixed(0) ?? '—'}</span>
            </div>
          </div>
          <div className="metric-card">
            <div className="metric-label">Max Pain</div>
            <div className="metric-value mono">{d.max_pain?.toFixed(1) ?? '—'}</div>
          </div>
          <div className="metric-card">
            <div className="metric-label">P/C Ratio</div>
            <div className="metric-value mono">
              {d.put_call_ratio?.toFixed(2) ?? '—'}
              {d.pc_signal && (
                <span className={d.pc_signal === 'contrarian_bullish' ? 'green' : d.pc_signal === 'contrarian_bearish' ? 'red' : 'muted'}>
                  {' '}({d.pc_signal?.replace(/_/g, ' ')})
                </span>
              )}
            </div>
          </div>
        </div>
      ) : (
        <div className="panel muted">Dealer data unavailable (set FLASHALPHA_API_KEY)</div>
      )}
    </div>
  );
}
