# Data Issues — Chain Snapshots Backtester

Last audited: 2026-05-21

This documents every known data limitation in `chain_snapshots.db` that affects
the chain-replay backtester (`src/backtest/chain_replay.py`). The BS backtester
(`local_backtest.py`) is not affected — it synthesizes prices from OHLCV.

---

## 0. Data Sources

The DB is populated from two sources with different characteristics:

| Period | Source | Script | Notes |
|--------|--------|--------|-------|
| 2020-01 to 2024-12 | **DoltHub** (`post-no-preference/options`) | `scripts/_parked/import_dolt.py` | Curated subset of strikes; no OI; every-other-day sampling |
| 2025-01 to present | **Alpaca Historical Options API** | `scripts/backfill_chains.py` | Full strike grid; OI from Apr 2026; daily collection via `scripts/collect_chains.py` |

The Dolt import pulled from a community-maintained dataset on `dolthub.com`.
It provides reliable bid/ask/mid/IV but stores a curated ~60-150 contracts per
snapshot (the most liquid strikes) rather than the full chain. This is why
2020-2024 has coarser strike grids.

The Alpaca data is the full chain as returned by the broker API — every listed
strike and expiry within the DTE filter. This is why 2025+ suddenly has 800+
contracts per snapshot.

Provider code: `src/data/dolt_provider.py` (Dolt query layer),
`src/data/chain_store.py` (SQLite writer used by both).

---

## 1. Snapshot Frequency: Every-Other-Day, Not Daily

The DB has ~992 SPY snapshots over 2,329 days (2020-01-04 to 2026-05-21).
That's roughly one snapshot every 2.3 days.

| Gap (days) | Occurrences | Meaning |
|------------|-------------|---------|
| 0 | 22 | Same-day duplicates (different labels) |
| 1 | 263 | Consecutive trading days |
| 2 | 413 | **Most common** — every other day |
| 3 | 262 | Typical weekend + 1 skip |
| 4-5 | 27 | Long weekends or holidays |
| 7+ | 3 | Gaps (holiday weeks, collection outages) |
| 127, 185 | 1 each | Two major collection gaps |

**Impact:** Trades can only enter/exit on snapshot dates. A trade that *should*
enter on Tuesday might enter on Wednesday instead. Profit targets and stop losses
are only checked at EOD snapshots — intraday exits are invisible.

**Mitigation:** The backtester snaps to nearest available date. Exit pricing
searches +/-3 days from the target date. This adds up to ~1 day of timing
slippage on average.

---

## 2. Strike Count Drops Sharply in Older Data

| Year | Avg Contracts/Snapshot | Avg 0-14 DTE Contracts | Min 0-14 DTE |
|------|----------------------|----------------------|--------------|
| 2020 | 130 | 38.6 | 0 |
| 2021 | 145 | 40.2 | 0 |
| 2022 | 147 | 42.4 | 0 |
| 2023 | 139 | 33.7 | 10 |
| 2024 | 113 | 27.3 | 0 |
| 2025 | 828 | 822.6 | 458 |
| 2026 | 1,153 | 962.8 | 2 |

**2020-2024:** ~30-40 contracts in the 0-14 DTE window per snapshot. That's
roughly 15 puts + 15 calls across 1-2 expiry dates. Strike spacing is $5-15
apart, so delta targeting is coarse — you might want the 0.20 delta put at
$520 but the nearest available strikes are $510 and $521.

**2025+:** 800+ contracts per snapshot after the backfill upgraded. Much finer
strike grid.

**Zero-DTE snapshots:** Some snapshots have 0 contracts in 0-14 DTE (4-15 per
year in 2020-2024). The backtester skips these — they appear in `data_issues`
as "entries skipped — insufficient strikes."

**Impact:** Backtests on 2020-2024 data have coarser strike selection than what
a real trader would have had. Iron condors and butterflies are most affected
since they need 4 specific strikes.

---

## 3. Open Interest Data Only Exists for April-May 2026

| Month | Snapshots with OI | Total Snapshots |
|-------|-------------------|-----------------|
| 2026-04 | 21 | 21 |
| 2026-05 | 14 | 14 |
| All other months | **0** | 957 |

