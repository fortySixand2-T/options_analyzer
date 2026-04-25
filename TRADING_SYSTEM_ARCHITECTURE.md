# Trading System Architecture — Short-Term Options

## The core problem with short-term options

Your edge decays in hours, not days. At 0-14 DTE, theta is nonlinear — a 5 DTE option loses more value per hour than a 14 DTE option loses per day. This means:

- **Entry timing matters more than strike selection**
- **Exit discipline matters more than entry logic**
- **Realized vol vs implied vol is the only sustainable edge**

The current system has good signal architecture (regime + bias + dealer) but treats entry as a once-per-interval event. A real trading system needs to be reactive.

---

## Architecture: Four Layers

```
+-----------------------------------------------------+
|  L4: PORTFOLIO ENGINE                               |
|  Position limits, correlation, margin, Greeks mgmt  |
+-----------------------------------------------------+
|  L3: EXECUTION & SIZING                             |
|  Kelly fraction, spread cost, fill optimization     |
+-----------------------------------------------------+
|  L2: TRADE GENERATION                               |
|  Signal confluence -> candidate -> filter -> rank   |
+-----------------------------------------------------+
|  L1: MARKET STATE                                   |
|  Regime, vol surface, dealer positioning, microstr. |
+-----------------------------------------------------+
```

---

## L1: Market State

**What exists (~70%):** VIX regime, IV rank, rolling vol, dealer GEX, bias detection, term structure.

**What's missing — the stuff that actually matters intraday:**

### 1. Realized vol vs implied vol spread (the edge)

The GARCH model computes forward vol estimates, and `edge.py` computes the spread. But it's not used as the *primary* entry signal. It should be. If IV is 25% and the GARCH estimate of realized vol over the next 5 days is 18%, that's a 7-point edge on a credit strategy. If the spread is <2 points, there's no trade.

### 2. Intraday vol regime shifts

VIX moves 2-3 points in a session. Regime detection currently runs once. Need a lightweight state machine:

| State | VIX | Intraday Range | Strategies |
|---|---|---|---|
| QUIET | < 15 | < 0.5% | Iron condors, butterflies |
| NORMAL | 15-22 | 0.5-1.2% | Credit spreads, iron condors |
| ELEVATED | 22-30 | 1.2-2% | Credit spreads, debit spreads |
| CRISIS | > 30 or gap > 2% | > 2% | Debit spreads only |

### 3. Vol surface skew (not just ATM IV)

Currently everything is priced with a single IV. Real edge comes from skew:

- **25-delta put IV vs ATM IV** (put skew)
- **Call skew** — usually flat, but inverts in squeezes
- **Skew term structure:** is near-term skew steeper than far-term? If yes, short near-term puts are overpriced -> credit spread edge

### 4. Microstructure signals for timing

- **Bid-ask spread as % of mid** — widening = uncertainty, don't enter
- **OI changes** (not just levels) — big OI increases at a strike = new positioning
- **Volume/OI ratio > 1** at a strike = someone is actively opening/closing

### Concrete addition: MarketState

```python
# src/market_state.py
@dataclass
class MarketState:
    regime: str                  # from detector.py
    iv_rv_spread: float          # IV - GARCH forward RV estimate
    iv_rv_edge_pct: float        # spread / IV * 100
    skew_25d: float              # 25-delta put IV - ATM IV
    skew_zscore: float           # current skew vs 20-day mean
    intraday_range_pct: float    # today's high-low / open
    bid_ask_quality: float       # avg bid-ask / mid across near-term chain
    dealer_regime: str           # from GEX
    gamma_flip_distance: float   # (spot - gamma_flip) / spot * 100
    bias: str                    # from bias_detector

    def has_edge(self, strategy: str) -> bool:
        """Does the current state present a tradeable edge?"""
        if strategy in CREDIT_STRATEGIES:
            return self.iv_rv_spread > 2.0 and self.bid_ask_quality < 0.05
        else:  # debit
            return self.iv_rv_spread < -2.0 and self.bid_ask_quality < 0.05
```

---

## L2: Trade Generation

**Current flow:** regime -> strategy_mapper -> pricer. Fine for screening, not for trading.

### Signal confluence scoring

Not a checklist — a weighted probability estimate:

```
Entry score = w1 * edge_signal      # IV-RV spread (this IS the edge)
            + w2 * regime_signal    # right vol environment
            + w3 * dealer_signal    # GEX confirms strategy type
            + w4 * bias_signal      # direction aligns
            + w5 * skew_signal      # skew supports the structure
            + w6 * timing_signal    # intraday timing
```

Current weights (20/20/20/15/10/10/5) are a guess. **Backtesting should set these weights.** Run regressions:

