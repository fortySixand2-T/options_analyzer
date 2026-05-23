import { useState } from 'react';
import { useApi } from '../hooks/useApi';
import './Dashboard.css';

export default function TradingView() {
  const [symbol, setSymbol] = useState('SPY');
  const [queryPath, setQueryPath] = useState(null);

  const { data, loading, error } = useApi(queryPath, { manual: !queryPath });
  const { data: portfolio, refetch: refetchPortfolio } = useApi('/api/portfolio');

  function handleScan() {
    setQueryPath(`/api/trade-candidates?symbol=${symbol.toUpperCase()}`);
  }

  return (
    <div className="dashboard">
      <div className="controls-row">
        <input
          className="input small"
          value={symbol}
          onChange={e => setSymbol(e.target.value.toUpperCase())}
          placeholder="SPY"
        />
        <button className="btn-primary" onClick={handleScan} disabled={loading}>
          {loading ? 'Scanning...' : 'Find Trades'}
        </button>
      </div>

      {error && <div className="panel error">Error: {error}</div>}

      {data && (
        <>
          <MarketStatePanel state={data.market_state} />
          <CandidatesPanel
            candidates={data.candidates}
            count={data.tradeable_count}
            symbol={symbol}
            onOrderPlaced={refetchPortfolio}
          />
        </>
      )}

      {portfolio && <PortfolioPanel portfolio={portfolio} />}
    </div>
  );
}


function MarketStatePanel({ state }) {
  if (!state) return null;

  const edgeColor = state.iv_rv_edge_pct > 5 ? 'green'
    : state.iv_rv_edge_pct < -5 ? 'red' : 'muted';

  const regimeColor = {
    HIGH_IV: 'amber', MODERATE_IV: '', LOW_IV: 'green', SPIKE: 'red',
  }[state.regime] || '';

  return (
    <div className="section">
      <div className="section-header">Market State</div>
      <div className="metrics-grid">
        <div className="metric-card">
          <div className="metric-label">Regime</div>
          <div className={`metric-value ${regimeColor}`}>
            {state.regime?.replace(/_/g, ' ')}
          </div>
        </div>
        <div className="metric-card">
          <div className="metric-label">IV-RV Edge</div>
          <div className={`metric-value mono ${edgeColor}`}>
            {state.iv_rv_edge_pct > 0 ? '+' : ''}{state.iv_rv_edge_pct?.toFixed(1)}%
          </div>
          <div className="metric-sub">
            Chain IV {(state.chain_iv * 100)?.toFixed(1)}% vs GARCH {(state.garch_vol * 100)?.toFixed(1)}%
          </div>
        </div>
        <div className="metric-card">
          <div className="metric-label">VIX</div>
          <div className="metric-value mono">{state.vix?.toFixed(1)}</div>
          <div className="metric-sub">
            Slope: {state.vix_term_slope > 0 ? '+' : ''}{state.vix_term_slope?.toFixed(1)}%
          </div>
        </div>
        <div className="metric-card">
          <div className="metric-label">IV Rank</div>
          <div className="metric-value mono">{state.iv_rank?.toFixed(0)}%</div>
        </div>
        <div className="metric-card">
          <div className="metric-label">Bias</div>
          <div className={`metric-value ${state.bias?.label?.includes('BULLISH') ? 'green' : state.bias?.label?.includes('BEARISH') ? 'red' : 'muted'}`}>
            {state.bias?.label?.replace(/_/g, ' ')}
          </div>
          <div className="metric-sub">Score: {state.bias?.score}</div>
        </div>
        <div className="metric-card">
          <div className="metric-label">Dealer</div>
          <div className={`metric-value ${state.dealer?.regime === 'LONG_GAMMA' ? 'green' : state.dealer?.regime === 'SHORT_GAMMA' ? 'red' : 'muted'}`}>
            {state.dealer?.regime?.replace(/_/g, ' ') || 'N/A'}
          </div>
        </div>
        <div className="metric-card">
          <div className="metric-label">Chain Quality</div>
          <div className="metric-value mono">{(state.chain_quality?.quality_score * 100)?.toFixed(0)}%</div>
          <div className="metric-sub">{state.chain_quality?.liquid_strikes} liquid strikes</div>
        </div>
        <div className="metric-card">
          <div className="metric-label">Skew (25d)</div>
          <div className="metric-value mono">
            {state.vol_surface?.skew_25d != null
              ? `${(state.vol_surface.skew_25d * 100).toFixed(1)}%`
              : 'N/A'}
          </div>
        </div>
      </div>

      {/* Edge assessment */}
      <div className="metrics-grid" style={{ marginTop: '0.5rem' }}>
        <div className="metric-card" style={{ gridColumn: 'span 2' }}>
          <div className="metric-label">Edge Assessment</div>
          <div className="metric-value">
            {state.edge?.has_credit_edge && <span className="green">Credit edge available</span>}
            {state.edge?.has_debit_edge && <span className="red">Debit edge available</span>}
            {!state.edge?.has_credit_edge && !state.edge?.has_debit_edge && (
              <span className="muted">No tradeable edge</span>
            )}
          </div>
          <div className="metric-sub">
            Magnitude: {state.edge?.magnitude?.toFixed(1)}% |
            Candidates: {state.edge?.candidates?.join(', ') || 'none'}
          </div>
        </div>
      </div>
    </div>
  );
}