Only 35 out of 992 SPY snapshots have open interest data. The rest have
`open_interest = 0` on every contract.

**Impact:** The dealer filter (`dealer_filter=True`) is a complete no-op on
any backtest before April 2026. The P/C OI ratio cannot be computed, so
`dealer_regime` is always `None`, and the filter passes everything through.
The VALIDATION.md finding that "dealer filter has near-zero effect" is a
**data gap**, not a signal quality finding.

**What to do:** Start collecting OI data on every chain snapshot going forward.
The `collect` service already does this — the gap is purely historical.
Consider backfilling OI from a provider that has it (CBOE, OptionMetrics).

---

## 4. Bid/Ask Spreads Are Wide on Far-OTM Strikes

| Year | Avg Spread (%) | Contracts > 20% Spread | Contracts > 50% Spread |
|------|---------------|----------------------|----------------------|
| 2020 | 5.3% | 1,479 (7.7%) | 103 (0.5%) |
| 2021 | 5.5% | 1,795 (8.9%) | 86 (0.4%) |
| 2022 | 4.9% | 1,631 (7.6%) | 50 (0.2%) |
| 2023 | 5.3% | 851 (8.8%) | 11 (0.1%) |
| 2024 | 5.7% | 1,891 (9.2%) | 79 (0.4%) |
| 2025 | 20.6% | 57,339 (42.2%) | 12,785 (9.4%) |
| 2026 | 16.3% | 42,543 (31.3%) | 8,989 (6.6%) |

The 2020-2024 average spread of ~5% is reasonable. The jump in 2025-2026 is
because the expanded strike grid includes more far-OTM contracts where spreads
are naturally wider.

**Impact:** The backtester uses **mid price** for entry and exit. In reality,
you'd pay the ask (buys) and receive the bid (sells). For a credit spread
with 5% average spread, actual fills would be ~2.5% worse than mid on each leg.
On a 2-leg spread, that's ~5% round-trip slippage from spread alone.

**Mitigation:** Use the `slippage_pct` parameter to model this. A 3-5%
slippage setting roughly approximates real fill quality for liquid SPY
options. The backtester also records `avg_spread_pct` per trade for analysis.

---

## 5. Symbol Coverage Is Uneven

| Symbol | Snapshots | Period | Notes |
|--------|-----------|--------|-------|
| SPY | 992 | 2020-01 to 2026-05 | Best coverage |
| AAPL | 814 | 2020-01 to 2026-05 | Good |
| AMZN | 810 | 2020-01 to 2026-05 | Good |
| GOOG | 810 | 2020-01 to 2026-05 | Good |
| NFLX | 805 | 2020-01 to 2026-05 | Good |
| AMD | 792 | 2020-01 to 2024-12 | Stops at end of 2024 |
| MSFT | 785 | 2020-01 to 2024-12 | Stops at end of 2024 |
| TSLA | 637 | 2021-01 to 2024-12 | Starts 2021, stops 2024 |
| META | 429 | 2022-07 to 2026-05 | Only from FB→META rename |
| **QQQ** | **280** | **2025-05 to 2026-05** | **12 months only** |
| **IWM** | **268** | **2025-05 to 2026-05** | **12 months only** |
| NVDA | 84 | 2020-01 to 2020-07 | Only 7 months |
| ^SPX | 28 | 2026-04 to 2026-05 | Index, very recent |
| ^NDX | 27 | 2026-04 to 2026-05 | Index, very recent |

**Impact:** Cross-asset validation is limited. The VALIDATION.md tested
QQQ and IWM, but those only have data from May 2025 — a 12-month window
in a bull market. That's not enough to validate strategy robustness.

SPY is the only symbol with enough data (6+ years) for serious backtesting.
AAPL/AMZN/GOOG/NFLX have good coverage but are single stocks, not indices.

---

## 6. No Intraday Data

All snapshots are end-of-day. There is no intraday option pricing data.

**Impact:** The backtester can only check profit targets and stop losses
once per snapshot (~every 2 days). A trade that hits its 50% profit target
intraday and then reverses by EOD will not be exited at the right time.

This biases results:
- **Credit strategies:** Understates wins. Many credit spreads hit 50% profit
  intraday and should be closed, but the backtester doesn't see it until
  the next snapshot (by which time the profit may have shrunk or reversed).
