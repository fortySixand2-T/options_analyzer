import { useState } from 'react';
import { useApi, postApi } from '../hooks/useApi';
import './Dashboard.css';

export default function Journal() {
  const { data, loading, error, refetch } = useApi('/api/journal');
  const [showForm, setShowForm] = useState(false);
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
    setShowForm(false);
    refetch();
  }

  return (
    <div className="dashboard">
      <div className="controls-row">
        <h3>Trade Journal</h3>
        <button className="btn-primary" onClick={() => setShowForm(!showForm)}>
          {showForm ? 'Cancel' : '+ Log Trade'}
        </button>
      </div>

      {showForm && (
        <form className="journal-form" onSubmit={handleSubmit}>
          <input className="input" placeholder="Strategy" value={form.strategy}
            onChange={e => setForm({ ...form, strategy: e.target.value })} />
          <input className="input small" placeholder="Symbol" value={form.symbol}
            onChange={e => setForm({ ...form, symbol: e.target.value.toUpperCase() })} />
          <input className="input" type="date" value={form.entry_date}
            onChange={e => setForm({ ...form, entry_date: e.target.value })} />
          <input className="input small" type="number" step="0.01" placeholder="Entry $"
            value={form.entry_price} onChange={e => setForm({ ...form, entry_price: e.target.value })} required />
          <input className="input" type="date" value={form.exit_date}
            onChange={e => setForm({ ...form, exit_date: e.target.value })} />
          <input className="input small" type="number" step="0.01" placeholder="Exit $"
            value={form.exit_price} onChange={e => setForm({ ...form, exit_price: e.target.value })} />
          <input className="input small" type="number" step="0.01" placeholder="P&L"
            value={form.pnl} onChange={e => setForm({ ...form, pnl: e.target.value })} />
          <input className="input" placeholder="Notes" value={form.notes}
            onChange={e => setForm({ ...form, notes: e.target.value })} />
          <button className="btn-primary" type="submit">Save</button>
        </form>
      )}

      {error && <div className="panel error">{error}</div>}

      {data?.entries?.length > 0 ? (
        <div className="table-wrap">
          <table className="data-table">
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
                  <td className="muted">{e.notes}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        !loading && <div className="panel muted">No journal entries yet.</div>
      )}
    </div>
  );
}
