import { useApi } from '../hooks/useApi';
import './RegimeDashboard.css';

function regimeClass(regime) {
  if (regime === 'HIGH_IV') return 'amber';
  if (regime === 'LOW_IV') return 'green';
  if (regime === 'SPIKE') return 'red';
  return 'muted';
}

function vixColor(value) {
  if (value > 30) return 'var(--red)';
  if (value > 18) return 'var(--amber)';
  return 'var(--green)';
}

function VixCell({ value, label }) {
  const pct = Math.min((value || 0) / 50 * 100, 100);
  const color = vixColor(value);
  return (
    <div className="vix-cell">
      <div className="vix-label">{label}</div>
      <div className="vix-value" style={{ color }}>{value?.toFixed(1) ?? '—'}</div>
      <div className="vix-bar">
        <div className="vix-bar-fill" style={{ width: `${pct}%`, background: color }} />
      </div>
    </div>
  );
}

function StatRow({ label, children }) {
  return (
    <div className="tv-stat-inline">
      <span className="stat-label">{label}</span>
      <span className="stat-value">{children}</span>
    </div>
  );
}

export default function RegimeDashboard() {
  const { data, loading, error, refetch } = useApi('/api/regime');

  if (loading) return <div className="tv-loading">Loading regime data...</div>;
  if (error) return <div className="tv-error">Error: {error} <button className="tv-btn" onClick={refetch} style={{ marginLeft: 8 }}>Retry</button></div>;
  if (!data) return null;

  const v = data.vix || {};
  const d = data.dealer;

  return (
    <div className="regime">
      <div className="regime-strip">
        <span className={`tv-badge ${regimeClass(data.regime)}`}>
          {data.regime?.replace(/_/g, ' ')}
        </span>
        <span className="regime-rationale">{data.rationale}</span>
        {data.event_active && (
          <span className="tv-badge amber">{data.event_type} in {data.event_days}d</span>
        )}
        <button className="tv-btn regime-refresh" onClick={refetch}>Refresh</button>
      </div>

      <div className="vix-strip">
        <VixCell value={v.vix} label="VIX" />
        <VixCell value={v.vix9d} label="VIX9D" />
        <VixCell value={v.vix3m} label="VIX3M" />
        <VixCell value={v.vix6m} label="VIX6M" />
      </div>

      <div className="regime-panels">
        <div className="tv-panel">
          <div className="tv-panel-header">
            <span className="tv-panel-title">Market Structure</span>
          </div>
          <div className="regime-panel-body">
            <StatRow label="Term Structure">
              {v.contango && <span className="green">Contango</span>}
              {v.backwardation && <span className="red">Backwardation</span>}
              {!v.contango && !v.backwardation && <span className="muted">Flat</span>}
              <span className="muted" style={{ marginLeft: 8, fontSize: 12 }}>
                {v.term_structure_slope?.toFixed(3) ?? ''}
              </span>
            </StatRow>
            <StatRow label="VIX Percentile (1Y)">
              <span className="mono">{v.vix_percentile_1y?.toFixed(0) ?? '—'}%</span>
            </StatRow>
            <StatRow label="Event Window">
              {data.event_active
                ? <span className="amber">{data.event_type} — {data.event_days}d</span>
                : <span className="green">Clear</span>
              }
            </StatRow>
          </div>
        </div>

        <div className="tv-panel">
          <div className="tv-panel-header">
            <span className="tv-panel-title">Dealer Positioning</span>
          </div>
          <div className="regime-panel-body">
            {d ? (
              <>
                <StatRow label="Dealer Regime">
                  <span className={`tv-badge ${d.regime === 'LONG_GAMMA' ? 'green' : 'red'}`}>
                    {d.regime?.replace(/_/g, ' ')}
                  </span>
                </StatRow>
                <StatRow label="Net GEX">
                  <span className="mono">{d.net_gex?.toLocaleString() ?? '—'}</span>
                </StatRow>
                <StatRow label="Gamma Flip">
                  <span className="mono">{d.gamma_flip?.toFixed(1) ?? '—'}</span>
                </StatRow>
                <StatRow label="Walls">
                  <span className="mono">
                    <span className="red">C: {d.call_wall?.toFixed(0) ?? '—'}</span>
                    {' / '}
                    <span className="green">P: {d.put_wall?.toFixed(0) ?? '—'}</span>
                  </span>
                </StatRow>
                <StatRow label="Max Pain">
                  <span className="mono">{d.max_pain?.toFixed(1) ?? '—'}</span>
                </StatRow>
                <StatRow label="P/C Ratio">
                  <span className="mono">
                    {d.put_call_ratio?.toFixed(2) ?? '—'}
                    {d.pc_signal && (
                      <span className={d.pc_signal === 'contrarian_bullish' ? 'green' : d.pc_signal === 'contrarian_bearish' ? 'red' : 'muted'}
                        style={{ marginLeft: 8, fontSize: 12 }}>
                        {d.pc_signal?.replace(/_/g, ' ')}
                      </span>
                    )}
                  </span>
                </StatRow>
                {d.implication && (
                  <div className="muted" style={{ fontSize: 12, marginTop: 6 }}>
                    {d.implication.slice(0, 80)}...
                  </div>
                )}
              </>
            ) : (
              <div className="muted" style={{ padding: '8px 0' }}>Dealer data unavailable</div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
