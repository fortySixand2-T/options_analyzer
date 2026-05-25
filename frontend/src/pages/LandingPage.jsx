import { Link } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';

function SignalFlowDiagram() {
  return (
    <div className="lp-flow">
      <div className="lp-flow-node lp-flow-node--vol">
        <span className="lp-flow-label">Vol Regime</span>
        <span className="lp-flow-detail">IV Rank + VIX + Term Structure</span>
      </div>
      <div className="lp-flow-connector" />
      <div className="lp-flow-node lp-flow-node--bias">
        <span className="lp-flow-label">Directional Bias</span>
        <span className="lp-flow-detail">EMA + RSI + MACD + Momentum</span>
      </div>
      <div className="lp-flow-connector" />
      <div className="lp-flow-node lp-flow-node--dealer">
        <span className="lp-flow-label">Dealer Positioning</span>
        <span className="lp-flow-detail">GEX + Max Pain + P/C Ratio</span>
      </div>
      <div className="lp-flow-connector lp-flow-connector--merge" />
      <div className="lp-flow-node lp-flow-node--output">
        <span className="lp-flow-label">Strategy + Conviction</span>
        <span className="lp-flow-detail">Defined-risk, 0-14 DTE</span>
      </div>
    </div>
  );
}

function StrategyTable() {
  const strategies = [
    { name: 'Iron Condor', regime: 'HIGH_IV', condition: 'LONG_GAMMA', dte: '7-14', color: 'var(--purple)' },
    { name: 'Credit Spread (Put)', regime: 'HIGH_IV', condition: 'Bullish Bias', dte: '3-10', color: 'var(--green)' },
    { name: 'Credit Spread (Call)', regime: 'HIGH_IV', condition: 'Bearish Bias', dte: '3-10', color: 'var(--red)' },
    { name: 'Debit Spread', regime: 'LOW/MOD IV', condition: 'Directional', dte: '3-14', color: 'var(--blue)' },
    { name: 'Butterfly', regime: 'MOD/LOW IV', condition: 'Pin @ Max Pain', dte: '0-7', color: 'var(--amber)' },
  ];

  return (
    <div className="lp-strategy-table">
      <div className="lp-strategy-row lp-strategy-row--header">
        <span>Strategy</span>
        <span>Regime</span>
        <span>Condition</span>
        <span>DTE</span>
      </div>
      {strategies.map(s => (
        <div key={s.name} className="lp-strategy-row">
          <span className="lp-strategy-name" style={{ borderLeftColor: s.color }}>{s.name}</span>
          <span className="lp-strategy-tag">{s.regime}</span>
          <span className="lp-strategy-cond">{s.condition}</span>
          <span className="lp-strategy-dte">{s.dte}</span>
        </div>
      ))}
    </div>
  );
}

