# Extensions Design Notes
## Jump-Diffusion · MC Greeks · American Options · Implied Vol Surface

This document explains what each extension does, why it was added, how it was
implemented, and how the pieces connect to each other and to the existing
codebase.

---

## Background: what existed before

The project already had:

| Layer | What it did |
|-------|-------------|
| `src/models/black_scholes.py` | Closed-form BS price and all five Greeks |
| `src/monte_carlo/gbm_simulator.py` | GBM path simulation + `run_monte_carlo()` orchestrator |
| `src/monte_carlo/garch_vol.py` | GARCH(1,1) calibration and vol-path generator |
| `src/monte_carlo/risk_metrics.py` | VaR, CVaR, percentile stats |
| `src/mc_runner.py` | CLI wiring everything together |

Three limitations drove the four extensions:

1. **Tail risk** — GBM and GARCH both produce continuous paths. Real markets
   jump (earnings, macro events). Jump-diffusion captures the fat tails and
   skew that GBM misses.

2. **Sensitivities** — BS Greeks are closed-form but model-specific. When you
   switch to GARCH or jump-diffusion, there are no closed-form Greeks anymore.
   A numerical bump-and-reprice approach works with any simulator.

3. **Early exercise** — Black-Scholes prices *European* options only. American
   puts carry a positive early-exercise premium that BS simply cannot compute.

4. **Market calibration** — Implied volatility shows what the market actually
   prices in at each strike and expiry. A flat `sigma` in the config is an
   assumption; the vol surface shows whether that assumption is reasonable.

---

## A — Merton Jump-Diffusion

### Why

Pure GBM produces normally distributed log-returns, which underweights extreme
moves. The Merton (1976) model adds a compound Poisson jump component:

```
S(t+dt) = S(t) · exp((r − λκ − ½σ²)dt + σ√dt·Z + J_t)
```

where `J_t` is the sum of a Poisson-random number of independent log-normal
shocks. The drift compensator `κ = exp(μ_J + ½σ_J²) − 1` keeps the
discounted price a martingale under the risk-neutral measure.

The practical effect: heavier tails and a negative skew (because `mu_J < 0`),
which raises put prices and lowers (slightly) call prices relative to BS.

### How

**New file: `src/monte_carlo/jump_diffusion.py`**

Three parts inside `simulate_jump_paths()`:

1. **Diffusion component** — identical to GBM: `drift + sigma·√dt·Z`.
2. **Jump component** — for each path and each step, draw `N ~ Poisson(λ·dt)`
   and then compute the compound log-jump as `N·μ_J + √N·σ_J·ε`. The
   `√N·σ_J·ε` form is the vectorised sum-of-iid trick: the sum of N iid
   `N(μ_J, σ_J²)` variables equals `N·μ_J + √N·σ_J·ε` exactly (and evaluates
   to zero when N=0 because `√0 = 0`).
3. **Antithetic variates** — only the diffusion Z draws are mirrored; jump draws
   are independent (mirroring jump counts is not meaningful for variance
   reduction).

**Modifications to `gbm_simulator.py`**

`run_monte_carlo()` gained three new parameters:
- `use_jumps` (bool): activates jump-diffusion
- `jump_params` (dict): `{lam, mu_J, sigma_J}`, falls back to
  `config['jump']` if not passed explicitly
- `option_style` (str): `'european'` (default) or `'american'` (wired to LSMC
  below)

The resolution order for the simulator is: **jump → GARCH → constant-GBM**.
Jump takes priority because it is the most model-specific choice; GARCH is
secondary. The results dict now includes `jump_params` (or `None`) alongside
the existing `garch_params` field.

**CLI** — three new flags in `mc_runner.py`:
```
--jumps          activate jump-diffusion
--lam FLOAT      jump intensity (default 0.1 jumps/year)
--mu_J FLOAT     mean log-jump (default -0.05)
--sigma_J FLOAT  log-jump std-dev (default 0.15)
```

---

## B — MC Greeks (bump-and-reprice)

### Why

Closed-form BS Greeks only apply to the BS model. When the simulator is
GARCH or jump-diffusion, no analytical formula exists for the sensitivities.
The standard numerical solution is *bump-and-reprice*: perturb one parameter
by a small amount and divide the price change by the bump size. With
**Common Random Numbers** (same seed for every call), path-level noise
cancels in the finite difference, keeping the variance low.

### How

**New file: `src/monte_carlo/mc_greeks.py`**

The function `compute_mc_greeks()` makes seven `run_monte_carlo()` calls, all
with the same seed:

