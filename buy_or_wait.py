"""
Buy-now-vs-wait recommendation for a FIXED (departure, return) pair.

Idea: hold the trip's departure/return dates fixed, and vary only the
"as of" search date (i.e. days_out shrinking day by day as today approaches
departure). The price model gives you the predicted fare trajectory for
that specific trip as time passes. Compare:
  - today's predicted price (or the actual quoted price, if you pass one)
  - the minimum the model expects to see between now and departure

If today's price is already at/near the expected future minimum -> BUY.
If the model expects a materially lower price later (and there's still
runway before the "last-minute markup" zone kicks in) -> WAIT.
Otherwise -> NEUTRAL, with the trajectory shown so the user can judge risk
appetite themselves.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from price_model import PriceModel


def price_trajectory(
    model: PriceModel,
    route: str,
    departure_date: pd.Timestamp,
    return_date: pd.Timestamp,
    today: pd.Timestamp,
    airline: str = "AA",
    stops: int = 0,
) -> pd.DataFrame:
    nights = (return_date - departure_date).days
    future_search_dates = pd.date_range(today, departure_date - pd.Timedelta(days=1), freq="D")
    if len(future_search_dates) == 0:
        future_search_dates = pd.DatetimeIndex([today])

    rows = pd.DataFrame({
        "search_date": future_search_dates,
        "departure_date": departure_date,
        "return_date": return_date,
        "days_out": (departure_date - future_search_dates).days,
        "nights": nights,
        "route": route,
        "airline": airline,
        "stops": stops,
    })
    preds = model.predict(rows)
    return pd.concat([rows[["search_date", "days_out"]], preds], axis=1)


def recommend(
    model: PriceModel,
    route: str,
    departure_date: pd.Timestamp,
    return_date: pd.Timestamp,
    today: pd.Timestamp,
    current_quoted_price: float | None = None,
    airline: str = "AA",
    stops: int = 0,
    wait_threshold_pct: float = 0.05,
) -> dict:
    traj = price_trajectory(model, route, departure_date, return_date, today, airline, stops)
    today_row = traj.iloc[0]
    current_price = current_quoted_price if current_quoted_price is not None else today_row["p50"]

    future_min_p50 = traj["p50"].min()
    future_min_date = traj.loc[traj["p50"].idxmin(), "search_date"]
    days_to_departure_at_min = traj.loc[traj["p50"].idxmin(), "days_out"]

    gap_pct = (current_price - future_min_p50) / current_price

    if gap_pct > wait_threshold_pct and days_to_departure_at_min >= 10:
        action = "WAIT"
        rationale = (
            f"Model expects the median price to drop to ~${future_min_p50:.0f} "
            f"around {future_min_date.date()} ({int(days_to_departure_at_min)} days out), "
            f"~{gap_pct*100:.1f}% below today's ${current_price:.0f}."
        )
    elif gap_pct < -wait_threshold_pct:
        action = "BUY"
        rationale = (
            f"Today's price (${current_price:.0f}) is already below the model's expected "
            f"future minimum (~${future_min_p50:.0f}). Prices are more likely to rise from here."
        )
    else:
        action = "BUY"
        rationale = (
            f"Today's price (${current_price:.0f}) is within {abs(gap_pct)*100:.1f}% of the "
            f"expected future floor (~${future_min_p50:.0f}) — little upside to waiting, "
            f"and downside risk (sellout, fare increase) grows closer to departure."
        )

    return {
        "action": action,
        "rationale": rationale,
        "current_price": round(float(current_price), 2),
        "expected_future_min_price": round(float(future_min_p50), 2),
        "expected_future_min_date": str(future_min_date.date()),
        "price_uncertainty_band_today": [round(float(today_row["p10"]), 2), round(float(today_row["p90"]), 2)],
        "trajectory": traj,
    }


if __name__ == "__main__":
    import joblib

    model = joblib.load("price_model.joblib")
    today = pd.Timestamp("2025-11-01")
    dep = pd.Timestamp("2025-11-25")
    ret = pd.Timestamp("2025-12-05")

    result = recommend(model, "JFK-LHR", dep, ret, today)
    print(f"Action: {result['action']}")
    print(f"Rationale: {result['rationale']}")
    print(f"Current predicted price: ${result['current_price']}")
    print(f"Expected future min: ${result['expected_future_min_price']} "
          f"around {result['expected_future_min_date']}")
    print(f"Today's uncertainty band (p10-p90): {result['price_uncertainty_band_today']}")
