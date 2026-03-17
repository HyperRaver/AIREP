"""Daily Google Trends collector for Bitcoin-related search terms."""

import csv
import os
from datetime import datetime, timezone

from pytrends.request import TrendReq

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
OUTPUT_FILE = os.path.join(DATA_DIR, "google_trends.csv")

KEYWORDS = [
    "Bitcoin",
    "BTC",
    "Bitcoin price",
    "buy Bitcoin",
    "crypto crash",
]


def fetch_google_trends():
    """Fetch Google Trends interest data for Bitcoin-related keywords.

    Uses the last 7 days of data and returns the most recent day's values.
    Interest is on a 0-100 scale relative to peak popularity in the timeframe.
    """
    pytrends = TrendReq(hl="en-US", tz=360)
    pytrends.build_payload(KEYWORDS, cat=0, timeframe="now 7-d", geo="", gprop="")

    df = pytrends.interest_over_time()

    if df.empty:
        return {kw: None for kw in KEYWORDS}

    # Get the most recent data point
    latest = df.iloc[-1]
    return {kw: int(latest[kw]) for kw in KEYWORDS}


def save_trends(record):
    """Append Google Trends record to CSV."""
    os.makedirs(DATA_DIR, exist_ok=True)
    file_exists = os.path.isfile(OUTPUT_FILE)
    fieldnames = ["date"] + [f"trend_{kw.lower().replace(' ', '_')}" for kw in KEYWORDS]

    with open(OUTPUT_FILE, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if not file_exists:
            writer.writeheader()
        writer.writerow(record)


def collect():
    """Main collection entry point."""
    print("Fetching Google Trends data...")
    trends = fetch_google_trends()

    record = {"date": datetime.now(timezone.utc).strftime("%Y-%m-%d")}
    for kw in KEYWORDS:
        col = f"trend_{kw.lower().replace(' ', '_')}"
        record[col] = trends.get(kw, "")

    save_trends(record)
    for kw in KEYWORDS:
        val = trends.get(kw, "N/A")
        print(f"  {kw}: {val}")
    return record


if __name__ == "__main__":
    collect()
