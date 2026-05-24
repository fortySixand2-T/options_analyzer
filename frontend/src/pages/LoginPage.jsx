import { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';

export default function LoginPage() {
  const { login } = useAuth();
  const navigate = useNavigate();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState(null);
  const [isLoading, setIsLoading] = useState(false);

  async function handleSubmit(e) {
    e.preventDefault();
    setError(null);
    setIsLoading(true);
    try {
      await login(email, password);
      navigate('/app', { replace: true });
    } catch (err) {
      setError(err.message);
    } finally {
      setIsLoading(false);
    }
  }

  return (
    <div className="auth-page">
      <div className="auth-brand">
        <div className="auth-brand-content">
          <h1 className="auth-logo">Options Scanner</h1>
          <p className="auth-tagline">
            Institutional-grade options signals for defined-risk strategies.
          </p>
          <div className="auth-stats">
            <div className="auth-stat">
              <span className="auth-stat-value">0-14</span>
              <span className="auth-stat-label">DTE Focus</span>
            </div>
            <div className="auth-stat">
              <span className="auth-stat-value">3</span>
              <span className="auth-stat-label">Signal Layers</span>
            </div>
            <div className="auth-stat">
              <span className="auth-stat-value">5</span>
              <span className="auth-stat-label">Strategies</span>
            </div>
          </div>
        </div>
      </div>

      <div className="auth-form-panel">
        <div className="auth-form-container">
          <h2 className="auth-title">Welcome back</h2>
          <p className="auth-subtitle">Sign in to your account</p>

          <form onSubmit={handleSubmit} className="auth-form">
            <div className="auth-field">
              <label htmlFor="email">Email</label>
              <input
                id="email"
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                autoComplete="email"
                autoFocus
                required
                placeholder="you@example.com"
              />
            </div>

            <div className="auth-field">
              <label htmlFor="password">Password</label>
              <input
                id="password"
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                autoComplete="current-password"
                required
                placeholder="Enter your password"
              />
            </div>

            {error && <div className="auth-error">{error}</div>}

            <button
              type="submit"
              disabled={isLoading || !email.trim() || !password}
              className="auth-submit"
            >
              {isLoading ? 'Signing in...' : 'Sign in'}
            </button>
          </form>

          <p className="auth-switch">
            Don't have an account?{' '}
            <Link to="/signup">Create one</Link>
          </p>
        </div>
      </div>
    </div>
  );
}
