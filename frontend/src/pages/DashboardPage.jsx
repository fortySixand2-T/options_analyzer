import { useState, useEffect, useCallback } from 'react';
import Sidebar, { TABS } from '../components/Sidebar';
import Watchlist from '../components/Watchlist';
import RegimeDashboard from '../components/RegimeDashboard';
import Scanner from '../components/Scanner';
import Positions from '../components/Positions';
import GreeksExplorer from '../components/GreeksExplorer';
import Backtest from '../components/Backtest';
import Performance from '../components/Performance';
import Journal from '../components/Journal';
import { useAuth } from '../context/AuthContext';
import { useNotifications } from '../context/NotificationContext';

function getInitialTab() {
  const hash = window.location.hash.slice(1);
  if (TABS.some(t => t.id === hash)) return hash;
  return 'watchlist';
}

export default function DashboardPage() {
  const { user, logout } = useAuth();
  const { unreadCount, notifications, markRead, markAllRead } = useNotifications();
  const [showNotifs, setShowNotifs] = useState(false);
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
          <div className="topbar-user">
            <div className="notif-wrapper">
              <button className="notif-bell" onClick={() => setShowNotifs(!showNotifs)} title="Notifications">
                <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.5" width="18" height="18">
                  <path d="M10 2a5 5 0 00-5 5v3l-1.5 2h13L15 10V7a5 5 0 00-5-5z"/>
                  <path d="M8 17h4"/>
                </svg>
                {unreadCount > 0 && <span className="notif-badge">{unreadCount > 9 ? '9+' : unreadCount}</span>}
              </button>
              {showNotifs && (
                <div className="notif-dropdown">
                  <div className="notif-header">
                    <span>Notifications</span>
                    {unreadCount > 0 && <button className="notif-clear" onClick={markAllRead}>Mark all read</button>}
                  </div>
                  {notifications.length === 0 ? (
                    <div className="notif-empty">No new notifications</div>
                  ) : (
                    notifications.map(n => (
                      <div key={n.id} className="notif-item" onClick={() => markRead(n.id)}>
                        <div className="notif-title">{n.title}</div>
                        {n.body && <div className="notif-body">{n.body}</div>}
                      </div>
                    ))
                  )}
                </div>
              )}
            </div>
            <span className="topbar-email">{user?.email}</span>
            <button onClick={logout} className="topbar-logout">Sign out</button>
          </div>
        </div>
        <main className="app-main">
          {tab === 'watchlist' && <Watchlist />}
          {tab === 'regime' && <RegimeDashboard />}
          {tab === 'scanner' && <Scanner />}
          {tab === 'positions' && <Positions />}
          {tab === 'greeks' && <GreeksExplorer />}
          {tab === 'backtest' && <Backtest />}
          {tab === 'performance' && <Performance />}
          {tab === 'journal' && <Journal />}
        </main>
      </div>
    </div>
  );
}
