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
| `amadeus_client.py` | Thin wrapper over the Amadeus Flight Offers Search API — OAuth2 token handling, never raises (returns `{"error": ...}`). |
| `quota_tracker.py` | Local monthly call-count guard so the free-tier Amadeus quota is never silently exceeded. |
| `collect_fares.py` | **The steady-stream data collector.** Run daily (cron/Task Scheduler) to append real, current fares to `data/real_fares.csv` in this repo's schema — see "Collecting real data" below. |
| `routes.json` | Routes the collector queries — edit this to match whatever routes Itinera actually needs; ships with a placeholder set. |

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
- **[BTS DB1C (Origin & Destination Survey)](https://www.bts.gov/topics/airlines-and-airports/origin-and-destination-survey-data)** — free, ticket-level US fare data, monthly 40% sample. One-time bulk download, not a stream.
- **[Kaggle: Flight Prices (dilwong)](https://www.kaggle.com/datasets/dilwong/flightprices)** — scraped Expedia fares with both search date and flight date. One-time bulk download; used to bootstrap the first real-data training pass (see `decisions.md`).
- **Amadeus Self-Service Flight Offers Search API, via `collect_fares.py` in this repo** — the ongoing steady-stream source. See below.

## Collecting real data (the steady stream) — currently blocked

**Amadeus decommissioned its self-service developer portal on
2026-07-17** — the collector described below can no longer be used as-is.
See `STATUS.md` and `decisions.md` for the current plan (evaluating
Travelpayouts as a replacement data source). The rest of this section
describes the original design, kept because the rotation/quota-guard
pattern is reusable against whatever provider replaces Amadeus.

`collect_fares.py` queries the Amadeus Flight Offers Search API for a
rotating slice of (route, departure date, trip length) combinations each
time it runs, and appends real current prices to `data/real_fares.csv` —
same schema as everywhere else in this repo, so it's a drop-in replacement
for the synthetic/Kaggle data once enough has accumulated.

**Setup**:
1. Free signup at [developers.amadeus.com](https://developers.amadeus.com) → create a Self-Service app → copy the Client ID/Secret.
2. `cp .env.example .env` and fill in `AMADEUS_CLIENT_ID` / `AMADEUS_CLIENT_SECRET`.
3. Edit `routes.json` to the routes you actually care about.

**Run it**:
```bash
python collect_fares.py --dry-run        # see what it would query, no API calls
python collect_fares.py                  # real run, 20 calls by default
```

**Run it daily** (this is what makes it a stream rather than a one-off):
schedule `python collect_fares.py` once a day via cron or Windows Task
Scheduler. Each run queries a different rotating slice of the
route/lead-time/trip-length grid (`collect_fares.py`'s docstring explains
the rotation), so over weeks the dataset naturally builds up real
coverage across lead times — exactly the signal the model needs and can't
get from a single bulk dataset.

**Cost safety**: `quota_tracker.py` tracks calls made this calendar month
in a local file and refuses to run once within a safety margin of
Amadeus's free 2,000/month production limit (default cap: 1,800). At the
default 20 calls/day this never gets close (~600/month).

## Model performance (on synthetic data)

Evaluated on a strictly future held-out period (never seen in training):

- MAPE: ~10.6%
- p10/p90 quantile coverage: ~89% each (target 90%)

Real-world accuracy will depend on how much historical search/price data is
available per route — a few thousand searches per route over several
months is a reasonable minimum for a usable signal.
