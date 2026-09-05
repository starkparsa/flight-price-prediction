# Decisions — flight-price-prediction

What was decided, why, and when to revisit. Newest first.

---

## Amadeus self-service is dead — pivot pending user's Travelpayouts terms check

**Decided**: 2026-09-05 (supersedes the entry below, kept for record)
**What happened**: user tried to sign up for Amadeus and it doesn't exist
as self-service anymore. Confirmed: Amadeus decommissioned the self-service
developer portal on **2026-07-17** — new registration was paused that
spring, existing keys are now disabled, portal inaccessible. (Enterprise
APIs still exist but require a commercial/sales relationship, not
self-service.) Everything built in the entry below (`amadeus_client.py`,
`quota_tracker.py`, `collect_fares.py`, `routes.json`, `.env.example`) is
now dead code against a nonexistent API.
**Alternatives re-surveyed same day**:
| Option | Real prices | Cost | Issue |
|---|---|---|---|
| Duffel | Yes | ~$0.005/search once past a booking-tied free allotment — effectively **~$3/month** at our planned volume with zero bookings | Not literally $0; needs an explicit budget exception |
| Sabre Dev Studio | Yes | Free sandbox (fake data) only; production is a commercial contract, reportedly $500-5,000+/month | Not viable under $0 |
| Travelpayouts Data API | Yes, crowdsourced, has `found_at` (search date) | Free | Affiliate-network terms, use-case fit unconfirmed (see open question) |
| RapidAPI "Sky Scrapper" (unofficial Skyscanner mirror) | Yes | Free tier: 100 req/month | Unofficial, no data-rights guarantee, thin volume |
| Kiwi Tequila | Yes | — | Confirmed invite-only, not accessible |
| AeroDataBox | **No prices at all** — schedules/status only | — | Eliminated outright, doesn't do what we need regardless of cost |
**Decision**: pause on the live collector. User is reading Travelpayouts'
actual terms directly ([Terms of the Travelpayouts Travel Affiliate
Network](https://support.travelpayouts.com/hc/en-us/articles/360004162111-Terms-of-the-Travelpayouts-Travel-Affiliate-Network),
[API FAQ](https://support.travelpayouts.com/hc/en-us/articles/204529267-FAQ-about-API),
[API and data docs](https://support.travelpayouts.com/hc/en-us/categories/200358578-API-and-data))
before any further code gets written against it or anything else.
One relevant detail surfaced while researching: their live real-time
search API requires "every search query must be initiated by a user,"
but that restriction is documented for the *live search* API
specifically — the **Data API** (the cached-price endpoints this project
would use: `/v1/prices/cheap`, `/v1/prices/calendar`, `/v2/prices/latest`)
is described separately as not carrying that restriction. Flagged for the
user to confirm directly rather than assumed.
**Revisit**: once the user reports back on the Travelpayouts terms. If
unusable, fall back to Duffel (with an explicit budget-exception decision)
or drop live collection for this phase and rely on the Kaggle bootstrap
dataset alone.

---

## Steady-stream data source: self-run Amadeus daily collector, not a third-party aggregator (SUPERSEDED — see entry above)

**Decided**: 2026-09-05
**Decision**: Build `collect_fares.py` as a scheduled, self-run daily
collector against the Amadeus Flight Offers Search API, rather than
depending on a third-party price-history site or aggregator API.
**Why**: Surveyed three classes of option before deciding:
- **FareDetective.com** (`faredetective.com/farehistory`) — investigated
  directly. Has an internal AJAX endpoint (`POST /faredetective/chart_data`)
  but it's undocumented, unofficial, the data it returns is stale (checked
  live: series stopped at **April 2010**), and it lacks lead-time/search-date
  fields entirely (just route+month+price). Also, its `robots.txt`
  explicitly disallows `ClaudeBot` site-wide — respected that and stopped
  investigating further. Not usable on any of the three grounds
  independently.
- **Travelpayouts/Aviasales Data API** — genuinely the best-shaped option
  found (`/v2/prices/latest` has a `found_at` field, i.e. real search-date +
  price pairs, continuously refreshed). Not chosen for the *first* build
  because it requires registering as a Travelpayouts affiliate and its docs
  describe the intended use as generating affiliate content pages — no
  clear terms found permitting bulk reuse for ML training. Left pending
  the user's own read of its terms (open question below), not ruled out.
- **Amadeus Self-Service** — official developer program, clean ToS built
  explicitly for this kind of use, free 2,000 calls/month in production.
  Doesn't arrive as a stream on its own (it's on-demand, one call = one
  query) — so the "stream" is this repo's own scheduled collector, not a
  property of the API.
**Design choices inside the collector**:
  - Deterministic day-of-epoch rotation through a fixed (route × days_out ×
    nights) grid, so repeated daily runs sweep the whole grid over time
    instead of hammering the same points — see `collect_fares.py`'s
    module docstring for the exact mechanism.
  - A local `quota_tracker.py` hard-caps monthly calls well under the free
    limit (1,800 of 2,000) so a misconfigured cron job can't generate a
    surprise bill.
  - `data/real_fares.csv` is committed to git (not gitignored) — unlike
    `synthetic_fares.csv` — because it's the actual accumulating asset
    this whole effort exists to produce, not a regenerable artifact.
**Revisit if**: the Travelpayouts terms check comes back permissive — it
would meaningfully speed up real lead-time coverage versus the Amadeus
collector alone (crowdsourced vs. self-polled), and the two aren't
mutually exclusive.

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

**Is Travelpayouts' Data API usable for this?** It's the best-shaped
third-party option found (real search-date + price pairs, continuously
refreshed, free) but its docs describe the intended use as affiliate
content generation and require joining their affiliate network — no
clear terms found permitting bulk ML-training reuse. User is checking
this themselves (2026-09-05). If it comes back permissive, it's a strong
complement to the Amadeus collector, not a replacement for it.

**How does the finished artifact actually get into Itinera's repo/deploy?**
Options not yet chosen between: hand-carry the `.joblib` + schema doc into
Itinera's backend directly once its "flights" feature work starts, vs.
opening a PR/issue against Itinera now to stage the wiring. Itinera's own
`STATUS.md` currently lists flights as "not started" with no active
branch for it — so there's nothing to PR into yet. Revisit once this
model is trained on real data and Itinera's flights work is scheduled.
