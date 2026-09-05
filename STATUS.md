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

**Built since (steady-stream data collection, 2026-09-05)**:
- `amadeus_client.py` — Amadeus Flight Offers Search wrapper (OAuth2,
  never raises, `{"error": ...}` on failure — matches Itinera's `tools.py`
  convention already).
- `quota_tracker.py` — local monthly call-count guard, hard-capped under
  Amadeus's free 2,000/month production limit.
- `collect_fares.py` — the actual steady-stream collector. Run daily, it
  queries a deterministically-rotating slice of (route, days_out, nights)
  combinations and appends real current prices to `data/real_fares.csv`
  in this repo's existing schema. Verified: dry-run mode works, quota
  guard correctly refuses to burn quota on a local auth/config failure
  (caught and fixed a bug where it originally did).
- `routes.json` — placeholder route list; **needs updating** to whatever
  routes Itinera actually needs once that's known.
- Not yet run against a real Amadeus account — needs a free
  developers.amadeus.com signup + API key (the user's own signup; not
  something this session can do on their behalf) before it produces any
  real rows.

**Not started yet — this is the actual remaining work**:
1. User signs up for Amadeus, adds credentials to `.env`, edits
   `routes.json`, and schedules `collect_fares.py` to run daily.
2. Pull the Kaggle bootstrap dataset. Kaggle credentials already present
   locally (`~/.kaggle/kaggle.json`) — [dilwong/flightprices](https://www.kaggle.com/datasets/dilwong/flightprices)
   is the target (real scraped Expedia fares with both search date and
   flight date). See `decisions.md` for why this is the bootstrap source
   while `collect_fares.py`'s output accumulates in parallel.
3. Build a loader that reshapes the Kaggle dataset into the existing
   schema so `price_model.py`/`train.py` need zero changes.
4. Retrain on real (Kaggle-bootstrapped, later Amadeus-augmented) data,
   re-evaluate honestly (expect MAPE meaningfully worse than the
   synthetic 10.6% — report it, don't tune against it).
5. Write the integration schema doc: exact function signatures, input/
   output JSON shape, error format matching Itinera's `tools.py`
   convention, and how Itinera should load `price_model.joblib`.
6. Hand off: hand-carry the artifact + schema doc, or open a PR/issue in
   Itinera once its own "flights" work actually starts — TBD, not yet
   decided (see `decisions.md`'s open question).

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

Two independent tracks, can happen in either order:
1. User: sign up for Amadeus, configure `.env`, edit `routes.json`,
   schedule `collect_fares.py` daily — starts the real-data clock ticking.
2. Build the Kaggle data loader (`load_kaggle_flightprices.py`) and rerun
   `train.py` against it — gets a real-data-trained model without
   waiting on the collector to accumulate enough spread.
