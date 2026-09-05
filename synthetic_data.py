"""
Generates synthetic round-trip fare-search data with the same *structure* as
real OTA fare logs (Kaggle flight-price datasets, Expedia ICDM13, etc.):

    search_date, route, departure_date, return_date, airline, stops, price

The "true" price-generating process encodes the well-documented real-world
drivers of airfare so the model has genuine signal to recover:
  - base fare per route
  - U-shaped lead-time curve (expensive very close-in AND very far out,
    cheapest ~6-8 weeks before departure for many routes)
  - day-of-week effects (depart Tue/Wed cheaper, Fri/Sun pricier)
  - trip-length effects (short trips and very long trips cost more;
    a 7-14 day round trip is often the local price minimum)
  - seasonality (summer / holiday peaks)
  - random daily noise + occasional demand shocks

Swap this module out for a loader over your real fare-history table and
nothing downstream changes, as long as you produce a DataFrame with the
same columns.
"""
import numpy as np
import pandas as pd

RNG = np.random.default_rng(42)

ROUTES = {
    "JFK-LHR": 550,
    "SFO-NRT": 700,
    "ORD-CDG": 600,
    "LAX-SYD": 900,
    "ATL-MIA": 150,
}


def _lead_time_multiplier(days_out: np.ndarray) -> np.ndarray:
    # U-shaped curve: high when booking last-minute (<14d) or very early (>180d),
    # trough around 45-60 days out.
    d = np.clip(days_out, 0, 330)
    trough = 50.0
    width = 55.0
    return 1.0 + 0.55 * np.exp(-((d - trough) ** 2) / (2 * width**2)) * -1 + 0.55 \
        + 0.9 * np.exp(-d / 10.0) \
        + 0.35 * (d > 200) * ((d - 200) / 130.0)


def _dow_multiplier(dow: np.ndarray) -> np.ndarray:
    # 0=Mon ... 6=Sun. Tue/Wed cheapest, Fri/Sun priciest.
    table = np.array([1.00, 0.92, 0.90, 0.97, 1.12, 1.05, 1.15])
    return table[dow]


def _trip_length_multiplier(nights: np.ndarray) -> np.ndarray:
    n = np.clip(nights, 1, 30)
    # local minimum around 7-14 nights, penalty for very short (<3) or long (>21)
    return 1.0 + 0.30 * np.exp(-((n - 10) ** 2) / (2 * 6.0**2)) * -1 + 0.30 \
        + 0.25 * (n < 3) + 0.15 * (n > 21)


def _seasonality_multiplier(month: np.ndarray) -> np.ndarray:
    table = {1: 0.95, 2: 0.92, 3: 1.0, 4: 1.05, 5: 1.05, 6: 1.20,
             7: 1.30, 8: 1.25, 9: 1.0, 10: 0.95, 11: 1.05, 12: 1.25}
    return np.array([table[m] for m in month])


def generate(n_searches: int = 40000, seed: int = 42) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    routes = rng.choice(list(ROUTES.keys()), size=n_searches)
    base_price = np.array([ROUTES[r] for r in routes])

    search_date = pd.Timestamp("2025-01-01") + pd.to_timedelta(
        rng.integers(0, 365, n_searches), unit="D"
    )
    days_out = rng.integers(1, 300, n_searches)
    departure_date = search_date + pd.to_timedelta(days_out, unit="D")
    nights = rng.integers(1, 28, n_searches)
    return_date = departure_date + pd.to_timedelta(nights, unit="D")

    dow = departure_date.dayofweek.values
    month = departure_date.month.values

    mult = (
        _lead_time_multiplier(days_out)
        * _dow_multiplier(dow)
        * _trip_length_multiplier(nights)
        * _seasonality_multiplier(month)
    )
    noise = rng.normal(1.0, 0.08, n_searches)
    demand_shock = rng.choice([1.0, 1.0, 1.0, 1.0, 1.35], size=n_searches)  # occasional spike
    price = np.round(base_price * mult * noise * demand_shock, 2)
    price = np.clip(price, 60, None)

    stops = rng.choice([0, 1, 2], size=n_searches, p=[0.45, 0.4, 0.15])
    airline = rng.choice(["AA", "DL", "UA", "BA", "AF", "JL"], size=n_searches)

    df = pd.DataFrame({
        "search_date": search_date,
        "route": routes,
        "departure_date": departure_date,
        "return_date": return_date,
        "days_out": days_out,
        "nights": nights,
        "stops": stops,
        "airline": airline,
        "price": price,
    })
    return df


if __name__ == "__main__":
    df = generate()
    print(df.head())
    print(df.shape)
    df.to_csv("synthetic_fares.csv", index=False)
    print("wrote synthetic_fares.csv")
