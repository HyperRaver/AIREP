"""
Google Trends Backfill — POSITIVE Sentiment Keywords
=====================================================
Anchor: "buy bitcoin"
Run in Google Colab.

Normalization method: Eichenauer et al. (2022), Economic Inquiry.
Cross-batch: median anchor ratio. Cross-period: 6-month overlap.
"""

import subprocess
subprocess.check_call(["pip", "install", "-q", "pytrends", "pandas"])

import csv
import os
import time

import pandas as pd
from pytrends.request import TrendReq

OUTPUT_DIR = "data"
os.makedirs(OUTPUT_DIR, exist_ok=True)

# ============================================================
# CONFIGURATION
# ============================================================

ANCHOR = "buy bitcoin"

KEYWORDS = [
    "bitcoin mining",
    "bitcoin wallet",
    "bitcoin atm",
    "how to buy bitcoin",
    "best crypto to buy",
    "bitcoin price prediction",
    "long bitcoin",
    "bitcoin halving",
    "invest in bitcoin",
    "bitcoin atm near me",
    "bitcoin etf price",
    "diamond hands",
    "bitcoin etf",
    "Coinbase",
]

PERIODS = [
    ("2018-04-06", "2022-10-06"),  # ~4.5 years
    ("2022-04-06", "2026-03-27"),  # ~4 years, 6-month overlap
]

# ============================================================
# BUILD BATCHES (anchor + up to 4 others)
# ============================================================

others = [kw for kw in KEYWORDS if kw.lower() != ANCHOR.lower()]
batches = []
for i in range(0, len(others), 4):
    batch = [ANCHOR] + others[i:i + 4]
    batches.append(batch)

print(f"POSITIVE SENTIMENT GROUP")
print(f"  Anchor: '{ANCHOR}'")
print(f"  Keywords: {len(KEYWORDS)}")
print(f"  Batches: {len(batches)}")
for i, b in enumerate(batches):
    print(f"    Batch {i + 1}: {b}")
print(f"  Periods: {len(PERIODS)}")
print(f"  Total API requests: {len(batches) * len(PERIODS)}")
print()

# ============================================================
# FETCH DATA
# ============================================================

pytrends = TrendReq(hl="en-US", tz=360)
raw_data = {}

for p_idx, (start, end) in enumerate(PERIODS):
    timeframe = f"{start} {end}"
    raw_data[p_idx] = {}

    for b_idx, batch in enumerate(batches):
        label = f"Period {p_idx + 1}/{len(PERIODS)}, Batch {b_idx + 1}/{len(batches)}"
        print(f"{label}: {batch}")

        max_retries = 3
        for attempt in range(max_retries):
            try:
                pytrends.build_payload(
                    batch, cat=0, timeframe=timeframe, geo="", gprop=""
                )
                df = pytrends.interest_over_time()
                if not df.empty and "isPartial" in df.columns:
                    df = df.drop(columns=["isPartial"])
                raw_data[p_idx][b_idx] = df
                print(f"  OK — {len(df)} weeks")
                break
            except Exception as e:
                wait = 60 * (attempt + 1)
                print(f"  Attempt {attempt + 1} failed: {e}")
                if attempt < max_retries - 1:
                    print(f"  Retrying in {wait}s...")
                    time.sleep(wait)
                    pytrends = TrendReq(hl="en-US", tz=360)
                else:
                    print(f"  FAILED after {max_retries} attempts")
                    raw_data[p_idx][b_idx] = pd.DataFrame()

        time.sleep(15)

# ============================================================
# NORMALIZE WITHIN EACH PERIOD (across batches)
# ============================================================

print("\n" + "=" * 60)
print("NORMALIZING WITHIN PERIODS")
print("=" * 60)

normalized_periods = {}

for p_idx in range(len(PERIODS)):
    ref_df = raw_data[p_idx].get(0, pd.DataFrame())
    if ref_df.empty:
        print(f"  Period {p_idx + 1}: batch 1 empty, skipping")
        continue

    combined = ref_df.copy()
    anchor_ref = ref_df[ANCHOR].astype(float)

    for b_idx in range(1, len(batches)):
        batch_df = raw_data[p_idx].get(b_idx, pd.DataFrame())
        if batch_df.empty:
            continue

        anchor_batch = batch_df[ANCHOR].astype(float)
        mask = (anchor_ref > 0) & (anchor_batch > 0)
        if mask.sum() > 0:
            ratios = anchor_ref[mask] / anchor_batch[mask]
            scale = ratios.median()
        else:
            scale = 1.0

        print(f"  Period {p_idx + 1}, Batch {b_idx + 1}: "
              f"scale={scale:.4f}, ratio_std={ratios.std():.4f}, n={mask.sum()}")

        for col in batch_df.columns:
            if col != ANCHOR:
                combined[col] = batch_df[col].astype(float) * scale

    normalized_periods[p_idx] = combined
    print(f"  Period {p_idx + 1} done: {len(combined)} weeks, "
          f"{len(combined.columns)} keywords")

# ============================================================
# NORMALIZE ACROSS PERIODS (using overlap)
# ============================================================

print("\n" + "=" * 60)
print("NORMALIZING ACROSS PERIODS")
print("=" * 60)

if len(normalized_periods) < 2:
    print("ERROR: Need at least 2 periods")
    final = normalized_periods.get(0, pd.DataFrame())
else:
    p0 = normalized_periods[0]
    p1 = normalized_periods[1]

    overlap_idx = p0.index.intersection(p1.index)
    print(f"  Overlap weeks: {len(overlap_idx)}")
    if len(overlap_idx) > 0:
        print(f"  Overlap range: {overlap_idx[0].strftime('%Y-%m-%d')} "
              f"to {overlap_idx[-1].strftime('%Y-%m-%d')}")

    anchor_p0 = p0.loc[overlap_idx, ANCHOR].astype(float)
    anchor_p1 = p1.loc[overlap_idx, ANCHOR].astype(float)
    mask = (anchor_p0 > 0) & (anchor_p1 > 0)

    if mask.sum() > 0:
        ratios = anchor_p0[mask] / anchor_p1[mask]
        cross_scale = ratios.median()
        print(f"  Cross-period scale: {cross_scale:.4f}")
        print(f"  Ratio std: {ratios.std():.4f}")
        print(f"  Ratio range: [{ratios.min():.4f}, {ratios.max():.4f}]")
        print(f"  n_overlap_nonzero: {mask.sum()}")
    else:
        cross_scale = 1.0
        print("  WARNING: No non-zero overlap, using scale=1.0")

    p1_scaled = p1 * cross_scale
    non_overlap_idx = p1_scaled.index.difference(p0.index)
    final = pd.concat([p0, p1_scaled.loc[non_overlap_idx]])
    final = final.sort_index()

# ============================================================
# SAVE
# ============================================================

print("\n" + "=" * 60)
print("RESULT")
print("=" * 60)
print(f"  Total weeks: {len(final)}")
print(f"  Date range: {final.index[0].strftime('%Y-%m-%d')} "
      f"to {final.index[-1].strftime('%Y-%m-%d')}")
print(f"  Keywords: {list(final.columns)}")

output_file = os.path.join(OUTPUT_DIR, "google_trends_positive.csv")
final.index.name = "date"
final = final.round(2)
final.to_csv(output_file)
print(f"\n  Saved to {output_file}")

print("\nFirst 5 rows:")
print(final.head().to_string())
print("\nLast 5 rows:")
print(final.tail().to_string())

try:
    from google.colab import files
    files.download(output_file)
    print("\nDownload started!")
except ImportError:
    print(f"\nNot in Colab — file at {output_file}")