export default function LandingPage() {
  const { isAuthenticated } = useAuth();

  return (
    <div className="lp">
      {/* ── Header ── */}
      <header className="lp-header">
        <Link to="/" className="lp-logo">
          <span className="lp-logo-icon">&#9670;</span>
          <span className="lp-logo-text">Options Scanner</span>
        </Link>
        <nav className="lp-nav">
          {isAuthenticated ? (
            <Link to="/app" className="lp-btn lp-btn--primary">Dashboard</Link>
          ) : (
            <>
              <Link to="/login" className="lp-btn lp-btn--ghost">Sign in</Link>
              <Link to="/signup" className="lp-btn lp-btn--primary">Get Started Free</Link>
            </>
          )}
        </nav>
      </header>

      {/* ── Hero ── */}
      <section className="lp-hero">
        <div className="lp-hero-glow" />
        <div className="lp-hero-content">
          <div className="lp-badge">0-14 DTE &bull; Defined Risk Only</div>
          <h1 className="lp-hero-title">
            Options signals built on<br />
            <span className="lp-hero-accent">three layers of conviction</span>
          </h1>
          <p className="lp-hero-sub">
            Volatility regime, directional bias, and dealer positioning fused into a single
            decision matrix. Every trade is defined-risk, scored for conviction, and backed
            by quantitative signals — not gut feel.
          </p>
          <div className="lp-hero-actions">
            <Link to="/signup" className="lp-btn lp-btn--primary lp-btn--lg">
              Start Scanning
            </Link>
            <a href="#how-it-works" className="lp-btn lp-btn--outline lp-btn--lg">
              See How It Works
            </a>
          </div>
          <div className="lp-hero-metrics">
            <div className="lp-metric">
              <span className="lp-metric-value">3</span>
              <span className="lp-metric-label">Signal Layers</span>
            </div>
            <div className="lp-metric-sep" />
            <div className="lp-metric">
              <span className="lp-metric-value">5</span>
              <span className="lp-metric-label">Strategies</span>
            </div>
            <div className="lp-metric-sep" />
            <div className="lp-metric">
              <span className="lp-metric-value">60+</span>
              <span className="lp-metric-label">Min Conviction</span>
            </div>
            <div className="lp-metric-sep" />
            <div className="lp-metric">
              <span className="lp-metric-value">0</span>
              <span className="lp-metric-label">Naked Exposure</span>
            </div>
          </div>
        </div>
      </section>

      {/* ── Signal Architecture ── */}
      <section className="lp-section" id="how-it-works">
        <div className="lp-section-inner">
          <span className="lp-section-label">Architecture</span>
          <h2 className="lp-section-title">Three signals. One decision.</h2>
          <p className="lp-section-sub">
            Each layer answers a different question. Together they produce a strategy
            recommendation with a conviction score — no ambiguity, no conflicting signals.
          </p>
          <SignalFlowDiagram />
        </div>
      </section>

      {/* ── Features ── */}
      <section className="lp-section lp-section--dark">
        <div className="lp-section-inner">
          <span className="lp-section-label">Capabilities</span>
          <h2 className="lp-section-title">Everything you need to trade with edge</h2>
          <div className="lp-features">
            <div className="lp-feature-card">
              <div className="lp-feature-icon" style={{ background: 'var(--green-dim)', color: 'var(--green)' }}>V</div>
              <h3>Vol Regime Detection</h3>
              <p>Real-time IV rank, VIX percentile, contango/backwardation, and GARCH volatility — classifies the market as HIGH_IV, MODERATE_IV, LOW_IV, or SPIKE.</p>
            </div>
            <div className="lp-feature-card">
              <div className="lp-feature-icon" style={{ background: 'var(--blue-dim)', color: 'var(--blue)' }}>D</div>
              <h3>Directional Bias</h3>
              <p>EMA 9/21 crossover, RSI(14), MACD histogram, prior candle pattern, 2-day momentum, and ATR percentile — scored from STRONG_BULLISH to STRONG_BEARISH.</p>
            </div>
            <div className="lp-feature-card">
              <div className="lp-feature-icon" style={{ background: 'rgba(171,71,188,0.12)', color: 'var(--purple)' }}>F</div>
              <h3>Dealer Positioning</h3>
              <p>Gamma exposure walls, max pain from open interest, put/call ratio, and net GEX — determines LONG_GAMMA vs SHORT_GAMMA for strike placement.</p>
            </div>
            <div className="lp-feature-card">
              <div className="lp-feature-icon" style={{ background: 'var(--accent-dim)', color: 'var(--accent)' }}>&#9881;</div>
              <h3>Strategy Engine</h3>
              <p>Decision matrix maps the three signals to one of five defined-risk strategies. Conviction scoring weights each layer to surface only high-probability setups.</p>
            </div>
            <div className="lp-feature-card">
              <div className="lp-feature-icon" style={{ background: 'rgba(255,152,0,0.12)', color: 'var(--amber)' }}>&#9733;</div>
              <h3>Greeks Explorer</h3>
              <p>Interactive Black-Scholes and LSMC pricing with full Greeks visualization. See how delta, gamma, theta, and vega evolve across strikes and expirations.</p>
            </div>
            <div className="lp-feature-card">
              <div className="lp-feature-icon" style={{ background: 'var(--red-dim)', color: 'var(--red)' }}>&#8644;</div>
              <h3>Backtesting Engine</h3>
              <p>Replay historical signals with configurable filters. Compare strategies, DTE buckets, exit rules, and signal layers — validated with real chain data.</p>
            </div>
          </div>
        </div>
      </section>

      {/* ── Strategy Matrix ── */}
      <section className="lp-section">
        <div className="lp-section-inner">
          <span className="lp-section-label">Decision Matrix</span>
          <h2 className="lp-section-title">Five strategies, always defined-risk</h2>
          <p className="lp-section-sub">
            No naked options. No strangles. No undefined risk. Every position has a known
            max loss at entry — the system trades spreads, condors, and butterflies only.
          </p>
          <StrategyTable />
        </div>
      </section>

      {/* ── CTA ── */}
      <section className="lp-cta-section">
        <div className="lp-cta-glow" />
        <div className="lp-cta-content">
          <h2>Ready to trade with conviction?</h2>
          <p>Join the scanner and get institutional-grade signals delivered to your dashboard.</p>
          <Link to="/signup" className="lp-btn lp-btn--primary lp-btn--lg">
            Create Free Account
          </Link>
        </div>
      </section>

      {/* ── Footer ── */}
      <footer className="lp-footer">
        <div className="lp-footer-inner">
          <div className="lp-footer-brand">
            <span className="lp-logo-icon">&#9670;</span>
            <span>Options Scanner</span>
          </div>
          <div className="lp-footer-links">
            <span className="lp-footer-note">
              Built for short-duration, defined-risk options trading.
            </span>
          </div>
          <div className="lp-footer-copy">
            &copy; {new Date().getFullYear()} Options Scanner. All rights reserved.
          </div>
        </div>
      </footer>
    </div>
  );
}
