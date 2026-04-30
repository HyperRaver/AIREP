"""
Google Trends Backfill — POSITIVE Sentiment (Pairwise Method)
==============================================================
Anchor: "buy bitcoin"
Each keyword queried individually with the anchor for reliable scaling.
Run in Google Colab.
"""

import subprocess
subprocess.check_call(["pip", "install", "-q", "pytrends", "pandas"])

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
# FETCH: one request per keyword per period
# ============================================================

print("POSITIVE SENTIMENT GROUP (pairwise method)")
print(f"  Anchor: '{ANCHOR}'")
print(f"  Keywords: {len(KEYWORDS)}")
print(f"  Periods: {len(PERIODS)}")
print(f"  Total API requests: {len(KEYWORDS) * len(PERIODS)}")
print()

pytrends = TrendReq(hl="en-US", tz=360)

# raw_pairs[period_idx][keyword] = DataFrame with columns [ANCHOR, keyword]
raw_pairs = {p: {} for p in range(len(PERIODS))}

for p_idx, (start, end) in enumerate(PERIODS):
    timeframe = f"{start} {end}"

    for kw in KEYWORDS:
        pair = [ANCHOR, kw]
        print(f"  Period {p_idx + 1}, {kw}...", end=" ", flush=True)

        max_retries = 3
        for attempt in range(max_retries):
            try:
                pytrends.build_payload(
                    pair, cat=0, timeframe=timeframe, geo="", gprop=""
                )
                df = pytrends.interest_over_time()
                if not df.empty and "isPartial" in df.columns:
                    df = df.drop(columns=["isPartial"])
                raw_pairs[p_idx][kw] = df
                print(f"OK ({len(df)} weeks)")
                break
            except Exception as e:
                wait = 60 * (attempt + 1)
                print(f"RETRY({attempt + 1})...", end=" ", flush=True)
                time.sleep(wait)
                pytrends = TrendReq(hl="en-US", tz=360)
                if attempt == max_retries - 1:
                    print(f"FAILED: {e}")
                    raw_pairs[p_idx][kw] = pd.DataFrame()

        time.sleep(10)

# ============================================================
# NORMALIZE WITHIN EACH PERIOD
# For each pair, compute: keyword_normalized = keyword * (100 / anchor)
# at each time point. This puts every keyword on the anchor's absolute scale.
# Then we keep the anchor's raw values from ONE reference pair.
# ============================================================

print("\n" + "=" * 60)
print("NORMALIZING WITHIN PERIODS")
print("=" * 60)

normalized_periods = {}

for p_idx in range(len(PERIODS)):
    # Get anchor's raw values from the first successful pair
    anchor_ref = None
    for kw in KEYWORDS:
        df = raw_pairs[p_idx].get(kw, pd.DataFrame())
        if not df.empty and ANCHOR in df.columns:
            anchor_ref = df[ANCHOR].astype(float)
            break

    if anchor_ref is None:
        print(f"  Period {p_idx + 1}: no data, skipping")
        continue

    combined = pd.DataFrame(index=anchor_ref.index)
    combined[ANCHOR] = anchor_ref

    for kw in KEYWORDS:
        df = raw_pairs[p_idx].get(kw, pd.DataFrame())
        if df.empty or kw not in df.columns:
            print(f"  Period {p_idx + 1}, {kw}: MISSING")
            continue

        kw_values = df[kw].astype(float)
        anchor_in_pair = df[ANCHOR].astype(float)

        # Scale keyword relative to anchor:
        # In this pair, anchor peaked at some value X (not necessarily 100
        # if the keyword was more popular). We rescale so anchor matches
        # anchor_ref from the reference pair.
        mask = anchor_in_pair > 0
        if mask.sum() > 0:
            ratios = anchor_ref[mask] / anchor_in_pair[mask]
            scale = ratios.median()
        else:
            scale = 1.0

        combined[kw] = kw_values * scale
        print(f"  Period {p_idx + 1}, {kw}: scale={scale:.4f}, "
              f"ratio_std={ratios.std():.4f}" if mask.sum() > 0 else
              f"  Period {p_idx + 1}, {kw}: scale=1.0 (no overlap)")

    normalized_periods[p_idx] = combined
    print(f"  Period {p_idx + 1} done: {len(combined)} weeks, "
          f"{len(combined.columns)} columns")

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
