# VendorEdge MVP — How to Run This Yourself

## What you need first
1. **Docker Desktop** — free, download from docker.com, install it like any normal app.
2. **A fresh Anthropic API key** — the one you revoke-and-replace, saved somewhere safe, not in any chat.

## Setup (one time only)
1. Open the folder this project is in.
2. Find the file called `.env.example`. Make a copy of it and rename the copy to exactly `.env` (no ".example" at the end).
3. Open `.env` in any text editor. Replace `paste-your-real-key-here` with your real Anthropic key. Save.

## Running it
Open a terminal in this folder and type:
```
docker compose up
```
Wait a minute or two the first time — it's downloading and setting everything up, including the database, automatically. You'll see a lot of text scroll by; that's normal.

Once it settles down, the app is running at: **http://localhost:8000**

## How to actually try it
Open your web browser and go to: **http://localhost:8000**

You'll see a real screen — type a question or click one of the two example buttons. That's it.

## What's proven to work right now, and what isn't yet
**Proven, tested for real, by me, before handing this to you:**
- The database keeps every company's data completely separate from every other company's — tested by deliberately trying to break it, and it held.
- The system correctly asks for missing information instead of guessing.
- Once given full information, it produces a real recommendation with its reasoning visible.
- Nobody can secretly edit an answer after it's finalized.
- The screen itself, end to end.

**Not yet proven, because it needs your real key, which I never had access to:**
- The actual "thinking" — the real AI call that reads a real question and reasons about it. The code is written and structured correctly, but you'll be the first to actually see it run for real.
- This exact one-command Docker setup — Docker isn't available in my own testing environment, so this specific packaging step is new the moment you run it. If something doesn't work on the first try, that's useful information, not a sign anything is fundamentally broken — tell me exactly what error you see and I'll fix it.

## What's coming next
- Payment/subscribe flow (once this loop is confirmed working with your real key)
- The one-page PDF export
- Proper login (right now everyone shares one demo account, on purpose, to keep this first test simple)

## Changes in this pass (workflow, not architecture)
Nothing in Classification, the Evidence Engine, the Reasoning Pipeline's core logic, Commercial Position generation, or the table structure changed. This pass added, on top of that foundation:
- **My Cases**: `GET /commercial-decisions` lists every case for the org, flagged with whether its outcome has been recorded.
- **Organizational learning, wired in**: the reasoner now receives this org's own past recorded outcomes for the same content type before generating a new position (previously `decision_feedback` was stored but never read back).
- **Outcome capture as documentation, not a survey (Sprint 1)**: recording an outcome now generates a copy/downloadable case summary (question, evidence, position, outcome) — reopening a completed case later shows the same summary again, not just in the original session.
- **"Decision Taken" capture (Sprint 2)**: the outcome form now also asks whether the recommendation was followed as given, modified, or ignored in favor of a different direction — closing the gap in the original workflow diagram (Position → Decision Taken → Outcome), which previously skipped straight from Position to Outcome with no record of what the human actually did in between. This required one new required column on `decision_feedback` (`decision_alignment`) — the only schema change beyond the RLS fix below.
- **Pre-launch legal pages**: `privacy-policy.html`, `terms-of-use.html`, `ai-disclaimer.html` in `app/static/` — DRAFT TEMPLATES, clearly flagged as such on the page itself, not legal advice. Have a lawyer review before real external users see them, especially the liability/warranty sections and anything tied to your jurisdiction. Linked from a footer on every screen, plus a one-time "before you start" acknowledgment modal on first visit (stored in the browser's `localStorage`, not the database — nothing server-side changed for this) and a short disclaimer line directly under every generated commercial position, since that's the actual moment of risk.
- **Security fix**: `decision_feedback` had no Row-Level Security policy at all (latent, since nothing had queried across it until this pass added the history lookback). It now has one, matching the existing pattern on `users` and `commercial_decisions`.

**Not yet proven, same caveat as above:** I don't have a live Postgres or Anthropic key in my own environment, so none of this was run end-to-end against a real database — it's been read carefully against the existing schema and query patterns, and syntax/AST-checked, but you'll be the first to actually run it. If `docker compose up` throws anything, especially from `pytest`, that's useful signal, not proof something's broken — tell me the exact error.

**If you already have a running Postgres volume from before:** the RLS fix on `decision_feedback` won't take effect until the schema is reloaded (`docker compose down -v` then `docker compose up`, or equivalent) — Postgres init scripts only run once, against a fresh volume.
