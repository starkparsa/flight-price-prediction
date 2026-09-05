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

**Superseded (2026-09-05, same day)**: user deprioritized the steady-stream
question — asked for "the past year or so" of real price data to start
instead, and to figure out the steady stream later. The Travelpayouts
terms check is still open (user hasn't reported back), but nothing below
depends on it anymore for now — see the BTS DB1C section that follows.

**Built and DONE (2026-09-05) — real data is in the repo**:
- `load_bts_db1c.py` — downloads and aggregates BTS's O&D DB1C Product
  File (real, ticket-level, U.S. government fare data, monthly 40%
  sample, no signup). 11 months available: July 2025 - May 2026 — this is
  the "past year or so" of real data the user asked for.
- Verified by direct inspection of the actual data (not just docs) before
  building anything on it: real routes recovered correctly (ORD-LGA,
  LAX-HNL, ATL-LGA, ...), round-trip detection works, `PurWinGrp` gives a
  genuine (coarse, 3-bucket) lead-time signal. Full detail + the
  round-trip-detection heuristic in `decisions.md`.
- One real implementation problem hit and fixed: the first version used
  pandas `groupby().agg()` with quantile lambdas and hung for 5+ minutes
  on a single 14.6M-row month with zero output — killed it and rewrote
  using DuckDB's `quantile_cont` querying the parquet directly via SQL;
  same aggregation now takes under 4 seconds.
- **`data/bts_real_fares_agg.csv` is committed**: 342,480 rows, 20,296
  real routes, all 11 months, filtered to groups with >=20 real tickets
  (dropped ~1M thinner groups where a 3-quantile estimate isn't
  trustworthy — raw unfiltered output was 1.37M rows / 90k routes / 97MB,
  right at GitHub's soft size limit; filtered version is 25MB).
- **Spot-checked the actual lead-time signal and it's real**: ORD-LGA,
  January 2026 — booking 91+ days out has a $209 median price; booking
  within 21 days of departure has a $312 median. That's the effect the
  whole buy/wait tool exists to detect, now backed by real ticket data
  instead of a hand-authored synthetic curve.

**Known, permanent limitation of this data**: month-level granularity,
not day-level. It can calibrate real price levels, route coverage, and
monthly seasonality, and can drive a coarse 3-bucket buy/wait signal — it
**cannot** power day-precise date-window search the way
`date_window_optimizer.py` currently does on synthetic data. This is an
open architecture question (see below), not something quietly absorbed.

**Not started yet — this is the actual remaining work**:
1. Once the full 11-month aggregate finishes: decide how `price_model.py`
   consumes it. It cannot go through the exact same feature pipeline as
   synthetic data (no day-of-week, no exact trip length, no per-airline
   breakdown available at this granularity) — likely needs either (a) a
   reduced-feature real-data model variant (route + month + lead-time
   bucket only), or (b) using this data purely to calibrate/sanity-check
   the synthetic-trained model's absolute price levels rather than
   retraining on it directly. Not yet decided — worth a deliberate choice
   before writing more code, not a default.
2. Separately, still available as a day-level (but 2022, stale) real data
   source if day-precision matters more than recency for a first pass:
   [dilwong/flightprices](https://www.kaggle.com/datasets/dilwong/flightprices)
   on Kaggle (credentials already present locally).
3. Write the integration schema doc: exact function signatures, input/
   output JSON shape, error format matching Itinera's `tools.py`
   convention, and how Itinera should load `price_model.joblib`.
4. Hand off: hand-carry the artifact + schema doc, or open a PR/issue in
   Itinera once its own "flights" work actually starts — TBD, not yet
   decided (see `decisions.md`'s open question).
5. Separately, still pending: the steady-stream question (Travelpayouts
   terms check) — deprioritized by the user, not abandoned.

## Known blockers / risks

- **Granularity mismatch**: BTS DB1C (month-level) vs. this repo's
  existing model (day-level synthetic). Needs a deliberate architecture
  decision, not a silent workaround — see "Not started yet" #1.
- **Turnaround-airport approximation**: for round-trip tickets with
  asymmetric outbound/return connection counts, `load_bts_db1c.py`'s
  midpoint heuristic for the destination airport can be slightly wrong.
  Rare in practice (most itineraries are symmetric) but not zero.
- **Route coverage**: BTS DB1C is U.S. domestic + U.S.-carrier
  international origin/destination — won't cover every route Itinera
  might ask about, and thin routes (few real tickets in the 40% sample)
  will have unreliable quantiles. `n_tickets` is included in the output
  specifically so low-volume groups can be filtered out downstream.
- **Timeline**: "a couple of days with full attention" — if real-data
  integration runs over that, the fallback is to ship the artifact
  trained on real data as of whatever point has been reached, clearly
  labeled with its actual training-data date range and known gaps,
  rather than silently reverting to synthetic data.

## Next action

Once the background aggregation job finishes: decide the model-adaptation
question above (#1 in "Not started yet") before writing a training script
against `data/bts_real_fares_agg.csv` — this is a real design choice, not
just plumbing.
