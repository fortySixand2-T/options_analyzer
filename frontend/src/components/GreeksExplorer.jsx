import { useState, useEffect, useMemo } from 'react';
import {
  AreaChart, Area, LineChart, Line, XAxis, YAxis,
  Tooltip, ResponsiveContainer, ReferenceLine,
} from 'recharts';
import { postApi } from '../hooks/useApi';
import './GreeksExplorer.css';

const tooltipStyle = {
  background: '#131722',
  border: '1px solid #363c4e',
  borderRadius: 4,
  fontSize: 12,
  padding: '8px 12px',
  boxShadow: '0 4px 12px rgba(0,0,0,0.4)',
};

function cdf(x) {
  const a1 = 0.254829592, a2 = -0.284496736, a3 = 1.421413741;
  const a4 = -1.453152027, a5 = 1.061405429, p = 0.3275911;
  const sign = x < 0 ? -1 : 1;
  x = Math.abs(x) / Math.SQRT2;
  const t = 1 / (1 + p * x);
  const y = 1 - ((((a5 * t + a4) * t + a3) * t + a2) * t + a1) * t * Math.exp(-x * x);
  return 0.5 * (1 + sign * y);
}

function pdf(x) {
  return Math.exp(-0.5 * x * x) / Math.sqrt(2 * Math.PI);
}

function bs(s, k, t, sigma, type) {
  if (t <= 0 || sigma <= 0) return { price: Math.max(type === 'call' ? s - k : k - s, 0), delta: 0, gamma: 0, theta: 0, vega: 0 };
  const sqrtT = Math.sqrt(t);
  const d1 = (Math.log(s / k) + 0.5 * sigma * sigma * t) / (sigma * sqrtT);
  const d2 = d1 - sigma * sqrtT;
  const nd1 = cdf(d1), nd2 = cdf(d2), pd1 = pdf(d1);
  let price, delta;
  if (type === 'call') {
    price = s * nd1 - k * Math.exp(0) * nd2;
    delta = nd1;
  } else {
    price = k * Math.exp(0) * cdf(-d2) - s * cdf(-d1);
    delta = nd1 - 1;
  }
  const gamma = pd1 / (s * sigma * sqrtT);
  const theta = -(s * pd1 * sigma) / (2 * sqrtT) / 365;
  const vega = s * pd1 * sqrtT / 100;
  return { price, delta, gamma, theta, vega };
}

