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

export default function RegimeDashboard() {
  const { data, loading, error, refetch } = useApi('/api/regime');

  if (loading) return <div className="panel loading">Loading regime data...</div>;
  if (error) return <div className="panel error">Error: {error} <button onClick={refetch}>Retry</button></div>;
  if (!data) return null;

  const v = data.vix || {};
  const regimeColor = {
    LOW_VOL_RANGING: 'var(--green)',
    HIGH_VOL_TRENDING: 'var(--amber)',
    SPIKE_EVENT: 'var(--red)',
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
    </div>
  );
}