- **Stop losses:** Understates losses. A position that gaps through 2x stop
  loss intraday won't be stopped until the next snapshot.

---

## 7. IV Data Is Reliable But Has Gaps in 2025+

| Year | Valid IV | Missing IV | IV Coverage |
|------|----------|------------|-------------|
| 2020 | 19,900 | 0 | 100% |
| 2021 | 21,885 | 36 | 99.8% |
| 2022 | 22,262 | 0 | 100% |
| 2023 | 10,356 | 0 | 100% |
| 2024 | 20,684 | 0 | 100% |
| 2025 | 120,305 | 15,616 | 88.5% |
| 2026 | 127,427 | 8,626 | 93.7% |

2020-2024 IV coverage is essentially 100%. The 2025-2026 gaps are on
deep-OTM contracts where the pricing model can't compute a stable IV.
These are contracts you wouldn't trade anyway.

**Impact:** Minimal. The backtester's delta calculation uses each contract's
IV, so missing IV just means that contract is skipped during strike selection.

---

## 8. Two Major Collection Gaps

There are two gaps of 127 and 185 days in the SPY snapshot timeline.
These likely correspond to collection infrastructure changes or outages.

**Impact:** Backtests spanning these gaps will have periods with no trade
entries. The backtester handles this gracefully (just fewer trades), but
you lose coverage during potentially interesting market periods.

---

## Summary: What You Can Trust

| Question | Answer |
|----------|--------|
| Can I backtest SPY 2020-2026? | Yes, but 2020-2024 has coarse strikes |
| Can I backtest QQQ/IWM? | Only May 2025 onward |
| Are entry/exit prices realistic? | Yes for mid; add 3-5% slippage for fills |
| Does the dealer filter work? | Only on April-May 2026 data |
| Are intraday exits captured? | No — EOD only |
| Is the IV data reliable? | Yes (99%+ coverage in 2020-2024) |
| How does this compare to BS backtest? | Real data is more conservative — BS overestimates precision of strike selection and underestimates spread costs |

## How to Fix Each Issue

### Fix #1 — Fill the Two Big Gaps (185d and 127d)

Gap 1: `2023-06-30` → `2024-01-01` (185 days, Dolt→Dolt seam)
Gap 2: `2024-12-31` → `2025-05-07` (127 days, Dolt→Alpaca seam)

**Alpaca covers data since Feb 2024**, so:

```bash
# Fix gap 2 (Alpaca has this data):
docker-compose run --rm backfill python scripts/backfill_chains.py SPY \
  --start 2025-01-01 --end 2025-05-06

# Gap 1 is pre-Alpaca — needs Dolt re-import:
# 1. Clone Dolt if not already present:
cd data && dolt clone post-no-preference/options dolt_options
# 2. Re-run import for the missing window:
docker-compose run --rm backfill python scripts/_parked/import_dolt.py \
  --tickers SPY --start 2023-07-01 --end 2023-12-31
```

**Effort:** ~2 hours for gap 2 (API rate limits). Gap 1 depends on whether
the Dolt dataset has that period — check first with a `dolt sql` query.

---

### Fix #2 — Backfill QQQ/IWM to Match SPY Coverage

Currently QQQ and IWM only have data from 2025-05-09. Alpaca goes back to
Feb 2024; Dolt covers further back.

```bash
# Alpaca backfill (Feb 2024 → May 2025):
docker-compose run --rm backfill python scripts/backfill_chains.py QQQ,IWM \
  --start 2024-02-01 --end 2025-05-08

# Dolt backfill (2020 → Jan 2024):
docker-compose run --rm backfill python scripts/_parked/import_dolt.py \
  --tickers QQQ,IWM --start 2020-01-01 --end 2024-01-31
```

**Effort:** ~8-12 hours for Alpaca (rate limited, 2 symbols × 15 months).
Dolt import is local, ~30 minutes if the clone is already present.

---

### Fix #3 — Move to Daily Collection

The `collect` service already runs daily when scheduled. The every-other-day
pattern is from historical imports, not current collection.

Going forward, ensure the collect service runs every trading day:

