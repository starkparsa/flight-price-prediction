# Progress — flight-price-prediction

Dated diary of what happened each session. Newest first.

---

## 2026-09-05 (continued) — Amadeus pivot

User tried to actually sign up for Amadeus (from this session's own
instructions) and it doesn't exist as self-service anymore. Confirmed via
search: Amadeus decommissioned the self-service developer portal on
2026-07-17 (registration had already been paused since spring 2026) —
everything built earlier today (`amadeus_client.py`, `quota_tracker.py`,
`collect_fares.py`, `routes.json`, `.env.example`) is now dead code
against a nonexistent API.

Re-surveyed alternatives: Duffel (real prices, effectively ~$3/month at
our volume once you factor the search-to-book ratio fee — not literally
free), Sabre Dev Studio (sandbox-only free, production is a $500+/month
commercial contract), Travelpayouts (still the best-shaped free option,
terms still unconfirmed), RapidAPI's unofficial Skyscanner mirror (100
free requests/month, unofficial), and re-confirmed Kiwi Tequila is still
invite-only. Also checked AeroDataBox directly — it has zero price data,
schedules/status only, eliminated outright regardless of cost.

Asked the user how to proceed given no option is both free and
unambiguous the way Amadeus was. **Decision: hold everything, user is
reading Travelpayouts' actual terms directly** (linked in `decisions.md`)
before any further code gets written. Updated `STATUS.md` and
`decisions.md` to mark the Amadeus work as dead/blocked rather than
silently leaving stale "next action" instructions pointing at a signup
flow that no longer exists.

**Not done this session**: no rewrite of the collector yet — waiting on
the user's terms review before choosing Travelpayouts vs. Duffel vs.
dropping live collection for this phase.

---

## 2026-09-05

**Grilled the project scope** at the user's request before touching code
again: wrote `CLAUDE.md`/`STATUS.md`/`decisions.md`/`progress.md` (this
file), mirroring Itinera's own doc-split convention (discovered by reading
Itinera's `CLAUDE.md` directly). This surfaced the real constraints —
Itinera integration, $0 budget, ~2-day timeline, artifact-not-API delivery,
real-data-required — that shaped everything below.

**Searched existing open-source repos** before building further, per the
user's request not to reinvent something that already exists. Checked ~15
repos by star count and by direct relevance to "buy or wait". Findings: the
popular ones (Mandal-21/Flight-Price-Prediction at 236★ down to ~10★) are
all the same pattern — single point-estimate regression on the Kaggle
Indian-flights or scraped-Kayak dataset, no lead-time modeling, no
date-window search, no buy/wait logic. Nothing found is more capable than
what's already in this repo. Two smaller repos aimed at "buy or wait"
specifically: `adriancervero/flight-prices-prediction` (classification
framing instead of regression, worth noting as a method but built on the
now-closed Kiwi API, unmaintained since 2022) and
`VishalMurali/flight-price-predictor` (turned out to be republishing a
Hopper interview take-home dataset — real OTA data with exactly our
schema, but no license and unclear redistribution rights; handed the link
to the user to evaluate themselves rather than deciding for them).

**Investigated faredetective.com/farehistory** for a usable API at the
user's request. Found an internal `POST /faredetective/chart_data`
endpoint by watching network traffic, but: data is stale (stopped at April
2010), lacks lead-time/search-date fields, and the site's `robots.txt`
explicitly disallows `ClaudeBot` — stopped there rather than pushing
further. Reported all three reasons rather than picking one.

**Researched steady-stream (ongoing, not one-time) data options** at the
user's request. Compared FareDetective (ruled out above), Travelpayouts/
Aviasales Data API (best-shaped but affiliate-terms ambiguity — left as an
open question for the user to check), Amadeus Self-Service (official,
clean terms, on-demand rather than a stream by itself), and BTS DB1C
(genuinely ongoing but monthly-grain, no lead-time field). Recommended
building a self-run daily collector against Amadeus. User approved.

**Built the Amadeus collector**:
- `amadeus_client.py` — OAuth2 client-credentials wrapper, a tiny built-in
  `.env` loader (avoided adding `python-dotenv` as a dependency), never
  raises publicly (Itinera `tools.py`-style `{"error": ...}` returns).
- `quota_tracker.py` — local monthly call-count guard, capped at 1,800 of
  Amadeus's free 2,000/month production limit.
- `collect_fares.py` — deterministic day-of-epoch rotation through a
  (route × days_out × nights) grid, appends real offers to
  `data/real_fares.csv` in the existing schema.
- `routes.json` — placeholder route list (needs updating once Itinera's
  actual target routes are known).
- `.env.example` — credential template, real `.env` gitignored.

**Bug caught and fixed during testing**: the first version incremented
the monthly quota counter even when the call never reached Amadeus (missing
credentials, failed locally at token acquisition) — verified by running
without credentials and inspecting `.amadeus_quota.json`, which showed 2
calls recorded for 2 calls that never left the machine. Fixed by adding a
preflight token check in `collect_fares.py` that aborts before the loop
(and before any quota is recorded) if authentication fails, rather than
recording each failed attempt as a used call inside the loop. Verified the
fix: reset the quota file, reran, confirmed it no longer gets created on an
auth failure.

**Also cleaned up**: deleted a leftover header-only `data/real_fares.csv`
that an earlier pre-fix test run had created, so nothing fake ships in the
repo.

**Not done yet**: the collector has never actually run against a real
Amadeus account — that needs the user's own free signup (account creation
isn't something this session does on someone's behalf) plus `.env`
configuration and a daily schedule (cron/Task Scheduler), none of which
happened this session.

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
