# ThetaData REST API Research — Bulk Backfill Planning

Date: 2026-05-21

## Architecture

ThetaData runs a local Java terminal (Theta Terminal v3) that acts as an HTTP proxy on
`http://127.0.0.1:25503`. All REST calls go to this local server, which fetches from
ThetaData's proprietary protocol (up to 30x bandwidth reduction vs raw HTTP). Java 21+
required. Terminal must be running for any data access.

---

## 1. Options Endpoints

### Contract Discovery

| Endpoint | Path | Notes |
|----------|------|-------|
| List expirations | `GET /v3/option/list/expirations?symbol=SPY` | Returns all expirations for a root. Free tier. |
| List strikes | `GET /v3/option/list/strikes?symbol=SPY&expiration=2026-05-29` | Returns all strikes for a given expiration. Free tier. |

Both update overnight. Both support `symbol=*` for all symbols.

### EOD (End of Day)

**`GET /v3/option/history/eod`**
- Required: `symbol`, `expiration`, `start_date`, `end_date`
- Optional: `strike` (default `*`), `right` (call/put/both), `max_dte`, `strike_range`, `format`
- Response fields: `symbol`, `expiration`, `strike`, `right`, `created`, `last_trade`,
  `open`, `high`, `low`, `close`, `volume`, `count`,
  `bid_size`, `bid_exchange`, `bid`, `bid_condition`,
  `ask_size`, `ask_exchange`, `ask`, `ask_condition`
- Combined OHLC + closing bid/ask in one call.

### Intraday OHLC

**`GET /v3/option/history/ohlc`**
- Required: `symbol`, `expiration`, `interval`
- Intervals: tick, 10ms, 100ms, 500ms, 1s, 5s, 10s, 15s, 30s, 1m, 5m, 10m, 15m, 30m, 1h
- Optional: `date` or `start_date`/`end_date`, `strike`, `right`, `start_time`, `end_time`, `strike_range`
- Response fields: `symbol`, `expiration`, `strike`, `right`, `timestamp`,
  `open`, `high`, `low`, `close`, `volume`, `count`, `vwap`

### Open Interest History

