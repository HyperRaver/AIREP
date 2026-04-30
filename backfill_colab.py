"""
Bitcoin 5-Year Historical Data Backfill — Run in Google Colab
=============================================================
1. Open Google Colab (colab.research.google.com)
2. Paste this entire script into a cell
3. Run the cell
4. Download the 3 CSVs from the file browser (left sidebar)

Or mount Google Drive and change OUTPUT_DIR to save there directly.
"""

import subprocess
subprocess.check_call(["pip", "install", "-q", "yfinance", "pytrends", "requests"])

import csv
import os
import time
from datetime import datetime, timedelta, timezone

import requests
import yfinance as yf

OUTPUT_DIR = "data"
os.makedirs(OUTPUT_DIR, exist_ok=True)

# ============================================================
# 1. BTC PRICE (Yahoo Finance — free, no API key)
# ============================================================
print("=" * 60)
print("1/3  Fetching BTC price data (5 years)...")
print("=" * 60)

btc = yf.Ticker("BTC-USD")
df = btc.history(period="5y", interval="1d")
print(f"  Got {len(df)} rows from Yahoo Finance")

# Write CSV
btc_file = os.path.join(OUTPUT_DIR, "btc_price.csv")
fieldnames = ["date", "price_usd", "market_cap_usd", "volume_24h_usd",
              "change_24h_pct", "open", "high", "low", "close"]

prev_close = None
records = {}
with open(btc_file, "w", newline="") as f:
    writer = csv.DictWriter(f, fieldnames=fieldnames)
    writer.writeheader()
    for idx, row in df.iterrows():
        date_str = idx.strftime("%Y-%m-%d")
        close = row["Close"]
        change_pct = round((close - prev_close) / prev_close * 100, 4) if prev_close else ""
        rec = {
            "date": date_str,
            "price_usd": round(close, 2),
            "market_cap_usd": "",
            "volume_24h_usd": round(row["Volume"], 2),
            "change_24h_pct": change_pct,
            "open": round(row["Open"], 2),
            "high": round(row["High"], 2),
            "low": round(row["Low"], 2),
            "close": round(close, 2),
        }
        writer.writerow(rec)
        records[date_str] = rec
        prev_close = close

print(f"  Saved {len(records)} days -> {btc_file}")

# ============================================================
# 2. FEAR & GREED INDEX (Alternative.me — free, no API key)
# ============================================================
print()
print("=" * 60)
print("2/3  Fetching Fear & Greed data (5 years)...")
print("=" * 60)

fg_url = "https://api.alternative.me/fng/"
resp = requests.get(fg_url, params={"limit": 1825, "format": "json"}, timeout=60)
resp.raise_for_status()
fg_data = resp.json()["data"]

fg_records = []
for entry in reversed(fg_data):  # API returns newest first
    ts = int(entry["timestamp"])
    date = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")
    fg_records.append({
        "date": date,
        "fear_greed_value": int(entry["value"]),
        "fear_greed_class": entry["value_classification"],
        "btc_dominance_pct": "",
        "market_cap_change_24h_pct": "",
        "sentix_proxy_score": "",
    })

fg_file = os.path.join(OUTPUT_DIR, "fear_greed.csv")
fg_fields = ["date", "fear_greed_value", "fear_greed_class",
             "btc_dominance_pct", "market_cap_change_24h_pct", "sentix_proxy_score"]
with open(fg_file, "w", newline="") as f:
    writer = csv.DictWriter(f, fieldnames=fg_fields)
    writer.writeheader()
    for rec in fg_records:
        writer.writerow(rec)

print(f"  Saved {len(fg_records)} days -> {fg_file}")

# ============================================================
# 3. GOOGLE TRENDS (pytrends — chunked for daily granularity)
# ============================================================
print()
print("=" * 60)
print("3/3  Fetching Google Trends data (5 years in chunks)...")
print("       This takes ~5-10 minutes due to rate limits.")
print("=" * 60)

from pytrends.request import TrendReq

KEYWORDS = ["Bitcoin", "BTC", "Bitcoin price", "buy Bitcoin", "crypto crash"]

pytrends = TrendReq(hl="en-US", tz=360)
end_date = datetime.now(timezone.utc).date()
start_date = end_date - timedelta(days=1825)

