import { useState, useEffect, useCallback } from 'react';

const API = '/api/shadow-trades';

function ShadowTrades() {
  const [trades, setTrades] = useState([]);
  const [stats, setStats] = useState(null);
  const [filter, setFilter] = useState('all');
  const [loading, setLoading] = useState(true);
  const [scanning, setScanning] = useState(false);
  const [checking, setChecking] = useState(false);
  const [error, setError] = useState(null);

  const fetchTrades = useCallback(async () => {
    try {
      const params = filter !== 'all' ? `?status=${filter}` : '';
      const res = await fetch(`${API}${params}`);
      const data = await res.json();
      setTrades(data.trades || []);
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, [filter]);

  const fetchStats = useCallback(async () => {
    try {
      const res = await fetch(`${API}/stats`);
      setStats(await res.json());
    } catch (e) {
      console.error('Stats fetch failed:', e);
    }
  }, []);

  useEffect(() => {
    fetchTrades();
    fetchStats();
  }, [fetchTrades, fetchStats]);

  // Auto-refresh for open trades
  useEffect(() => {
    if (filter === 'open' || filter === 'all') {
      const interval = setInterval(fetchTrades, 60000);
      return () => clearInterval(interval);
    }
  }, [filter, fetchTrades]);

  const handleScan = async () => {
    setScanning(true);
    try {
      const res = await fetch(`${API}/scan-and-log?symbols=SPY,QQQ,IWM`, { method: 'POST' });
      const data = await res.json();
      alert(`Scanned ${data.scanned} tickers: ${data.logged} new trades logged, ${data.candidates} candidates found`);
      fetchTrades();
      fetchStats();
    } catch (e) {
      alert('Scan failed: ' + e.message);
    } finally {
      setScanning(false);
    }
  };

  const handleCheck = async () => {
    setChecking(true);
    try {
      const res = await fetch(`${API}/check`, { method: 'POST' });
      const data = await res.json();
      alert(`Checked ${data.trades_checked} trades: ${data.trades_closed} closed`);
      fetchTrades();
      fetchStats();
    } catch (e) {
      alert('Check failed: ' + e.message);
    } finally {
      setChecking(false);
    }
  };

  if (loading) return <div className="loading">Loading shadow trades...</div>;

  return (
    <div className="shadow-trades">
      <div className="shadow-header">
        <h2>Shadow Paper Trading</h2>
        <div className="shadow-actions">
          <button onClick={handleScan} disabled={scanning} className="btn btn-primary">
            {scanning ? 'Scanning...' : 'Scan & Log'}
          </button>
          <button onClick={handleCheck} disabled={checking} className="btn btn-secondary">
            {checking ? 'Checking...' : 'Check Exits'}
          </button>
        </div>
      </div>

      {stats && (
        <div className="shadow-stats-grid">
          <StatCard label="Total Trades" value={stats.total_trades} />
          <StatCard label="Open" value={stats.open_trades} />
          <StatCard label="Win Rate" value={stats.win_rate ? `${stats.win_rate}%` : '—'} />
          <StatCard label="Total P&L" value={`$${(stats.total_pnl || 0).toFixed(2)}`}
                    className={stats.total_pnl >= 0 ? 'positive' : 'negative'} />
          <StatCard label="Avg P&L" value={`$${(stats.avg_pnl || 0).toFixed(2)}`}
                    className={stats.avg_pnl >= 0 ? 'positive' : 'negative'} />
          <StatCard label="Best" value={`$${(stats.best_trade || 0).toFixed(2)}`} className="positive" />
          <StatCard label="Worst" value={`$${(stats.worst_trade || 0).toFixed(2)}`} className="negative" />
        </div>
      )}

      {stats?.by_strategy && Object.keys(stats.by_strategy).length > 0 && (
        <div className="strategy-breakdown">
          <h3>By Strategy</h3>
          <table className="shadow-table compact">
            <thead>
              <tr>
                <th>Strategy</th><th>Trades</th><th>Win Rate</th><th>Avg P&L</th><th>Total P&L</th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(stats.by_strategy).map(([name, s]) => (
                <tr key={name}>
                  <td>{name.replace(/_/g, ' ')}</td>
                  <td>{s.trades}</td>
                  <td>{s.win_rate}%</td>
                  <td className={s.avg_pnl >= 0 ? 'positive' : 'negative'}>${s.avg_pnl}</td>
                  <td className={s.pnl >= 0 ? 'positive' : 'negative'}>${s.pnl.toFixed(2)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <div className="shadow-filter-row">
        <h3>Trades</h3>
        <div className="filter-btns">
          {['all', 'open', 'closed'].map(f => (
            <button key={f} className={`filter-btn ${filter === f ? 'active' : ''}`}
                    onClick={() => setFilter(f)}>
              {f.charAt(0).toUpperCase() + f.slice(1)}
            </button>
          ))}
        </div>
      </div>

      {error && <div className="error-msg">{error}</div>}

      {trades.length === 0 ? (
        <div className="empty-state">
          No {filter !== 'all' ? filter : ''} shadow trades yet.
          Click "Scan & Log" to start tracking signals.
        </div>
      ) : (
        <table className="shadow-table">
          <thead>
            <tr>
              <th>ID</th>
              <th>Date</th>
              <th>Symbol</th>
              <th>Strategy</th>
              <th>Entry</th>
              <th>Exit</th>
              <th>P&L</th>
              <th>Score</th>
              <th>Regime</th>
              <th>Bias</th>
              <th>Status</th>
              <th>Exit Reason</th>
            </tr>
          </thead>
          <tbody>
            {trades.map(t => (
              <tr key={t.id} className={`trade-row ${t.status}`}>
                <td>{t.id}</td>
                <td>{t.entry_date}</td>
                <td className="symbol">{t.symbol}</td>
                <td>{t.strategy_label}</td>
                <td>${t.entry_net_price?.toFixed(4)}</td>
                <td>{t.exit_net_price != null ? `$${t.exit_net_price.toFixed(4)}` : '—'}</td>
                <td className={t.pnl_total > 0 ? 'positive' : t.pnl_total < 0 ? 'negative' : ''}>
                  {t.pnl_total != null ? `$${t.pnl_total.toFixed(2)}` : '—'}
                </td>
                <td>{t.confluence_score?.toFixed(0)}</td>
                <td><span className={`regime-badge ${(t.regime || '').toLowerCase()}`}>{t.regime || '—'}</span></td>
                <td>{t.bias_label || '—'}</td>
                <td><span className={`status-badge ${t.status}`}>{t.status}</span></td>
                <td>{t.exit_reason || '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      <style>{`
        .shadow-trades { padding: 0 1rem; }
        .shadow-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 1rem; }
        .shadow-header h2 { margin: 0; font-size: 1.3rem; }
        .shadow-actions { display: flex; gap: 0.5rem; }
        .btn { padding: 0.4rem 1rem; border: none; border-radius: 4px; cursor: pointer; font-size: 0.85rem; }
        .btn-primary { background: #2563eb; color: white; }
        .btn-primary:hover { background: #1d4ed8; }
        .btn-primary:disabled { background: #93c5fd; cursor: wait; }
        .btn-secondary { background: #374151; color: white; }
        .btn-secondary:hover { background: #4b5563; }
        .btn-secondary:disabled { background: #6b7280; cursor: wait; }

        .shadow-stats-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(100px, 1fr)); gap: 0.5rem; margin-bottom: 1rem; }
        .stat-card { background: #1e293b; border-radius: 6px; padding: 0.6rem; text-align: center; }
        .stat-card .stat-label { font-size: 0.7rem; color: #94a3b8; text-transform: uppercase; }
        .stat-card .stat-value { font-size: 1.1rem; font-weight: 600; margin-top: 0.2rem; }
        .stat-card .stat-value.positive { color: #22c55e; }
        .stat-card .stat-value.negative { color: #ef4444; }

        .strategy-breakdown { margin-bottom: 1rem; }
        .strategy-breakdown h3 { font-size: 0.9rem; margin-bottom: 0.5rem; }

        .shadow-filter-row { display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.5rem; }
        .shadow-filter-row h3 { margin: 0; font-size: 0.9rem; }
        .filter-btns { display: flex; gap: 0.3rem; }
        .filter-btn { padding: 0.25rem 0.7rem; border: 1px solid #374151; background: transparent; color: #94a3b8; border-radius: 4px; cursor: pointer; font-size: 0.8rem; }
        .filter-btn.active { background: #2563eb; color: white; border-color: #2563eb; }

        .shadow-table { width: 100%; border-collapse: collapse; font-size: 0.82rem; }
        .shadow-table.compact { font-size: 0.8rem; margin-bottom: 0.5rem; }
        .shadow-table th { text-align: left; padding: 0.4rem 0.6rem; border-bottom: 1px solid #334155; color: #94a3b8; font-size: 0.75rem; text-transform: uppercase; }
        .shadow-table td { padding: 0.35rem 0.6rem; border-bottom: 1px solid #1e293b; }
        .shadow-table .symbol { font-weight: 600; }
        .positive { color: #22c55e; }
        .negative { color: #ef4444; }

        .trade-row.closed { opacity: 0.8; }
        .status-badge { padding: 0.15rem 0.5rem; border-radius: 10px; font-size: 0.72rem; font-weight: 500; }
        .status-badge.open { background: #1e3a5f; color: #60a5fa; }
        .status-badge.closed { background: #1a2e1a; color: #86efac; }
        .status-badge.expired { background: #3b2020; color: #fca5a5; }
        .regime-badge { padding: 0.1rem 0.4rem; border-radius: 3px; font-size: 0.72rem; }
        .regime-badge.high_iv { background: #7c2d12; color: #fed7aa; }
        .regime-badge.moderate_iv { background: #1e3a5f; color: #93c5fd; }
        .regime-badge.low_iv { background: #14532d; color: #bbf7d0; }

        .empty-state { text-align: center; padding: 2rem; color: #64748b; }
        .error-msg { color: #ef4444; padding: 0.5rem; background: #3b1010; border-radius: 4px; margin-bottom: 0.5rem; }
        .loading { text-align: center; padding: 2rem; color: #64748b; }
      `}</style>
    </div>
  );
}

function StatCard({ label, value, className = '' }) {
  return (
    <div className="stat-card">
      <div className="stat-label">{label}</div>
      <div className={`stat-value ${className}`}>{value}</div>
    </div>
  );
}

export default ShadowTrades;
