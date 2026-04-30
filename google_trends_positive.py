"""
Google Trends Backfill — POSITIVE Sentiment (Solo Anchor + Pointwise)
=====================================================================
Anchor: "buy bitcoin"
Method: query anchor alone for baseline, then pairwise with pointwise rescaling.
Run in Google Colab.
"""

import subprocess
subprocess.check_call(["pip", "install", "-q", "pytrends", "pandas"])

import os
import time

import numpy as np
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

MIN_ANCHOR = 3  # ignore weeks where anchor < this (noisy division)

# ============================================================
# HELPER
# ============================================================

def fetch(pytrends_obj, keywords, timeframe, max_retries=3):
    for attempt in range(max_retries):
        try:
            pytrends_obj.build_payload(
                keywords, cat=0, timeframe=timeframe, geo="", gprop=""
            )
            df = pytrends_obj.interest_over_time()
            if not df.empty and "isPartial" in df.columns:
                df = df.drop(columns=["isPartial"])
            return df
        except Exception as e:
            wait = 60 * (attempt + 1)
            print(f"  attempt {attempt + 1} failed: {e}")
            if attempt < max_retries - 1:
                print(f"  retrying in {wait}s...")
                time.sleep(wait)
                pytrends_obj = TrendReq(hl="en-US", tz=360)
            else:
                print(f"  FAILED after {max_retries} attempts")
                return pd.DataFrame()
    return pd.DataFrame()

# ============================================================
# STEP 1: FETCH ANCHOR SOLO for each period
# ============================================================

print("POSITIVE SENTIMENT GROUP (solo anchor + pointwise method)")
print(f"  Anchor: '{ANCHOR}'")
print(f"  Keywords: {len(KEYWORDS)}")
print(f"  Total API requests: {(1 + len(KEYWORDS)) * len(PERIODS)}")
print()

pytrends = TrendReq(hl="en-US", tz=360)

solo = {}
for p_idx, (start, end) in enumerate(PERIODS):
    timeframe = f"{start} {end}"
    print(f"Period {p_idx + 1} — solo anchor '{ANCHOR}'...", end=" ", flush=True)
    df = fetch(pytrends, [ANCHOR], timeframe)
    if not df.empty:
        solo[p_idx] = df[ANCHOR].astype(float)
        print(f"OK ({len(df)} weeks, peak={solo[p_idx].max():.0f})")
    else:
        print("FAILED")
    time.sleep(10)

# ============================================================
# STEP 2: FETCH PAIRWISE and compute pointwise rescaling
# ============================================================

normalized_periods = {}

for p_idx, (start, end) in enumerate(PERIODS):
    timeframe = f"{start} {end}"

    if p_idx not in solo:
        print(f"Period {p_idx + 1}: no solo anchor data, skipping")
        continue

    anchor_solo = solo[p_idx]
    combined = pd.DataFrame(index=anchor_solo.index)
    combined[ANCHOR] = anchor_solo

    for kw in KEYWORDS:
        print(f"  Period {p_idx + 1}, [{ANCHOR}, {kw}]...", end=" ", flush=True)
        df = fetch(pytrends, [ANCHOR, kw], timeframe)

        if df.empty or kw not in df.columns:
            print("MISSING")
            continue

        anchor_pair = df[ANCHOR].astype(float)
        kw_pair = df[kw].astype(float)

        # Pointwise rescaling:
        # kw_final[t] = (kw_pair[t] / anchor_pair[t]) * solo[t]
        # This cancels Google's normalization base and puts kw on solo scale
        mask = anchor_pair >= MIN_ANCHOR
        kw_final = pd.Series(np.nan, index=anchor_solo.index)

        if mask.sum() > 0:
            kw_final[mask] = (kw_pair[mask] / anchor_pair[mask]) * anchor_solo[mask]
            # For weeks below threshold, interpolate
            kw_final = kw_final.interpolate(method="linear", limit_direction="both")
            kw_final = kw_final.fillna(0)
        else:
            kw_final = kw_pair * 0  # all zeros

        combined[kw] = kw_final

        # Diagnostic: check ratio consistency
        if mask.sum() > 0:
            ratios = anchor_solo[mask] / anchor_pair[mask]
            print(f"OK (scale_median={ratios.median():.2f}, "
                  f"std={ratios.std():.2f}, n={mask.sum()})")
        else:
            print("OK (no valid anchor points)")

        time.sleep(10)

    normalized_periods[p_idx] = combined
    print(f"  Period {p_idx + 1} done: {len(combined)} weeks, "
          f"{len(combined.columns)} columns\n")

# ============================================================
# STEP 3: NORMALIZE ACROSS PERIODS (using overlap)
# ============================================================

print("=" * 60)
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

    # Use solo anchor values for cross-period scaling
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
