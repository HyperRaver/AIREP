"""Daily Bitcoin Fear & Greed index collector.

Sources:
- Alternative.me Crypto Fear & Greed Index (primary, free API)
- Bloomberg-style sentiment via proxy (Alternative.me aggregates Bloomberg-like signals)
- Sentix-style confidence via CoinGecko market sentiment
"""

import csv
import os
from datetime import datetime, timezone

import requests

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
OUTPUT_FILE = os.path.join(DATA_DIR, "fear_greed.csv")

FEAR_GREED_URL = "https://api.alternative.me/fng/"
COINGECKO_GLOBAL_URL = "https://api.coingecko.com/api/v3/global"


def fetch_fear_greed_index():
    """Fetch the Crypto Fear & Greed Index from Alternative.me.

    This index aggregates signals similar to Bloomberg and Sentix:
    - Volatility (25%)
    - Market momentum/volume (25%)
    - Social media sentiment (15%)
    - Surveys (15%) — comparable to Sentix investor confidence
    - Bitcoin dominance (10%)
    - Google Trends (10%)
    """
    params = {"limit": 1, "format": "json"}
    resp = requests.get(FEAR_GREED_URL, params=params, timeout=30)
    resp.raise_for_status()
    data = resp.json()["data"][0]

    return {
        "value": int(data["value"]),
        "classification": data["value_classification"],
        "timestamp": data["timestamp"],
    }


def fetch_market_sentiment():
    """Fetch market-level sentiment data from CoinGecko (Sentix-style proxy).

    Returns BTC dominance and market direction indicators that mirror
    institutional sentiment surveys like Sentix.
    """
    resp = requests.get(COINGECKO_GLOBAL_URL, timeout=30)
    resp.raise_for_status()
    data = resp.json()["data"]

    market_cap_change = data.get("market_cap_change_percentage_24h_usd", 0)
    btc_dominance = data.get("market_cap_percentage", {}).get("btc", 0)

    # Derive a simple sentiment score from market momentum (-100 to 100 scale)
    # Positive market cap change = bullish sentiment, negative = bearish
    sentix_proxy = max(-100, min(100, market_cap_change * 10))

    return {
        "btc_dominance_pct": round(btc_dominance, 2),
        "market_cap_change_24h_pct": round(market_cap_change, 2),
        "sentix_proxy_score": round(sentix_proxy, 2),
    }


def save_fear_greed(record):
    """Append Fear & Greed record to CSV."""
    os.makedirs(DATA_DIR, exist_ok=True)
    file_exists = os.path.isfile(OUTPUT_FILE)
    fieldnames = [
        "date", "fear_greed_value", "fear_greed_class",
        "btc_dominance_pct", "market_cap_change_24h_pct", "sentix_proxy_score",
    ]

    with open(OUTPUT_FILE, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if not file_exists:
            writer.writeheader()
        writer.writerow(record)


def collect():
    """Main collection entry point."""
    print("Fetching Fear & Greed data...")
    fg = fetch_fear_greed_index()

    print("Fetching market sentiment (Sentix proxy)...")
    sentiment = fetch_market_sentiment()

    record = {
        "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "fear_greed_value": fg["value"],
        "fear_greed_class": fg["classification"],
        "btc_dominance_pct": sentiment["btc_dominance_pct"],
        "market_cap_change_24h_pct": sentiment["market_cap_change_24h_pct"],
        "sentix_proxy_score": sentiment["sentix_proxy_score"],
    }

    save_fear_greed(record)
    print(f"  Fear & Greed: {fg['value']} ({fg['classification']})")
    print(f"  Sentix proxy: {sentiment['sentix_proxy_score']}")
    return record


if __name__ == "__main__":
    collect()