OVERLAP_DAYS = 7
chunk_size = 250
all_data = {}
scale_factor = 1.0
prev_chunk_last_week = None
current_start = start_date
chunk_num = 0
consecutive_failures = 0
MAX_CONSECUTIVE_FAILURES = 3

while current_start < end_date:
    current_end = min(current_start + timedelta(days=chunk_size), end_date)

    # Avoid tiny chunks that cause infinite loops
    if (current_end - current_start).days < 2:
        break

    timeframe = f"{current_start.strftime('%Y-%m-%d')} {current_end.strftime('%Y-%m-%d')}"
    chunk_num += 1
    print(f"  Chunk {chunk_num}: {timeframe}")

    try:
        pytrends.build_payload(KEYWORDS, cat=0, timeframe=timeframe, geo="", gprop="")
        df = pytrends.interest_over_time()
        consecutive_failures = 0
    except Exception as e:
        print(f"    WARNING: Failed ({e}), retrying in 60s...")
        time.sleep(60)
        try:
            pytrends = TrendReq(hl="en-US", tz=360)
            pytrends.build_payload(KEYWORDS, cat=0, timeframe=timeframe, geo="", gprop="")
            df = pytrends.interest_over_time()
            consecutive_failures = 0
        except Exception as e2:
            print(f"    SKIPPED: {e2}")
            consecutive_failures += 1
            if consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                print(f"    Stopping after {MAX_CONSECUTIVE_FAILURES} consecutive failures (rate limited).")
                break
            # Advance past this chunk to avoid re-requesting the same range
            current_start = current_end
            time.sleep(60)
            continue

    if df.empty:
        print("    Empty response, skipping")
        current_start = current_end
        time.sleep(15)
        continue

    # Normalize across chunks using overlap
    if prev_chunk_last_week is not None and len(df) > OVERLAP_DAYS:
        overlap_dates = sorted(set(prev_chunk_last_week.keys()) & set(
            d.strftime("%Y-%m-%d") for d in df.index
        ))
        if overlap_dates:
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

    # Save overlap for next chunk
    prev_chunk_last_week = {}
    for i in range(max(0, len(df) - OVERLAP_DAYS), len(df)):
        row = df.iloc[i]
        date_str = row.name.strftime("%Y-%m-%d")
        prev_chunk_last_week[date_str] = {
            kw: int(row[kw]) * scale_factor for kw in KEYWORDS
        }

    # Store data
    for i in range(len(df)):
        row = df.iloc[i]
        date_str = row.name.strftime("%Y-%m-%d")
        if date_str not in all_data:
            all_data[date_str] = {
                kw: round(int(row[kw]) * scale_factor, 2) for kw in KEYWORDS
            }

    # Advance with overlap for normalization
    current_start = current_end - timedelta(days=OVERLAP_DAYS)
    time.sleep(15)

# Write CSV
trends_file = os.path.join(OUTPUT_DIR, "google_trends.csv")
trend_fields = ["date"] + [f"trend_{kw.lower().replace(' ', '_')}" for kw in KEYWORDS]
sorted_trend_dates = sorted(all_data.keys())

with open(trends_file, "w", newline="") as f:
    writer = csv.DictWriter(f, fieldnames=trend_fields)
    writer.writeheader()
    for date_str in sorted_trend_dates:
        record = {"date": date_str}
        for kw in KEYWORDS:
            col = f"trend_{kw.lower().replace(' ', '_')}"
            record[col] = all_data[date_str].get(kw, "")
        writer.writerow(record)

print(f"  Saved {len(all_data)} days -> {trends_file}")

# ============================================================
# SUMMARY
# ============================================================
print()
print("=" * 60)
print("DONE! Files saved:")
print(f"  - {btc_file}    ({len(records)} rows)")
print(f"  - {fg_file}     ({len(fg_records)} rows)")
print(f"  - {trends_file} ({len(all_data)} rows)")
print("=" * 60)

# In Colab, download the files:
try:
    from google.colab import files
    files.download(btc_file)
    files.download(fg_file)
    files.download(trends_file)
    print("\nDownloads started!")
except ImportError:
    print("\nNot running in Colab — files are in the 'data/' directory.")