```
trade_pnl ~ edge_at_entry + regime_at_entry + dealer_at_entry + bias_at_entry + skew_at_entry
```

The coefficients *are* the weights. Don't guess. Measure.

### Timing within the day

The single biggest edge in short-term options:

- **Sell premium at 10:00-10:30 AM ET** — IV spikes at open as market makers widen spreads. By 10 AM, spreads tighten and IV is still elevated from overnight uncertainty. Best credit entry.
- **Buy premium at 3:30-3:45 PM ET** — less theta bleed overnight.
- **Market-on-close flows** create predictable last-30-min moves. Gamma exposure peaks here.

```python
# src/timing.py
def optimal_entry_window(strategy: str, market_state: MarketState) -> tuple[time, time]:
    if strategy in CREDIT_STRATEGIES:
        if market_state.intraday_range_pct > 1.5:
            return (time(10, 30), time(11, 30))  # wait for vol crush after spike
        return (time(10, 0), time(11, 0))  # standard premium selling window
    else:  # debit
        return (time(15, 0), time(15, 45))  # buy late, minimize overnight theta
```

### Strike selection — use the vol surface

Current `strategy_pricer.py` uses ATM +/- width. Wrong for credit strategies. The right approach:

- **Short strikes:** target a specific delta (entry_delta=0.20). But compute delta from the actual IV *at that strike*, not ATM IV. Skew means the 20-delta put is further OTM than the 20-delta call.
- **GEX-informed adjustment:** if call wall is at 600 and selling call spreads on SPY at 595, the call wall acts as resistance — the short call is likely to stay OTM. Move the short strike *to* the wall.
- **Max pain anchor:** butterflies centered at max pain, not ATM. (Already implemented.)

---

## L3: Execution & Sizing

This is where most retail options systems fail. Currently no position sizing, no execution logic, no fill modeling.

### Position sizing — Kelly criterion

```python
def kelly_size(win_rate: float, avg_win: float, avg_loss: float,
               max_risk_pct: float = 0.02) -> float:
    """Kelly fraction capped at max portfolio risk per trade."""
    if avg_loss == 0:
        return 0
    b = avg_win / abs(avg_loss)  # payoff ratio
    p = win_rate
    kelly = (p * b - (1 - p)) / b
    kelly = max(0, kelly)
    # Half-Kelly is standard practice (accounts for estimation error)
    half_kelly = kelly / 2
    return min(half_kelly, max_risk_pct)
```

### What the backtests say about sizing

| Strategy | Win Rate | Avg Win | Avg Loss | Kelly | Verdict |
|---|---|---|---|---|---|
| Short put spread | 75% | $68 | -$232 | **-0.11** | No edge. Don't trade as configured. |
| Short call spread | 64% | $78 | -$212 | **-0.05** | No edge. |
| Iron condor | 43% | $118 | -$171 | **-0.38** | Strongly negative. |
| Long call spread | 65% | $148 | -$172 | **+0.24** | Positive edge. Half-Kelly = 12%. |
| Butterfly (hold) | 46% | $520 | -$271 | **+0.26** | Positive edge. Half-Kelly = 13%. |

**Negative Kelly = no edge.** The raw credit strategies as currently configured don't have positive expectancy. Only long call spreads and butterflies (hold-to-expiry) survive.

### Execution — spread cost matters enormously at short DTE

A $5-wide SPY credit spread at 7 DTE might have a mid of $1.20. Natural fill is $1.15 (give up $0.05 crossing the spread). That's 4% of premium — huge when average edge is 5-10%.

```python
@dataclass
class ExecutionModel:
    fill_assumption: str = "mid_minus_1tick"  # conservative
    tick_size: float = 0.01  # penny increments for SPY
    slippage_pct: float = 0.03  # 3% of premium
    max_spread_pct: float = 0.10  # don't enter if bid-ask > 10% of mid

    def adjusted_entry(self, mid: float, is_credit: bool) -> float:
        slip = mid * self.slippage_pct
        if is_credit:
            return mid - slip  # collect less
        else:
            return mid + slip  # pay more
```

**The backtests don't model this.** `local_backtest.py` uses BS mid prices with zero slippage. Every backtest result is optimistic. Add a slippage parameter.

---

## L4: Portfolio Engine

The difference between a screener and a trading system.

### Concurrent position management

