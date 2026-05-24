import { useState } from 'react';
import { useApi, postApi } from '../hooks/useApi';
import './Journal.css';

export default function Journal() {
  const { data, loading, error, refetch } = useApi('/api/journal');
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [form, setForm] = useState({
    strategy: 'iron_condor', symbol: 'SPY', entry_date: new Date().toISOString().split('T')[0],
    entry_price: '', exit_date: '', exit_price: '', contracts: 1, pnl: '', notes: '',
  });

  async function handleSubmit(e) {
    e.preventDefault();
    await postApi('/api/journal', {
      ...form,
      entry_price: +form.entry_price,
      exit_price: form.exit_price ? +form.exit_price : null,
      pnl: form.pnl ? +form.pnl : null,
      exit_date: form.exit_date || null,
    });
    setDrawerOpen(false);
    refetch();
  }

  return (
    <div className="journal">
      <div className="journal-header">
        <h3>Trade Journal</h3>
        <button className="tv-btn-primary" onClick={() => setDrawerOpen(true)}>+ Log Trade</button>
      </div>

      {error && <div className="tv-error">{error}</div>}

      {data?.entries?.length > 0 ? (
        <div className="tv-panel" style={{ overflow: 'auto' }}>
          <table className="tv-table journal-table">
            <thead>
              <tr>
                <th>Date</th><th>Strategy</th><th>Symbol</th>
                <th>Entry</th><th>Exit</th><th>P&L</th><th>Notes</th>
              </tr>
            </thead>
            <tbody>
              {data.entries.map(e => (
                <tr key={e.id}>
                  <td className="mono">{e.entry_date}</td>
                  <td>{e.strategy}</td>
                  <td className="mono">{e.symbol}</td>
                  <td className="mono">${e.entry_price?.toFixed(2)}</td>
                  <td className="mono">{e.exit_price ? `$${e.exit_price.toFixed(2)}` : '—'}</td>
                  <td className={`mono ${e.pnl > 0 ? 'green' : e.pnl < 0 ? 'red' : ''}`}>
                    {e.pnl != null ? `$${e.pnl.toFixed(0)}` : '—'}
                  </td>
                  <td className="muted" style={{ maxWidth: 200, overflow: 'hidden', textOverflow: 'ellipsis' }}>
                    {e.notes}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        !loading && <div className="tv-panel tv-loading">No journal entries yet.</div>
      )}

      <div className={`journal-backdrop ${drawerOpen ? 'open' : ''}`} onClick={() => setDrawerOpen(false)} />
      <div className={`journal-drawer ${drawerOpen ? 'open' : ''}`}>
        <div className="journal-drawer-header">
          <h4>Log Trade</h4>
          <button className="journal-drawer-close" onClick={() => setDrawerOpen(false)}>✕</button>
        </div>
        <form className="journal-form" onSubmit={handleSubmit}>
          <Field label="Strategy">
            <select className="tv-select" value={form.strategy}
              onChange={e => setForm({ ...form, strategy: e.target.value })}>
              <option value="iron_condor">Iron Condor</option>
              <option value="credit_spread">Credit Spread</option>
              <option value="debit_spread">Debit Spread</option>
              <option value="butterfly">Butterfly</option>
            </select>
          </Field>
          <Field label="Symbol">
            <input className="tv-input" value={form.symbol}
              onChange={e => setForm({ ...form, symbol: e.target.value.toUpperCase() })} />
          </Field>
          <Field label="Entry Date">
            <input className="tv-input" type="date" value={form.entry_date}
              onChange={e => setForm({ ...form, entry_date: e.target.value })} />
          </Field>
          <Field label="Entry Price">
            <input className="tv-input" type="number" step="0.01" placeholder="0.00"
              value={form.entry_price} onChange={e => setForm({ ...form, entry_price: e.target.value })} required />
          </Field>
          <Field label="Exit Date">
            <input className="tv-input" type="date" value={form.exit_date}
              onChange={e => setForm({ ...form, exit_date: e.target.value })} />
          </Field>
          <Field label="Exit Price">
            <input className="tv-input" type="number" step="0.01" placeholder="0.00"
              value={form.exit_price} onChange={e => setForm({ ...form, exit_price: e.target.value })} />
          </Field>
          <Field label="Contracts">
            <input className="tv-input" type="number" min="1" value={form.contracts}
              onChange={e => setForm({ ...form, contracts: +e.target.value })} />
          </Field>
          <Field label="P&L">
            <input className="tv-input" type="number" step="0.01" placeholder="0.00"
              value={form.pnl} onChange={e => setForm({ ...form, pnl: e.target.value })} />
          </Field>
          <Field label="Notes">
            <input className="tv-input" placeholder="Optional notes"
              value={form.notes} onChange={e => setForm({ ...form, notes: e.target.value })} />
          </Field>
          <div className="journal-form-actions">
            <button className="tv-btn-primary" type="submit" style={{ width: '100%' }}>Save Trade</button>
          </div>
        </form>
      </div>
    </div>
  );
}

function Field({ label, children }) {
  return (
    <div className="journal-form-field">
      <span className="tv-label">{label}</span>
      {children}
    </div>
  );
}
