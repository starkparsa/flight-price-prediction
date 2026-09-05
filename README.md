# Flight Price Prediction

**Status**: see [`STATUS.md`](STATUS.md) for the current snapshot, next
action, and known blockers — read that before this file if you're picking
this project back up. [`decisions.md`](decisions.md) has the why behind
each choice below; [`progress.md`](progress.md) is the session diary.

A round-trip flight price prediction component being built for
integration into [Itinera](../Itinera) (a chat-driven AI trip planner).
The deliverable is a **trained model artifact + documented schema** that
a consuming backend loads directly — not a hosted API. It answers two
practical questions:

1. **Which travel dates are cheapest?** Given a route and a flexible date
   range, grid-search every (departure, return) pair and surface the
   cheapest *windows* — not just single dates.
2. **Should I buy now or wait?** Given a fixed departure/return pair, predict
   how the price is expected to move as departure approaches, and recommend
   BUY or WAIT with a rationale.

Both tools are powered by one underlying price model: gradient-boosted
quantile regressors (p10 / p50 / p90) predicting `log(price)` from route,
lead time, day-of-week, trip length, and seasonality features.

## Why quantiles, not a single number

Real fares are noisy and fare-class/quota driven. Predicting p10/p50/p90
instead of one point estimate lets the date optimizer and buy/wait
recommendation reason about uncertainty (e.g. "typical $513, but could be as
low as $458 or as high as $702") rather than presenting false precision.

## Project structure

| File | Purpose |
|---|---|
| `synthetic_data.py` | Generates synthetic fare-search data with realistic structure (lead-time U-curve, day-of-week effects, trip-length effects, seasonality). Replace with a loader over real fare-history data — the schema is documented in the module docstring. |
| `price_model.py` | Feature engineering + `PriceModel` class (p10/p50/p90 `HistGradientBoostingRegressor`s), time-based train/test split, evaluation metrics. |
| `train.py` | Driver script: generates data, trains the model, evaluates on a strictly future held-out period, saves `price_model.joblib`. |
| `date_window_optimizer.py` | Grid-searches departure/return date pairs for a route and collapses results into ranked, human-readable booking windows. |
| `buy_or_wait.py` | Given a fixed trip, projects the price trajectory forward to departure and recommends BUY or WAIT. |

## Setup

```bash
pip install -r requirements.txt
python train.py
```

This trains on synthetic data and saves `price_model.joblib`. Evaluation
metrics (MAPE, RMSE, quantile coverage) print to stdout, computed on a
held-out future date range the model never saw during training.

## Usage

**Find the cheapest travel windows for a route:**

```bash
python date_window_optimizer.py
```

**Get a buy-now-vs-wait recommendation for a specific trip:**

```bash
python buy_or_wait.py
```

Edit the `__main__` blocks in each file to change the route, date range, or
trip parameters — or import `grid_search`/`summarize_windows` and
`recommend` directly into your own script.

## Using real data instead of synthetic

Replace `synthetic_data.generate()` with a loader that returns a DataFrame
with these columns, then rerun `train.py` — nothing else changes:

```
search_date, route, departure_date, return_date, days_out, nights, stops, airline, price
```

Good sources for real fare data:
- **[BTS DB1C (Origin & Destination Survey)](https://www.bts.gov/topics/airlines-and-airports/origin-and-destination-survey-data)** — free, ticket-level US fare data, monthly 40% sample.
- **[Kaggle: Flight Prices (dilwong)](https://www.kaggle.com/datasets/dilwong/flightprices)** — scraped Expedia fares with both search date and flight date, structurally closest to what this model needs.
- **[Amadeus Self-Service Flight Offers Search API](https://developers.amadeus.com/self-service/category/flights/api-doc/flight-offers-search)** — live pricing, 2,000 free calls/month in production, unlimited in the test environment. Use it to collect real price observations over time to feed the model, rather than querying it live for every date combination.

## Model performance (on synthetic data)

Evaluated on a strictly future held-out period (never seen in training):

- MAPE: ~10.6%
- p10/p90 quantile coverage: ~89% each (target 90%)

Real-world accuracy will depend on how much historical search/price data is
available per route — a few thousand searches per route over several
months is a reasonable minimum for a usable signal.