```python
@dataclass
class Portfolio:
    max_positions: int = 5
    max_per_symbol: int = 2
    max_delta: float = 50.0    # absolute portfolio delta
    max_gamma: float = 20.0    # absolute portfolio gamma
    max_theta: float = -100.0  # min daily theta
    max_vega: float = 200.0    # max vega exposure
    max_risk: float = 5000.0   # max capital at risk across all positions

    positions: List[Position] = field(default_factory=list)

    def can_add(self, candidate: Trade) -> tuple[bool, str]:
        """Check if adding this trade violates any portfolio constraint."""
        if len(self.positions) >= self.max_positions:
            return False, "max positions reached"

        symbol_count = sum(1 for p in self.positions if p.symbol == candidate.symbol)
        if symbol_count >= self.max_per_symbol:
            return False, f"max positions for {candidate.symbol}"

        new_delta = self.net_delta + candidate.delta
        if abs(new_delta) > self.max_delta:
            return False, f"delta would be {new_delta:.0f}"

        new_risk = self.total_risk + candidate.max_loss
        if new_risk > self.max_risk:
            return False, f"total risk would be ${new_risk:.0f}"

        return True, "ok"
```

### Correlation-aware risk

3 credit spreads on SPY, QQQ, and IWM are not 3 independent positions. A broad selloff hits all three.

```python
def correlated_risk(positions: List[Position]) -> float:
    """Worst-case loss accounting for correlation."""
    individual_risks = [p.max_loss for p in positions]
    corr = 0.7  # SPY/QQQ/IWM average correlation
    var = sum(r**2 for r in individual_risks) + \
          2 * corr * sum(individual_risks[i] * individual_risks[j]
                         for i in range(len(individual_risks))
                         for j in range(i+1, len(individual_risks)))
    return var ** 0.5
```

### Dynamic hedge triggers

| Portfolio Delta | Action |
|---|---|
| > +30 | Buy put spread or sell call spread to reduce |
| < -30 | Buy call spread or sell put spread to reduce |
| Vega > 150 | Reduce long premium positions |
| Near max pain into expiry | Tighten stops on butterflies |

---

## What to Build — Priority Order

Based on the backtest results, here's what will actually move PnL:

### Priority 1: Fix the edge problem

The backtests show most strategies have **negative expectancy** as configured. Iron condors: Sharpe -2.03. Short call spreads: Sharpe -1.26. Only winners are long call spreads (Sharpe 1.59) and butterflies hold-to-expiry (Sharpe 1.20).

The regime filter helped iron condors (reduced trades from 76 to 16, concentrated on HIGH_IV entries). But 16 trades over 4 years isn't a system — it's occasional.

**Action items:**
1. Add IV-RV spread as primary entry gate (only trade when edge > 3%)
2. Add slippage modeling to backtests (3% of premium)
3. Re-run backtests with these filters and see which strategies survive

### Priority 2: Exit management

Hold-to-expiry vs 50% target showed butterflies perform *much* better with hold-to-expiry (Sharpe 1.20 vs 0.33). Credit strategies showed the opposite — 50% target is better.

**Per-strategy exit rules (not a global toggle):**

| Strategy | Profit Target | Stop Loss | Notes |
|---|---|---|---|
| Iron condor | 50% of credit | 2x credit | |
| Credit spread | 50% of credit | 2x credit | |
| Debit spread | Trail stop at 30% after 50% hit | 100% of debit | Let winners run |
| Butterfly | Hold to expiry | 75% of debit | Pin play — needs time |

### Priority 3: Position sizing

Use Kelly-derived sizing from backtest results. Allocate capital proportional to edge, not equally. **Don't trade strategies with negative Kelly.**

### Priority 4: Portfolio-level Greeks management

Track aggregate delta/gamma/vega/theta across positions. Set limits. Auto-hedge when breached.

### Priority 5: Intraday timing and execution

Time entries to optimal windows. Model slippage. Only enter when bid-ask quality meets threshold.

---

## The Uncomfortable Truth

Most strategies don't have positive expectancy in the backtest. That means either:

1. **The BS pricer underestimates short-term option pricing** — likely. BS assumes constant vol, but realized vol clusters. The GARCH model captures this but isn't used in the backtester.

2. **The entry logic isn't selective enough** — entering every N days regardless of conditions is not a system. The regime filter reduced iron condor trades by 80% and the remaining trades *still* had negative PnL, suggesting the problem is deeper than regime selection.

3. **The exit logic needs work** — fixed 50% / 200% targets don't adapt to the vol environment. In low vol, 50% might trigger too early (leaving money on the table). In high vol, 200% stop might trigger too late.

**The first thing to build:** a backtester that uses the GARCH vol estimate as the entry gate and the vol surface for pricing (not flat IV). That alone will reveal whether there's actually edge in selling premium at the strike/DTE combinations being targeted.

---

*Options Analytics Team — 2026-04*
