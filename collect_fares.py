"""
⚠️ DEAD CODE as of 2026-09-05: depends on amadeus_client.py, which depends
on an Amadeus self-service API that no longer exists (portal decommissioned
2026-07-17). Do not run this expecting it to work. Kept for reference —
the rotation/quota-guard design is reusable against whatever provider
replaces Amadeus. See decisions.md's pivot entry and STATUS.md.

Daily fare collector: the "steady stream" data source for this project.

Run this once a day (cron / Windows Task Scheduler / any scheduler) and it
appends real, current round-trip prices from Amadeus to
`data/real_fares.csv`, in the same schema `price_model.py` already expects
(see synthetic_data.py's docstring) — so as this file grows, retraining
against real data is just `python train_real.py`, no pipeline changes.

Design constraints (see decisions.md / STATUS.md):
  - $0 budget: stays under Amadeus's free monthly quota via quota_tracker.py
    (default cap 1,800/month) and a small per-run call budget (default 20/day
    = ~600/month, comfortably under the cap even with manual testing calls).
  - One API call can return several offers (different airlines/stops) —
    each becomes its own training row, so quota is used efficiently.
  - Which (route, departure_date, nights) combination gets queried on a
    given day rotates deterministically by day-of-epoch, so repeated daily
    runs sweep across the whole lead-time/trip-length grid over time
    instead of hammering the same few points.

Usage:
    python collect_fares.py                  # real run, up to --max-calls calls
    python collect_fares.py --dry-run         # show what would be queried, no API calls
    python collect_fares.py --max-calls 10 --routes-file routes.json
"""
from __future__ import annotations

import argparse
import csv
import sys
from datetime import date, timedelta
from pathlib import Path

from amadeus_client import AmadeusClient
from quota_tracker import QuotaTracker

DAYS_OUT_GRID = [7, 14, 21, 30, 45, 60, 75, 90, 120, 150, 180, 240, 300]
NIGHTS_GRID = [3, 5, 7, 10, 14, 21]

OUTPUT_COLUMNS = [
    "search_date", "route", "departure_date", "return_date",
    "days_out", "nights", "stops", "airline", "price", "currency", "source",
]


def build_grid(routes: list[dict]) -> list[tuple[str, str, int, int]]:
    """Every (origin, destination, days_out, nights) combination, in a fixed
    deterministic order so the rotation below is reproducible."""
    grid = []
    for r in routes:
        for days_out in DAYS_OUT_GRID:
            for nights in NIGHTS_GRID:
                grid.append((r["origin"], r["destination"], days_out, nights))
    return grid


def pick_todays_slice(grid: list[tuple], max_calls: int) -> list[tuple]:
    """Deterministic rotation by epoch day, wrapping around the grid — each
    day advances to a new slice so repeated runs eventually cover it all."""
    if not grid:
        return []
    epoch_day = (date.today() - date(1970, 1, 1)).days
    start = (epoch_day * max_calls) % len(grid)
    if start + max_calls <= len(grid):
        return grid[start:start + max_calls]
    return grid[start:] + grid[: (start + max_calls) - len(grid)]


def collect(routes_file: str, output_file: str, max_calls: int, dry_run: bool,
            max_offers_per_call: int = 3) -> int:
    routes = __import__("json").loads(Path(routes_file).read_text())
    grid = build_grid(routes)
    todays_calls = pick_todays_slice(grid, max_calls)

    tracker = QuotaTracker()
    if not dry_run and not tracker.can_call(len(todays_calls)):
        print(
            f"Only {tracker.remaining()} calls left this month "
            f"(cap {tracker.monthly_limit}), need {len(todays_calls)}. "
            f"Reduce --max-calls or wait for next month. Aborting.",
            file=sys.stderr,
        )
        return 1

    print(f"Today's plan: {len(todays_calls)} calls "
          f"({tracker.remaining()} of monthly quota remaining before this run).")

    if dry_run:
        for origin, dest, days_out, nights in todays_calls:
            dep = date.today() + timedelta(days=days_out)
            ret = dep + timedelta(days=nights)
            print(f"  [dry-run] {origin}-{dest}  depart={dep} return={ret} "
                  f"(days_out={days_out}, nights={nights})")
        return 0

    client = AmadeusClient()
    try:
        client._get_token()
    except Exception as e:  # noqa: BLE001 - surfacing any auth/config problem before burning quota
        print(f"Cannot authenticate with Amadeus, aborting before making any calls: {e}",
              file=sys.stderr)
        return 1

    out_path = Path(output_file)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    write_header = not out_path.exists() or out_path.stat().st_size == 0
    today = date.today()

    rows_written = 0
    errors = 0
    with out_path.open("a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=OUTPUT_COLUMNS)
        if write_header:
            writer.writeheader()

        calls_made = 0
        for origin, dest, days_out, nights in todays_calls:
            dep = today + timedelta(days=days_out)
            ret = dep + timedelta(days=nights)

            result = client.search_flight_offers(
                origin, dest, dep.isoformat(), ret.isoformat(),
                max_results=max_offers_per_call,
            )
            calls_made += 1

            if "error" in result:
                print(f"  [error] {origin}-{dest} {dep}: {result['error']}", file=sys.stderr)
                errors += 1
                continue

            for offer in result["offers"]:
                writer.writerow({
                    "search_date": today.isoformat(),
                    "route": f"{origin}-{dest}",
                    "departure_date": dep.isoformat(),
                    "return_date": ret.isoformat(),
                    "days_out": days_out,
                    "nights": nights,
                    "stops": offer["stops"],
                    "airline": offer["airline"],
                    "price": offer["price"],
                    "currency": offer["currency"],
                    "source": "amadeus",
                })
                rows_written += 1

    tracker.record_calls(calls_made)
    print(f"Done: {calls_made} API calls, {rows_written} rows written, "
          f"{errors} errors. Quota remaining this month: {tracker.remaining()}.")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--routes-file", default="routes.json")
    parser.add_argument("--output", default="data/real_fares.csv")
    parser.add_argument("--max-calls", type=int, default=20,
                         help="API calls to make this run (default 20/day ~= 600/month)")
    parser.add_argument("--dry-run", action="store_true",
                         help="Print what would be queried without calling the API or using quota")
    args = parser.parse_args()

    sys.exit(collect(args.routes_file, args.output, args.max_calls, args.dry_run))
