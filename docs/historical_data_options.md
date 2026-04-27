# Historical Options Data: Provider Analysis for Priority 1c

## What We Need

Replace simulated option P&L in our backtester with real chain data:
- Actual bid/ask spreads (replace flat 3% slippage assumption)
- Real IV at entry/exit for accurate P&L
- Volume and OI per strike for liquidity filtering
- Greeks (delta, gamma, theta, vega) for portfolio engine validation
- Coverage: SPY 2022-2026 minimum, ideally 2013+

---

## Provider Comparison

### 1. CBOE DataShop (Gold Standard)

The exchange itself. Data sourced directly from OPRA feed, not a third-party reseller.

**Products relevant to us:**

| Product | Resolution | Fields | Coverage | Price Estimate |
|---|---|---|---|---|
| Option EOD Summary | Daily (EOD + 3:45PM snapshot) | NBBO bid/ask, OHLC, volume, VWAP, OI, IV, Greeks | All US listed options | ~$13/day per symbol for minute w/ Greeks |
| Option Quote Intervals | 1-min or N-min | NBBO quote + size, OHLC, volume | 2012+ | Higher — pay per interval |
| Option Trades (TBT) | Tick (every trade) | Full transaction detail | All exchanges | Expensive — institutional |
| Open-Close Volume | Daily | Volume by customer type (firm, market maker, etc.) | CBOE venues | $1,000/mo subscription |

**What "Option EOD Summary" gives us:**
- End-of-day NBBO bid and ask for every option series
- OHLC prices, trade volume, VWAP
- Open interest
- Optional "Calcs" add-on: IV and Greeks (delta, gamma, theta, vega, rho)
- Two snapshots per day: EOD close + 3:45 PM ET

**Pricing model:**
- One-time purchase (historical) or subscription (ongoing)
- Per-symbol, per-day pricing — a user reported ~$13/day for SPY minute data with Greeks
- For EOD-only (which is what we need for daily backtesting): cheaper but still not cheap
- SPY 2022-2026 = ~1,000 trading days. At even $2-5/day for EOD = $2,000-5,000 one-time
- Need to request a quote from CBOE for exact pricing

