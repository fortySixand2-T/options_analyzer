"""Terminal output formatter for the options opportunity scanner."""
from typing import Any, Dict, List

STRATEGY_LABELS = {
    "long_call":        "Long Call",
    "long_put":         "Long Put",
    "bull_call_spread": "Bull Call Spread",
    "bear_put_spread":  "Bear Put Spread",
    "iron_condor":      "Iron Condor",
    "short_strangle":   "Short Strangle",
    "long_straddle":    "Long Straddle",
    "long_strangle":    "Long Strangle",
}

BIAS_LABELS = {
    "bullish":         "BULLISH",
    "bearish":         "BEARISH",
    "neutral_high_iv": "NEUTRAL  (High IV — favour selling premium)",
    "neutral_low_iv":  "NEUTRAL  (Low IV  — favour buying premium)",
}

OUTLOOK_LABELS = {
    "short":  "SHORT  (7–21 DTE)",
    "medium": "MEDIUM (30–60 DTE)",
    "long":   "LONG   (61–120 DTE)",
}

W = 68


def _fmt_legs(legs: List[Dict]) -> List[str]:
    """Render the legs table and net premium line."""
    lines = ["  │  ── LEGS ──────────────────────────────────────────────────"]

    for leg in legs:
        action  = leg["action"].upper().ljust(4)
        otype   = leg["option_type"].upper().ljust(4)
        strike  = f"${leg['strike']:<8.2f}"
        iv_str  = f"IV {leg['iv']}%".ljust(10)
        price   = f"${leg['price']:.2f}".ljust(8)
        delta   = f"Δ {leg['delta']:+.3f}"
        theta   = f"Θ ${leg['theta']:+.3f}/day"
        lines.append(f"  │    {action}  {otype}  {strike}  {iv_str}  {price}  {delta}  {theta}")

    # Net credit / debit
    net = sum(
        (leg["price"] if leg["action"] == "sell" else -leg["price"])
        for leg in legs
    )
    if net >= 0:
        lines.append(f"  │    {'─'*56}")
        lines.append(f"  │    Net credit received : ${net:.2f}")
    else:
        lines.append(f"  │    {'─'*56}")
        lines.append(f"  │    Net debit paid      : ${abs(net):.2f}")

    return lines