```bash
# Add to crontab or scheduler (already in docker-compose as 'collect'):
# Run at 4:30 PM ET (after market close)
30 16 * * 1-5 cd /path/to/options_analyzer && docker-compose run --rm collect
```

The `eod` label snapshots from `collect_chains.py` already capture the full
chain with OI. No code changes needed — just ensure it runs daily.

**Effort:** 5 minutes (cron entry).

---

### Fix #4 — Backfill OI Data

OI only exists on snapshots from April 2026+. Historical OI is **not available
from Alpaca** (their bars API returns OHLCV, not OI). Two options:

**Option A — Accept the gap.** OI is only used by the dealer filter, which
showed near-zero effect in validation. Once you have 6+ months of daily
OI collection (by late 2026), re-run the dealer filter validation.

**Option B — CBOE DataShop** (paid). CBOE sells historical end-of-day option
data with OI going back to 2004. Costs ~$500-2,000 depending on scope.
Would need a new import script to ingest their CSV format.

**Recommendation:** Option A. Let daily collection accumulate OI naturally.
Revisit the dealer filter after 6 months of OI data.

**Effort:** Option A = 0 (just wait). Option B = $500+ and a day of scripting.

---

### Fix #5 — Improve Bid/Ask Accuracy on Alpaca Data

The Alpaca backfill estimates bid/ask from OHLC bars (see
`src/data/backfill_pipeline.py:_estimate_bid_ask`):

```python
bid = min(open, close)
ask = max(open, close)
```

This is a rough estimate — real bid/ask can differ significantly from
bar extremes, especially on low-volume contracts.

**Fix:** Use the `slippage_pct` parameter in backtests to account for this.
A setting of 3-5% is a reasonable proxy. No code change — just use the
parameter when running chain-replay backtests.

For future collection: the live `collect_chains.py` already gets real
bid/ask from yfinance. Only the Alpaca backfill has estimated spreads.

**Effort:** 0 (already handled by slippage parameter).

---

### Fix #6 — Intraday Data

No practical fix with current providers. Would require:
- **Alpaca intraday option bars** (1-minute or 5-minute) — available but
  storage-intensive (~500K bars/day for SPY options) and slow to backfill
- **CBOE LiveVol** or **OptionMetrics IvyDB** for tick-level data (expensive)

**Recommendation:** Don't pursue. EOD backtesting is the industry standard
for strategies with 3-14 DTE holding periods. The bias from missing intraday
exits is small relative to other uncertainties (model risk, regime shifts).

**Effort:** Not recommended.

---

### Fix #7 — Enrich Dolt Data with More Strikes

The Dolt dataset has ~60-150 contracts per snapshot (curated liquid strikes).
You can't add strikes that weren't in the original dataset.

**Workaround:** For 2020-2024 backtests, widen the delta tolerance in strike
selection. Instead of targeting exactly 0.20 delta, accept 0.15-0.25. The
chain-replay backtester already does this — `_find_delta_strike` picks the
closest available strike.

**Alternative:** Alpaca data goes back to Feb 2024 with full strike grids.
Backfill Feb-Dec 2024 from Alpaca to replace the sparse Dolt data for that
window:

```bash
docker-compose run --rm backfill python scripts/backfill_chains.py SPY \
  --start 2024-02-01 --end 2024-12-31
```

This would upgrade 2024 from ~113 contracts/snapshot (Dolt) to ~800+ (Alpaca).

**Effort:** ~4-6 hours for the Alpaca backfill.

---

### Priority Order

| Priority | Fix | Effort | Impact |
|----------|-----|--------|--------|
| 1 | Daily collection cron (#3) | 5 min | Prevents future gaps |
| 2 | Fill gap 2: Jan-May 2025 (#1) | 2 hrs | Closes the Dolt→Alpaca seam |
| 3 | Backfill 2024 from Alpaca (#7) | 4-6 hrs | Better strike grids for recent data |
| 4 | Backfill QQQ/IWM (#2) | 8-12 hrs | Enables cross-asset validation |
| 5 | Fill gap 1: Jul-Dec 2023 (#1) | 30 min | Requires Dolt clone |
| 6 | Let OI accumulate (#4) | 0 (wait) | Dealer filter validation by late 2026 |
| 7 | Intraday data (#6) | Not recommended | Low ROI for this strategy timeframe |
