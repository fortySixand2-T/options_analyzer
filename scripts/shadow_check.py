#!/usr/bin/env python3
"""
Shadow paper trading CLI.

Usage:
    python scripts/shadow_check.py                         # Daily check: mark-to-market + exit rules
    python scripts/shadow_check.py --scan-and-log SPY,QQQ  # Scan tickers and log qualifying trades
    python scripts/shadow_check.py --stats                 # Show shadow trading statistics
    python scripts/shadow_check.py --list                  # List open trades
    python scripts/shadow_check.py --dry-run               # Check exits without persisting

Options Analytics Team — 2026-05
"""

import argparse
import json
import logging
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


def _resolve_entry_prices(ticker: str, tc, spot: float) -> list:
    """Resolve entry leg prices from chain snapshots or live data."""
    from data.shadow_pricer import lookup_leg_price, _live_fallback
    from scanner.providers.yfinance_provider import YFinanceProvider
    from trade_generator import DTE_RANGES
    from datetime import datetime, timedelta

    # Determine target expiry from DTE
    min_dte, max_dte = DTE_RANGES.get(tc.strategy, (3, 14))
    target_dte = tc.suggested_dte
    target_expiry = (datetime.now() + timedelta(days=target_dte)).strftime("%Y-%m-%d")

    # Fetch a fresh chain to get exact expiry and prices
    provider = YFinanceProvider(delay=0.5)
    chain = provider.get_chain(ticker, min_dte=0, max_dte=max_dte + 5)

    entry_legs = []
    for leg in tc.legs:
        mid = bid = ask = expiry = None

        # Find matching contract in chain (closest expiry to target)
        best_match = None
        best_dte_diff = 999
        for c in chain.contracts:
            if c.strike == leg["strike"] and c.option_type == leg["option_type"]:
                if c.mid and c.mid > 0:
                    try:
                        exp_dt = datetime.strptime(c.expiry, "%Y-%m-%d")
                        dte_diff = abs((exp_dt - datetime.now()).days - target_dte)
                        if dte_diff < best_dte_diff:
                            best_dte_diff = dte_diff
                            best_match = c
                    except ValueError:
                        continue

        if best_match:
            mid, bid, ask, expiry = best_match.mid, best_match.bid, best_match.ask, best_match.expiry

        entry_legs.append({
            "strike": leg["strike"],
            "expiry": tc.expiry or expiry,
            "option_type": leg["option_type"],
            "action": leg["action"],
            "mid": mid, "bid": bid, "ask": ask,
        })

    return entry_legs


def scan_and_log(tickers: list) -> dict:
    """Run the scanner for each ticker and log qualifying trades."""
    from market_state import build_market_state
    from trade_generator import generate_trades
    from data.shadow_store import log_shadow_trade

    results = {"scanned": 0, "candidates": 0, "logged": 0, "errors": []}

    for ticker in tickers:
        logger.info("Scanning %s for shadow trades...", ticker)
        results["scanned"] += 1

        try:
            state = build_market_state(ticker)
            candidates = generate_trades(state)

            for tc in candidates:
                results["candidates"] += 1

                entry_legs = _resolve_entry_prices(ticker, tc, state.spot)

                if all(lp.get("mid") for lp in entry_legs):
                    trade_id = log_shadow_trade(tc, entry_legs, state.spot)
                    if trade_id:
                        results["logged"] += 1
                        logger.info("  Logged: %s %s score=%.0f",
                                    tc.symbol, tc.strategy_label,
                                    tc.confluence_score)
                else:
                    missing = [lp["strike"] for lp in entry_legs if not lp.get("mid")]
                    logger.warning("  Skipped %s %s: missing prices for strikes %s",
                                   tc.symbol, tc.strategy_label, missing)

        except Exception as e:
            msg = f"{ticker}: {e}"
            logger.error("Scan failed for %s: %s", ticker, e)
            results["errors"].append(msg)

    return results


def main():
    parser = argparse.ArgumentParser(
        description="Shadow paper trading — log signals, track P&L",
    )
    parser.add_argument(
        "--scan-and-log", metavar="TICKERS",
        help="Scan tickers (comma-separated) and log qualifying trades",
    )
    parser.add_argument(
        "--stats", action="store_true",
        help="Show shadow trading statistics",
    )
    parser.add_argument(
        "--list", action="store_true",
        help="List open shadow trades",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Check exits without persisting changes",
    )

    args = parser.parse_args()

    # Stats mode
    if args.stats:
        from data.shadow_store import get_stats
        stats = get_stats()
        print(json.dumps(stats, indent=2))
        return

    # List mode
    if args.list:
        from data.shadow_store import get_open_trades
        trades = get_open_trades()
        if not trades:
            print("No open shadow trades.")
            return
        print(f"\n{'ID':>4} {'Symbol':>6} {'Strategy':<20} {'Entry':>8} "
              f"{'Score':>6} {'Regime':<12} {'Date':<12}")
        print("-" * 75)
        for t in trades:
            print(f"{t['id']:>4} {t['symbol']:>6} {t['strategy_label']:<20} "
                  f"{t['entry_net_price']:>8.4f} {t['confluence_score']:>6.1f} "
                  f"{t['regime'] or 'N/A':<12} {t['entry_date']:<12}")
        print(f"\nTotal: {len(trades)} open trades")
        return

    # Scan-and-log mode
    if args.scan_and_log:
        tickers = [t.strip().upper() for t in args.scan_and_log.split(",") if t.strip()]
        if not tickers:
            print("No tickers specified", file=sys.stderr)
            sys.exit(1)

        print(f"Scanning {len(tickers)} tickers for shadow trades...")
        result = scan_and_log(tickers)

        print(f"\n{'='*50}")
        print(f"Shadow Scan Summary")
        print(f"{'='*50}")
        print(f"  Scanned:    {result['scanned']} tickers")
        print(f"  Candidates: {result['candidates']} (score >= 60)")
        print(f"  Logged:     {result['logged']} new shadow trades")
        if result["errors"]:
            print(f"  Errors:")
            for e in result["errors"]:
                print(f"    - {e}")

    # Daily check mode (default, also runs after scan-and-log)
    from data.shadow_checker import run_daily_check
    print(f"\nRunning daily exit check (dry_run={args.dry_run})...")
    summary = run_daily_check(dry_run=args.dry_run)

    print(f"\n{'='*50}")
    print(f"Daily Check Summary — {summary['date']}")
    print(f"{'='*50}")
    print(f"  Trades checked: {summary['trades_checked']}")
    print(f"  Trades closed:  {summary['trades_closed']}")
    print(f"  Trades marked:  {summary['trades_marked']}")

    if summary["closures"]:
        print(f"\n  Closures:")
        for c in summary["closures"]:
            dr = " (DRY RUN)" if c.get("dry_run") else ""
            print(f"    #{c['trade_id']} {c['symbol']} {c['strategy']}: "
                  f"{c['reason']}, P&L=${c['pnl']:.2f}{dr}")

    if summary["errors"]:
        print(f"\n  Errors:")
        for e in summary["errors"]:
            print(f"    - {e}")


if __name__ == "__main__":
    main()
