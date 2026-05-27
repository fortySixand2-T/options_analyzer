import { useState, useCallback } from 'react';
import { useApi } from '../hooks/useApi';
import './Sentiment.css';

const LABEL_COLORS = {
  STRONG_POSITIVE: 'var(--green)',
  LEAN_POSITIVE: '#4ade80',
  NEUTRAL: 'var(--text-muted)',
  LEAN_NEGATIVE: '#fb923c',
  STRONG_NEGATIVE: 'var(--red)',
};

const LABEL_BG = {
  STRONG_POSITIVE: 'rgba(34,197,94,0.15)',
  LEAN_POSITIVE: 'rgba(74,222,128,0.10)',
  NEUTRAL: 'rgba(128,128,128,0.10)',
  LEAN_NEGATIVE: 'rgba(251,146,60,0.10)',
  STRONG_NEGATIVE: 'rgba(239,68,68,0.15)',
};

function ScoreGauge({ score, label }) {
  const pct = ((score + 1) / 2) * 100;
  const color = LABEL_COLORS[label] || 'var(--text-muted)';
  return (
    <div className="score-gauge">
      <div className="gauge-track">
        <div className="gauge-center" />
        <div
          className="gauge-fill"
          style={{
            left: score >= 0 ? '50%' : `${pct}%`,
            width: `${Math.abs(score) * 50}%`,
            background: color,
          }}
        />
        <div className="gauge-needle" style={{ left: `${pct}%` }} />
      </div>
      <div className="gauge-labels">
        <span>-1.0</span>
        <span>0</span>
        <span>+1.0</span>
      </div>
    </div>
  );
}

function SignalCard({ signal }) {
  if (!signal) return null;
  const color = LABEL_COLORS[signal.label] || 'var(--text-muted)';
  const bg = LABEL_BG[signal.label] || 'transparent';

  return (
    <div className="sentiment-signal-card">
      <div className="signal-header">
        <span
          className="signal-label-badge"
          style={{ color, background: bg, borderColor: color }}
        >
          {signal.label?.replace(/_/g, ' ')}
        </span>
        {signal.is_actionable ? (
          <span className="signal-actionable yes">Actionable</span>
        ) : (
          <span className="signal-actionable no">Low data</span>
        )}
        {signal.scorer && (
          <span className="signal-actionable no" title="Scoring model">
            {signal.scorer === 'keyword-v1' ? 'Keyword' : 'FinBERT'}
          </span>
        )}
      </div>

      <ScoreGauge score={signal.score} label={signal.label} />

      <div className="signal-metrics">
        <div className="metric">
          <span className="metric-label">Score</span>
          <span className="metric-value" style={{ color }}>
            {signal.score > 0 ? '+' : ''}{signal.score?.toFixed(4)}
          </span>
        </div>
        <div className="metric">
          <span className="metric-label">Velocity</span>
          <span className="metric-value">
            {signal.velocity > 0 ? '+' : ''}{signal.velocity?.toFixed(4)}
          </span>
        </div>
        <div className="metric">
          <span className="metric-label">Confidence</span>
          <span className="metric-value">{signal.confidence?.toFixed(3)}</span>
        </div>
        <div className="metric">
          <span className="metric-label">Headlines</span>
          <span className="metric-value">{signal.headline_count}</span>
        </div>
      </div>
    </div>
  );
}

