import { useState } from 'react';
import RegimeDashboard from './components/RegimeDashboard';
import Scanner from './components/Scanner';
import SwingScanner from './components/SwingScanner';
import TradingView from './components/TradingView';
import GreeksExplorer from './components/GreeksExplorer';
import Backtest from './components/Backtest';
import Portfolio from './components/Portfolio';
import Journal from './components/Journal';
import ShadowTrades from './components/ShadowTrades';
import './App.css';

const TABS = [
  { id: 'regime', label: 'Regime' },
  { id: 'scanner', label: 'Scanner' },
  { id: 'swing', label: 'Swing' },
  { id: 'portfolio', label: 'Portfolio' },
  { id: 'trades', label: 'Trades' },
  { id: 'greeks', label: 'Greeks' },
  { id: 'backtest', label: 'Backtest' },
  { id: 'journal', label: 'Journal' },
  { id: 'shadow', label: 'Shadow' },
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
        {tab === 'swing' && <SwingScanner />}
        {tab === 'portfolio' && <Portfolio />}
        {tab === 'trades' && <TradingView />}
        {tab === 'greeks' && <GreeksExplorer />}
        {tab === 'backtest' && <Backtest />}
        {tab === 'journal' && <Journal />}
        {tab === 'shadow' && <ShadowTrades />}
      </main>
    </div>
  );
}

export default App;
