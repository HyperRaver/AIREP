"""Daily BTC price data collector using CoinGecko API (free, no key required)."""

import csv
import os
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


if __name__ == "__main__":
    collect()
