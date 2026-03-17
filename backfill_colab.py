"""
Bitcoin 5-Year Historical Data Backfill — Run in Google Colab
=============================================================
1. Open Google Colab (colab.research.google.com)
2. Paste this entire script into a cell
3. Run the cell
4. Download the 3 CSVs from the file browser (left sidebar)

Or mount Google Drive and change OUTPUT_DIR to save there directly.
"""

# !pip install pytrends requests  # Uncomment if needed in Colab

import csv
import os
import time
from datetime import datetime, timedelta, timezone

import requests

OUTPUT_DIR = "data"
os.makedirs(OUTPUT_DIR, exist_ok=True)

# ============================================================
# 1. BTC PRICE (CoinGecko — free, no API key)
# ============================================================
print("=" * 60)
print("1/3  Fetching BTC price data (5 years)...")
print("=" * 60)

url = "https://api.coingecko.com/api/v3/coins/bitcoin/market_chart"
params = {"vs_currency": "usd", "days": 1825, "interval": "daily"}
resp = requests.get(url, params=params, timeout=60)
resp.raise_for_status()
data = resp.json()

prices = data["prices"]
market_caps = data["market_caps"]
volumes = data["total_volumes"]

# Build records keyed by date
records = {}
for ts_ms, price in prices:
    date = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d")
    records[date] = {"date": date, "price_usd": round(price, 2)}
for ts_ms, mcap in market_caps:
    date = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d")
    if date in records:
        records[date]["market_cap_usd"] = round(mcap, 2)
for ts_ms, vol in volumes:
    date = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d")
    if date in records:
        records[date]["volume_24h_usd"] = round(vol, 2)

# Derive OHLC approximation + daily change from daily closes
sorted_dates = sorted(records.keys())
prev_price = None
for date in sorted_dates:
    rec = records[date]
    price = rec["price_usd"]
    rec["open"] = prev_price if prev_price is not None else price
    rec["high"] = max(rec["open"], price)
    rec["low"] = min(rec["open"], price)
    rec["close"] = price
    rec["change_24h_pct"] = round((price - prev_price) / prev_price * 100, 4) if prev_price else ""
    rec.setdefault("market_cap_usd", "")
    rec.setdefault("volume_24h_usd", "")
    prev_price = price

# Write CSV
btc_file = os.path.join(OUTPUT_DIR, "btc_price.csv")
fieldnames = ["date", "price_usd", "market_cap_usd", "volume_24h_usd",
              "change_24h_pct", "open", "high", "low", "close"]
with open(btc_file, "w", newline="") as f:
    writer = csv.DictWriter(f, fieldnames=fieldnames)
    writer.writeheader()
    for date in sorted_dates:
        writer.writerow(records[date])

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

chunk_size = 250
all_data = {}
scale_factor = 1.0
prev_chunk_last_week = None
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
        print(f"    WARNING: Failed ({e}), retrying in 60s...")
        time.sleep(60)
        try:
            pytrends = TrendReq(hl="en-US", tz=360)
            pytrends.build_payload(KEYWORDS, cat=0, timeframe=timeframe, geo="", gprop="")
            df = pytrends.interest_over_time()
        except Exception as e2:
            print(f"    SKIPPED: {e2}")
            current_start = current_end - timedelta(days=7)
            continue

    if df.empty:
        print("    Empty response, skipping")
        current_start = current_end - timedelta(days=7)
        time.sleep(15)
        continue

    # Normalize across chunks using overlap
    if prev_chunk_last_week is not None and len(df) > 7:
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
    for i in range(max(0, len(df) - 7), len(df)):
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

    current_start = current_end - timedelta(days=7)
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
