# Progress — flight-price-prediction

Dated diary of what happened each session. Newest first.

---

## 2026-09-04

**Context established**: this started as a general "how would I build a
flight price predictor" conversation, then was scoped down through direct
questions into: a component being built for integration into **Itinera**
(existing chat-driven trip planner, "flights" listed as not-started),
under Itinera's inherited **$0 budget** constraint, on a **~2-day**
timeline, with the deliverable being a **trained model artifact +
schema** (not a hosted API) that Itinera's backend will load directly.

**Built and validated** (synthetic data, to prove the pipeline before
spending the timeline on real data):
- `synthetic_data.py`: generator encoding known real-world fare drivers
  (lead-time U-curve trough ~50 days out, day-of-week effects, trip-length
  effects, seasonality) with noise + occasional demand shocks.
- `price_model.py`: `PriceModel` — p10/p50/p90
  `HistGradientBoostingRegressor`s predicting `log(price)`, ordinal-
  encoded categoricals (route, airline) — hit a bug here, see below.
- `train.py`: driver script (generate → time-based split → train →
  evaluate → save `price_model.joblib`).
- `date_window_optimizer.py`: grid-search over (departure, return) pairs,
  collapses into ranked human-readable windows with a price tolerance
  band.
- `buy_or_wait.py`: fixed-trip price trajectory projection + BUY/WAIT
  recommendation with rationale.

**Bugs hit and fixed this session**:
1. `HistGradientBoostingRegressor(categorical_features=...)` on sklearn
   1.3.2 failed trying to cast the raw string category column to float —
   that sklearn version needs categoricals pre-encoded (ordinal), not
   just dtype-tagged as `category`. Fixed by adding an `OrdinalEncoder`
   step in `PriceModel.fit`/`_prep` instead of relying on native
   categorical passthrough.
2. Loading `price_model.joblib` from a fresh script (`test_wait_case.py`)
   threw `AttributeError: Can't get attribute 'PriceModel' on <module
   '__main__'>` — the model had been pickled while `price_model.py` was
   itself running as `__main__`, so joblib recorded the class's module as
   `__main__` instead of `price_model`. Fixed by moving training into a
   separate `train.py` driver so the class is always pickled under its
   real importable module path.

**Verified**: 10.6% MAPE / ~89% p10-p90 coverage on a strictly future
held-out period; date optimizer correctly recovered the synthetic
lead-time trough (~50 days out, 7-14 nights); buy/wait correctly returned
BUY for a booking already near the trough and WAIT (with a 37% expected
drop) for a booking made 7.5 months early.

**Repo work**:
- Created public GitHub repo `starkparsa/flight-price-prediction`,
  pushed initial commit (README, requirements.txt, .gitignore, the 5
  modules above).
- Cloned/copied to `C:\Mine\Projects\flight-price-prediction`; moved this
  Claude Code session's working directory there.
- Discovered (by reading Itinera's own `CLAUDE.md`/`STATUS.md`) that
  Itinera already uses this exact README/CLAUDE/STATUS/decisions/
  progress file split, that it's FastAPI + SQLAlchemy + Postgres with a
  `tools.py` tool-function convention, and that it runs under a **$0
  budget** — all of which directly shaped the decisions logged in
  `decisions.md` today (deliverable shape, data source choice).
- Confirmed Kaggle API credentials already exist locally
  (`~/.kaggle/kaggle.json`), making `dilwong/flightprices` the practical
  choice for real data given the timeline (see `decisions.md`).

**Next action** (per `STATUS.md`): build a loader that reshapes
`dilwong/flightprices` into this repo's existing schema and rerun
`train.py` against real data.
