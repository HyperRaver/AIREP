"""
Google Trends 8-Year Weekly Backfill — Normalized Cross-Batch & Cross-Period
=============================================================================
Run in Google Colab. Produces a single CSV with consistent 0-100 scale.

Methodology:
- 11 keywords split into 3 batches of max 5 (pytrends API limit)
- One anchor keyword ("buy bitcoin") included in every batch
- Within each period: batches normalized to batch 1's scale via the anchor
- Across periods: 6-month overlap used to compute a median scaling factor
- Result: all keywords on a single, consistent relative scale
"""

import subprocess
subprocess.check_call(["pip", "install", "-q", "pytrends", "pandas"])

import csv
import os
import time
from datetime import datetime, timedelta, timezone

import pandas as pd
from pytrends.request import TrendReq

OUTPUT_DIR = "data"
os.makedirs(OUTPUT_DIR, exist_ok=True)

# ============================================================
# CONFIGURATION
# ============================================================

KEYWORDS = [
    "bitcoin crash",
    "bitcoin scam",
    "bitcoin all time high",
    "bitcoin dead",
    "bitcoin 100k",
    "how to buy bitcoin",
    "bitcoin ETF",
    "buy bitcoin",
    "bitcoin to the moon",
    "bitcoin going to zero",
    "hyperbitcoinization",
]

# Anchor keyword — included in every batch for cross-calibration.
# Selected from the study's own keywords (not an external reference).
# "buy bitcoin" chosen for relatively consistent, non-zero search volume.
ANCHOR = "buy bitcoin"

# Time periods — each MUST be < 5 years for weekly granularity from Google.
# 6-month overlap between periods enables cross-period normalization.
PERIODS = [
    ("2018-04-24", "2022-10-24"),  # ~4.5 years
    ("2022-04-24", "2026-04-24"),  # ~4 years, 6-month overlap with period 1
]

# ============================================================
# BUILD BATCHES (anchor + up to 4 others per batch)
# ============================================================

others = [kw for kw in KEYWORDS if kw != ANCHOR]
batches = []
for i in range(0, len(others), 4):
    batch = [ANCHOR] + others[i:i + 4]
    batches.append(batch)

print(f"Keywords: {len(KEYWORDS)}")
print(f"Anchor: '{ANCHOR}'")
print(f"Batches: {len(batches)}")
for i, b in enumerate(batches):
    print(f"  Batch {i + 1}: {b}")
print(f"Periods: {len(PERIODS)}")
print(f"Total API requests: {len(batches) * len(PERIODS)}")
print()

# ============================================================
# FETCH DATA
# ============================================================

pytrends = TrendReq(hl="en-US", tz=360)

raw_data = {}  # raw_data[period_idx][batch_idx] = DataFrame

for p_idx, (start, end) in enumerate(PERIODS):
    timeframe = f"{start} {end}"
    raw_data[p_idx] = {}

    for b_idx, batch in enumerate(batches):
        label = f"Period {p_idx + 1}/{len(PERIODS)}, Batch {b_idx + 1}/{len(batches)}"
        print(f"{label}: {batch}")
        print(f"  Timeframe: {timeframe}")

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
# STEP 1: NORMALIZE WITHIN EACH PERIOD (across batches)
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

    # Batch 0 is the reference scale
    combined = ref_df.copy()
    anchor_ref = ref_df[ANCHOR].astype(float)

    for b_idx in range(1, len(batches)):
        batch_df = raw_data[p_idx].get(b_idx, pd.DataFrame())
        if batch_df.empty:
            continue

        anchor_batch = batch_df[ANCHOR].astype(float)

        # Compute median ratio where both anchor values > 0
        mask = (anchor_ref > 0) & (anchor_batch > 0)
        if mask.sum() > 0:
            ratios = anchor_ref[mask] / anchor_batch[mask]
            scale = ratios.median()
        else:
            scale = 1.0

        print(f"  Period {p_idx + 1}, Batch {b_idx + 1}: "
              f"scale={scale:.4f}, "
              f"ratio_std={ratios.std():.4f}, "
              f"n_overlap={mask.sum()}")

        # Scale non-anchor columns and add to combined
        for col in batch_df.columns:
            if col != ANCHOR:
                combined[col] = batch_df[col].astype(float) * scale

    normalized_periods[p_idx] = combined
    print(f"  Period {p_idx + 1} done: {len(combined)} weeks, "
          f"{len(combined.columns)} keywords")

# ============================================================
# STEP 2: NORMALIZE ACROSS PERIODS (using overlap)
# ============================================================

print("\n" + "=" * 60)
print("NORMALIZING ACROSS PERIODS")
print("=" * 60)

if len(normalized_periods) < 2:
    print("ERROR: Need at least 2 periods!")
    final = normalized_periods.get(0, pd.DataFrame())
else:
    p0 = normalized_periods[0]
    p1 = normalized_periods[1]

    # Find overlapping weeks
    overlap_idx = p0.index.intersection(p1.index)
    print(f"  Overlap weeks: {len(overlap_idx)}")
    if len(overlap_idx) > 0:
        print(f"  Overlap range: {overlap_idx[0].strftime('%Y-%m-%d')} "
              f"to {overlap_idx[-1].strftime('%Y-%m-%d')}")

    # Compute cross-period scale using anchor in overlap
    anchor_p0 = p0.loc[overlap_idx, ANCHOR].astype(float)
    anchor_p1 = p1.loc[overlap_idx, ANCHOR].astype(float)

    mask = (anchor_p0 > 0) & (anchor_p1 > 0)
    if mask.sum() > 0:
        ratios = anchor_p0[mask] / anchor_p1[mask]
        cross_scale = ratios.median()
        print(f"  Cross-period scale: {cross_scale:.4f}")
        print(f"  Ratio std: {ratios.std():.4f} (lower = more consistent)")
        print(f"  Ratio range: [{ratios.min():.4f}, {ratios.max():.4f}]")
        print(f"  n_overlap_nonzero: {mask.sum()}")
    else:
        cross_scale = 1.0
        print("  WARNING: No non-zero overlap — using scale=1.0")

    # Scale period 1
    p1_scaled = p1 * cross_scale

    # Merge: period 0 in full, then non-overlapping part of period 1
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

output_file = os.path.join(OUTPUT_DIR, "google_trends.csv")
final.index.name = "date"
final = final.round(2)
final.to_csv(output_file)
print(f"\n  Saved to {output_file}")

# Preview
print("\nFirst 5 rows:")
print(final.head().to_string())
print("\nLast 5 rows:")
print(final.tail().to_string())

# Download in Colab
try:
    from google.colab import files
    files.download(output_file)
    print("\nDownload started!")
except ImportError:
    print(f"\nNot in Colab — file is at {output_file}")