**`GET /v3/option/history/open_interest`**
- Required: `symbol`, `expiration`
- Optional: `date` or `start_date`/`end_date`, `strike`, `right`, `max_dte`, `strike_range`
- Response fields: `symbol`, `expiration`, `strike`, `right`, `timestamp`, `open_interest`
- Reported once/day by OPRA at ~06:30 ET (previous day's close).
- Tier: Standard or Pro.

### Greeks — EOD (best for backfill)

**`GET /v3/option/history/greeks/eod`**
- Required: `symbol`, `expiration`, `start_date`, `end_date`
- Optional: `strike`, `right`, `annual_dividend`, `rate_type` (default sofr), `rate_value`,
  `version` (latest or 1), `underlyer_use_nbbo`, `max_dte`, `strike_range`
- Response fields — ALL Greeks in one call:
  - Price: `open`, `high`, `low`, `close`, `volume`, `count`
  - Quote: `bid`, `ask` (+ size, exchange, condition)
  - 1st order: `delta`, `theta`, `vega`, `rho`, `epsilon`, `lambda`, `gamma`
  - 2nd order: `vanna`, `charm`, `vomma`, `veta`, `vera`
  - 3rd order: `speed`, `zomma`, `color`, `ultima`
  - Calc: `d1`, `d2`, `dual_delta`, `dual_gamma`, `implied_vol`, `iv_error`
  - Underlying: `underlying_timestamp`, `underlying_price`
- Black-Scholes model, tick-by-tick underlying price matching.

### Greeks — Intraday (1st order)

**`GET /v3/option/history/greeks/first_order`**
- Same params as OHLC plus `interval`, `annual_dividend`, `rate_type`, `rate_value`, `version`
- Response fields: `bid`, `ask`, `delta`, `theta`, `vega`, `rho`, `epsilon`, `lambda`,
  `implied_vol`, `iv_error`, `underlying_timestamp`, `underlying_price`

### Greeks — Intraday (2nd order)

**`GET /v3/option/history/greeks/second_order`**
- Response fields: `bid`, `ask`, `gamma`, `vanna`, `charm`, `vomma`, `veta`,
  `implied_vol`, `iv_error`, `underlying_timestamp`, `underlying_price`

### Trade Tick Data

**`GET /v3/option/history/trade`**
- Response fields: `symbol`, `expiration`, `strike`, `right`, `timestamp`, `sequence`,
  `condition`, `ext_condition1-4`, `size`, `exchange`, `price`
- Multi-day requests limited to 1 month of data.

### Quote Tick Data (NBBO)

**`GET /v3/option/history/quote`**
- Returns every NBBO quote reported by OPRA.
- Response fields: `timestamp`, `bid_size`, `bid_exchange`, `bid`, `bid_condition`,
  `ask_size`, `ask_exchange`, `ask`, `ask_condition`
- Supports `interval` param for downsampling (tick to 1h).
- Multi-day requests limited to 1 month.

---

## 2. Bulk Download Capabilities

### Wildcard parameters (key feature of v3)
- `expiration=*` — all expirations for a symbol
- `strike=*` — all strikes (this is the DEFAULT)
- `right=both` — calls and puts (this is the DEFAULT)
- `symbol=*` — all symbols (on list endpoints)

**One call to get all strikes for SPY on a given date:**
```
GET /v3/option/history/eod?symbol=SPY&expiration=*&start_date=2026-01-02&end_date=2026-01-02
```
This returns every contract (all expirations, all strikes, calls+puts) for SPY on that date.

### Filtering helpers
- `max_dte=14` — only contracts with DTE <= 14 (perfect for our 0-14 DTE scanner)
- `strike_range=10` — returns 10 strikes above + 10 below spot + ATM (21 total)

### No pagination
Responses are streamed as CSV/NDJSON. No cursor or page tokens. Large responses just return
all rows. Use `format=ndjson` for streaming parse.

### No daily download cap
There is no daily request limit or download cap. The only constraint is concurrency (see below).

---

## 3. Plan Details

| Feature | FREE | VALUE ($40/mo) | STANDARD ($80/mo) | PRO ($160/mo) |
|---------|------|-----------------|--------------------|--------------------|
| Options history depth | 2023-06-01 | 2020-01-01 | 2016-01-01 | 2012-06-01 |
| Granularity | EOD only | 1 minute | Tick level | Tick level |
| Concurrent requests | 1 (20 req/min) | 2 | 4 | 8 |
| Real-time delay | 1 day | 15 min | Real-time | Real-time |
| Greeks | None | 1st order + IV | 1st order + IV | 1st/2nd/3rd order + trade Greeks |
| Quote streaming | 0 | 0 | 10,000 | 15,000 |
| Trade streaming | 0 | 0 | 15,000 | Unlimited |
| Request types | 3 | 3 | 7 | 12 |

### Greeks by plan
- **Value & Standard**: 1st order Greeks (delta, theta, vega, rho, epsilon, lambda) + implied_vol
- **Pro only**: 2nd order (gamma, vanna, charm, vomma, veta) + 3rd order (speed, zomma, color, ultima) + trade Greeks

### No ticker limits
All plans cover 100% of US index and stock options. No per-ticker restrictions.

### Historical depth note
- Standard goes back to 2016-01-01 (~10 years) — sufficient for most backtesting
- Pro goes back to 2012-06-01 (~14 years)
- Index data (SPX, VIX): Value=2023, Standard=2022, Pro=2017. NDX not supported (CGIF indices only).

---

## 4. Rate Limits / Concurrency

**There is NO traditional rate limit (req/sec).** Instead, ThetaData limits concurrent
outstanding requests:

| Tier | Max concurrent |
|------|---------------|
| FREE | 1 (+ 20 req/min hard cap) |
| VALUE | 2 |
| STANDARD | 4 |
| PRO | 8 |

- Requests beyond the limit are queued (default queue size 16, expandable to 128).
- Queue overflow returns HTTP 429.
- No daily cap. No per-endpoint distinction — it's global concurrency.
- Use semaphores in client code to respect limits.

**Throughput implication**: With Standard (4 concurrent) and EOD bulk requests, you can
sustain ~4 requests in flight. Each bulk request (all strikes for a ticker on a date)
returns in ~1-3 seconds, so effective throughput is ~1-4 tickers/second for EOD data.

---

## 5. Contract Identification

ThetaData does NOT use OCC symbols. Contracts are identified by 4 fields:
- `symbol` (root, e.g., "SPY")
- `expiration` (date, e.g., "2026-05-29")
- `strike` (float in dollars, e.g., 420.00)
- `right` ("call" or "put")

### Discovery workflow for backfill:
1. `GET /v3/option/list/expirations?symbol=SPY` → all expiration dates
2. `GET /v3/option/list/strikes?symbol=SPY&expiration=2026-05-29` → all strikes for that exp
3. Or skip discovery entirely: `GET /v3/option/history/eod?symbol=SPY&expiration=*&strike=*` returns everything

---

## 6. Recommended Backfill Strategy for Options Analyzer

### Plan recommendation: Standard ($80/mo)
- 10 years of history (2016+), tick-level granularity
- 1st order Greeks + IV (sufficient for delta, theta, vega; we compute gamma from chain)
- 4 concurrent requests
- If 2nd/3rd order Greeks needed (gamma history, vanna/charm), upgrade to Pro ($160/mo)

### Optimal bulk request pattern:
```
For each ticker in watchlist (SPY, QQQ, IWM, ...):
  For each trading date in backfill range:
    GET /v3/option/history/greeks/eod?symbol={ticker}&expiration=*&max_dte=14
        &start_date={date}&end_date={date}&format=ndjson
```
This returns all Greeks + OHLC + bid/ask for every contract with DTE<=14 in one call.

### Key endpoint for our scanner: `/v3/option/history/greeks/eod`
- Returns OHLC + bid/ask + all Greeks + IV + underlying price in a single call
- With `expiration=*&max_dte=14`, gets exactly the contracts we care about
- One request per ticker per date — extremely efficient for backfill

### Estimated backfill volume:
- 3 tickers x 2,500 trading days (10 years) = 7,500 requests
- At 4 concurrent, ~30 minutes for full backfill
- Data size: ~50-100 rows per ticker per date (all strikes, both sides, <=14 DTE)
