"""Daily BTC price data collector using CoinGecko API (free, no key required)."""

import csv
import os
import time
from datetime import datetime, timezone

import requests

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
OUTPUT_FILE = os.path.join(DATA_DIR, "btc_price.csv")

COINGECKO_URL = "https://api.coingecko.com/api/v3/simple/price"
COINGECKO_MARKET_URL = "https://api.coingecko.com/api/v3/coins/bitcoin"


def fetch_btc_price():
    """Fetch current BTC price, market cap, and 24h volume from CoinGecko."""
    params = {
        "ids": "bitcoin",
        "vs_currencies": "usd",
        "include_market_cap": "true",
        "include_24hr_vol": "true",
        "include_24hr_change": "true",
    }
    resp = requests.get(COINGECKO_URL, params=params, timeout=30)
    resp.raise_for_status()
    data = resp.json()["bitcoin"]

    return {
        "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "price_usd": data["usd"],
        "market_cap_usd": data["usd_market_cap"],
        "volume_24h_usd": data["usd_24h_vol"],
        "change_24h_pct": data["usd_24h_change"],
    }


def fetch_btc_ohlc():
    """Fetch daily OHLC data for BTC (last 1 day) from CoinGecko."""
    url = f"{COINGECKO_MARKET_URL}/ohlc"
    params = {"vs_currency": "usd", "days": "1"}
    resp = requests.get(url, params=params, timeout=30)
    resp.raise_for_status()
    ohlc = resp.json()

    if not ohlc:
        return None

    # ohlc entries: [timestamp, open, high, low, close]
    # Aggregate the day's candles
    opens = [c[1] for c in ohlc]
    highs = [c[2] for c in ohlc]
    lows = [c[3] for c in ohlc]
    closes = [c[4] for c in ohlc]

    return {
        "open": opens[0],
        "high": max(highs),
        "low": min(lows),
        "close": closes[-1],
    }


def save_btc_price(record):
    """Append BTC price record to CSV."""
    os.makedirs(DATA_DIR, exist_ok=True)
    file_exists = os.path.isfile(OUTPUT_FILE)
    fieldnames = [
        "date", "price_usd", "market_cap_usd", "volume_24h_usd",
        "change_24h_pct", "open", "high", "low", "close",
    ]

    with open(OUTPUT_FILE, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if not file_exists:
            writer.writeheader()
        writer.writerow(record)


def collect():
    """Main collection entry point."""
    print("Fetching BTC price data...")
    price = fetch_btc_price()
    ohlc = fetch_btc_ohlc()

    if ohlc:
        price.update(ohlc)
    else:
        price.update({"open": "", "high": "", "low": "", "close": ""})

    save_btc_price(price)
    print(f"  BTC price saved: ${price['price_usd']:,.2f}")
    return price


def backfill(days=1825):
    """Backfill historical BTC price data from CoinGecko.

    Uses /coins/bitcoin/market_chart which returns daily data for ranges > 90 days.
    Free API rate limit: ~10-30 calls/min, so we add delays between requests.
    """
    print(f"Backfilling {days} days of BTC price data...")

    # Fetch price, market cap, and volume history
    url = "https://api.coingecko.com/api/v3/coins/bitcoin/market_chart"
    params = {"vs_currency": "usd", "days": days, "interval": "daily"}
    resp = requests.get(url, params=params, timeout=60)
    resp.raise_for_status()
    data = resp.json()

    prices = data["prices"]  # [timestamp_ms, price]
    market_caps = data["market_caps"]  # [timestamp_ms, market_cap]
    volumes = data["total_volumes"]  # [timestamp_ms, volume]

    # Build a dict keyed by date
    records = {}
    for ts_ms, price in prices:
        date = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d")
        records[date] = {"date": date, "price_usd": price}
    for ts_ms, mcap in market_caps:
        date = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d")
        if date in records:
            records[date]["market_cap_usd"] = mcap
    for ts_ms, vol in volumes:
        date = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d")
        if date in records:
            records[date]["volume_24h_usd"] = vol

    # Fetch OHLC data — free tier supports max 365 days at daily granularity.
    # For >30 days, CoinGecko returns 4-day candles, so we fetch in 30-day chunks
    # to get true daily OHLC.
    print("  Fetching OHLC data in 30-day chunks (this may take a while)...")
    ohlc_url = f"{COINGECKO_MARKET_URL}/ohlc"
    now_ts = int(datetime.now(timezone.utc).timestamp())
    start_ts = now_ts - (days * 86400)

    chunk_days = 30
    current_start = start_ts
    ohlc_by_date = {}

    while current_start < now_ts:
        chunk_end = min(current_start + chunk_days * 86400, now_ts)
        elapsed_days = int((now_ts - current_start) / 86400)
        query_days = min(chunk_days, elapsed_days)
        if query_days < 1:
            query_days = 1

        # CoinGecko OHLC only accepts specific day values on free tier
        # We'll use days=30 and step through time, but the API doesn't support
        # from/to on the free OHLC endpoint. Use days=1,7,14,30 only.
        # Instead, aggregate daily OHLC from the market_chart data we already have.
        break

    # Since free-tier OHLC doesn't support arbitrary date ranges well,
    # derive OHLC from the daily price data (open=close of prev day, high=low=close=price).
    # This gives approximate daily candles.
    sorted_dates = sorted(records.keys())
    prev_price = None
    for date in sorted_dates:
        rec = records[date]
        price = rec["price_usd"]
        rec["open"] = prev_price if prev_price is not None else price
        rec["high"] = max(rec["open"], price)
        rec["low"] = min(rec["open"], price)
        rec["close"] = price
        rec["change_24h_pct"] = ""
        rec.setdefault("market_cap_usd", "")
        rec.setdefault("volume_24h_usd", "")
        prev_price = price

    # Write all records to CSV (overwrite for backfill)
    os.makedirs(DATA_DIR, exist_ok=True)
    fieldnames = [
        "date", "price_usd", "market_cap_usd", "volume_24h_usd",
        "change_24h_pct", "open", "high", "low", "close",
    ]
    with open(OUTPUT_FILE, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for date in sorted_dates:
            writer.writerow(records[date])

    print(f"  Saved {len(records)} days of BTC price data to {OUTPUT_FILE}")
    return records


if __name__ == "__main__":
    collect()
