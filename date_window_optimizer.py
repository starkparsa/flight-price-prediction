"""
Round-trip date-window optimizer.

Given a route, a "today" search date, a range of acceptable departure dates,
and an acceptable trip-length range, this grids every (departure, return)
pair, scores it with the price model, and returns:
  1. a ranked table of the single cheapest date pairs (p10/p50/p90 predicted
     fare for each), and
  2. that same table collapsed into human-readable WINDOWS — contiguous
     departure-date ranges whose predicted median price stays within a
     tolerance of the cheapest pair, e.g.
         "Depart Mar 3-5, return Mar 10-12 (7-9 nights): predicted $612-$648"
     which is what you actually want to hand a user instead of 400 rows.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from price_model import PriceModel


def grid_search(
    model: PriceModel,
    route: str,
    today: pd.Timestamp,
    earliest_departure: pd.Timestamp,
    latest_departure: pd.Timestamp,
    min_nights: int,
    max_nights: int,
    airline: str | None = None,
    stops: int = 0,
) -> pd.DataFrame:
    departures = pd.date_range(earliest_departure, latest_departure, freq="D")
    rows = []
    for dep in departures:
        days_out = (dep - today).days
        if days_out < 0:
            continue
        for nights in range(min_nights, max_nights + 1):
            ret = dep + pd.Timedelta(days=nights)
            rows.append((dep, ret, days_out, nights))
    grid = pd.DataFrame(rows, columns=["departure_date", "return_date", "days_out", "nights"])
    grid["route"] = route
    grid["airline"] = airline or "AA"  # placeholder if not comparing airlines
    grid["stops"] = stops

    preds = model.predict(grid)
    result = pd.concat([grid, preds], axis=1)
    return result.sort_values("p50").reset_index(drop=True)


def summarize_windows(
    ranked: pd.DataFrame, top_n: int = 5, tolerance_pct: float = 0.06
) -> list[dict]:
    """Collapse the ranked grid into up to top_n non-overlapping windows,
    each anchored on a local cheap pair, absorbing neighboring dates within
    `tolerance_pct` of that pair's price."""
    remaining = ranked.copy()
    windows = []
    while len(remaining) and len(windows) < top_n:
        anchor = remaining.iloc[0]
        price_ceiling = anchor["p50"] * (1 + tolerance_pct)
        band = remaining[remaining["p50"] <= price_ceiling]
        # keep the band tight around the anchor's nights (+/-1) so it reads
        # as one coherent trip-length window rather than mixing 3-night and
        # 20-night trips just because both happen to be cheap
        band = band[(band["nights"] - anchor["nights"]).abs() <= 2]

        dep_min, dep_max = band["departure_date"].min(), band["departure_date"].max()
        ret_min, ret_max = band["return_date"].min(), band["return_date"].max()
        windows.append({
            "depart_window": f"{dep_min.date()} to {dep_max.date()}",
            "return_window": f"{ret_min.date()} to {ret_max.date()}",
            "nights_range": f"{band['nights'].min()}-{band['nights'].max()}",
            "predicted_price_low": round(band["p10"].min(), 2),
            "predicted_price_typical": round(anchor["p50"], 2),
            "predicted_price_high": round(band["p90"].max(), 2),
            "n_date_pairs_in_window": len(band),
        })
        remaining = remaining.drop(band.index)
    return windows


if __name__ == "__main__":
    import joblib

    model = joblib.load("price_model.joblib")
    today = pd.Timestamp("2025-11-01")

    ranked = grid_search(
        model,
        route="JFK-LHR",
        today=today,
        earliest_departure=today + pd.Timedelta(days=20),
        latest_departure=today + pd.Timedelta(days=90),
        min_nights=5,
        max_nights=16,
    )
    print("Top 10 individual cheapest date pairs:")
    print(ranked.head(10)[["departure_date", "return_date", "nights", "p10", "p50", "p90"]]
          .to_string(index=False))

    print("\nRecommended booking windows:")
    for w in summarize_windows(ranked, top_n=5):
        print(w)
