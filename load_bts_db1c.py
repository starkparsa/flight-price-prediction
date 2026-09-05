"""
Loader/aggregator for BTS's O&D DB1C Product File — real, U.S.-government,
ticket-level airline fare data, monthly 40% sample, publicly downloadable
with no signup. See https://www.bts.gov/topics/airlines-and-airports/origin-and-destination-survey-data

This is the "past year or so" real bootstrap data source (decisions.md).
11 monthly files are available as of 2026-09-05: July 2025 - May 2026.

IMPORTANT — what this data actually supports, and what it doesn't:
  - Real per-ticket fares, real routes, real round-trip detection (see
    below) — genuinely real price levels and seasonality, not synthetic.
  - Granularity is MONTH-level, not day-level (fields like SchFlMo_1 give
    only the travel month). This cannot drive day-precise date-window
    search the way date_window_optimizer.py's synthetic-trained model
    can pretend to — it can only calibrate month-level seasonality and a
    coarse lead-time signal.
  - Lead time is a genuine but COARSE 3-bucket field, `PurWinGrp`:
    '21AP' = bought <=21 days before departure, '2290' = 22-90 days,
    '91UP' = 91+ days. Mapped below to an approximate midpoint (10/55/150
    days) for anything downstream that wants a numeric days_out — that
    midpoint is a modeling approximation, not a measurement.
  - Round-trip detection: each record's itinerary path is given as
    Apt_1, Apt_2, ... (one column per coupon boundary). A ticket is a
    round trip if the FINAL airport in that path equals Apt_1 (the
    origin) — it returns home. For round trips, the actual destination
    (the turnaround point) is NOT the final airport (that's back to
    origin, by definition) — it's approximated here as the airport at
    position CouponSeg // 2, i.e., the midpoint of the path. This assumes
    a symmetric outbound/return connection count, which holds for the
    common cases (nonstop-both-ways, 1-connection-both-ways) but can be
    slightly off for asymmetric itineraries (different number of
    connections each direction) — a known, accepted approximation, not a
    bug being hidden.
  - price_per_pax = TotalAmt / NumPax. Quantiles below are unweighted
    across ticket records (most have NumPax=1; not weighting by NumPax
    is a minor simplification, not expected to materially skew results).

Usage:
    python load_bts_db1c.py                     # download (if needed) + aggregate all known months
    python load_bts_db1c.py --months 202507      # just one month, for testing
    python load_bts_db1c.py --skip-download      # aggregate only what's already cached locally
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import duckdb
import pandas as pd
import requests

CACHE_DIR = Path(__file__).parent / ".bts_cache"  # gitignored - raw files are too large to commit
OUTPUT_FILE = Path(__file__).parent / "data" / "bts_real_fares_agg.csv"

# (YYYYMM, direct Azure blob URL) - from bts.gov/topics/airlines-and-airports/origin-and-destination-survey-data-product
# on 2026-09-05. BTS adds a new month periodically and occasionally revises
# a REL (release) number for an existing month; re-check that page if a
# URL below starts 404ing.
MONTHLY_FILES = {
    "202507": "https://ostrapeispubdownloadprod.blob.core.windows.net/ostrapeis-pub-download-prod/ond40/products/db1c_public/DB1C.PUBLIC.202507.REL05.21MAY2026.zip",
    "202508": "https://ostrapeispubdownloadprod.blob.core.windows.net/ostrapeis-pub-download-prod/ond40/products/db1c_public/DB1C.PUBLIC.202508.REL03.22MAY2026.zip",
    "202509": "https://ostrapeispubdownloadprod.blob.core.windows.net/ostrapeis-pub-download-prod/ond40/products/db1c_public/DB1C.PUBLIC.202509.REL03.26MAY2026.zip",
    "202510": "https://ostrapeispubdownloadprod.blob.core.windows.net/ostrapeis-pub-download-prod/ond40/products/db1c_public/DB1C.PUBLIC.202510.REL04.26MAY2026.zip",
    "202511": "https://ostrapeispubdownloadprod.blob.core.windows.net/ostrapeis-pub-download-prod/ond40/products/db1c_public/DB1C.PUBLIC.202511.REL02.26MAY2026.zip",
    "202512": "https://ostrapeispubdownloadprod.blob.core.windows.net/ostrapeis-pub-download-prod/ond40/products/db1c_public/DB1C.PUBLIC.202512.REL02.27MAY2026.zip",
    "202601": "https://ostrapeispubdownloadprod.blob.core.windows.net/ostrapeis-pub-download-prod/ond40/products/db1c_public/DB1C.PUBLIC.202601.REL02.02JUN2026.zip",
    "202602": "https://ostrapeispubdownloadprod.blob.core.windows.net/ostrapeis-pub-download-prod/ond40/products/db1c_public/DB1C.PUBLIC.202602.REL01.02JUN2026.zip",
    "202603": "https://ostrapeispubdownloadprod.blob.core.windows.net/ostrapeis-pub-download-prod/ond40/products/db1c_public/DB1C.PUBLIC.202603.REL02.02JUL2026.zip",
    "202604": "https://ostrapeispubdownloadprod.blob.core.windows.net/ostrapeis-pub-download-prod/ond40/products/db1c_public/DB1C.PUBLIC.202604.REL01.15JUL2026.zip",
    "202605": "https://ostrapeispubdownloadprod.blob.core.windows.net/ostrapeis-pub-download-prod/ond40/products/db1c_public/DB1C.PUBLIC.202605.REL01.20AUG2026.zip",
}

PURWIN_DAYS_OUT_MIDPOINT = {"21AP": 10, "2290": 55, "91UP": 150}

APT_COLS = [f"Apt_{i}" for i in range(1, 24)]

# DuckDB does the whole real->turnaround->round-trip->groupby-quantile
# aggregation over a ~15M-row parquet file in a few seconds via SQL,
# operating directly on the file (no need to load it into Python first).
# An earlier pandas/pyarrow-batch-iteration version of this same logic was
# abandoned after running 5+ minutes with no result on a single month —
# groupby().agg() with per-group quantile lambdas is a known-slow pandas
# pattern at this row count; DuckDB's columnar quantile_cont is built for
# exactly this.
_APT_LIST_SQL = ", ".join(APT_COLS)
_AGGREGATE_SQL = f"""
WITH base AS (
  SELECT
    RpYear AS year, RpMonth AS month, CouponSeg, TotalAmt, NumPax, PurWinGrp,
    Apt_1 AS origin,
    LastApt,
    [{_APT_LIST_SQL}][LEAST(CouponSeg + 1, 23)::BIGINT] AS final_apt_raw,
    [{_APT_LIST_SQL}][(LEAST(GREATEST(CouponSeg / 2, 0), 22) + 1)::BIGINT] AS turnaround_apt
  FROM read_parquet(?)
),
resolved AS (
  SELECT *,
    CASE WHEN CouponSeg >= 23 THEN LastApt ELSE final_apt_raw END AS final_apt
  FROM base
),
withdest AS (
  SELECT *,
    (final_apt = origin) AS round_trip,
    CASE WHEN final_apt = origin THEN turnaround_apt ELSE final_apt END AS destination,
    TotalAmt / GREATEST(NumPax, 1) AS price_per_pax
  FROM resolved
)
SELECT origin, destination, year, month, PurWinGrp AS purwin,
       count(*) AS n_tickets,
       quantile_cont(price_per_pax, 0.10) AS price_p10,
       quantile_cont(price_per_pax, 0.50) AS price_p50,
       quantile_cont(price_per_pax, 0.90) AS price_p90
