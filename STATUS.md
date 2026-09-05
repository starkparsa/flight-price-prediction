# STATUS — flight-price-prediction

Current snapshot. For why things are the way they are, see
[`decisions.md`](decisions.md). For the session-by-session history, see
[`progress.md`](progress.md).

_Last updated: 2026-09-04, after the initial synthetic-data pipeline was
built/validated and pushed to GitHub, and after clarifying this is a
component being built for integration into Itinera under a $0 budget and
a ~2-day timeline._

## Where the project stands

**Goal**: a trained flight price prediction model — delivered as an
artifact + input/output schema — that Itinera's backend can load to power
two capabilities: (1) find the cheapest round-trip date windows within a
flexible range, (2) recommend buy-now-vs-wait for a fixed trip. Real fare
data is required before integration (synthetic data was explicitly ruled
out as the final training source — see `decisions.md`).

**Built and validated (on synthetic data)**:
- `synthetic_data.py` — realistic fare-search generator (lead-time
  U-curve, day-of-week, trip-length, seasonality effects).
- `price_model.py` — `PriceModel` class: p10/p50/p90 quantile
  `HistGradientBoostingRegressor`s on `log(price)`, time-based split.
- `train.py` — driver: generate → train → evaluate on a future held-out
  period → save `price_model.joblib`.
- `date_window_optimizer.py` — grids departure/return date pairs, returns
  ranked cheap booking windows.
- `buy_or_wait.py` — projects price trajectory to departure, recommends
  BUY/WAIT with rationale.
- Result on synthetic data: ~10.6% MAPE, ~89% p10/p90 quantile coverage
  on a strictly future held-out period. Confirms the pipeline is sound;
  says nothing about real-world accuracy.
- Public repo live: https://github.com/starkparsa/flight-price-prediction

**Not started yet — this is the actual remaining work**:
1. Pull real fare data. Kaggle credentials already present locally
   (`~/.kaggle/kaggle.json`) — [dilwong/flightprices](https://www.kaggle.com/datasets/dilwong/flightprices)
   is the target dataset (real scraped Expedia fares with both search
   date and flight date — the only free dataset found with the fields
   this model needs). See `decisions.md` for why this beats BTS/Amadeus
   for the first real pass.
2. Build a loader that reshapes that dataset into the existing schema
   (`search_date, route, departure_date, return_date, days_out, nights,
   stops, airline, price`) so `price_model.py`/`train.py` need zero
   changes.
3. Retrain on real data, re-evaluate (expect MAPE to be meaningfully
   worse than the synthetic 10.6% — that's expected and fine, report it
   honestly rather than tuning against it).
4. Write the integration schema doc: exact function signatures, input/
   output JSON shape, error format matching Itinera's `tools.py`
   convention, and how Itinera should load `price_model.joblib`.
5. Hand off: hand-carry the artifact + schema doc, or open a PR/issue in
   Itinera once Itinera's own "flights" work actually starts — TBD, not
   yet decided (see `decisions.md`'s open question).

## Known blockers / risks

- **Route coverage**: the Kaggle dataset covers specific US city pairs
  scraped in 2022 — it will not cover every route Itinera might ask
  about. The model's accuracy outside covered routes/date-ranges is
  unknown and should be flagged as a limitation in the handoff doc, not
  silently extrapolated.
- **Staleness**: 2022 fare levels don't reflect 2026 pricing. Absolute
  price predictions will likely be off; *relative* signals (which dates/
  windows are cheaper, whether to wait) are the more defensible product
  to ship first — flag this explicitly to whoever integrates it.
- **Timeline**: "a couple of days with full attention" — if real-data
  integration runs over that, the fallback is to ship the artifact
  trained on real data as of whatever point has been reached, clearly
  labeled with its actual training-data date range and known gaps,
  rather than silently reverting to synthetic data.

## Next action

Build the Kaggle data loader (`load_kaggle_flightprices.py`) and rerun
`train.py` against it.
