import { useState } from 'react';
import { useApi } from '../hooks/useApi';
import { SingleView, CompareView, Guide } from './BacktestParts';
import './Dashboard.css';

const ACTIVE_STRATEGIES = [
  { value: 'iron_condor', label: 'Iron Condor' },
  { value: 'short_put_spread', label: 'Credit Spread' },
  { value: 'long_call_spread', label: 'Debit Spread' },
  { value: 'butterfly', label: 'Butterfly' },
];

export default function Backtest() {
  const [showGuide, setShowGuide] = useState(false);
  const [strategy, setStrategy] = useState('iron_condor');
  const [symbol, setSymbol] = useState('SPY');
  const [start, setStart] = useState('2024-01-01');
  const [exitRule, setExitRule] = useState('50pct');
  const [regimeFilter, setRegimeFilter] = useState(false);
  const [biasFilter, setBiasFilter] = useState(false);
  const [dealerFilter, setDealerFilter] = useState(false);
  const [edgeThreshold, setEdgeThreshold] = useState(0);
  const [slippage, setSlippage] = useState(3);
  const [source, setSource] = useState('local');
  const [compareMode, setCompareMode] = useState(false);
  const [compareStrategies, setCompareStrategies] = useState(['iron_condor', 'butterfly']);
  const [showTrades, setShowTrades] = useState(false);
  const [sortCol, setSortCol] = useState('entry_date');
  const [sortAsc, setSortAsc] = useState(false);
  const [queryPath, setQueryPath] = useState(null);

  const { data, loading, error } = useApi(queryPath, { manual: !queryPath });

  function buildFilterParams() {
    const p = new URLSearchParams({ symbol, start, exit_rule: exitRule });
    if (regimeFilter) p.set('regime_filter', 'true');
    if (biasFilter) p.set('bias_filter', 'true');
    if (dealerFilter) p.set('dealer_filter', 'true');
    if (edgeThreshold > 0) p.set('edge_threshold', edgeThreshold);
    if (slippage > 0) p.set('slippage_pct', (slippage / 100).toFixed(4));
    if (source !== 'local') p.set('source', source);
    return p;
  }

  function handleRun() {
    const p = buildFilterParams();
    if (compareMode) {
      p.set('strategies', compareStrategies.join(','));
      setQueryPath(`/api/backtest/compare?${p}`);
    } else {
      setQueryPath(`/api/backtest/${strategy}?${p}`);
    }
  }

  function toggleCompareStrategy(s) {
    setCompareStrategies(prev =>
      prev.includes(s) ? prev.filter(x => x !== s) : [...prev, s].slice(0, 3)
    );
  }

  const isCompare = compareMode && data?.strategies;

  return (
    <div className="bt">
      <div className="bt-guide-bar">
        <button className="bt-guide-toggle" onClick={() => setShowGuide(!showGuide)}>
          {showGuide ? 'Hide' : 'How to use'}
        </button>
      </div>
      {showGuide && <Guide />}

      <div className="bt-config">
        <div className="bt-config-main">
          <div className="bt-field">
            <label className="bt-label">Strategy</label>
            {!compareMode ? (
              <select className="bt-select" value={strategy}
                onChange={e => setStrategy(e.target.value)}>
                {ACTIVE_STRATEGIES.map(s =>
                  <option key={s.value} value={s.value}>{s.label}</option>
                )}
              </select>
            ) : (
              <div className="bt-strategy-pills">
                {ACTIVE_STRATEGIES.map(s => (
                  <button key={s.value}
                    className={`bt-pill ${compareStrategies.includes(s.value) ? 'active' : ''}`}
                    onClick={() => toggleCompareStrategy(s.value)}>
                    {s.label}
                  </button>
                ))}
              </div>
            )}
          </div>

          <div className="bt-field">
            <label className="bt-label">Symbol</label>
            <input className="bt-input" value={symbol}
              onChange={e => setSymbol(e.target.value.toUpperCase())}
              style={{ width: 80 }} />
          </div>

          <div className="bt-field">
            <label className="bt-label">Start Date</label>
            <input className="bt-input" type="date" value={start}
              onChange={e => setStart(e.target.value)} />
          </div>

          <div className="bt-field">
            <label className="bt-label">Data Source</label>
            <div className="bt-toggle-group">
              <button className={`bt-toggle ${source === 'local' ? 'active' : ''}`}
                onClick={() => setSource('local')}>BS Model</button>
              <button className={`bt-toggle ${source === 'chain_replay' ? 'active' : ''}`}
                onClick={() => setSource('chain_replay')}>Real Data</button>
            </div>
          </div>

          <div className="bt-field">
            <label className="bt-label">Exit Rule</label>
            <div className="bt-toggle-group">
              {[
                ['50pct', '50% TP'],
                ['hold', 'Hold'],
                ['strategy', 'Auto'],
              ].map(([val, label]) => (
                <button key={val}
                  className={`bt-toggle ${exitRule === val ? 'active' : ''}`}
                  onClick={() => setExitRule(val)}>{label}</button>
              ))}
            </div>
          </div>

          <div className="bt-field bt-field-actions">
            <label className="bt-label">&nbsp;</label>
            <div className="bt-actions">
              <button className={`bt-mode-toggle ${compareMode ? 'active' : ''}`}
                onClick={() => setCompareMode(!compareMode)}>
                Compare
              </button>
              <button className="bt-run" onClick={handleRun} disabled={loading}>
                {loading ? 'Running...' : 'Run'}
              </button>
            </div>
          </div>
        </div>

        <div className="bt-filters">
          <span className="bt-filters-label">Signal Filters</span>
          <div className="bt-filter-chips">
            <button className={`bt-chip ${regimeFilter ? 'active' : ''}`}
              onClick={() => setRegimeFilter(!regimeFilter)}>Regime</button>
            <button className={`bt-chip ${biasFilter ? 'active' : ''}`}
              onClick={() => setBiasFilter(!biasFilter)}>Bias</button>
            <button className={`bt-chip ${dealerFilter ? 'active' : ''}`}
              onClick={() => setDealerFilter(!dealerFilter)}>Dealer</button>
          </div>
          <div className="bt-filter-inputs">
            <label className="bt-inline-label">
              Edge &gt;
              <input className="bt-input bt-input-sm" type="number" value={edgeThreshold}
                onChange={e => setEdgeThreshold(+e.target.value)} min={0} step={1} />
              <span className="bt-unit">%</span>
            </label>
            <label className="bt-inline-label">
              Slippage
              <input className="bt-input bt-input-sm" type="number" value={slippage}
                onChange={e => setSlippage(+e.target.value)} min={0} max={10} step={0.5} />
              <span className="bt-unit">%</span>
            </label>
          </div>
        </div>
      </div>

      {error && <div className="bt-error">Error: {error}</div>}

      {isCompare && <CompareView data={data} />}
      {!isCompare && data && data.stats && (
        <SingleView data={data}
          showTrades={showTrades} setShowTrades={setShowTrades}
          sortCol={sortCol} setSortCol={setSortCol}
          sortAsc={sortAsc} setSortAsc={setSortAsc} />
      )}
    </div>
  );
}
