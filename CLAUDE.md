# CLAUDE.md — flight-price-prediction

This file stays short on purpose — it's auto-loaded as project instructions
every session. Read [`STATUS.md`](STATUS.md) next (current snapshot, next
action, blockers), then [`decisions.md`](decisions.md) for anything you're
about to touch or reconsider. [`progress.md`](progress.md) is the
session-by-session diary. [`README.md`](README.md) is what a new reader
(or Itinera's team) needs to run and integrate this.

## What this is

A flight price prediction component being built **for integration into
[Itinera](../Itinera)** (a chat-driven AI trip planner where "flights" is
a listed-but-not-started capability). The deliverable is a **trained model
artifact + documented input/output schema** — not a running service.
Itinera's own backend imports/loads the artifact; this repo does not need
to expose a REST API to satisfy the integration, though a demo
dashboard/CLI may exist here for testing.

## Operating principles

1. **The trained artifact + schema is the deliverable.** Any API/dashboard
   built here is scaffolding for testing and demoing, not the integration
   surface. Don't let scaffolding work block finishing the artifact.
2. **$0 budget, inherited from Itinera.** No paid APIs at runtime. Live
   API calls (Amadeus, etc.) are acceptable only as a one-time/occasional
   *data collection* step against a free tier — never as a per-request
   dependency of the shipped model.
3. **Match Itinera's tool contract** (see its `backend/app/tools.py`
   pattern): functions return small, flat, pre-aggregated JSON: never
   raise, return `{"error": ...}` on failure instead. Design this repo's
   public functions (`grid_search`, `summarize_windows`, `recommend`) to
   be directly wrappable in that pattern.
4. **Always split train/test by date, never randomly.** A random split
   leaks future price information into training and silently inflates
   accuracy. Every evaluation in this repo must hold out a strictly future
   date range.
5. **Predict quantiles (p10/p50/p90), never a single point estimate.**
   Real fares are noisy/quota-driven; the date-optimizer and buy/wait
   tools both need an uncertainty band, not false precision.
6. **Prefer real data over synthetic once any is available.** The
   synthetic generator (`synthetic_data.py`) exists to prove the pipeline
   end-to-end and stays as a fallback/test fixture — it is not the
   training source for the delivered artifact.
7. **If scope or timeline pressure starts pushing toward cutting the real
   data step, stop and re-read `decisions.md`'s data-source entry before
   continuing** — that decision was made deliberately against the $0/
   2-day constraints, not as a default.