export default function GreeksExplorer() {
  const [ticker, setTicker] = useState('');
  const [tickerInput, setTickerInput] = useState('');
  const [tickerLoading, setTickerLoading] = useState(false);
  const [spot, setSpot] = useState(100);
  const [strike, setStrike] = useState(100);
  const [dte, setDte] = useState(30);
  const [iv, setIv] = useState(0.25);
  const [optionType, setOptionType] = useState('call');
  const [optionStyle, setOptionStyle] = useState('european');
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);

  async function loadTicker(sym) {
    if (!sym) return;
    setTickerLoading(true);
    setError(null);
    try {
      const res = await fetch(`/api/quote/${sym.toUpperCase()}`);
      if (!res.ok) throw new Error(`Failed to load ${sym.toUpperCase()}`);
      const data = await res.json();
      setTicker(data.symbol);
      setSpot(data.spot);
      setStrike(Math.round(data.spot));
      if (data.iv) setIv(data.iv);
    } catch (e) {
      setError(e.message);
    } finally {
      setTickerLoading(false);
    }
  }

  function handleTickerSubmit(e) {
    e.preventDefault();
    if (tickerInput.trim()) loadTicker(tickerInput.trim());
  }

  async function compute() {
    setError(null);
    try {
      const data = await postApi('/api/greeks', { spot, strike, dte, iv, option_type: optionType, option_style: optionStyle });
      setResult(data);
    } catch (e) {
      setError(e.message);
    }
  }

  useEffect(() => { compute(); }, [spot, strike, dte, iv, optionType, optionStyle]);

  const [chartMode, setChartMode] = useState('price');

  const chartData = useMemo(() => {
    const lo = Math.max(strike * 0.7, 1);
    const hi = strike * 1.3;
    const step = Math.max((hi - lo) / 80, 0.5);
    const t = dte / 365;
    const pts = [];
    for (let s = lo; s <= hi; s += step) {
      const r = bs(s, strike, t, iv, optionType);
      const intrinsic = Math.max(optionType === 'call' ? s - strike : strike - s, 0);
      pts.push({ spot: +s.toFixed(1), price: +r.price.toFixed(4), intrinsic: +intrinsic.toFixed(2), delta: +r.delta.toFixed(4), gamma: +r.gamma.toFixed(6), theta: +r.theta.toFixed(4), vega: +r.vega.toFixed(4) });
    }
    return pts;
  }, [strike, dte, iv, optionType]);

  return (
    <div className="greeks">
      <div className="greeks-params tv-panel">
        <div className="tv-panel-header">
          <span className="tv-panel-title">Parameters</span>
          {ticker && <span className="tv-badge blue">{ticker}</span>}
        </div>
        <div className="tv-panel-body greeks-controls">
          <form className="greeks-ticker-form" onSubmit={handleTickerSubmit}>
            <input className="tv-input" placeholder="Ticker e.g. SPY"
              value={tickerInput} onChange={e => setTickerInput(e.target.value.toUpperCase())} />
            <button className="tv-btn-primary" type="submit" disabled={tickerLoading || !tickerInput.trim()}>
              {tickerLoading ? '...' : 'Load'}
            </button>
          </form>
          <Param label="Spot" prefix="$" value={spot} min={1} max={Math.max(spot * 2, 600)} step={1}
            onChange={setSpot} />
          <Param label="Strike" prefix="$" value={strike} min={1} max={Math.max(spot * 2, 600)} step={1}
            onChange={v => setStrike(Math.round(v))} />
          <Param label="DTE" suffix="d" value={dte} min={1} max={365} step={1}
            onChange={setDte} />
          <Param label="IV" suffix="%" value={+(iv * 100).toFixed(1)} min={1} max={200} step={0.5}
            onChange={v => setIv(v / 100)} />
          <div className="greeks-toggles">
            <div className="tv-toggle-group">
              <button className={`tv-toggle ${optionType === 'call' ? 'active' : ''}`}
                onClick={() => setOptionType('call')}>Call</button>
              <button className={`tv-toggle ${optionType === 'put' ? 'active' : ''}`}
                onClick={() => setOptionType('put')}>Put</button>
            </div>
            <div className="tv-toggle-group">
              <button className={`tv-toggle ${optionStyle === 'european' ? 'active' : ''}`}
                onClick={() => setOptionStyle('european')}>EU</button>
              <button className={`tv-toggle ${optionStyle === 'american' ? 'active' : ''}`}
                onClick={() => setOptionStyle('american')}>US</button>
            </div>
          </div>
        </div>
      </div>

      <div className="greeks-results">
        {error && <div className="tv-error">{error}</div>}
        {result && (
          <>
            <div className="greeks-price-row">
              <div className="tv-panel greeks-price">
                <div className="greeks-price-label">
                  Option Price{result.option_style === 'american' ? ' (LSMC)' : ''}
                </div>
                <div className="greeks-price-value">${result.price?.toFixed(4)}</div>
                {result.early_exercise_premium > 0 && (
                  <div className="greeks-eep">
                    Early exercise premium: ${result.early_exercise_premium?.toFixed(4)}
                    {result.std_error != null && <span className="muted"> (SE: ±{result.std_error?.toFixed(4)})</span>}
                  </div>
                )}
              </div>
            </div>
            <div className="tv-panel greeks-grid-wrap">
              <div className="greeks-grid">
                {Object.entries(result.greeks || {}).map(([k, v]) => (
                  <div key={k} className="greeks-cell">
                    <div className="greeks-cell-label">{k}</div>
                    <div className="greeks-cell-value">{v?.toFixed(6)}</div>
                  </div>
                ))}
              </div>
            </div>
          </>
        )}
      </div>

      <div className="tv-panel greeks-chart-panel">
        <div className="tv-panel-header">
          <span className="tv-panel-title">P&L Profile</span>
          <div className="tv-toggle-group">
            {['price', 'delta', 'gamma', 'theta', 'vega'].map(m => (
              <button key={m} className={`tv-toggle ${chartMode === m ? 'active' : ''}`}
                onClick={() => setChartMode(m)}>{m.charAt(0).toUpperCase() + m.slice(1)}</button>
            ))}
          </div>
        </div>
        <div className="greeks-chart-body">
          <ResponsiveContainer width="100%" height={340}>
            {chartMode === 'price' ? (
              <AreaChart data={chartData}>
                <defs>
                  <linearGradient id="gkPrice" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="#2962ff" stopOpacity={0.3} />
                    <stop offset="100%" stopColor="#2962ff" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <XAxis dataKey="spot" tick={{ fill: '#545862', fontSize: 11 }} tickLine={false}
                  axisLine={{ stroke: '#2a2e39' }} tickFormatter={v => `$${v}`} />
                <YAxis tick={{ fill: '#545862', fontSize: 11 }} tickLine={false}
                  axisLine={{ stroke: '#2a2e39' }} tickFormatter={v => `$${v}`} />
                <Tooltip contentStyle={tooltipStyle} formatter={(v, n) => [`$${v}`, n === 'price' ? 'Option Price' : 'Intrinsic']}
                  labelFormatter={v => `Spot: $${v}`} />
                <ReferenceLine x={spot} stroke="#ff9800" strokeDasharray="4 4" label={{ value: 'Current', fill: '#ff9800', fontSize: 10, position: 'top' }} />
                <ReferenceLine x={strike} stroke="#545862" strokeDasharray="3 3" />
                <Area type="monotone" dataKey="intrinsic" stroke="#545862" strokeDasharray="4 4" fill="none" dot={false} />
                <Area type="monotone" dataKey="price" stroke="#2962ff" strokeWidth={2} fill="url(#gkPrice)" dot={false} />
              </AreaChart>
            ) : (
              <LineChart data={chartData}>
                <XAxis dataKey="spot" tick={{ fill: '#545862', fontSize: 11 }} tickLine={false}
                  axisLine={{ stroke: '#2a2e39' }} tickFormatter={v => `$${v}`} />
                <YAxis tick={{ fill: '#545862', fontSize: 11 }} tickLine={false}
                  axisLine={{ stroke: '#2a2e39' }} />
                <Tooltip contentStyle={tooltipStyle} formatter={(v) => [v, chartMode.charAt(0).toUpperCase() + chartMode.slice(1)]}
                  labelFormatter={v => `Spot: $${v}`} />
                <ReferenceLine x={spot} stroke="#ff9800" strokeDasharray="4 4" label={{ value: 'Current', fill: '#ff9800', fontSize: 10, position: 'top' }} />
                <ReferenceLine x={strike} stroke="#545862" strokeDasharray="3 3" />
                <Line type="monotone" dataKey={chartMode} stroke="#26a69a" strokeWidth={2} dot={false} />
              </LineChart>
            )}
          </ResponsiveContainer>
        </div>
      </div>
    </div>
  );
}

function Param({ label, prefix, suffix, value, min, max, step, onChange }) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState('');

  function startEdit() {
    setDraft(String(value));
    setEditing(true);
  }

  function commitEdit() {
    setEditing(false);
    const n = parseFloat(draft);
    if (!isNaN(n)) onChange(Math.max(min, Math.min(max, n)));
  }

  function onKey(e) {
    if (e.key === 'Enter') commitEdit();
    if (e.key === 'Escape') setEditing(false);
  }

  return (
    <div className="greeks-param">
      <div className="greeks-param-header">
        <span className="greeks-param-label">{label}</span>
        {editing ? (
          <input className="greeks-param-input" type="number" value={draft}
            min={min} max={max} step={step} autoFocus
            onChange={e => setDraft(e.target.value)}
            onBlur={commitEdit} onKeyDown={onKey} />
        ) : (
          <span className="greeks-param-value" onClick={startEdit} title="Click to edit">
            {prefix}{value}{suffix}
          </span>
        )}
      </div>
      <input type="range" className="tv-slider" min={min} max={max} step={step}
        value={value} onChange={e => onChange(+e.target.value)} />
    </div>
  );
}
