import { useState, useEffect } from 'react';
import { postApi } from '../hooks/useApi';
import './GreeksExplorer.css';

export default function GreeksExplorer() {
  const [spot, setSpot] = useState(100);
  const [strike, setStrike] = useState(100);
  const [dte, setDte] = useState(30);
  const [iv, setIv] = useState(0.25);
  const [optionType, setOptionType] = useState('call');
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);

  async function compute() {
    setError(null);
    try {
      const data = await postApi('/api/greeks', { spot, strike, dte, iv, option_type: optionType });
      setResult(data);
    } catch (e) {
      setError(e.message);
    }
  }

  useEffect(() => { compute(); }, [spot, strike, dte, iv, optionType]);

  return (
    <div className="greeks">
      <div className="tv-panel">
        <div className="tv-panel-header">
          <span className="tv-panel-title">Parameters</span>
        </div>
        <div className="tv-panel-body greeks-controls">
          <Slider label="Spot" value={`$${spot}`} min={50} max={600} step={1}
            val={spot} onChange={setSpot} />
          <Slider label="Strike" value={`$${strike}`} min={50} max={600} step={1}
            val={strike} onChange={setStrike} />
          <Slider label="DTE" value={`${dte}d`} min={1} max={365} step={1}
            val={dte} onChange={setDte} />
          <Slider label="IV" value={`${(iv * 100).toFixed(0)}%`} min={5} max={150} step={1}
            val={iv * 100} onChange={v => setIv(v / 100)} />
          <div className="tv-toggle-group">
            <button className={`tv-toggle ${optionType === 'call' ? 'active' : ''}`}
              onClick={() => setOptionType('call')}>Call</button>
            <button className={`tv-toggle ${optionType === 'put' ? 'active' : ''}`}
              onClick={() => setOptionType('put')}>Put</button>
          </div>
        </div>
      </div>

      <div className="greeks-results">
        {error && <div className="tv-error">{error}</div>}
        {result && (
          <>
            <div className="tv-panel greeks-price">
              <div className="greeks-price-label">Option Price</div>
              <div className="greeks-price-value">${result.price?.toFixed(4)}</div>
            </div>
            <div className="tv-panel">
              <div className="tv-panel-header">
                <span className="tv-panel-title">Greeks</span>
              </div>
              <div className="greeks-grid">
                {Object.entries(result.greeks || {}).map(([k, v]) => (
                  <div key={k} className="tv-stat-inline">
                    <span className="stat-label">{k.charAt(0).toUpperCase() + k.slice(1)}</span>
                    <span className="stat-value mono">{v?.toFixed(6)}</span>
                  </div>
                ))}
              </div>
            </div>
          </>
        )}
      </div>
    </div>
  );
}

function Slider({ label, value, min, max, step, val, onChange }) {
  return (
    <div className="greeks-slider">
      <div className="greeks-slider-header">
        <span>{label}</span>
        <span className="greeks-slider-value">{value}</span>
      </div>
      <input type="range" className="tv-slider" min={min} max={max} step={step}
        value={val} onChange={e => onChange(+e.target.value)} />
    </div>
  );
}
