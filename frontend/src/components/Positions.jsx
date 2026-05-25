import { useState, useCallback } from 'react';
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell } from 'recharts';
import { useApi, postApi, putApi } from '../hooks/useApi';
import './Positions.css';

const STRATEGIES = ['iron_condor', 'credit_spread', 'debit_spread', 'butterfly'];

export default function Positions() {
  const [view, setView] = useState('open');
  const [showForm, setShowForm] = useState(false);
  const [closingId, setClosingId] = useState(null);
  const [exitPrice, setExitPrice] = useState('');
  const [exitReason, setExitReason] = useState('profit_target');
  const [busy, setBusy] = useState(false);

  const queryStatus = view === 'greeks' ? 'open' : view;
  const { data, loading, refetch } = useApi(`/api/positions?status=${queryStatus}&limit=200`);
  const { data: greeksData, refetch: refetchGreeks } = useApi('/api/positions/greeks');
  const { data: summary } = useApi('/api/positions/summary');

  const positions = data?.positions || [];

  const handleClose = useCallback(async (id) => {
    if (!exitPrice) return;
    setBusy(true);
    try {
      const result = await postApi(`/api/positions/${id}/close`, {
        exit_price: +exitPrice,
        exit_reason: exitReason,
      });
      setClosingId(null);
      setExitPrice('');
      refetch();
      refetchGreeks();
      alert(`Closed for P&L: $${result.pnl}`);
    } catch (e) {
      alert(e.message);
    } finally {
      setBusy(false);
    }
  }, [exitPrice, exitReason, refetch, refetchGreeks]);

  const greeks = greeksData?.greeks || {};
  const greeksChartData = [
    { name: 'Delta', value: greeks.delta || 0 },
    { name: 'Gamma', value: greeks.gamma || 0 },
    { name: 'Theta', value: greeks.theta || 0 },
    { name: 'Vega', value: greeks.vega || 0 },
  ];

  return (
    <div className="positions">
      {/* Summary strip */}
      {summary && (
        <div className="pos-summary-strip">
          <div className="pos-stat">
            <span className="pos-stat-label">Open</span>
            <span className="pos-stat-val">{summary.open}</span>
          </div>
          <div className="pos-stat">
            <span className="pos-stat-label">Closed</span>
            <span className="pos-stat-val">{summary.closed}</span>
          </div>
          <div className="pos-stat">
            <span className="pos-stat-label">Win Rate</span>
            <span className="pos-stat-val">{summary.win_rate}%</span>
          </div>
          <div className="pos-stat">
            <span className="pos-stat-label">Total P&L</span>
            <span className={`pos-stat-val ${summary.total_pnl >= 0 ? 'text-green' : 'text-red'}`}>
              ${summary.total_pnl.toLocaleString()}
            </span>
          </div>
        </div>
      )}

      {/* Toolbar */}
      <div className="tv-toolbar pos-toolbar">
        <div className="tv-toggle-group">
          <button className={`tv-toggle ${view === 'open' ? 'active' : ''}`} onClick={() => setView('open')}>Open</button>
          <button className={`tv-toggle ${view === 'closed' ? 'active' : ''}`} onClick={() => setView('closed')}>Closed</button>
          <button className={`tv-toggle ${view === 'greeks' ? 'active' : ''}`} onClick={() => setView('greeks')}>Greeks</button>
        </div>
        <button className="tv-btn-primary" onClick={() => setShowForm(!showForm)}>
          {showForm ? 'Cancel' : '+ New Position'}
        </button>
      </div>

      {showForm && <NewPositionForm onDone={() => { setShowForm(false); refetch(); refetchGreeks(); }} />}

      {/* Greeks view */}
      {view === 'greeks' && (
        <div className="pos-greeks-panel">
          <h3>Aggregate Greeks ({greeksData?.open_count || 0} open positions)</h3>
          <div className="pos-greeks-strip">
            {greeksChartData.map(g => (
              <div key={g.name} className="pos-greek-box">
                <span className="pos-greek-label">{g.name}</span>
                <span className={`pos-greek-val ${g.value >= 0 ? 'text-green' : 'text-red'}`}>
                  {g.value.toFixed(2)}
                </span>
              </div>
            ))}
          </div>
          <ResponsiveContainer width="100%" height={160}>
            <BarChart data={greeksChartData} margin={{ top: 10, right: 10, left: -10, bottom: 0 }}>
              <XAxis dataKey="name" tick={{ fill: '#787b86', fontSize: 11 }} />
              <YAxis tick={{ fill: '#787b86', fontSize: 10 }} />
              <Tooltip contentStyle={{ background: '#1e222d', border: '1px solid #363c4e', borderRadius: 4 }} />
              <Bar dataKey="value" radius={[3, 3, 0, 0]}>
                {greeksChartData.map((e, i) => (
                  <Cell key={i} fill={e.value >= 0 ? '#26a69a' : '#ef5350'} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}

      {/* Positions table */}
      {loading && positions.length === 0 && <div className="pos-loading">Loading...</div>}

      {positions.length === 0 && !loading && (
        <div className="pos-empty">No {view === 'open' ? 'open' : view === 'closed' ? 'closed' : ''} positions</div>
      )}

      {positions.length > 0 && (
        <table className="tv-table pos-table">
          <thead>
            <tr>
              <th>Symbol</th>
              <th>Strategy</th>
              <th>Entry</th>
              <th>Price</th>
              <th>Contracts</th>
              {view === 'open' && <th>Target / Stop</th>}
              {view === 'closed' && <th>Exit</th>}
              {view === 'closed' && <th>P&L</th>}
              <th>Regime</th>
              <th>Notes</th>
              {view === 'open' && <th></th>}
            </tr>
          </thead>
          <tbody>
            {positions.map(p => (
              <tr key={p.id}>
                <td className="pos-symbol">{p.symbol}</td>
                <td><span className="pos-strat-badge">{p.strategy.replace('_', ' ')}</span></td>
                <td>{p.entry_date}</td>
                <td className="mono">${p.entry_price.toFixed(2)}</td>
                <td className="mono">{p.contracts}</td>
                {view === 'open' && (
                  <td className="mono">
                    {p.profit_target ? `T:$${p.profit_target}` : '—'}
                    {' / '}
                    {p.stop_loss ? `S:$${p.stop_loss}` : '—'}
                  </td>
                )}
                {view === 'closed' && (
                  <>
                    <td className="mono">{p.exit_date} @ ${p.exit_price?.toFixed(2)}</td>
                    <td className={`mono ${p.pnl >= 0 ? 'text-green' : 'text-red'}`}>
                      ${p.pnl?.toFixed(2)}
                    </td>
                  </>
                )}
                <td>{p.regime_at_entry && <span className="wl-badge badge-blue">{p.regime_at_entry}</span>}</td>
                <td className="pos-notes">{p.notes}</td>
                {view === 'open' && (
                  <td className="pos-actions">
                    {closingId === p.id ? (
                      <div className="pos-close-form">
                        <input className="tv-input xs" type="number" step="0.01"
                          value={exitPrice} onChange={e => setExitPrice(e.target.value)}
                          placeholder="Exit $" />
                        <select className="tv-input xs" value={exitReason} onChange={e => setExitReason(e.target.value)}>
                          <option value="profit_target">Profit target</option>
                          <option value="stop_loss">Stop loss</option>
                          <option value="time_exit">Time exit</option>
                          <option value="manual">Manual</option>
                        </select>
                        <button className="tv-btn-primary sm" onClick={() => handleClose(p.id)} disabled={busy}>Close</button>
                        <button className="tv-btn sm" onClick={() => setClosingId(null)}>X</button>
                      </div>
                    ) : (
                      <button className="tv-btn sm" onClick={() => { setClosingId(p.id); setExitPrice(''); }}>Close</button>
                    )}
                  </td>
                )}
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}


function NewPositionForm({ onDone }) {
  const [form, setForm] = useState({
    symbol: '', strategy: 'iron_condor', entry_date: new Date().toISOString().slice(0, 10),
    entry_price: '', is_credit: true, contracts: 1, max_loss: '', profit_target: '',
    stop_loss: '', regime_at_entry: '', bias_at_entry: '', notes: '',
  });
  const [busy, setBusy] = useState(false);

  const update = (k, v) => setForm(prev => ({ ...prev, [k]: v }));

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!form.symbol || !form.entry_price) return;
    setBusy(true);
    try {
      await postApi('/api/positions', {
        ...form,
        symbol: form.symbol.toUpperCase(),
        entry_price: +form.entry_price,
        max_loss: form.max_loss ? +form.max_loss : null,
        profit_target: form.profit_target ? +form.profit_target : null,
        stop_loss: form.stop_loss ? +form.stop_loss : null,
      });
      onDone();
    } catch (e) {
      alert(e.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <form className="pos-new-form" onSubmit={handleSubmit}>
      <div className="pos-form-row">
        <input className="tv-input" value={form.symbol} onChange={e => update('symbol', e.target.value)} placeholder="Symbol" required />
        <select className="tv-input" value={form.strategy} onChange={e => update('strategy', e.target.value)}>
          {STRATEGIES.map(s => <option key={s} value={s}>{s.replace('_', ' ')}</option>)}
        </select>
        <input className="tv-input sm" type="date" value={form.entry_date} onChange={e => update('entry_date', e.target.value)} />
        <input className="tv-input sm" type="number" step="0.01" value={form.entry_price} onChange={e => update('entry_price', e.target.value)} placeholder="Entry $" required />
        <label className="pos-credit-toggle">
          <input type="checkbox" checked={form.is_credit} onChange={e => update('is_credit', e.target.checked)} />
          Credit
        </label>
        <input className="tv-input xs" type="number" value={form.contracts} onChange={e => update('contracts', +e.target.value)} min="1" />
      </div>
      <div className="pos-form-row">
        <input className="tv-input sm" type="number" step="0.01" value={form.profit_target} onChange={e => update('profit_target', e.target.value)} placeholder="Target $" />
        <input className="tv-input sm" type="number" step="0.01" value={form.stop_loss} onChange={e => update('stop_loss', e.target.value)} placeholder="Stop $" />
        <input className="tv-input sm" type="number" step="0.01" value={form.max_loss} onChange={e => update('max_loss', e.target.value)} placeholder="Max loss $" />
        <input className="tv-input" value={form.notes} onChange={e => update('notes', e.target.value)} placeholder="Notes" />
        <button className="tv-btn-primary" type="submit" disabled={busy}>Add Position</button>
      </div>
    </form>
  );
}
