import { useState, useCallback } from 'react';
import { useApi, postApi, putApi, deleteApi } from '../hooks/useApi';
import './Alerts.css';

const TRIGGER_TYPES = [
  { value: 'iv_rank_above', label: 'IV Rank Above' },
  { value: 'iv_rank_below', label: 'IV Rank Below' },
  { value: 'regime_change', label: 'Regime Change' },
  { value: 'price_above', label: 'Price Above' },
  { value: 'price_below', label: 'Price Below' },
  { value: 'scan_match', label: 'Scan Match' },
];

export default function Alerts() {
  const { data, loading, refetch } = useApi('/api/alerts');
  const { data: historyData } = useApi('/api/alerts/history?limit=20');
  const [showForm, setShowForm] = useState(false);
  const [busy, setBusy] = useState(false);

  const alerts = data?.alerts || [];
  const history = historyData?.history || [];

  const toggleActive = useCallback(async (alert) => {
    try {
      await putApi(`/api/alerts/${alert.id}`, { is_active: !alert.is_active });
      refetch();
    } catch (e) {
      alert(e.message);
    }
  }, [refetch]);

  const handleDelete = useCallback(async (id, name) => {
    if (!confirm(`Delete alert "${name}"?`)) return;
    try {
      await deleteApi(`/api/alerts/${id}`);
      refetch();
    } catch (e) {
      alert(e.message);
    }
  }, [refetch]);

  const handleTest = useCallback(async (id) => {
    setBusy(true);
    try {
      await postApi(`/api/alerts/${id}/test`, {});
      window.alert('Test notification sent — check the bell icon');
    } catch (e) {
      window.alert(e.message);
    } finally {
      setBusy(false);
    }
  }, []);

  return (
    <div className="alerts-page">
      <div className="tv-toolbar alerts-toolbar">
        <button className="tv-btn-primary" onClick={() => setShowForm(!showForm)}>
          {showForm ? 'Cancel' : '+ New Alert'}
        </button>
        <button className="tv-btn" onClick={refetch} disabled={loading}>Refresh</button>
      </div>

      {showForm && <NewAlertForm onDone={() => { setShowForm(false); refetch(); }} />}

      {alerts.length === 0 && !loading && (
        <div className="alerts-empty">
          <p>No alerts configured</p>
          <p className="alerts-hint">Create alerts to get notified about IV rank changes, regime shifts, or scan matches</p>
        </div>
      )}

      {alerts.length > 0 && (
        <div className="alerts-list">
          {alerts.map(a => (
            <div key={a.id} className={`alert-card ${a.is_active ? '' : 'inactive'}`}>
              <div className="alert-header">
                <div className="alert-name">{a.name}</div>
                <div className="alert-actions">
                  <button className={`alert-toggle ${a.is_active ? 'on' : 'off'}`}
                    onClick={() => toggleActive(a)} title={a.is_active ? 'Disable' : 'Enable'}>
                    {a.is_active ? 'ON' : 'OFF'}
                  </button>
                  <button className="tv-btn-icon" onClick={() => handleTest(a.id)} disabled={busy} title="Test">
                    <svg viewBox="0 0 16 16" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="1.5">
                      <path d="M8 2v4M8 10v4M2 8h4M10 8h4" />
                    </svg>
                  </button>
                  <button className="tv-btn-icon danger" onClick={() => handleDelete(a.id, a.name)} title="Delete">
                    <svg viewBox="0 0 16 16" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="1.5">
                      <line x1="4" y1="4" x2="12" y2="12" /><line x1="12" y1="4" x2="4" y2="12" />
                    </svg>
                  </button>
                </div>
              </div>
              <div className="alert-meta">
                <span className="alert-type-badge">{a.trigger_type.replace('_', ' ')}</span>
                <span className="alert-config">
                  {a.trigger_config.symbol && `${a.trigger_config.symbol} `}
                  {a.trigger_config.threshold != null && `@ ${a.trigger_config.threshold}`}
                </span>
                <span className="alert-channels">{a.channels.join(', ')}</span>
                {a.last_triggered_at && (
                  <span className="alert-last">Last: {a.last_triggered_at.slice(0, 16)}</span>
                )}
              </div>
            </div>
          ))}
        </div>
      )}

      {history.length > 0 && (
        <div className="alerts-history">
          <h3>Alert History</h3>
          <div className="alerts-history-list">
            {history.map(h => (
              <div key={h.id} className="alert-history-item">
                <span className="alert-history-title">{h.title}</span>
                <span className="alert-history-body">{h.body}</span>
                <span className="alert-history-time">{h.created_at?.slice(0, 16)}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}


function NewAlertForm({ onDone }) {
  const [form, setForm] = useState({
    name: '', trigger_type: 'iv_rank_above',
    symbol: 'SPY', threshold: 60, cooldown_minutes: 60,
  });
  const [busy, setBusy] = useState(false);

  const update = (k, v) => setForm(prev => ({ ...prev, [k]: v }));

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!form.name.trim()) return;
    setBusy(true);
    try {
      await postApi('/api/alerts', {
        name: form.name,
        trigger_type: form.trigger_type,
        trigger_config: { symbol: form.symbol.toUpperCase(), threshold: +form.threshold },
        channels: ['in_app'],
        cooldown_minutes: form.cooldown_minutes,
      });
      onDone();
    } catch (e) {
      alert(e.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <form className="alert-new-form" onSubmit={handleSubmit}>
      <div className="alert-form-row">
        <input className="tv-input" value={form.name} onChange={e => update('name', e.target.value)} placeholder="Alert name" required />
        <select className="tv-input" value={form.trigger_type} onChange={e => update('trigger_type', e.target.value)}>
          {TRIGGER_TYPES.map(t => <option key={t.value} value={t.value}>{t.label}</option>)}
        </select>
        <input className="tv-input sm" value={form.symbol} onChange={e => update('symbol', e.target.value)} placeholder="Symbol" />
        <input className="tv-input sm" type="number" value={form.threshold} onChange={e => update('threshold', e.target.value)} placeholder="Threshold" />
        <div className="tv-field">
          <span className="tv-label">Cooldown (min)</span>
          <input className="tv-input xs" type="number" value={form.cooldown_minutes} onChange={e => update('cooldown_minutes', +e.target.value)} />
        </div>
        <button className="tv-btn-primary" type="submit" disabled={busy}>Create</button>
      </div>
    </form>
  );
}