FROM withdest
-- this repo's model is round-trip focused; one-way tickets are dropped here
WHERE round_trip AND destination IS NOT NULL AND destination != origin
GROUP BY origin, destination, year, month, purwin
"""


def ensure_downloaded(yyyymm: str) -> Path | None:
    url = MONTHLY_FILES[yyyymm]
    CACHE_DIR.mkdir(exist_ok=True)
    zip_path = CACHE_DIR / f"DB1C.{yyyymm}.zip"
    if zip_path.exists() and zip_path.stat().st_size > 0:
        return zip_path
    print(f"  downloading {yyyymm} from {url} ...", flush=True)
    try:
        resp = requests.get(url, timeout=300, stream=True)
        resp.raise_for_status()
        with zip_path.open("wb") as f:
            for chunk in resp.iter_content(chunk_size=1 << 20):
                f.write(chunk)
    except requests.RequestException as e:
        print(f"  [error] failed to download {yyyymm}: {e}", file=sys.stderr)
        if zip_path.exists():
            zip_path.unlink()
        return None
    return zip_path


def extract_parquet(zip_path: Path) -> Path | None:
    import zipfile
    with zipfile.ZipFile(zip_path) as zf:
        parquet_names = [n for n in zf.namelist() if n.endswith(".parquet")]
        if not parquet_names:
            print(f"  [error] no .parquet member in {zip_path.name}", file=sys.stderr)
            return None
        out_path = CACHE_DIR / parquet_names[0]
        if not out_path.exists():
            zf.extract(parquet_names[0], CACHE_DIR)
        return out_path


def aggregate_month(parquet_path: Path) -> pd.DataFrame:
    """Runs _AGGREGATE_SQL against the parquet file via DuckDB - a few
    seconds even for a ~15M-row month, operating on the file directly."""
    con = duckdb.connect()
    agg = con.execute(_AGGREGATE_SQL, [str(parquet_path)]).fetchdf()
    agg["days_out_midpoint"] = agg["purwin"].map(PURWIN_DAYS_OUT_MIDPOINT)
    agg["route"] = agg["origin"] + "-" + agg["destination"]
    return agg


def main(months: list[str], skip_download: bool, min_tickets: int = 20):
    all_aggs = []
    for yyyymm in months:
        print(f"Processing {yyyymm}...")
        if skip_download:
            candidates = list(CACHE_DIR.glob(f"*{yyyymm}*.zip"))
            zip_path = candidates[0] if candidates else None
            if zip_path is None:
                print(f"  [skip] no cached zip for {yyyymm} and --skip-download set", file=sys.stderr)
                continue
        else:
            zip_path = ensure_downloaded(yyyymm)
            if zip_path is None:
                continue

        parquet_path = extract_parquet(zip_path)
        if parquet_path is None:
            continue

        agg = aggregate_month(parquet_path)
        agg["source_month"] = yyyymm
        all_aggs.append(agg)
        print(f"  {yyyymm}: {len(agg)} route/purwin groups from real ticket data")

        # free disk: the raw parquet is ~300MB+ and we only need the tiny
        # aggregate going forward. Keep the zip (cheap re-extract) but drop
        # the extracted parquet.
        parquet_path.unlink(missing_ok=True)

    if not all_aggs:
        print("Nothing aggregated.", file=sys.stderr)
        sys.exit(1)

    result = pd.concat(all_aggs, ignore_index=True)
    before = len(result)
    # Real 40%-sample ticket counts are heavily skewed thin: median group
    # across the first full 11-month run was only 5 tickets, useless for a
    # trustworthy p10/p50/p90 estimate. Filtering to >=20 tickets keeps ~25%
    # of rows (still ~20k routes) while making every remaining quantile
    # estimate meaningful, and keeps the committed CSV well under GitHub's
    # 100MB soft limit (was ~97MB unfiltered, single file).
    result = result[result["n_tickets"] >= min_tickets]
    OUTPUT_FILE.parent.mkdir(exist_ok=True)
    result.to_csv(OUTPUT_FILE, index=False)
    print(f"\nWrote {len(result)} rows to {OUTPUT_FILE} "
          f"(dropped {before - len(result)} thin groups with <{min_tickets} tickets)")
    print(f"Routes covered: {result['route'].nunique()}")
    print(f"Months covered: {sorted(result['source_month'].unique())}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--months", nargs="+", default=list(MONTHLY_FILES.keys()),
                         help="YYYYMM values to process (default: all known months)")
    parser.add_argument("--skip-download", action="store_true",
                         help="Only process months already cached in .bts_cache/")
    parser.add_argument("--min-tickets", type=int, default=20,
                         help="Drop route/month/purwin groups with fewer real tickets than this "
                              "(default 20 - below this, p10/p50/p90 estimates are unreliable)")
    args = parser.parse_args()
    main(args.months, args.skip_download, args.min_tickets)
