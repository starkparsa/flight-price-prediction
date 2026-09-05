# Decisions — flight-price-prediction

What was decided, why, and when to revisit. Newest first.

---

## Deliverable shape: trained artifact + schema, not a REST service

**Decided**: 2026-09-04
**Decision**: The integration surface for Itinera is a trained model
artifact (`price_model.joblib`) plus a documented function-level
input/output schema — not a running HTTP service this repo hosts.
**Why**: Itinera's own backend is FastAPI and already has a `tools.py`
pattern for wrapping capabilities as small, flat-JSON, never-raising
functions. Standing up a second service (auth, deployment, uptime) for a
single model call is unnecessary overhead versus Itinera importing the
artifact directly into its own process.
**Revisit if**: the model needs to be shared across multiple independent
products/services (not just Itinera), or needs to retrain/refresh on a
schedule Itinera's deploy cycle can't accommodate — either would justify
a standalone service instead.

---

## Real data source: Kaggle dilwong/flightprices, not BTS or Amadeus

**Decided**: 2026-09-04
**Decision**: First real-data training pass uses the Kaggle
[dilwong/flightprices](https://www.kaggle.com/datasets/dilwong/flightprices)
dataset (scraped Expedia one-way fares, Apr–Oct 2022, with both search
date and flight date).
**Why**: Under the inherited $0-budget constraint and a ~2-day timeline,
this was the only free, immediately-downloadable option with the exact
fields the model needs (a paired search-date + flight-date, which is what
makes the lead-time/date-window modeling possible at all):
- **BTS DB1C** (free, real, government-sourced) has real ticket-level
  fares but is quarterly/monthly-aggregated market data — no per-search
  lead-time signal, so it can't drive the date-window optimizer or
  buy/wait tool, only a route-level seasonal baseline.
- **Amadeus Self-Service API** (free tier, 2,000 calls/month in
  production) gives live, current prices — but building a *dataset* from
  it means querying it repeatedly over time to observe how price moves
  with lead time, which the 2-day timeline doesn't allow. It remains the
  right choice for *keeping the model fresh* later, not for the initial
  training pass.
- **Kiwi Tequila / Skyscanner official APIs**: confirmed closed to new
  developers as of this check (2026-09-04) — not viable at all.
**Known cost of this choice**: 2022 US-route-only data. Absolute price
levels will be stale and route coverage is limited — documented as an
explicit limitation in `STATUS.md`, not hidden.
**Revisit if**: Itinera's actual flight feature scope needs routes/regions
outside what dilwong/flightprices covers, or once there's time budget to
run a proper Amadeus collection campaign (query a fixed route/date matrix
daily for a few weeks) to get current, lead-time-labeled data.

---

## Model family: sklearn HistGradientBoostingRegressor over LightGBM/XGBoost

**Decided**: 2026-09-04
**Decision**: Use sklearn's built-in `HistGradientBoostingRegressor`
(quantile loss) rather than installing LightGBM or XGBoost.
**Why**: Equivalent algorithm family (histogram-based gradient boosting),
already available in the environment with zero install risk, and
supports native quantile loss out of the box. Avoided an extra dependency
under time pressure.
**Revisit if**: real-data accuracy is insufficient and a few extra points
of MAPE from LightGBM/XGBoost's more mature categorical handling would
matter enough to justify the added dependency — worth a quick A/B once
real data is in.

---

## Predict quantiles (p10/p50/p90), not a single point estimate

**Decided**: 2026-09-04
**Decision**: Every price prediction is three numbers (p10/p50/p90 of
`log(price)`), not one.
**Why**: Both downstream tools need uncertainty, not just a point:
`date_window_optimizer` reports a price *range* per window so a window
with a low median but huge variance can be seen for what it is; `buy_or_
wait` needs the trajectory's spread to judge how confident the BUY/WAIT
call actually is.
**Revisit if**: never, unless downstream Itinera UX genuinely only wants
one number — in which case collapse to p50 at the presentation layer, not
by retraining a point-estimate model.

---

## Train/test split by date, never randomly

**Decided**: 2026-09-04
**Decision**: All evaluation holds out a strictly future date range
(`time_based_split`), never a random row split.
**Why**: A random split lets the model see prices from dates
chronologically after some training examples, which leaks the future
into training and produces evaluation numbers that look good but don't
reflect real forecasting ability (you can never randomly sample "the
future" in production).
**Revisit if**: never — this is a correctness requirement, not a
preference.

---

## Repo hosting: public GitHub repo (starkparsa/flight-price-prediction)

**Decided**: 2026-09-04
**Decision**: Public repo, pushed to https://github.com/starkparsa/flight-price-prediction,
cloned locally to `C:\Mine\Projects\flight-price-prediction`.
**Why**: User explicitly chose public over private when asked (no
sensitive data in the repo — synthetic data, no credentials).
**Revisit if**: real trained model or data pulled in later turns out to
carry anything sensitive (unlikely for public flight fare data, but check
before any future data source swap).

---

## Open question — not yet decided

**How does the finished artifact actually get into Itinera's repo/deploy?**
Options not yet chosen between: hand-carry the `.joblib` + schema doc into
Itinera's backend directly once its "flights" feature work starts, vs.
opening a PR/issue against Itinera now to stage the wiring. Itinera's own
`STATUS.md` currently lists flights as "not started" with no active
branch for it — so there's nothing to PR into yet. Revisit once this
model is trained on real data and Itinera's flights work is scheduled.