function CandidatesPanel({ candidates, count, symbol, onOrderPlaced }) {
  const [expanded, setExpanded] = useState(null);

  if (!candidates || candidates.length === 0) {
    return (
      <div className="section">
        <div className="section-header">Trade Candidates</div>
        <div className="panel muted">No trade candidates meet the confluence threshold (60+) and edge requirements.</div>
      </div>
    );
  }

  return (
    <div className="section">
      <div className="section-header">
        Trade Candidates ({count} tradeable of {candidates.length})
      </div>
      {candidates.map((tc, i) => (
        <TradeCard key={i} tc={tc} index={i} symbol={symbol}
          isExpanded={expanded === i}
          onToggle={() => setExpanded(expanded === i ? null : i)}
          onOrderPlaced={onOrderPlaced} />
      ))}
    </div>
  );
}


function TradeCard({ tc, index, symbol, isExpanded, onToggle, onOrderPlaced }) {
  const executable = tc.execution?.executable;
  const [orderState, setOrderState] = useState(null); // null | 'previewing' | 'preview' | 'submitting' | 'result'
  const [orderData, setOrderData] = useState(null);

  async function handlePreview(e) {
    e.stopPropagation();
    setOrderState('previewing');
    try {
      const res = await fetch('/api/order/from-candidate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          symbol: symbol,
          candidate_index: index,
          dry_run: true,
        }),
      });
      const data = await res.json();
      if (!res.ok) {
        setOrderData({ status: 'error', message: data.detail || 'Request failed' });
        setOrderState('result');
      } else {
        setOrderData(data);
        setOrderState('preview');
      }
    } catch (err) {
      setOrderData({ status: 'error', message: err.message });
      setOrderState('result');
    }
  }

  async function handleSubmit(e) {
    e.stopPropagation();
    setOrderState('submitting');
    try {
      const res = await fetch('/api/order/from-candidate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          symbol: symbol,
          candidate_index: index,
          dry_run: false,
        }),
      });
      const data = await res.json();
      setOrderData(data);
      setOrderState('result');
      if (data.status === 'submitted' || data.status === 'filled') {
        onOrderPlaced?.();
      }
    } catch (err) {
      setOrderData({ status: 'error', message: err.message });
      setOrderState('result');
    }
  }

  function handleCancel(e) {
    e.stopPropagation();
    setOrderState(null);
    setOrderData(null);
  }

  return (
    <div className="strategy-card" onClick={onToggle}>
      <div className="strategy-header">
        <span className="strategy-name">{tc.strategy_label}</span>
        <span className="score-badge" style={{
          background: tc.confluence_score >= 75 ? 'var(--green-dim)'
            : tc.confluence_score >= 60 ? '#92400e' : 'var(--red-dim)',
        }}>
          {tc.confluence_score?.toFixed(0)}
        </span>
        <span className={`mono ${tc.iv_rv_edge_pct > 0 ? 'green' : 'red'}`}>
          Edge: {tc.iv_rv_edge_pct > 0 ? '+' : ''}{tc.iv_rv_edge_pct?.toFixed(1)}%
        </span>
        <span className="mono muted">{tc.suggested_dte}d DTE</span>
        {tc.entry_window && (
          <span className="mono muted">Entry: {tc.entry_window[0]}-{tc.entry_window[1]} ET</span>
        )}
        {executable != null && (
          <span className={executable ? 'green' : 'red'}>
            {executable ? 'Tradeable' : 'Blocked'}
          </span>
        )}
      </div>

      {isExpanded && (
        <div className="strategy-detail">
          {/* Confluence breakdown */}
          <div className="score-breakdown">
            <h4>Confluence Score Breakdown</h4>
            <div className="breakdown-bars">
              {tc.score_breakdown && Object.entries(tc.score_breakdown)
                .sort((a, b) => b[1] - a[1])
                .map(([key, val]) => (
                  <div key={key} className="breakdown-row">
                    <span className="breakdown-label">{key}</span>
                    <div className="breakdown-bar-bg">
                      <div className="breakdown-bar-fill"
                        style={{ width: `${Math.min(val / 25 * 100, 100)}%` }} />
                    </div>
                    <span className="mono">{val?.toFixed(1)}</span>
                  </div>
                ))}
            </div>
          </div>

          {/* Legs */}
          <div className="legs-section">
            <h4>Structure</h4>
            <table className="data-table compact">
              <thead>
                <tr><th>Action</th><th>Type</th><th>Strike</th></tr>
              </thead>
              <tbody>
                {tc.legs?.map((leg, j) => (
                  <tr key={j}>
                    <td className={leg.action === 'buy' ? 'green' : 'red'}>
                      {leg.action.toUpperCase()}
                    </td>
                    <td>{leg.option_type}</td>
                    <td className="mono">{leg.strike?.toFixed(0)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {/* Exit rules */}
          <div className="exit-rules">
            <h4>Exit Rules</h4>
            <span>Profit: {tc.exit_rule?.profit_target_pct}%</span>
            <span>Stop: {tc.exit_rule?.stop_loss_pct}%</span>
            <span>Time: {tc.exit_rule?.time_exit_dte} DTE</span>
            {tc.exit_rule?.hold_to_expiry && <span className="amber">Hold to expiry</span>}
          </div>

          {/* Execution assessment */}
          {tc.execution && (
            <div className="execution-section">
              <h4>Execution (L3)</h4>
              {tc.execution.executable ? (
                <div className="exec-details">
                  <span>Contracts: <strong>{tc.execution.size?.contracts}</strong></span>
                  <span>Risk: ${tc.execution.size?.risk_dollars?.toFixed(0)}</span>
                  <span>Kelly: {(tc.execution.size?.kelly_half * 100)?.toFixed(1)}%</span>
                  {tc.execution.adjusted_entry && (
                    <span>Fill est: ${tc.execution.adjusted_entry?.toFixed(2)}</span>
                  )}
                  {tc.execution.slippage_cost > 0 && (
                    <span className="muted">Slippage: ${tc.execution.slippage_cost?.toFixed(3)}</span>
                  )}
                </div>
              ) : (
                <div className="exec-blocked red">
                  Blocked: {tc.execution.reason}
                </div>
              )}
            </div>
          )}

          {/* Order placement flow */}
          {tc.execution?.executable && (
            <div className="order-section">
              {orderState === null && (
                <button className="btn-order" onClick={handlePreview}>
                  Preview Order
                </button>
              )}

              {orderState === 'previewing' && (
                <div className="order-status muted">Building order preview...</div>
              )}

              {orderState === 'preview' && orderData && (
                <div className="order-preview">
                  <h4>Order Preview</h4>
                  <div className="order-details">
                    <span>{orderData.order?.strategy?.replace(/_/g, ' ')}</span>
                    <span>{orderData.order?.contracts} contracts</span>
                    <span>Limit: ${orderData.order?.price?.toFixed(2)}</span>
                    <span>Risk: ${orderData.order?.risk_dollars?.toFixed(0)}</span>
                  </div>
                  <table className="data-table compact">
                    <thead><tr><th>Action</th><th>Type</th><th>Strike</th><th>Symbol</th></tr></thead>
                    <tbody>
                      {orderData.order?.legs?.map((leg, j) => (
                        <tr key={j}>
                          <td className={leg.action.includes('buy') ? 'green' : 'red'}>
                            {leg.action.replace(/_/g, ' ').toUpperCase()}
                          </td>
                          <td>{leg.option_type}</td>
                          <td className="mono">{leg.strike?.toFixed(0)}</td>
                          <td className="mono muted" style={{ fontSize: '0.75rem' }}>{leg.symbol}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  <div className="order-actions">
                    <button className="btn-confirm" onClick={handleSubmit}>
                      Submit Order (Paper)
                    </button>
                    <button className="btn-cancel" onClick={handleCancel}>
                      Cancel
                    </button>
                  </div>
                </div>
              )}

              {orderState === 'submitting' && (
                <div className="order-status muted">Submitting order...</div>
              )}

              {orderState === 'result' && orderData && (
                <div className={`order-result ${orderData.status === 'submitted' || orderData.status === 'filled' ? 'green' : 'red'}`}>
                  <strong>{orderData.status?.toUpperCase()}</strong>: {orderData.message}
                  {orderData.order_id && <span className="mono muted"> (ID: {orderData.order_id})</span>}
                  {orderData.is_paper && <span className="muted"> [PAPER]</span>}
                  <button className="btn-cancel" onClick={handleCancel} style={{ marginLeft: '1rem' }}>
                    Dismiss
                  </button>
                </div>
              )}
            </div>
          )}

          <div className="rationale muted">{tc.rationale}</div>
        </div>
      )}
    </div>
  );
}


function PortfolioPanel({ portfolio }) {
  if (!portfolio) return null;

  const g = portfolio.greeks || {};
  const r = portfolio.risk || {};
  const triggers = portfolio.hedge_triggers || [];

  return (
    <div className="section">
      <div className="section-header">
        Portfolio ({portfolio.position_count} positions)
      </div>
      <div className="metrics-grid">
        <div className="metric-card">
          <div className="metric-label">Net Delta</div>
          <div className={`metric-value mono ${Math.abs(g.net_delta) > 30 ? 'red' : ''}`}>
            {g.net_delta > 0 ? '+' : ''}{g.net_delta?.toFixed(1)}
          </div>
        </div>
        <div className="metric-card">
          <div className="metric-label">Net Theta</div>
          <div className="metric-value mono">{g.net_theta?.toFixed(1)}</div>
        </div>
        <div className="metric-card">
          <div className="metric-label">Net Vega</div>
          <div className={`metric-value mono ${Math.abs(g.net_vega) > 150 ? 'amber' : ''}`}>
            {g.net_vega?.toFixed(1)}
          </div>
        </div>
        <div className="metric-card">
          <div className="metric-label">Total Risk</div>
          <div className="metric-value mono">${r.total_risk?.toFixed(0)}</div>
          <div className="metric-sub">{r.risk_pct?.toFixed(1)}% of portfolio</div>
        </div>
        <div className="metric-card">
          <div className="metric-label">Unrealized P&L</div>
          <div className={`metric-value mono ${portfolio.pnl?.total_unrealized > 0 ? 'green' : portfolio.pnl?.total_unrealized < 0 ? 'red' : ''}`}>
            ${portfolio.pnl?.total_unrealized?.toFixed(0)}
          </div>
        </div>
        <div className="metric-card">
          <div className="metric-label">Available Risk</div>
          <div className="metric-value mono">${r.available_risk?.toFixed(0)}</div>
        </div>
      </div>

      {triggers.length > 0 && (
        <div className="hedge-triggers">
          <h4>Hedge Triggers</h4>
          {triggers.map((t, i) => (
            <div key={i} className={`trigger-alert ${t.urgency === 'high' ? 'red' : 'amber'}`}>
              <strong>{t.trigger}</strong>: {t.action}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
