import { Link } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';

export default function LandingPage() {
  const { isAuthenticated } = useAuth();

  return (
    <div className="landing-page">
      <header className="landing-header">
        <div className="landing-logo">Options Scanner</div>
        <nav className="landing-nav">
          {isAuthenticated ? (
            <Link to="/app" className="landing-btn landing-btn-primary">Dashboard</Link>
          ) : (
            <>
              <Link to="/login" className="landing-btn landing-btn-ghost">Sign in</Link>
              <Link to="/signup" className="landing-btn landing-btn-primary">Get Started</Link>
            </>
          )}
        </nav>
      </header>

      <section className="landing-hero">
        <h1>Defined-risk options signals<br />with institutional conviction</h1>
        <p className="landing-hero-sub">
          Three-layer signal architecture: volatility regime, directional bias,
          and dealer positioning — combined into high-conviction 0-14 DTE strategies.
        </p>
        <div className="landing-cta">
          <Link to="/signup" className="landing-btn landing-btn-primary landing-btn-lg">
            Start Scanning
          </Link>
        </div>
      </section>

      <section className="landing-features">
        <div className="landing-feature">
          <div className="landing-feature-icon">V</div>
          <h3>Vol Regime Detection</h3>
          <p>IV rank, VIX percentile, and term structure classify the environment in real-time.</p>
        </div>
        <div className="landing-feature">
          <div className="landing-feature-icon">D</div>
          <h3>Directional Bias</h3>
          <p>EMA crossovers, RSI, MACD, and momentum signals fused into a clear directional read.</p>
        </div>
        <div className="landing-feature">
          <div className="landing-feature-icon">F</div>
          <h3>Dealer Positioning</h3>
          <p>GEX walls, max pain, and P/C ratio reveal where market makers are hedging.</p>
        </div>
        <div className="landing-feature">
          <div className="landing-feature-icon">S</div>
          <h3>Strategy Engine</h3>
          <p>Five defined-risk strategies mapped to regime + bias + dealer state with conviction scoring.</p>
        </div>
      </section>

      <section className="landing-strategies">
        <h2>Strategies</h2>
        <div className="landing-strategy-grid">
          <div className="landing-strategy-card">
            <h4>Iron Condor</h4>
            <p>HIGH_IV + LONG_GAMMA &bull; 7-14 DTE</p>
          </div>
          <div className="landing-strategy-card">
            <h4>Short Put Spread</h4>
            <p>HIGH_IV + Bullish &bull; 3-10 DTE</p>
          </div>
          <div className="landing-strategy-card">
            <h4>Short Call Spread</h4>
            <p>HIGH_IV + Bearish &bull; 3-10 DTE</p>
          </div>
          <div className="landing-strategy-card">
            <h4>Long Debit Spread</h4>
            <p>LOW/MOD IV + Directional &bull; 3-14 DTE</p>
          </div>
          <div className="landing-strategy-card">
            <h4>Butterfly</h4>
            <p>Pin at max pain &bull; 0-7 DTE</p>
          </div>
        </div>
      </section>

      <footer className="landing-footer">
        <p>Options Scanner &copy; {new Date().getFullYear()}</p>
      </footer>
    </div>
  );
}
