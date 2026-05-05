import { useState } from 'react';
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell } from 'recharts';
import { useApi } from '../hooks/useApi';
import './Dashboard.css';

export default function Portfolio() {
  const [regime, setRegime] = useState('MODERATE_IV');
  const [portfolioValue, setPortfolioValue] = useState(100000);

  const { data: allocation } = useApi(
    `/api/portfolio/allocation?regime=${regime}&portfolio_value=${portfolioValue}`
  );
  const { data: portfolio } = useApi('/api/portfolio');

  return (
    <div className="dashboard">
      <h2 style={{ marginBottom: 16 }}>Portfolio Allocation</h2>

      {/* Regime selector */}
      <div className="controls-row" style={{ marginBottom: 16 }}>
        <select className="input" value={regime} onChange={e => setRegime(e.target.value)}>
          <option value="HIGH_IV">HIGH IV</option>
          <option value="MODERATE_IV">MODERATE IV</option>
          <option value="LOW_IV">LOW IV</option>
          <option value="SPIKE">SPIKE</option>
        </select>
        <input
          className="input" type="number" value={portfolioValue}
          onChange={e => setPortfolioValue(Number(e.target.value))}
          style={{ width: 140 }}
        />
      </div>

      {/* Allocation bar */}
      {allocation && <AllocationBar allocation={allocation} />}

      {/* Book breakdown */}
      <div className="grid-2" style={{ marginTop: 16 }}>
        <BookPanel
          title="Short-DTE Book"
          book={portfolio?.books?.short_dte}
          pct={allocation?.short_dte_pct}
          dollars={allocation?.dollars?.short_dte}
        />
        <BookPanel
          title="Swing Book"
          book={portfolio?.books?.swing}
          pct={allocation?.swing_pct}
          dollars={allocation?.dollars?.swing}
        />
      </div>

      {/* Cross-book warnings */}
      {portfolio?.cross_book_warnings?.length > 0 && (
        <div style={{ marginTop: 16 }}>
          {portfolio.cross_book_warnings.map((w, i) => (
            <div key={i} className="panel" style={{
              borderLeft: `3px solid ${w.severity === 'high' ? 'var(--red)' : 'var(--yellow)'}`,
              marginBottom: 8,
            }}>
              <span style={{ fontWeight: 600, color: w.severity === 'high' ? 'var(--red)' : 'var(--yellow)' }}>
                {w.severity?.toUpperCase()}
              </span>
              <span style={{ marginLeft: 8 }}>{w.warning}</span>
            </div>
          ))}
        </div>
      )}

      {/* Rationale */}
      {allocation?.rationale && (
        <div className="panel muted" style={{ marginTop: 16, fontSize: '0.85rem' }}>
          {allocation.rationale}
        </div>
      )}
    </div>
  );
}


function AllocationBar({ allocation }) {
  const shortPct = Math.round((allocation.short_dte_pct || 0) * 100);
  const swingPct = Math.round((allocation.swing_pct || 0) * 100);

  return (
    <div className="panel">
      <div className="mono" style={{ marginBottom: 8, fontSize: '0.85rem' }}>
        Capital Split
      </div>
      <div style={{ display: 'flex', height: 28, borderRadius: 6, overflow: 'hidden' }}>
        <div style={{
          width: `${shortPct}%`, background: '#3b82f6',
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          color: '#fff', fontSize: 12, fontWeight: 600,
        }}>
          Short-DTE {shortPct}%
        </div>
        <div style={{
          width: `${swingPct}%`, background: '#8b5cf6',
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          color: '#fff', fontSize: 12, fontWeight: 600,
        }}>
          Swing {swingPct}%
        </div>
      </div>
      {allocation.dollars && (
        <div className="mono muted" style={{ marginTop: 6, fontSize: '0.8rem' }}>
          Short-DTE: ${allocation.dollars.short_dte?.toLocaleString()}
          {' | '}Swing: ${allocation.dollars.swing?.toLocaleString()}
          {' | '}Total risk: ${allocation.dollars.total?.toLocaleString()}
        </div>
      )}
    </div>
  );
}


function BookPanel({ title, book, pct, dollars }) {
  if (!book) {
    return (
      <div className="panel">
        <h4>{title}</h4>
        <div className="muted">No positions</div>
        {pct != null && (
          <div className="mono muted" style={{ marginTop: 8 }}>
            Allocated: {Math.round(pct * 100)}%
            {dollars != null && ` ($${dollars.toLocaleString()})`}
          </div>
        )}
      </div>
    );
  }

  const greeksData = book.greeks ? [
    { name: 'Delta', value: book.greeks.delta || 0 },
    { name: 'Gamma', value: book.greeks.gamma || 0 },
    { name: 'Theta', value: book.greeks.theta || 0 },
    { name: 'Vega', value: book.greeks.vega || 0 },
  ] : [];

  return (
    <div className="panel">
      <h4>{title}</h4>
      <div className="mono" style={{ display: 'flex', gap: 16, marginBottom: 8 }}>
        <span>Positions: <strong>{book.positions || 0}</strong></span>
        <span>Risk: <strong>${(book.risk || 0).toLocaleString()}</strong></span>
      </div>
      {pct != null && (
        <div className="mono muted" style={{ marginBottom: 8, fontSize: '0.8rem' }}>
          Allocated: {Math.round(pct * 100)}%
          {dollars != null && ` ($${dollars.toLocaleString()})`}
        </div>
      )}
      {greeksData.length > 0 && (
        <ResponsiveContainer width="100%" height={100}>
          <BarChart data={greeksData} margin={{ top: 5, right: 5, left: -20, bottom: 0 }}>
            <XAxis dataKey="name" tick={{ fill: '#9ca3af', fontSize: 10 }} />
            <YAxis tick={{ fill: '#9ca3af', fontSize: 10 }} />
            <Tooltip
              contentStyle={{ background: '#1f2937', border: '1px solid #374151', borderRadius: 6 }}
              labelStyle={{ color: '#d1d5db' }}
            />
            <Bar dataKey="value" radius={[3, 3, 0, 0]}>
              {greeksData.map((entry, i) => (
                <Cell key={i} fill={entry.value >= 0 ? '#22c55e' : '#ef4444'} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      )}
    </div>
  );
}