def _fmt_opp(opp: Dict[str, Any]) -> str:
    outlook   = OUTLOOK_LABELS.get(opp["outlook"], opp["outlook"].upper())
    strategy  = STRATEGY_LABELS.get(opp["strategy"], opp["strategy"])
    bias      = BIAS_LABELS.get(opp["bias"], opp["bias"])
    is_credit = opp.get("is_credit", False)

    iv_note = (
        "IV rich vs HV — premium elevated"  if opp["iv_vs_hv"] > 10
        else "IV cheap vs HV — premium depressed" if opp["iv_vs_hv"] < -10
        else "IV roughly inline with HV"
    )

    # ── Trade level labels differ for credit vs debit ─────────────────────
    if is_credit:
        entry_label  = "Premium received"
        exit_label   = "Take-profit (buy back at)"
        stop_label   = "Stop (buy back at)"
        exit_detail  = f"${opp['exit_target']:.2f}  (50% of credit)"
        stop_detail  = f"${opp['option_stop']:.2f}  (2× credit — full loss)"
    else:
        entry_label  = "Premium paid     "
        exit_label   = "Target exit      "
        stop_label   = "Option stop      "
        tgt = f"  ← underlying ${opp['target_underlying']:.2f}" if opp.get("target_underlying") else ""
        exit_detail  = f"${opp['exit_target']:.2f}  ({opp['exit_pct']:+.1f}%){tgt}"
        stop_detail  = f"${opp['option_stop']:.2f}  (–{int(round(OPTION_STOP_PCT * 100))}% of entry)"

    # ── Max profit / max loss ─────────────────────────────────────────────
    mp = opp.get("max_profit")
    ml = opp.get("max_loss")
    mp_str = f"${mp:.2f}" if mp is not None else "Unlimited"
    ml_str = f"${ml:.2f}" if ml is not None else "Unlimited"

    # ── American price (puts only) ────────────────────────────────────────
    am_line = ""
    if opp.get("american_price") and any(
        l["option_type"] == "put" for l in opp.get("legs", [])
    ):
        am_line = (
            f"\n  │  American price : ${opp['american_price']:.2f}  "
            f"(early-ex premium: +${opp['early_exercise_premium']:.2f})"
        )

    lines = [
        f"  ┌─ {outlook}  ·  Exp {opp['expiry']}  ({opp['dte']} DTE) {'─'*max(0,W-50)}",
        f"  │  Strategy  : {strategy}",
        f"  │  Bias      : {bias}  (score {opp['bias_score']:+d})",
        f"  │  Volatility: HV {opp['hist_vol']}%  ·  IV/HV spread {opp['iv_vs_hv']:+.1f}%  — {iv_note}",
        f"  │",
    ]

    # Legs table
    lines += _fmt_legs(opp.get("legs", []))

    lines += [
        f"  │",
        f"  │  ── TRADE LEVELS ──────────────────────────────────────────",
        f"  │  {entry_label} : ${opp['entry']:.2f}",
        f"  │  {exit_label} : {exit_detail}",
        f"  │  {stop_label} : {stop_detail}",
        f"  │  Underlying stop : {'close below' if not is_credit else 'break of'} ${opp['underlying_stop']:.2f}",
        f"  │  Max profit      : {mp_str}",
        f"  │  Max loss        : {ml_str}",
        f"  │",
        f"  │  ── NET GREEKS ─────────────────────────────────────────────",
        f"  │  Δ {opp['delta']:+.3f}   Γ {opp['gamma']:+.4f}   "
        f"Θ ${opp['theta']:+.3f}/day   ν {opp['vega']:+.3f}",
        f"  │  ATR ${opp['atr']:.2f}  ({opp['atr_pct']:.1f}% of price)",
        f"  │",
        f"  │  ── MONTE CARLO — primary leg (jump-diffusion, 5k paths) ───",
        f"  │  P(profit) {opp['prob_profit']:.1f}%   Expected payoff ${opp['expected_payoff']:.2f}",
        am_line,
        f"  └{'─'*W}",
    ]
    return "\n".join(l for l in lines if l != "")


# Expose stop pct for formatter use
OPTION_STOP_PCT = 0.50


def _fmt_knowledge(text: str) -> str:
    """Render the knowledge base strategy section inside a ticker block."""
    lines = [
        f"  ┌─ KNOWLEDGE BASE STRATEGIES {'─'*39}",
    ]
    for line in text.splitlines():
        lines.append(f"  │  {line}")
    lines.append(f"  └{'─'*W}")
    return "\n".join(lines)


def format_ticker_block(result: Dict[str, Any]) -> str:
    lines = [
        "",
        "╔" + "═" * W + "╗",
        f"║  {result['ticker']}  ·  {result.get('name','')}  ·  {result.get('sector','')}",
        f"║  Price: ${result['current_price']:.2f}",
    ]

    if "signals" in result:
        sr = result["signals"]["support_resistance"]
        lines.append(
            f"║  S/R:   Resistance ${sr['nearest_resistance']:.2f}   "
            f"Support ${sr['nearest_support']:.2f}"
        )

    lines.append("╚" + "═" * W + "╝")

    if "error" in result:
        lines.append(f"  ERROR: {result['error']}")
        return "\n".join(lines)

    if not result["opportunities"]:
        lines.append("  No opportunities generated for this ticker.")
        return "\n".join(lines)

    for opp in result["opportunities"]:
        lines.append(_fmt_opp(opp))

    kb = result.get("knowledge_strategies")
    if kb:
        lines.append(_fmt_knowledge(kb))

    return "\n".join(lines)


def print_scan_results(results: List[Dict[str, Any]], ai_narrative: str = "") -> None:
    border = "█" * (W + 4)
    print(f"\n{border}")
    print("  OPTIONS OPPORTUNITY SCANNER")
    print(border)

    for result in results:
        print(format_ticker_block(result))

    if ai_narrative:
        print(f"\n{'═'*(W+4)}")
        print("  AI SYNTHESIS  (Claude)")
        print(f"{'═'*(W+4)}")
        print()
        for line in ai_narrative.splitlines():
            print(f"  {line}")
        print(f"\n{border}\n")