| Greek | Formula | Bump |
|-------|---------|------|
| Delta | `(V(S+h) − V(S−h)) / (2h)` | `h = S₀ × 1%` |
| Gamma | `(V(S+h) − 2V₀ + V(S−h)) / h²` | same `h` |
| Vega  | `(V(σ+ε) − V(σ−ε)) / (2ε) × 0.01` | `ε = 0.01` |
| Theta | `V(expiry−1day) − V₀` | −1 calendar day |
| Rho   | `(V(r+ε) − V(r−ε)) / (2ε) × 0.01` | `ε = 0.001` |

**Scaling conventions** match `calculate_greeks()` in `black_scholes.py`:
- Vega and Rho are expressed *per 1 percentage-point change* (the `× 0.01`
  factor). Without this, the raw central difference gives `dV/dσ` in units
  of "per unit of sigma", which is 100× larger than the BS convention.
- Theta is expressed per calendar day. After a one-day bump on the expiry
  date, `V_theta − V₀` is already the per-day change (the bump is exactly
  one day), so no further scaling is needed. Dividing by `1/365` (as one
  might naively write for a "rate") would give theta per *year*, which would
  be ~365× too large.

The function also calls `calculate_greeks()` from BS and returns both sets
side-by-side (`delta`, `bs_delta`, etc.) for easy comparison.

**CLI** — `--greeks` flag prints the comparison table after the main results
block.

---

## C — American Options (Longstaff-Schwartz)

### Why

The right to exercise early is valuable for put options, particularly when
they are deep in-the-money and interest rates are positive. BS has no
early-exercise mechanism; it always prices the European payoff. For real
long-put positions, the difference can be material.

### How

**New file: `src/monte_carlo/american_mc.py`**

The Longstaff-Schwartz (2001) algorithm runs *after* the paths are already
simulated — it works on any path array regardless of how it was generated
(GBM, GARCH, or jump-diffusion).

The algorithm in `price_american_lsmc()`:

1. **Initialise** with terminal payoffs at `t = T`.
2. **Backward loop** from `t = T − dt` down to `t = dt`:
   - Discount the cash-flow array by one step: `cash_flows × exp(−r·dt)`.
   - Identify in-the-money paths at the current time step.
   - On the ITM paths, regress the discounted continuation values on a
     polynomial basis `[(S/K)^1, (S/K)^2, …, (S/K)^degree]` (normalised
     by K for numerical stability) using `np.linalg.lstsq`.
   - Where the intrinsic value exceeds the regression-predicted continuation
     value, replace the cash flow with the intrinsic (early exercise).
3. **Final discount** from `t = dt` to `t = 0`.
4. Return `mean(cash_flows)` as the price and `std / √n` as the std error.

**Integration with `run_monte_carlo()`**

Passing `option_style='american'` runs `price_american_lsmc()` on the paths
that were already simulated for the European price. The results dict gets:
- `american_price`: the LSMC estimate
- `early_exercise_premium`: `american_price − mc_price` (always ≥ 0 for puts)

The European price is still computed and reported alongside the American
price, making it easy to see the premium in the printed output.

**CLI** — `--american` flag. Output:
```
European MC Price:  $4.23  (std error: ±0.0042)
American  MC Price: $4.81   (early exercise premium: +$0.58)
```

---

## D — Implied Volatility Surface

### Why

