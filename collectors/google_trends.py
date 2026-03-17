"""Daily Google Trends collector for Bitcoin-related search terms."""

import csv
import os
import time
from datetime import datetime, timedelta, timezone

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


def backfill(days=1825):
    """Backfill historical Google Trends data.

    Google Trends returns daily data only for date ranges <= 270 days.
    For longer periods, we fetch in ~250-day chunks and normalize overlap points
    to stitch the data together on a consistent scale.
    """
    print(f"Backfilling {days} days of Google Trends data...")

    pytrends = TrendReq(hl="en-US", tz=360)
    end_date = datetime.now(timezone.utc).date()
    start_date = end_date - timedelta(days=days)

    chunk_size = 250  # days per chunk (< 270 for daily granularity)
    all_data = {}  # date_str -> {keyword: value}

    # Track scaling factor to normalize across chunks
    scale_factor = 1.0
    prev_chunk_last_week = None  # overlap data for normalization

    current_start = start_date
    chunk_num = 0

    while current_start < end_date:
        current_end = min(current_start + timedelta(days=chunk_size), end_date)
        timeframe = f"{current_start.strftime('%Y-%m-%d')} {current_end.strftime('%Y-%m-%d')}"

        chunk_num += 1
        print(f"  Chunk {chunk_num}: {timeframe}")

        try:
            pytrends.build_payload(KEYWORDS, cat=0, timeframe=timeframe, geo="", gprop="")
            df = pytrends.interest_over_time()
        except Exception as e:
            print(f"    WARNING: Failed to fetch chunk: {e}")
            current_start = current_end - timedelta(days=7)  # overlap for next chunk
            time.sleep(60)  # back off on error
            continue

        if df.empty:
            print("    WARNING: Empty response, skipping chunk")
            current_start = current_end - timedelta(days=7)
            time.sleep(30)
            continue

        # Normalize this chunk relative to previous chunks using overlap period
        if prev_chunk_last_week is not None and len(df) > 7:
            overlap_dates = sorted(set(prev_chunk_last_week.keys()) & set(
                d.strftime("%Y-%m-%d") for d in df.index
            ))
            if overlap_dates:
                # Compute average ratio across overlap for the first keyword
                ratios = []
                for od in overlap_dates:
                    old_val = prev_chunk_last_week[od].get(KEYWORDS[0], 0)
                    new_row = df.loc[df.index.strftime("%Y-%m-%d") == od]
                    if not new_row.empty:
                        new_val = int(new_row.iloc[0][KEYWORDS[0]])
                        if new_val > 0:
                            ratios.append(old_val / new_val)
                if ratios:
                    scale_factor = sum(ratios) / len(ratios)

        # Save overlap data for next chunk (last 7 days of this chunk)
        prev_chunk_last_week = {}
        for i in range(max(0, len(df) - 7), len(df)):
            row = df.iloc[i]
            date_str = row.name.strftime("%Y-%m-%d")
            prev_chunk_last_week[date_str] = {
                kw: int(row[kw]) * scale_factor for kw in KEYWORDS
            }

        # Store all data points from this chunk
        for i in range(len(df)):
            row = df.iloc[i]
            date_str = row.name.strftime("%Y-%m-%d")
            if date_str not in all_data:  # don't overwrite earlier normalized data
                all_data[date_str] = {
                    kw: round(int(row[kw]) * scale_factor, 2) for kw in KEYWORDS
                }

        current_start = current_end - timedelta(days=7)  # 7-day overlap
        time.sleep(15)  # rate limit: be gentle with Google

    # Write to CSV
    os.makedirs(DATA_DIR, exist_ok=True)
    fieldnames = ["date"] + [f"trend_{kw.lower().replace(' ', '_')}" for kw in KEYWORDS]
    sorted_dates = sorted(all_data.keys())

    with open(OUTPUT_FILE, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for date_str in sorted_dates:
            record = {"date": date_str}
            for kw in KEYWORDS:
                col = f"trend_{kw.lower().replace(' ', '_')}"
                record[col] = all_data[date_str].get(kw, "")
            writer.writerow(record)

    print(f"  Saved {len(all_data)} days of Google Trends data to {OUTPUT_FILE}")
    return all_data


if __name__ == "__main__":
    collect()