**Verdict:**
- Best data quality (it's the source exchange)
- Best for final validation / publishable results
- Too expensive for development iteration
- No API — CSV/file download, then you process it yourself

---

### 2. ThetaData ($30/mo)

**What it offers:**
- REST API + Theta Terminal for historical options chains
- Tick, second, minute, EOD resolution
- Full NBBO bid/ask/mid, IV, 1st/2nd/3rd order Greeks, volume, OI
- Coverage: 2013+ for options (30+ years for equities)
- Free tier available (rate-limited, historical data accessible)
- Value plan: $30/mo — unlimited API calls, data back to 2017
- Standard plan: higher limits, data back to 2013

**Data fields per contract per timestamp:**
- Bid price, bid size, ask price, ask size
- Last trade price, volume
- Open interest (daily)
- IV, delta, gamma, theta, vega, rho

**Integration path:**
Write a data loader (~200 lines) that fetches historical chain snapshots per day and feeds them into our existing `local_backtest.py`. No framework rewrite needed.

**Verdict:**
- Best value for development — $30/mo gets everything we need
- Clean REST API, easy to automate
- Good enough for all 6 validation backtests
- QuantConnect has a native LEAN CLI integration if we ever need it
- Community well-reviewed for options data quality

---

### 3. QuantConnect (Free Cloud / $60+ Local)

**What it offers:**
- Minute-resolution options data (AlgoSeek source) back to 2010
- Bid/ask OHLC per bar (QuoteBar) — NBBO consolidated
- Open interest (daily)
- IV and Greeks (daily pre-calculated; intraday requires custom indicators)

**Three access paths:**

| Approach | Cost | Data Access | Fits Our System? |
|---|---|---|---|
| Cloud backtesting | Free: unlimited backtests | Minute options data, cloud only | No — must rewrite backtester in LEAN |
| LEAN CLI + ThetaData | $30/mo TD + $60/mo QC | Local minute data via Theta Terminal | Yes but adds $60/mo overhead |
| LEAN CLI + QC data | $60/mo QC + credits | Download CSVs locally ($1/file) | SPY = thousands of files, expensive |

**Verdict:**
- Free tier is powerful but locks you into LEAN framework
- Would require rewriting our entire backtester, signal architecture, edge gates
- Not worth it — we'd lose all validated work (BT1-BT6, regression weights, Kelly sizing)
- Good option if starting from scratch, bad option given where we are

---

### 4. Polygon.io ($29/mo)

**What it offers:**
- REST API + WebSocket for all 17 US options exchanges
- NBBO quotes with bid/ask, size, exchange ID, timestamps
- Minute aggregates, trades, quotes
- Options Starter: $29/mo (15-min delayed + minute aggregates)
- Options Developer: higher tier for real-time

**Coverage:**
- Historical options data from 2019+ (shorter than ThetaData)
- Full OPRA feed consolidated

**Verdict:**
- Similar price to ThetaData ($29 vs $30)
- Shorter history (2019 vs 2013/2017)
- Good API quality, well-documented
- Our backtest window (2022-2026) is covered
- Viable alternative to ThetaData

---

### 5. Other Providers (Brief Notes)

| Provider | Cost | Coverage | Notes |
|---|---|---|---|
| Databento | Pay-per-use, $125 free credits | OPRA full feed | Raw tick data, professional grade, expensive at scale |
| FirstRate Data | $100-500 one-time | 2010+ | CSV downloads, simple but less flexible |
| IVolatility | Varies | All US listed | NBBO + IV + Greeks, academic pricing available |
| ORATS | $99+/mo | Full chain | Options-focused, good Greeks/IV, pricier |
| Intrinio | $75+/mo | US options | REST API, good docs |
| Market Data (Google Sheets) | Free | 15+ years | Limited to spreadsheet use, not API-friendly |

---

## Decision Matrix

| Factor | CBOE DataShop | ThetaData | Polygon.io | QuantConnect |
|---|---|---|---|---|
| Monthly cost | $2,000-5,000 one-time | $30/mo | $29/mo | $0-60/mo |
| Data quality | Gold standard (source) | Very good (OPRA derived) | Very good (OPRA derived) | Good (AlgoSeek) |
| History depth | 2004+ | 2013-2017+ | 2019+ | 2010+ |
| Bid/ask spreads | Yes (NBBO) | Yes (NBBO) | Yes (NBBO) | Yes (NBBO) |
| IV + Greeks | Yes (with Calcs add-on) | Yes (included) | Limited | Yes (daily only) |
| Open interest | Yes | Yes (daily) | Yes | Yes (daily) |
| API access | No (file download) | REST API | REST API | Cloud or LEAN CLI |
| Keeps our backtester? | Yes (parse CSVs) | Yes (API loader) | Yes (API loader) | No (rewrite in LEAN) |
| Best for | Final validation | Development + production | Development + production | Starting from scratch |

---

## Recommendation: Two-Phase Approach

### Phase 1: Development — ThetaData Value ($30/mo)

- Subscribe to ThetaData Value plan
- Build `src/backtest/thetadata_loader.py`
- Cache chain snapshots locally (SQLite or parquet)
- Re-run all 6 validation backtests with real bid/ask data
- Iterate on slippage model, chain quality filters
- Duration: 1-2 months of development

### Phase 2: Final Validation — CBOE DataShop (one-time)

- Purchase SPY Option EOD Summary with Calcs (IV + Greeks) for 2022-2026
- Cross-validate ThetaData results against CBOE source data
- Publish results with confidence intervals
- This is a one-time cost for the authoritative dataset
- Only do this if ThetaData results look promising and you want institutional-grade validation

### Why not CBOE first?

- CBOE is file-download only — slower iteration cycle
- CBOE pricing requires a quote (not self-serve at our scale)
- ThetaData's API lets us build, test, and iterate in days, not weeks
- If ThetaData results invalidate the strategy, we've saved thousands
- CBOE data would confirm ThetaData results, not replace them

---

## Implementation Plan

### Step 1: ThetaData Adapter

```
src/backtest/thetadata_loader.py
```

- `fetch_eod_chain(symbol, date)` → all contracts for that day
- `get_contract(symbol, date, strike, expiry, option_type)` → bid/ask/mid/IV/Greeks/OI
- `get_chain_snapshot(symbol, date, dte_range)` → filtered chain for backtest entry
- Local cache in `data/chains/` (parquet by date, ~5-10 MB/day for SPY)
- Bulk download script for 2022-2026 (~1,000 trading days)

### Step 2: Backtester Integration

Modify `src/backtest/local_backtest.py`:

**Entry:**
- Look up actual contracts matching our strike selection
- Use real bid/ask to compute entry price (not BS model)
- Slippage = actual half-spread, not flat 3%
- Reject if bid-ask > 10% of mid (spread cost gate)

**During hold:**
- Track actual contract prices day-by-day
- Check profit target / stop loss against real mid prices

**Exit:**
- Use real bid/ask at exit for P&L
- Compute actual slippage incurred vs our 3% assumption

### Step 3: Re-run Validation

Re-run all 6 backtests with real chain data:
1. Compare Sharpe ratios: simulated vs real
2. Compare actual slippage vs 3% assumption per strategy
3. Validate chain quality filter (are we rejecting the right strikes?)
4. Check if edge gates still hold with real IV (not GARCH estimate)
5. Recalibrate if results diverge significantly

### Step 4: CBOE Cross-Validation (optional)

If ThetaData results are strong:
- Purchase CBOE EOD Summary for the same window
- Run identical backtests on CBOE data
- Report both results with confidence intervals
- Differences would indicate data quality issues in either source

---

## Data Storage Estimate

SPY has ~2,000-4,000 active option contracts on any given day (multiple expiries x ~50-100 strikes each).

| Resolution | Per Day | 4 Years (1,000 days) |
|---|---|---|
| EOD snapshot | ~5-10 MB | 5-10 GB |
| Minute bars (all contracts) | ~500 MB-1 GB | 500 GB-1 TB |

For our backtester, **EOD is sufficient** — we enter/exit on daily bars and check daily P&L. Minute data would only matter for intraday timing validation (Priority 3), which is a separate concern.

---

## Sources

- CBOE DataShop: https://datashop.cboe.com/
- CBOE Option EOD Summary: https://datashop.cboe.com/option-eod-summary
- CBOE Option Quote Intervals: https://datashop.cboe.com/option-quote-intervals
- ThetaData Options: https://www.thetadata.net/options-data
- ThetaData Pricing: https://www.thetadata.net/pricing
- ThetaData Docs: https://http-docs.thetadata.us/
- Polygon.io Options: https://polygon.io/options
- Polygon.io Pricing: https://polygon.io/pricing
- QuantConnect Options: https://www.quantconnect.com/docs/v2/writing-algorithms/securities/asset-classes/equity-options/handling-data
- QuantConnect + ThetaData: https://www.quantconnect.com/docs/v2/lean-cli/datasets/theta-data
- QuantConnect Pricing: https://www.quantconnect.com/pricing/
- Databento OPRA: https://databento.com/datasets/OPRA.PILLAR
- FirstRate Data: https://firstratedata.com/options-data
