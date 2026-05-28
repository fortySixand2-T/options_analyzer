#!/usr/bin/env python3
"""
CLI runner for the sentiment backtest.

Usage:
    python scripts/run_sentiment_backtest.py --csv data/headlines.csv --ticker SPY
    python scripts/run_sentiment_backtest.py --csv data/headlines.csv --ticker QQQ --primary 6h --velocity 1h

Decision gate (from DESIGN.md):
    hit_rate > 52% AND Sharpe > 0.3 AND correlation > 0.05 → proceed to Phase 5
"""

import argparse
import json
import logging
import os
import sys
from dataclasses import asdict

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.sentiment.backtest import run_backtest


def main():
    parser = argparse.ArgumentParser(description="Sentiment backtest runner")
    parser.add_argument("--csv", required=True, help="Path to headlines CSV")
    parser.add_argument("--ticker", default="MACRO", help="Headline ticker filter (default: MACRO)")
    parser.add_argument("--price-ticker", default="SPY", help="Price ticker for returns (default: SPY)")
    parser.add_argument("--primary", default="24h", help="Primary sentiment window (default: 24h)")
    parser.add_argument("--velocity", default="6h", help="Velocity window (default: 6h)")
    parser.add_argument("--start", default=None, help="Start date YYYY-MM-DD")
    parser.add_argument("--end", default=None, help="End date YYYY-MM-DD")
    parser.add_argument("--output", default="data/sentiment_backtest_results.json", help="Output JSON path")
    parser.add_argument("--scorer", default="auto", choices=["auto", "finbert", "keyword"],
                        help="Scorer: auto (try FinBERT, fallback keyword), finbert, keyword")
    parser.add_argument("--target", default="direction", choices=["direction", "volatility"],
                        help="Prediction target: direction (next-day return sign) or volatility (next-day realized vol)")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    prefer_finbert = args.scorer != "keyword"
    if args.scorer == "keyword":
        prefer_finbert = False

    result = run_backtest(
        csv_path=args.csv,
        ticker=args.ticker,
        price_ticker=args.price_ticker,
        start_date=args.start,
        end_date=args.end,
        primary_window=args.primary,
        velocity_window=args.velocity,
        prefer_finbert=prefer_finbert,
        target=args.target,
    )

    print("\n" + "=" * 60)
    print(f"SENTIMENT BACKTEST RESULTS — {result.ticker} vs {args.price_ticker} [{args.target}]")
    print("=" * 60)
    print(f"Period:          {result.start_date} → {result.end_date}")
    print(f"Total days:      {result.total_days}")
    print(f"Signal days:     {result.signal_days}")

    if args.target == "volatility":
        print(f"\n--- Volatility prediction metrics ---")
        print(f"Sentiment|abs| → vol corr:  {result.vol_correlation:.4f}")
        print(f"Neg sentiment → vol corr:   {result.neg_vol_correlation:.4f}")
        print(f"High-sentiment avg vol:     {result.high_sent_avg_vol:.4%}")
        print(f"Low-sentiment avg vol:      {result.low_sent_avg_vol:.4%}")
        print(f"Vol predictive ratio:       {result.vol_predictive_ratio:.2f}x")

        print(f"\n--- Direction metrics (for reference) ---")

    print(f"Hit rate:        {result.hit_rate:.1%}")
    print(f"Avg return:      {result.avg_return:.4%}")
    print(f"Sharpe ratio:    {result.sharpe:.2f}")
    print(f"Max drawdown:    {result.max_drawdown:.2%}")
    print(f"Dir correlation: {result.correlation:.4f}")

    print("\n--- Per-label breakdown ---")
    for label, stats in sorted(result.label_stats.items()):
        vol_str = f"  avg_vol={stats.get('avg_vol', 0):.4%}" if args.target == "volatility" else ""
        print(f"  {label:20s}  n={stats['count']:3d}  "
              f"hit={stats['hit_rate']:.1%}  "
              f"avg_ret={stats['avg_return']:.4%}  "
              f"avg_score={stats['avg_score']:.3f}{vol_str}")

    # Decision gate
    if args.target == "volatility":
        print("\n--- Volatility decision gate ---")
        vol_gate_pass = (
            abs(result.vol_correlation) > 0.10
            and result.vol_predictive_ratio > 1.10
        )
        print(f"  |vol_corr| > 0.10:       {'PASS' if abs(result.vol_correlation) > 0.10 else 'FAIL'} ({result.vol_correlation:.4f})")
        print(f"  vol_ratio > 1.10x:       {'PASS' if result.vol_predictive_ratio > 1.10 else 'FAIL'} ({result.vol_predictive_ratio:.2f}x)")
        print(f"  OVERALL:                 {'✓ SENTIMENT PREDICTS VOLATILITY' if vol_gate_pass else '✗ No volatility edge'}")
    else:
        print("\n--- Direction decision gate ---")
        gate_pass = (
            result.hit_rate > 0.52
            and result.sharpe > 0.3
            and result.correlation > 0.05
        )
        print(f"  hit_rate > 52%:     {'PASS' if result.hit_rate > 0.52 else 'FAIL'} ({result.hit_rate:.1%})")
        print(f"  Sharpe > 0.3:       {'PASS' if result.sharpe > 0.3 else 'FAIL'} ({result.sharpe:.2f})")
        print(f"  correlation > 0.05: {'PASS' if result.correlation > 0.05 else 'FAIL'} ({result.correlation:.4f})")
        print(f"  OVERALL:            {'✓ PROCEED to Phase 5' if gate_pass else '✗ PARK — signal not validated'}")

    os.makedirs(os.path.dirname(args.output), exist_ok=True)
    output = asdict(result)
    with open(args.output, "w") as f:
        json.dump(output, f, indent=2, default=str)
    print(f"\nFull results saved to {args.output}")


if __name__ == "__main__":
    main()