A single `implied_volatility` field in the config is a snapshot. In practice,
different strikes and expiries trade at different implied vols (the "vol
smile" / "skew"). Displaying the full surface lets you:
- See whether the config's flat vol is a reasonable approximation.
- Identify how much the market prices in tail risk (steep skew) or crash
  protection (high OTM put vol).

### How

**New file: `src/analytics/vol_surface.py`**

Three functions:

**`compute_implied_vol(market_price, S, K, T, r, option_type)`**

Back-solves the BS equation for sigma using `scipy.optimize.brentq` with
bracket `[1e-4, 10.0]`. Before calling brentq, it checks whether the market
price is below the arbitrage lower bound (`max(S − K·e^{−rT}, 0)` for calls);
if so it returns `nan` immediately rather than letting brentq fail with a
confusing error. Any brentq failure (e.g., market price above the stock price)
also returns `nan`.

**`fetch_vol_surface(ticker, r, max_expiries)`**

Uses yfinance to pull the full option chain. Filters:
- `bid > 0`, `ask > 0` — illiquid options with zero quotes are excluded
- `open_interest > 0` — ensures there's real trading activity
- Moneyness `K/S ∈ [0.70, 1.40]` — very deep OTM options have wide bid-ask
  spreads and unreliable IVs

Mid price `= (bid + ask) / 2` is passed to `compute_implied_vol`. Rows where
IV is `nan` (arbitrage violation or failed root-find) are silently dropped.
The output is a `DataFrame` with columns `[expiry, T, strike, moneyness, iv,
option_type]`.

**`plot_vol_surface(df, ticker, save_path)`**

Two-panel figure:
- **Left panel**: 3D scatter (moneyness × time-to-expiry × IV), coloured by IV
  level using a `RdYlGn_r` colormap (red = high vol, green = low vol).
- **Right panel**: 2D "smile" — IV vs moneyness, one line per expiry. A
  vertical dashed line marks moneyness = 1 (ATM). This is the view most
  traders use in practice.

**New file: `src/vol_surface_runner.py`**

Standalone CLI that calls `fetch_vol_surface`, prints a summary table, saves
the CSV and the chart. Keeps the vol surface workflow separate from the MC
runner since it doesn't simulate paths at all.

**`src/analytics/__init__.py`** was extended to export the three new functions.

---

## Where each file fits in the module tree

```
src/
├── models/
│   └── black_scholes.py          (unchanged)
├── analytics/
│   ├── __init__.py               (+ compute_implied_vol, fetch_vol_surface, plot_vol_surface)
│   ├── simulations.py            (unchanged)
│   ├── visualization.py          (unchanged)
│   └── vol_surface.py            (NEW — D)
├── monte_carlo/
│   ├── __init__.py               (+ simulate_jump_paths, compute_mc_greeks, price_american_lsmc)
│   ├── gbm_simulator.py          (+ use_jumps, jump_params, option_style in run_monte_carlo)
│   ├── garch_vol.py              (unchanged)
│   ├── risk_metrics.py           (unchanged)
│   ├── jump_diffusion.py         (NEW — A)
│   ├── mc_greeks.py              (NEW — B)
│   └── american_mc.py            (NEW — C)
├── utils/                        (unchanged)
├── mc_runner.py                  (+ --jumps, --greeks, --american flags; print_greeks())
├── options_test_runner.py        (unchanged)
└── vol_surface_runner.py         (NEW — D)
tests/
├── test_black_scholes.py         (unchanged)
├── test_monte_carlo.py           (+ TestJumpDiffusion, TestMCGreeks, TestAmericanMC)
└── test_vol_surface.py           (NEW — D)
```

---

## Design decisions worth noting

**No new dependencies.** All four extensions use only `scipy` (already
present for BS), `numpy`, `matplotlib`, and `yfinance`. No arch, numba, or
other packages were added.

**Jump takes priority over GARCH.** In `run_monte_carlo()`, the resolution
order is `use_jumps → use_garch → constant GBM`. This prevents ambiguity when
both flags are set. In principle you could combine jump-diffusion *with*
time-varying volatility (a GARCH-jump model), but that adds complexity for
limited gain at typical path counts.

**CRN for MC Greeks.** All seven repricing calls in `compute_mc_greeks()`
share the same random seed. This means each path pair `(V_up, V_down)` uses
the same Brownian draws, so noise in the numerator largely cancels. Without
CRN, delta would require ~10× more paths to reach the same precision.

**LSMC works on any paths.** `price_american_lsmc()` takes a `paths` array
as input without caring how it was generated. This means American pricing
comes for free with GARCH paths or jump paths, not just GBM.

**Theta scaling trap.** The MC theta formula computes `V(expiry−1day) − V₀`
directly. An intuitive but wrong version would divide by `1/365`, yielding
the annual rate of decay (~365× too large). Since `V(expiry−1day) − V₀` is
already the change for exactly one calendar day, no further scaling is needed
to match `calculate_greeks()['Theta']`.

**IV lower bound guard.** Before calling `brentq`, `compute_implied_vol` checks
`market_price ≤ max(S − K·e^{−rT}, 0)`. This prevents the root-finder from
receiving a function that is positive on both sides of the bracket (which
raises a `ValueError`), and it correctly returns `nan` for arbitrage-violating
quotes from the live chain.

---

## Test coverage

| Test class | Count | Key assertions |
|-----------|-------|---------------|
| `TestJumpDiffusion` | 6 | shape, S0 start, positivity, price within $2 of BS, vol_model='jump' key, fallback to constant |
| `TestMCGreeks` | 5 | all 10 keys present, 0 < delta < 1, gamma > 0, vega > 0, \|mc_delta − bs_delta\| < 0.05 |
| `TestAmericanMC` | 4 | am_put ≥ eu_put, am_call premium ≈ 0, keys in results, premium ≥ 0 |
| `TestImpliedVol` | 4 | IV roundtrip to 1e-4, nan on zero price, IV in (0.01, 5.0), call/put parity |

All 54 tests pass in ~2 s.
