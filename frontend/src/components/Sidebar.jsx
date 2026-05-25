import { useState, useEffect } from 'react';

const TABS = [
  {
    id: 'watchlist', label: 'Watchlist',
    icon: <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.5"><path d="M10 2l2.4 4.9 5.4.8-3.9 3.8.9 5.4L10 14.3 5.2 17l.9-5.4L2.2 7.7l5.4-.8z"/></svg>,
  },
  {
    id: 'regime', label: 'Regime',
    icon: <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.5"><rect x="2" y="3" width="16" height="4" rx="1"/><rect x="2" y="9" width="11" height="4" rx="1"/><rect x="2" y="15" width="7" height="4" rx="1"/></svg>,
  },
  {
    id: 'scanner', label: 'Scanner',
    icon: <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.5"><circle cx="8.5" cy="8.5" r="5.5"/><line x1="12.5" y1="12.5" x2="17" y2="17"/></svg>,
  },
  {
    id: 'positions', label: 'Positions',
    icon: <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.5"><rect x="2" y="4" width="16" height="12" rx="1"/><path d="M6 10h8M10 7v6"/></svg>,
  },
  {
    id: 'greeks', label: 'Greeks',
    icon: <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.5"><polyline points="2,16 6,8 10,12 14,4 18,9"/></svg>,
  },
  {
    id: 'backtest', label: 'Backtest',
    icon: <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.5"><circle cx="10" cy="10" r="7"/><polyline points="10,6 10,10 13,12"/></svg>,
  },
  {
    id: 'journal', label: 'Journal',
    icon: <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.5"><rect x="4" y="2" width="12" height="16" rx="1"/><line x1="7" y1="6" x2="13" y2="6"/><line x1="7" y1="9" x2="13" y2="9"/><line x1="7" y1="12" x2="10" y2="12"/></svg>,
  },
];

export default function Sidebar({ activeTab, onTabChange, onToggle }) {
  const [expanded, setExpanded] = useState(() => {
    try { return localStorage.getItem('sidebar-expanded') === 'true'; } catch { return false; }
  });

  useEffect(() => {
    try { localStorage.setItem('sidebar-expanded', expanded); } catch {}
    onToggle?.(expanded);
  }, [expanded, onToggle]);

  return (
    <aside className={`sidebar ${expanded ? 'expanded' : ''}`}>
      <div className="sidebar-header">
        <div className="sidebar-logo">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <polyline points="4,18 8,10 12,14 16,6 20,10" />
            <line x1="4" y1="20" x2="20" y2="20" />
          </svg>
        </div>
        <span className="sidebar-brand">Options Scanner</span>
      </div>

      <nav className="sidebar-nav">
        {TABS.map(t => (
          <button
            key={t.id}
            className={`nav-item ${activeTab === t.id ? 'active' : ''}`}
            onClick={() => onTabChange(t.id)}
            title={expanded ? undefined : t.label}
          >
            <span className="nav-icon">{t.icon}</span>
            <span className="nav-label">{t.label}</span>
          </button>
        ))}
      </nav>

      <button className="sidebar-toggle" onClick={() => setExpanded(!expanded)}>
        <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5">
          <polyline points="6,4 10,8 6,12" />
        </svg>
      </button>
    </aside>
  );
}

export { TABS };
