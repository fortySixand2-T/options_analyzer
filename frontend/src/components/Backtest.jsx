import { useState, useCallback } from 'react';
import { useApi } from '../hooks/useApi';
import { SingleView, CompareView, Guide } from './BacktestParts';
import './Backtest.css';

const ACTIVE_STRATEGIES = [
  { value: 'iron_condor', label: 'Iron Condor' },
  { value: 'short_put_spread', label: 'Credit Spread' },
  { value: 'long_call_spread', label: 'Debit Spread' },
  { value: 'butterfly', label: 'Butterfly' },
];

const COMPARE_DIMS = [
  { key: 'strategy', label: 'Strategy' },
  { key: 'option_style', label: 'Option Style' },
  { key: 'exit_rule', label: 'Exit Rule' },
  { key: 'source', label: 'Data Source' },
];

const DIM_OPTIONS = {
  strategy: ACTIVE_STRATEGIES.map(s => ({ value: s.value, label: s.label })),
  option_style: [{ value: 'european', label: 'European' }, { value: 'american', label: 'American' }],
  exit_rule: [{ value: '50pct', label: '50% TP' }, { value: 'hold', label: 'Hold' }, { value: 'strategy', label: 'Auto' }],
  source: [{ value: 'local', label: 'BS Model' }, { value: 'chain_replay', label: 'Real Data' }],
};

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
  const [optionStyle, setOptionStyle] = useState('european');
  const [compareMode, setCompareMode] = useState(false);
  const [compareDim, setCompareDim] = useState('strategy');
  const [compareSelections, setCompareSelections] = useState({
    strategy: ['iron_condor', 'butterfly'],
    option_style: ['european', 'american'],
    exit_rule: ['50pct', 'hold'],
    source: ['local', 'chain_replay'],
  });
  const [sortCol, setSortCol] = useState('entry_date');
  const [sortAsc, setSortAsc] = useState(false);
  const [queryPath, setQueryPath] = useState(null);
  const [multiData, setMultiData] = useState(null);
  const [multiLoading, setMultiLoading] = useState(false);
  const [multiError, setMultiError] = useState(null);

  const { data: singleData, loading: singleLoading, error: singleError } = useApi(queryPath, { manual: !queryPath });

  const data = compareMode ? multiData : singleData;
  const loading = compareMode ? multiLoading : singleLoading;
  const error = compareMode ? multiError : singleError;

  function buildBaseParams() {
    const p = { symbol, start, exit_rule: exitRule, source, option_style: optionStyle };
    if (regimeFilter) p.regime_filter = 'true';
    if (biasFilter) p.bias_filter = 'true';
    if (dealerFilter) p.dealer_filter = 'true';
    if (edgeThreshold > 0) p.edge_threshold = edgeThreshold;
    if (slippage > 0) p.slippage_pct = (slippage / 100).toFixed(4);
    return p;
  }

  const handleRun = useCallback(async () => {
    if (!compareMode) {
      const p = new URLSearchParams(buildBaseParams());
      setQueryPath(`/api/backtest/${strategy}?${p}`);
      return;
    }

    const selected = compareSelections[compareDim];
    if (selected.length < 2) return;

    if (compareDim === 'strategy') {
      const p = new URLSearchParams(buildBaseParams());
      p.set('strategies', selected.join(','));
      setQueryPath(`/api/backtest/compare?${p}`);
      setMultiData(null);
      return;
    }

    setMultiLoading(true);
    setMultiError(null);
    setQueryPath(null);
    try {
      const base = buildBaseParams();
      const results = {};
      for (const val of selected) {
        const params = { ...base, [compareDim]: val };
        const p = new URLSearchParams(params);
        const strat = compareDim === 'strategy' ? val : strategy;
        const res = await fetch(`/api/backtest/${strat}?${p}`);
        if (!res.ok) throw new Error(`Failed for ${val}`);
        const d = await res.json();
        const label = DIM_OPTIONS[compareDim].find(o => o.value === val)?.label || val;
        results[label] = d;
      }
      setMultiData({ strategies: results, symbol, period: { start } });
    } catch (e) {
      setMultiError(e.message);
    } finally {
      setMultiLoading(false);
    }
  }, [compareMode, compareDim, compareSelections, strategy, symbol, start, exitRule, source, optionStyle, regimeFilter, biasFilter, dealerFilter, edgeThreshold, slippage]);

  function toggleSelection(dim, val) {
    setCompareSelections(prev => {
      const cur = prev[dim];
      const next = cur.includes(val) ? cur.filter(x => x !== val) : [...cur, val];
      if (next.length < 1) return prev;
      return { ...prev, [dim]: next };
    });
  }

  const isCompare = compareMode && (data?.strategies || (compareDim === 'strategy' && singleData?.strategies));

  const isCompareDim = (dim) => compareMode && compareDim === dim;

  return (
    <div className="bt">
      <div className="bt-config">
        <div className="bt-config-main">
          <div className="bt-field">
            <label className="tv-label">Strategy</label>
            {isCompareDim('strategy') ? (
              <div className="bt-strategy-pills">
                {ACTIVE_STRATEGIES.map(s => (
                  <button key={s.value}
                    className={`bt-pill ${compareSelections.strategy.includes(s.value) ? 'active' : ''}`}
                    onClick={() => toggleSelection('strategy', s.value)}>
                    {s.label}
                  </button>
                ))}
              </div>
            ) : (
              <select className="tv-select" value={strategy}
                onChange={e => setStrategy(e.target.value)}>
                {ACTIVE_STRATEGIES.map(s =>
                  <option key={s.value} value={s.value}>{s.label}</option>
                )}
              </select>
            )}
          </div>

          <div className="bt-field">
            <label className="tv-label">Symbol</label>
            <input className="tv-input sm" value={symbol}
              onChange={e => setSymbol(e.target.value.toUpperCase())} />
          </div>

          <div className="bt-field">
            <label className="tv-label">Start Date</label>
            <input className="tv-input" type="date" value={start}
              onChange={e => setStart(e.target.value)} />
          </div>

          <div className="bt-field">
            <label className="tv-label">Data Source</label>
            {isCompareDim('source') ? (
              <div className="bt-strategy-pills">
                {DIM_OPTIONS.source.map(o => (
                  <button key={o.value}
                    className={`bt-pill ${compareSelections.source.includes(o.value) ? 'active' : ''}`}
                    onClick={() => toggleSelection('source', o.value)}>
                    {o.label}
                  </button>
                ))}
              </div>
            ) : (
              <div className="tv-toggle-group">
                <button className={`tv-toggle ${source === 'local' ? 'active' : ''}`}
                  onClick={() => setSource('local')}>BS Model</button>
                <button className={`tv-toggle ${source === 'chain_replay' ? 'active' : ''}`}
                  onClick={() => setSource('chain_replay')}>Real Data</button>
              </div>
            )}
          </div>

          <div className="bt-field">
            <label className="tv-label">Option Style</label>
            {isCompareDim('option_style') ? (
              <div className="bt-strategy-pills">
                {DIM_OPTIONS.option_style.map(o => (
                  <button key={o.value}
                    className={`bt-pill ${compareSelections.option_style.includes(o.value) ? 'active' : ''}`}
                    onClick={() => toggleSelection('option_style', o.value)}>
                    {o.label}
                  </button>
                ))}
              </div>
            ) : (
              <div className="tv-toggle-group">
                <button className={`tv-toggle ${optionStyle === 'european' ? 'active' : ''}`}
                  onClick={() => setOptionStyle('european')}>European</button>
                <button className={`tv-toggle ${optionStyle === 'american' ? 'active' : ''}`}
                  onClick={() => setOptionStyle('american')}>American</button>
              </div>
            )}
          </div>

          <div className="bt-field">
            <label className="tv-label">Exit Rule</label>
            {isCompareDim('exit_rule') ? (
              <div className="bt-strategy-pills">
                {DIM_OPTIONS.exit_rule.map(o => (
                  <button key={o.value}
                    className={`bt-pill ${compareSelections.exit_rule.includes(o.value) ? 'active' : ''}`}
                    onClick={() => toggleSelection('exit_rule', o.value)}>
                    {o.label}
                  </button>
                ))}
              </div>
            ) : (
              <div className="tv-toggle-group">
                {[['50pct', '50% TP'], ['hold', 'Hold'], ['strategy', 'Auto']].map(([val, label]) => (
                  <button key={val}
                    className={`tv-toggle ${exitRule === val ? 'active' : ''}`}
                    onClick={() => setExitRule(val)}>{label}</button>
                ))}
              </div>
            )}
          </div>

          <div className="bt-field bt-field-actions">
            <label className="tv-label">&nbsp;</label>
            <div className="bt-actions">
              <button className={`bt-mode-toggle ${compareMode ? 'active' : ''}`}
                onClick={() => setCompareMode(!compareMode)}>Compare</button>
              <button className="tv-btn-primary" onClick={handleRun} disabled={loading}>
                {loading ? 'Running...' : 'Run'}
              </button>
              <button className="tv-btn" onClick={() => setShowGuide(true)}
                title="Help">?</button>
            </div>
          </div>
        </div>

        {compareMode && (
          <div className="bt-compare-dim-bar">
            <span className="tv-label">Compare by</span>
            <div className="tv-toggle-group">
              {COMPARE_DIMS.map(d => (
                <button key={d.key}
                  className={`tv-toggle ${compareDim === d.key ? 'active' : ''}`}
                  onClick={() => setCompareDim(d.key)}>{d.label}</button>
              ))}
            </div>
          </div>
        )}

        <div className="bt-filters">
          <span className="tv-label">Filters</span>
          <div className="bt-filter-chips">
            <button className={`tv-chip ${regimeFilter ? 'active' : ''}`}
              onClick={() => setRegimeFilter(!regimeFilter)}>Regime</button>
            <button className={`tv-chip ${biasFilter ? 'active' : ''}`}
              onClick={() => setBiasFilter(!biasFilter)}>Bias</button>
            <button className={`tv-chip ${dealerFilter ? 'active' : ''}`}
              onClick={() => setDealerFilter(!dealerFilter)}>Dealer</button>
          </div>
          <div className="bt-filter-inputs">
            <div className="tv-field">
              Edge &gt;
              <input className="tv-input sm" type="number" value={edgeThreshold}
                onChange={e => setEdgeThreshold(+e.target.value)} min={0} step={1} />
              <span className="muted">%</span>
            </div>
            <div className="tv-field">
              Slippage
              <input className="tv-input sm" type="number" value={slippage}
                onChange={e => setSlippage(+e.target.value)} min={0} max={10} step={0.5} />
              <span className="muted">%</span>
            </div>
          </div>
        </div>
      </div>

      {error && <div className="tv-error">Error: {error}</div>}

      {isCompare && <CompareView data={data} />}
      {!isCompare && data && data.stats && (
        <SingleView data={data}
          sortCol={sortCol} setSortCol={setSortCol}
          sortAsc={sortAsc} setSortAsc={setSortAsc} />
      )}

      {showGuide && <Guide onClose={() => setShowGuide(false)} />}
    </div>
  );
}
