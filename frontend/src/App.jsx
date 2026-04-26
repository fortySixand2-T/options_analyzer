import { useState } from 'react';
import RegimeDashboard from './components/RegimeDashboard';
import Scanner from './components/Scanner';
import TradingView from './components/TradingView';
import GreeksExplorer from './components/GreeksExplorer';
import Backtest from './components/Backtest';
import Journal from './components/Journal';
import './App.css';

const TABS = [
  { id: 'regime', label: 'Regime' },
  { id: 'scanner', label: 'Scanner' },
  { id: 'trades', label: 'Trades' },
  { id: 'greeks', label: 'Greeks' },
  { id: 'backtest', label: 'Backtest' },
  { id: 'journal', label: 'Journal' },
];

function App() {
  const [tab, setTab] = useState('regime');

  return (
    <div className="app">
      <header className="app-header">
        <div className="app-title">Options Scanner</div>
        <nav className="tab-nav">
          {TABS.map(t => (
            <button
              key={t.id}
              className={`tab-btn ${tab === t.id ? 'active' : ''}`}
              onClick={() => setTab(t.id)}
            >
              {t.label}
            </button>
          ))}
        </nav>
      </header>
      <main className="app-main">
        {tab === 'regime' && <RegimeDashboard />}
        {tab === 'scanner' && <Scanner />}
        {tab === 'trades' && <TradingView />}
        {tab === 'greeks' && <GreeksExplorer />}
        {tab === 'backtest' && <Backtest />}
        {tab === 'journal' && <Journal />}
      </main>
    </div>
  );
}

export default App;
