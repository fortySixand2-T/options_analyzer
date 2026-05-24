import { useState, useEffect, useCallback } from 'react';
import Sidebar, { TABS } from './components/Sidebar';
import RegimeDashboard from './components/RegimeDashboard';
import Scanner from './components/Scanner';
import GreeksExplorer from './components/GreeksExplorer';
import Backtest from './components/Backtest';
import Journal from './components/Journal';

function getInitialTab() {
  const hash = window.location.hash.slice(1);
  if (TABS.some(t => t.id === hash)) return hash;
  return 'regime';
}

function App() {
  const [tab, setTab] = useState(getInitialTab);
  const [sidebarExpanded, setSidebarExpanded] = useState(() => {
    try { return localStorage.getItem('sidebar-expanded') === 'true'; } catch { return false; }
  });

  useEffect(() => {
    const onHash = () => {
      const hash = window.location.hash.slice(1);
      if (TABS.some(t => t.id === hash)) setTab(hash);
    };
    window.addEventListener('hashchange', onHash);
    return () => window.removeEventListener('hashchange', onHash);
  }, []);

  const handleTabChange = useCallback((id) => {
    setTab(id);
    window.location.hash = id;
  }, []);

  const handleSidebarToggle = useCallback((expanded) => {
    setSidebarExpanded(expanded);
  }, []);

  const pageTitle = TABS.find(t => t.id === tab)?.label || '';

  return (
    <div className="app">
      <Sidebar activeTab={tab} onTabChange={handleTabChange} onToggle={handleSidebarToggle} />
      <div className={`app-content ${sidebarExpanded ? 'sidebar-expanded' : ''}`}>
        <div className="topbar">
          <div className="topbar-title">{pageTitle}</div>
        </div>
        <main className="app-main">
          {tab === 'regime' && <RegimeDashboard />}
          {tab === 'scanner' && <Scanner />}
          {tab === 'greeks' && <GreeksExplorer />}
          {tab === 'backtest' && <Backtest />}
          {tab === 'journal' && <Journal />}
        </main>
      </div>
    </div>
  );
}

export default App;