function WindowSnapshots({ snapshots }) {
  if (!snapshots || Object.keys(snapshots).length === 0) return null;
  const windows = ['1h', '6h', '24h'];
  return (
    <div className="sentiment-panel">
      <div className="panel-title">Window Breakdown</div>
      <div className="windows-grid">
        {windows.map(w => {
          const s = snapshots[w];
          if (!s) return null;
          const color = LABEL_COLORS[s.signal_label] || 'var(--text-muted)';
          return (
            <div key={w} className="window-card">
              <div className="window-header">
                <span className="window-name">{w}</span>
                <span className="window-label" style={{ color }}>
                  {s.signal_label?.replace(/_/g, ' ')}
                </span>
              </div>
              <div className="window-stats">
                <div><span className="ws-label">Composite</span><span>{s.composite_score?.toFixed(4)}</span></div>
                <div><span className="ws-label">Velocity</span><span>{s.velocity?.toFixed(4) ?? '—'}</span></div>
                <div><span className="ws-label">Breadth</span><span>{(s.breadth * 100)?.toFixed(1)}%</span></div>
                <div><span className="ws-label">Headlines</span><span>{s.headline_count}</span></div>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function HeadlinesTable({ headlines }) {
  if (!headlines || headlines.length === 0) {
    return <div className="sentiment-panel"><div className="panel-title">Recent Headlines</div><div className="empty-state">No scored headlines available</div></div>;
  }

  const sentimentColor = (label) => {
    if (label === 'positive') return 'var(--green)';
    if (label === 'negative') return 'var(--red)';
    return 'var(--text-muted)';
  };

  return (
    <div className="sentiment-panel">
      <div className="panel-title">Recent Headlines ({headlines.length})</div>
      <div className="headlines-table-wrap">
        <table className="headlines-table">
          <thead>
            <tr>
              <th>Time</th>
              <th>Headline</th>
              <th>Label</th>
              <th>Pos</th>
              <th>Neg</th>
              <th>Neu</th>
              <th>Conf</th>
            </tr>
          </thead>
          <tbody>
            {headlines.map((h, i) => (
              <tr key={i}>
                <td className="hl-time">{h.published_at?.slice(0, 16)}</td>
                <td className="hl-text">{h.text}</td>
                <td style={{ color: sentimentColor(h.label) }}>{h.label}</td>
                <td className="num">{h.positive?.toFixed(3)}</td>
                <td className="num">{h.negative?.toFixed(3)}</td>
                <td className="num">{h.neutral?.toFixed(3)}</td>
                <td className="num">{h.confidence?.toFixed(3)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export default function Sentiment() {
  const [ticker, setTicker] = useState('SPY');
  const [inputVal, setInputVal] = useState('SPY');

  const signalPath = `/api/sentiment/signal/${ticker}`;
  const headlinesPath = `/api/sentiment/headlines/${ticker}?limit=50`;

  const { data: signal, loading: sigLoading, error: sigError, refetch: refetchSignal } = useApi(signalPath);
  const { data: hlData, loading: hlLoading, refetch: refetchHeadlines } = useApi(headlinesPath);

  const handleSubmit = useCallback((e) => {
    e.preventDefault();
    const val = inputVal.trim().toUpperCase();
    if (val) setTicker(val);
  }, [inputVal]);

  const handleRefresh = useCallback(() => {
    refetchSignal();
    refetchHeadlines();
  }, [refetchSignal, refetchHeadlines]);

  return (
    <div className="sentiment-page">
      <div className="sentiment-controls">
        <form onSubmit={handleSubmit} className="ticker-form">
          <input
            type="text"
            className="input"
            value={inputVal}
            onChange={e => setInputVal(e.target.value)}
            placeholder="Ticker (e.g. SPY)"
          />
          <button type="submit" className="btn-primary">Analyze</button>
        </form>
        <button className="refresh-btn" onClick={handleRefresh}>Refresh</button>
      </div>

      {sigLoading && <div className="panel loading">Loading sentiment for {ticker}...</div>}
      {sigError && (
        <div className="panel error">
          {sigError.includes('501') ? (
            <>FinBERT not available — increase Docker memory to 4GB+ and ensure torch is installed.</>
          ) : sigError.includes('404') ? (
            <>No headline data found. Place a CSV at data/headlines.csv or configure NewsAPI.</>
          ) : (
            <>Error: {sigError}</>
          )}
          <button className="refresh-btn" onClick={refetchSignal} style={{ marginLeft: 12 }}>Retry</button>
        </div>
      )}

      {signal && !sigError && (
        <>
          <SignalCard signal={signal} />
          <WindowSnapshots snapshots={signal.snapshots} />
        </>
      )}

      {hlLoading ? (
        <div className="panel loading">Loading headlines...</div>
      ) : (
        <HeadlinesTable headlines={hlData?.headlines} />
      )}
    </div>
  );
}
