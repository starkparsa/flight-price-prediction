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
| `load_bts_db1c.py` | **The real bootstrap data loader.** Downloads and aggregates BTS's O&D DB1C Product File (real U.S. government ticket data, 11 months: Jul 2025 - May 2026) into `data/bts_real_fares_agg.csv` — see "Real bootstrap data" below. |
| `amadeus_client.py`, `quota_tracker.py`, `collect_fares.py`, `routes.json` | **Dead code** — built for a live daily collector against Amadeus's Flight Offers Search API, which was decommissioned (2026-07-17) before it could ever be used. Kept for reference; see in-file warnings and `decisions.md`. |

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
- **BTS DB1C, via `load_bts_db1c.py` in this repo** — the current real bootstrap source. See below.
- **[Kaggle: Flight Prices (dilwong)](https://www.kaggle.com/datasets/dilwong/flightprices)** — scraped Expedia fares with both search date and flight date, day-level (but from 2022 — not "the past year"). A secondary option if day-level precision matters more than recency.
- ~~Amadeus Self-Service Flight Offers Search API~~ — **decommissioned 2026-07-17**, no longer available. `amadeus_client.py`/`collect_fares.py` are dead code kept for reference.

## Real bootstrap data: BTS DB1C

`data/bts_real_fares_agg.csv` is committed in this repo: **342,480 rows,
20,296 real U.S. routes, 11 months (July 2025 - May 2026)**, aggregated
from BTS's O&D DB1C Product File — real ticket-level government fare data,
monthly 40% sample, freely downloadable with no signup. Regenerate it
(or extend it as new months are published) with:

```bash
python load_bts_db1c.py                    # downloads all known months + aggregates (~11GB, takes a while)
python load_bts_db1c.py --skip-download    # re-aggregate from already-cached files in .bts_cache/ (seconds)
python load_bts_db1c.py --months 202605    # just one month, for testing
```

**What's in each row**: `origin`, `destination`, `year`, `month`,
`purwin` (purchase-window bucket: `21AP`/`2290`/`91UP` = booked ≤21 /
22-90 / 91+ days before departure), `n_tickets`, `price_p10`/`price_p50`/
`price_p90` (per-passenger, round-trip only — one-way tickets are
dropped), `days_out_midpoint` (an approximate numeric lead time derived
from `purwin`, for anything downstream that wants a number rather than a
bucket label).

**What this data can and can't do** — read before using it for anything:
- Real price levels, real route coverage, real monthly seasonality, and a
  genuine (if coarse) lead-time effect: e.g. ORD-LGA in Jan 2026 shows a
  $209 median fare booked 91+ days out vs. $312 booked within 21 days.
- **Cannot** drive day-precise date-window search — the source data is
  month-level, not day-level (`SchFlMo_1` etc. give only the travel
  month). `date_window_optimizer.py`'s day-by-day grid search is not
  something this data source can honestly back; that gap is still open
  (see `STATUS.md`).
- Filtered to route/month/purwin groups with ≥20 real tickets
  (`--min-tickets`, default 20) — below that, a 3-quantile estimate isn't
  trustworthy. The unfiltered aggregate is 1.37M rows / 90k routes / 97MB;
  filtering trades thin/noisy routes for a file 4x smaller and estimates
  that are actually meaningful.
- Full detail on the round-trip-detection heuristic (there's no explicit
  round-trip column in the source; it's inferred from the itinerary path)
  and every other design choice: `decisions.md`.

Raw downloads land in `.bts_cache/` (gitignored, ~11GB total — regenerate
locally, don't expect it in the repo).

## Model performance (on synthetic data)

Evaluated on a strictly future held-out period (never seen in training):

- MAPE: ~10.6%
- p10/p90 quantile coverage: ~89% each (target 90%)

This is the synthetic-data pipeline's validation number, not a real-world
accuracy claim. `price_model.py` has not yet been retrained against
`data/bts_real_fares_agg.csv` — see `STATUS.md` for why that's a real
design decision (the BTS data has a coarser feature set: no day-of-week,
no exact trip length) rather than a drop-in swap.
