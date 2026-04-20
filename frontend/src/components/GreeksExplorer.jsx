import { useState, useEffect } from 'react';
import { postApi } from '../hooks/useApi';
import './Dashboard.css';

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
    <div className="dashboard">
      <div className="controls-grid">
        <label className="slider-label">
          Spot: <span className="mono">${spot}</span>
          <input type="range" min={50} max={600} step={1} value={spot}
            onChange={e => setSpot(+e.target.value)} />
        </label>
        <label className="slider-label">
          Strike: <span className="mono">${strike}</span>
          <input type="range" min={50} max={600} step={1} value={strike}
            onChange={e => setStrike(+e.target.value)} />
        </label>
        <label className="slider-label">
          DTE: <span className="mono">{dte}d</span>
          <input type="range" min={1} max={365} step={1} value={dte}
            onChange={e => setDte(+e.target.value)} />
        </label>
        <label className="slider-label">
          IV: <span className="mono">{(iv * 100).toFixed(0)}%</span>
          <input type="range" min={5} max={150} step={1} value={iv * 100}
            onChange={e => setIv(+e.target.value / 100)} />
        </label>
        <div className="toggle-group">
          <button className={`toggle ${optionType === 'call' ? 'active' : ''}`}
            onClick={() => setOptionType('call')}>Call</button>
          <button className={`toggle ${optionType === 'put' ? 'active' : ''}`}
            onClick={() => setOptionType('put')}>Put</button>
        </div>
      </div>

      {error && <div className="panel error">{error}</div>}

      {result && (
        <div className="greeks-result">
          <div className="metric-card large">
            <div className="metric-label">Price</div>
            <div className="metric-value mono">${result.price?.toFixed(4)}</div>
          </div>
          <div className="metrics-grid greeks-grid">
            {Object.entries(result.greeks || {}).map(([k, v]) => (
              <div key={k} className="metric-card">
                <div className="metric-label">{k.charAt(0).toUpperCase() + k.slice(1)}</div>
                <div className="metric-value mono">{v?.toFixed(6)}</div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
