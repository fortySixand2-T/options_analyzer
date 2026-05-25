import { useState, useCallback } from 'react';
import { useApi, postApi, putApi, deleteApi } from '../hooks/useApi';
import './Watchlist.css';

export default function Watchlist() {
  const { data, loading, refetch } = useApi('/api/watchlist');
  const [adding, setAdding] = useState(false);
  const [newSymbol, setNewSymbol] = useState('');
  const [editingId, setEditingId] = useState(null);
  const [editNotes, setEditNotes] = useState('');
  const [editAbove, setEditAbove] = useState('');
  const [editBelow, setEditBelow] = useState('');
  const [busy, setBusy] = useState(false);

  const items = data?.items || [];

  const handleAdd = useCallback(async () => {
    const sym = newSymbol.trim().toUpperCase();
    if (!sym) return;
    setBusy(true);
    try {
      await postApi('/api/watchlist', { symbol: sym });
      setNewSymbol('');
      setAdding(false);
      refetch();
    } catch (e) {
      alert(e.message);
    } finally {
      setBusy(false);
    }
  }, [newSymbol, refetch]);

  const handleDelete = useCallback(async (id, symbol) => {
    if (!confirm(`Remove ${symbol} from watchlist?`)) return;
    try {
      await deleteApi(`/api/watchlist/${id}`);
      refetch();
    } catch (e) {
      alert(e.message);
    }
  }, [refetch]);

  const startEdit = useCallback((item) => {
    setEditingId(item.id);
    setEditNotes(item.notes || '');
    setEditAbove(item.alert_iv_rank_above ?? '');
    setEditBelow(item.alert_iv_rank_below ?? '');
  }, []);

  const saveEdit = useCallback(async () => {
    setBusy(true);
    try {
      await putApi(`/api/watchlist/${editingId}`, {
        notes: editNotes,
        alert_iv_rank_above: editAbove === '' ? null : +editAbove,
        alert_iv_rank_below: editBelow === '' ? null : +editBelow,
      });
      setEditingId(null);
      refetch();
    } catch (e) {
      alert(e.message);
    } finally {
      setBusy(false);
    }
  }, [editingId, editNotes, editAbove, editBelow, refetch]);

  const regimeBadge = (regime) => {
    if (!regime) return null;
    const cls = regime === 'HIGH_IV' ? 'badge-red'
      : regime === 'SPIKE' ? 'badge-amber'
      : regime === 'LOW_IV' ? 'badge-green'
      : 'badge-blue';
    return <span className={`wl-badge ${cls}`}>{regime.replace('_', ' ')}</span>;
  };

  return (
    <div className="watchlist">
      <div className="tv-toolbar wl-toolbar">
        {adding ? (
          <div className="wl-add-row">
            <input
              className="tv-input"
              value={newSymbol}
              onChange={e => setNewSymbol(e.target.value)}
              onKeyDown={e => e.key === 'Enter' && handleAdd()}
              placeholder="Symbol (e.g. SPY)"
              autoFocus
            />
            <button className="tv-btn-primary" onClick={handleAdd} disabled={busy}>Add</button>
            <button className="tv-btn" onClick={() => { setAdding(false); setNewSymbol(''); }}>Cancel</button>
          </div>
        ) : (
          <button className="tv-btn-primary" onClick={() => setAdding(true)}>+ Add Symbol</button>
        )}
        <button className="tv-btn" onClick={refetch} disabled={loading}>Refresh</button>
      </div>

      {loading && items.length === 0 && <div className="wl-loading">Loading watchlist...</div>}

      {items.length === 0 && !loading && (
        <div className="wl-empty">
          <p>Your watchlist is empty</p>
          <p className="wl-hint">Add symbols to track IV rank, regime, and set alerts</p>
        </div>
      )}

      {items.length > 0 && (
        <table className="tv-table wl-table">
          <thead>
            <tr>
              <th>Symbol</th>
              <th>Spot</th>
              <th>1D %</th>
              <th>IV Rank</th>
              <th>Regime</th>
              <th>Alert</th>
              <th>Notes</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {items.map(item => (
              <tr key={item.id}>
                <td className="wl-symbol">{item.symbol}</td>
                <td>{item.spot != null ? item.spot.toFixed(2) : '—'}</td>
                <td className={item.change_1d > 0 ? 'text-green' : item.change_1d < 0 ? 'text-red' : ''}>
                  {item.change_1d != null ? `${item.change_1d > 0 ? '+' : ''}${item.change_1d}%` : '—'}
                </td>
                <td>
                  {item.iv_rank != null ? (
                    <div className="wl-iv-bar-wrap">
                      <div className="wl-iv-bar" style={{ width: `${Math.min(item.iv_rank, 100)}%` }}
                        data-high={item.iv_rank > 50 ? '' : undefined} />
                      <span className="wl-iv-val">{Math.round(item.iv_rank)}</span>
                    </div>
                  ) : '—'}
                </td>
                <td>{regimeBadge(item.regime)}</td>
                <td className="wl-alert-cell">
                  {(item.alert_iv_rank_above || item.alert_iv_rank_below) ? (
                    <span className="wl-alert-tag">
                      {item.alert_iv_rank_above && `↑${item.alert_iv_rank_above}`}
                      {item.alert_iv_rank_above && item.alert_iv_rank_below && ' '}
                      {item.alert_iv_rank_below && `↓${item.alert_iv_rank_below}`}
                    </span>
                  ) : '—'}
                </td>
                <td className="wl-notes-cell">
                  {editingId === item.id ? (
                    <div className="wl-edit-form">
                      <input className="tv-input sm" value={editNotes}
                        onChange={e => setEditNotes(e.target.value)} placeholder="Notes" />
                      <div className="wl-edit-alerts">
                        <label>Alert IV above:
                          <input className="tv-input xs" type="number" value={editAbove}
                            onChange={e => setEditAbove(e.target.value)} />
                        </label>
                        <label>Alert IV below:
                          <input className="tv-input xs" type="number" value={editBelow}
                            onChange={e => setEditBelow(e.target.value)} />
                        </label>
                      </div>
                      <div className="wl-edit-actions">
                        <button className="tv-btn-primary sm" onClick={saveEdit} disabled={busy}>Save</button>
                        <button className="tv-btn sm" onClick={() => setEditingId(null)}>Cancel</button>
                      </div>
                    </div>
                  ) : (
                    <span className="wl-notes-text">{item.notes || ''}</span>
                  )}
                </td>
                <td className="wl-actions">
                  {editingId !== item.id && (
                    <>
                      <button className="tv-btn-icon" title="Edit" onClick={() => startEdit(item)}>
                        <svg viewBox="0 0 16 16" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="1.5">
                          <path d="M11.5 1.5l3 3L5 14H2v-3z" />
                        </svg>
                      </button>
                      <button className="tv-btn-icon danger" title="Remove" onClick={() => handleDelete(item.id, item.symbol)}>
                        <svg viewBox="0 0 16 16" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="1.5">
                          <line x1="4" y1="4" x2="12" y2="12" /><line x1="12" y1="4" x2="4" y2="12" />
                        </svg>
                      </button>
                    </>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
