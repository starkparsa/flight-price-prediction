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

**BLOCKED — Amadeus self-service is dead (discovered 2026-09-05).** Amadeus
decommissioned its self-service developer portal on 2026-07-17 (new
registration was paused that spring); the user hit this directly trying to
sign up. `amadeus_client.py` / `quota_tracker.py` / `collect_fares.py` /
`routes.json` / `.env.example` are now **dead code against a nonexistent
API** — left in the repo for reference (the rotation/quota-guard design is
reusable against a different provider) but not wired to anything live.
See `decisions.md`'s pivot entry for the full alternative comparison
(Duffel, Sabre, Travelpayouts, RapidAPI mirrors — none free-and-unambiguous
the way Amadeus was).

**Current plan (as of 2026-09-05, awaiting user input)**: user is reading
Travelpayouts' actual terms (linked in `decisions.md`) to decide if its
Data API — genuinely free, real crowdsourced fares with search-date via
`found_at` — is usable for this. Nothing else proceeds on the live-collector
front until that comes back one way or the other. If it comes back
unusable, the fallback options in the comparison table are Duffel (~$3/mo,
needs an explicit budget-exception decision) or dropping live collection
for this phase entirely (Kaggle-only).

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

1. **Blocked on user**: read Travelpayouts' terms (linked in `decisions.md`)
   and decide if its Data API is usable — this determines whether the
   live-collector code gets rewritten against Travelpayouts, rewritten
   against Duffel (with an explicit $0-budget exception), or dropped for
   this phase.
2. **Not blocked, can proceed independently**: build the Kaggle data
   loader (`load_kaggle_flightprices.py`) and rerun `train.py` against
   it — gets a real-data-trained model regardless of how the live-stream
   question resolves.
