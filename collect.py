#!/usr/bin/env python3
"""Bitcoin daily data collection orchestrator.

Collects:
- BTC price (OHLCV) from CoinGecko
- Fear & Greed Index from Alternative.me + market sentiment (Sentix proxy)
- Google Trends for Bitcoin-related keywords

Usage:
    python collect.py              # Run all collectors once
    python collect.py --schedule   # Run daily at 00:05 UTC
    python collect.py --price      # Run only BTC price collector
    python collect.py --sentiment  # Run only Fear & Greed collector
    python collect.py --trends     # Run only Google Trends collector
"""

import argparse
import sys
import time
from datetime import datetime, timezone

import schedule

from collectors import btc_price, fear_greed, google_trends


def run_all():
    """Run all collectors."""
    print(f"\n{'='*60}")
    print(f"Bitcoin Data Collection - {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    print(f"{'='*60}\n")

    results = {}
    errors = []

    for name, collector in [
        ("BTC Price", btc_price),
        ("Fear & Greed", fear_greed),
        ("Google Trends", google_trends),
    ]:
        try:
            results[name] = collector.collect()
        except Exception as e:
            errors.append((name, str(e)))
            print(f"  ERROR [{name}]: {e}")

    print(f"\n{'='*60}")
    print(f"Done. {len(results)} succeeded, {len(errors)} failed.")
    if errors:
        for name, err in errors:
            print(f"  FAILED: {name} - {err}")
    print(f"{'='*60}\n")

    return len(errors) == 0


def main():
    parser = argparse.ArgumentParser(description="Bitcoin daily data collector")
    parser.add_argument("--schedule", action="store_true", help="Run on daily schedule (00:05 UTC)")
    parser.add_argument("--price", action="store_true", help="Collect BTC price only")
    parser.add_argument("--sentiment", action="store_true", help="Collect Fear & Greed only")
    parser.add_argument("--trends", action="store_true", help="Collect Google Trends only")
    args = parser.parse_args()

    # Run specific collector if flagged
    if args.price:
        btc_price.collect()
        return
    if args.sentiment:
        fear_greed.collect()
        return
    if args.trends:
        google_trends.collect()
        return

    if args.schedule:
        print("Scheduling daily collection at 00:05 UTC...")
        schedule.every().day.at("00:05").do(run_all)
        run_all()  # Also run immediately on start
        while True:
            schedule.run_pending()
            time.sleep(60)
    else:
        success = run_all()
        sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
