# VendorEdge Reasoning Job Lifecycle — World-Class Reliability Architecture
No code in this document. Design only, per instruction.

---

## 1. Current architecture — precisely, not summarized

`BackgroundTasks` (Starlette's in-process thread pool) runs `_run_reasoning_safe` → `_run_reasoning`. Status is `reasoning` from the moment a task is scheduled until `completed` or `provider_unavailable`. Staleness is a single, cumulative elapsed-time check (`reasoning_started_at` vs. now), computed at read time. Reclaiming a stale or failed case uses one atomic `UPDATE ... WHERE status = ...`.

**The exact, confirmed gap** — I checked this directly before writing anything else: the final completion write is

```sql
UPDATE commercial_decisions SET status = 'completed', commercial_position = %s, ... WHERE id = %s
```

**Nothing else in the `WHERE` clause.** Any attempt, however old, however already superseded by a reclaim, can unconditionally overwrite this row. **Two workers can absolutely both legitimately write the final answer today.** This confirms your suspicion precisely — not a theoretical risk, a real, present gap.

## 2. Failure modes, named precisely

1. **False-positive staleness** (the triggering incident) — cumulative elapsed time conflates "many legitimate stages" with "dead."
2. **No liveness signal at all** — nothing distinguishes "mid-search, working" from "process died 3 minutes ago."
3. **Unguarded final write** — confirmed above. The root cause behind everything else in this list.
4. **No attempt identity** — there is currently no way to say "this specific execution is the one allowed to finish," which is the actual reason #3 is possible.
5. **Reactive-only detection** — recovery only happens when someone actively polls or submits again; nothing proactively notices a dead job.

---

## 3. Proposed architecture — the core idea in one sentence

**Stop trying to prevent two workers from ever running concurrently — that can't be guaranteed with certainty in any real system. Instead, guarantee that only one of them can ever successfully *finish*, and make that guarantee real at the database level, not the application level.**

### Job identity + attempt identity
Every time reasoning is kicked off — initial submission, `/respond`, a reclaim — it gets a fresh, unique `attempt_id`. The row stores `current_attempt_id`: whichever attempt is presently the *legitimate* one. A worker only carries its own `attempt_id` in memory for its entire run; it never re-reads "am I still current" from the database except at the moments it writes.

### The guard that actually prevents duplicate execution from mattering
Every write a worker makes — heartbeat *and* final completion — is conditioned on its own `attempt_id` still matching the row's `current_attempt_id`:

```
WHERE id = %s AND current_attempt_id = %s
```

If a reclaim has since happened, this attempt's `attempt_id` no longer matches. Its writes affect zero rows. This is true **no matter when** the old worker wakes up — immediately, or ten minutes later after finally finishing a hung search call. It cannot silently overwrite a newer attempt's work, because it structurally has no path to write to that row anymore. This is *why* the architecture prevents duplicate execution from causing harm: not by stopping the second worker from running, but by making its output provably discardable.

### Heartbeat / liveness — revised for requirement 1

**The gap in the original design, found on review**: stage-boundary heartbeats alone are insufficient. `client.messages.create()` is a synchronous, blocking call — once invoked, the calling thread is simply waiting on network I/O and cannot also update a heartbeat. If a single call (especially one with web-search tool use) legitimately runs 5–15 minutes, stage-boundary heartbeats would produce *zero* updates for that entire window — indistinguishable from death by the very mechanism meant to detect it.

**The fix: a heartbeat ticker thread, decoupled from the blocking call itself.** Immediately before any real outbound call (classify, primary reasoning, market verification), start a lightweight background thread that writes a heartbeat at a fixed interval; stop it the moment the call returns, succeeds, or raises.

```
start ticker thread
  loop: sleep(tick_interval); write heartbeat (attempt-id-guarded)
try:
    response = client.messages.create(...)   # the real blocking call
finally:
    stop ticker thread
```

**Why this gives the right signal, precisely**: if the *entire worker process* dies — crash, Render restart, OOM kill — the ticker thread dies with it, in the same instant, for the same reason. Heartbeats correctly stop. If only the *network call* is slow — the process is alive, just waiting on I/O — the ticker keeps ticking on its own independent schedule, completely unaffected by how long the call takes. This is the actual mechanism that distinguishes "slow" from "dead" at the granularity your instruction is asking for: a genuinely 15-minute LLM call now produces ~60 heartbeats and is provably alive throughout, while a process that dies mid-call goes silent immediately, not after some proxy timeout expires.

---

### Timeouts and intervals — derived, not guessed (requirement 2)

Every number below is justified from the real execution model, not picked because it felt reasonable. I want to be explicit about the reasoning, not just the conclusion.

**Operation-level timeout (the outbound SDK call itself)**: the Anthropic client accepts an explicit `timeout` parameter — I'd set this deliberately, not rely on the SDK's own default. Since your instruction explicitly wants 5/10/15-minute calls treated as *legitimate*, this ceiling must sit comfortably above that — **20 minutes**. This is the hard stop for a single call that's truly hung (not merely slow), independent of the heartbeat mechanism entirely.

**Heartbeat tick interval — 15 seconds.** Reasoning: frequent enough that a real death is noticed within roughly a minute; infrequent enough that even a 20-minute call produces only ~80 heartbeat writes — trivial load, not a concern.

**Missed-tick tolerance before treating a gap as meaningful.** A *single* missed heartbeat write must never be treated as death — your own test list explicitly requires this ("database unavailable during heartbeat... must not immediately duplicate"). The ticker thread stays alive and simply retries on its next scheduled tick; a transient DB hiccup that resolves within one or two ticks must self-heal with zero special-case code, because the *next* successful tick naturally refreshes `last_heartbeat_at`.

**Recovery grace period — derived as a multiple of the tick interval, not a standalone number.** `grace_period = 6 × tick_interval = 90 seconds`. The reasoning: 6 consecutive missed ticks (90 seconds of total silence) is a materially different signal than 1–2 missed ticks — it tolerates realistic transient blips (a slow DB connection, brief network hiccup) while still being fast enough to matter for real recovery. This number is *derived from* the tick interval, not chosen independently of it — if the tick interval ever changes, the grace period changes with it, by design, rather than needing to be separately re-justified.

**Boundary conditions, to be tested adversarially, not just described**: exactly at 89 seconds of silence (must not reclaim), exactly at 90 seconds (the genuine threshold), and a case where ticks resume at 89.9 seconds (must cancel any reclaim consideration entirely, not just "barely miss" being reclaimed).

---
Reclaiming does three things in one atomic statement: confirms the heartbeat is genuinely stale, generates a *new* `attempt_id`, and resets `reasoning_started_at`/`last_heartbeat_at`. The new attempt starts reasoning **fresh, from the beginning**, using the same stored evidence — it does not try to resume mid-stage. I want to be direct about the honest tradeoff here: recovery is safe, but it is not free. A worker that died after a completed LLM call still throws that work away; there's no cheap way to persist and resume partial reasoning state without a much larger, genuinely different architecture (real checkpointing), which I'm not proposing here.

---

## 4. State machine

The *stored* status stays deliberately simple — three real states plus one known-failure state, exactly as today:

```
awaiting_user_input → reasoning → completed
                    ↘ reasoning → provider_unavailable → reasoning (new attempt)
```

**"Stale" is never a stored status.** It's a computed, read-time fact (`last_heartbeat_at` age vs. grace period), exactly like `processing_is_stale` already works today — just now driven by heartbeat freshness instead of raw elapsed time. This avoids an entire class of new bugs about "who transitions to a stale status, and could that itself race" by never introducing that transition at all.

---

## 5. BackgroundTasks today, and the real migration boundary (requirement 4)

**Staying with `BackgroundTasks` for this fix, deliberately** — no new infrastructure (queue, broker, scheduler) is being introduced. But its real limitation needs to be stated plainly, not glossed over: it is in-process. If the entire worker process dies — a Render restart, an OOM kill, a deploy — every in-flight background task dies with it, with nothing external watching. Detection is **reactive**: a dead job is only discovered the next time a user polls or submits against it, not proactively swept by anything running in the background on its own schedule.

**This becomes insufficient the moment any of the following becomes true**: horizontal scaling across multiple worker processes/dynos, a genuine need for jobs to survive a full process restart with automatic requeue, or a proactive sweep that notices and recovers stale jobs without waiting for a user to stumble back into one. None of those are true for the current pilot scale — but naming the exact line matters more than pretending it doesn't exist.

**The genuinely reassuring part, worth being explicit about**: the attempt-ID fencing mechanism this design centers on is not BackgroundTasks-specific at all. It's a database-level guarantee — "only the attempt matching `current_attempt_id` may write" — that works identically regardless of what dispatches the work. Migrating to a real job queue (Celery+Redis, a Postgres-backed queue, SQS) later would swap out *how* a worker gets invoked, not *how* it's proven safe to let it write. The safety mechanism being built now is the same safety mechanism a durable queue would need — this work is not throwaway.

---

## 6. Material Caveat Ledger — for the "technically qualified" question

**Not a keyword filter.** A small, structured registry of rules, each triggered by a real combination of structured evidence fields, each producing a standard caveat phrase that must accompany its paired positive claim.

**The real gap this exposes**: there is currently no structured field capturing production track record at all — only `qualification_status`. Fixing this needs a new field.

**Revised per your explicit correction**: a plain boolean is the wrong shape — it forces "we never discussed this" and "we confirmed there is none" into the same false value, which is exactly the kind of fabrication-by-omission Hard Rule 1 exists to prevent. The real field needs four genuinely distinct states:

```
ProductionHistoryStatus = Literal["established", "limited", "none", "unknown"]
```

`SupplierEvidence.production_history_status: ProductionHistoryStatus = "unknown"` — defaulting to `unknown`, never to `none`. Populated with the same provenance rigor as every other supplier fact (a real `FieldProvenance` entry, `source="llm_extraction"` from the same per-supplier extraction pass), never treated as second-class.

**The caveat rule only fires on a genuinely known absence, never on silence**:

```
CaveatRule:
    trigger: qualification_status == "complete"
             AND production_history_status in ("none", "limited")
    positive_claim_patterns: ["qualified", "technically qualified", "approved"]
    required_caveat_patterns: ["no production history", "not production-proven",
                                "unproven in production", "limited production history"]
    correction: pair the qualification claim with the known, structured caveat
```

`unknown` deliberately does **not** trigger this rule — the system genuinely doesn't know, and asserting a caveat it can't support would itself be a fabrication in the other direction. This is the precise fix for "unknown must never be converted into false": the rule structurally cannot fire on an absence of information, only on a confirmed one.

For the exact VoltDrive case — where the source text explicitly says *"no historical production performance"* — `production_history_status` would correctly resolve to `"none"`, the rule fires, and the required pairing becomes *"technically qualified, but not production-proven"* rather than "technically qualified" standing alone.

This slots into the existing claim-integrity retry pattern precisely — same architecture, one new rule type: instead of "claim contradicts a known fact," it's "claim omits a known, structurally-registered, material caveat." Deterministic, rule-based, no second AI call — consistent with every other guardrail built tonight.

---

## 7. Adversarial test matrix — expanded (to be built once approved — not built yet)

| # | Scenario | Expected outcome |
|---|---|---|
| 1 | Worker alive but slow, heartbeat fresh | Never reclaimed |
| 2 | Heartbeat delayed but within grace | Not reclaimed yet |
| 3 | Heartbeat genuinely stale (> 90s silence) | Becomes recoverable |
| 4 | Worker dies after LLM response, before save | Clean recovery, no corruption |
| 5 | Worker dies mid-guardrail-retry | Clean recovery |
| 6 | Browser closes, worker continues | Backend unaffected; correct final state on next access |
| 7 | Browser refresh mid-processing | Same |
| 8 | Double-click | Atomic claim — one winner |
| 9 | Resubmit while genuinely reasoning | Graceful, no duplicate |
| 10 | Two recovery attempts simultaneously | Atomic reclaim — one winner |
| 11 | **Original worker wakes up after a new attempt owns the case** | Its write is rejected by attempt-id mismatch — see dedicated proof below |
| 12 | Provider timeout (SDK call exceeds 20-minute operation ceiling) | Treated as a genuine failure, `provider_unavailable`, safely retriable |
| 13 | Web-search timeout specifically | Same path as #12, isolated to the market-verification stage |
| 14 | Genuinely successful 10+ minute case | Never falsely flagged stale |
| 15 | LLM call alive for 5 / 10 / 15 minutes | Ticker produces continuous heartbeats throughout; never reclaimed at any point in that window |
| 16 | Heartbeat *during* a long LLM call specifically | Direct proof the ticker fires while the blocking call is still in flight, not just before/after it |
| 17 | Heartbeat write fails once, worker remains alive | Ticker retries on its next tick; a single transient failure never triggers reclaim |
| 18 | Worker killed immediately before the final write | Recovery produces one clean result; no partial/corrupt state |
| 19 | Two recovery workers racing each other | Atomic reclaim — exactly one wins, proven under real concurrent threads |
| 20 | Simulated Render/process restart | Ticker and main thread die together; heartbeat correctly goes silent, not falsely "still alive" |
| 21 | Database unavailable during a heartbeat write | Tolerated by the missed-tick allowance; self-heals on the next successful tick |
| 22 | Database unavailable during the final completion write | The write itself fails and is caught by the existing broad safety net; the case naturally becomes stale-and-recoverable once the database returns — no special-case logic needed, an honest, self-healing property, not a gap papered over |
| 23 | Browser disappears for the entire analysis, start to finish | Backend correctness is fully independent of the browser; case is complete and correctly retrievable whenever the user returns |
| 24 | Boundary: exactly 89s of silence | Not reclaimed |
| 25 | Boundary: exactly 90s of silence | Genuinely reclaimable |
| 26 | Boundary: a tick arrives at 89.9s | Cancels any reclaim consideration entirely, not a near-miss |

Every test proven as: **EXPECTED FAILURE → DETECTION → SAFE RESPONSE → NO DUPLICATE WORK → NO SILENT CORRUPTION**.

---

### The single most important proof, isolated and stated explicitly

**Claim**: an old attempt can never overwrite the current attempt's result, regardless of how long it has been running or how late it wakes up.

**Why this is true, mechanically, not just asserted**: every write an attempt makes — heartbeat *and* final completion — carries its own `attempt_id` in the `WHERE` clause, matched against the row's `current_attempt_id`. A reclaim doesn't just mark the old attempt "stale" — it atomically *replaces* `current_attempt_id` with a new value. From that instant, the old attempt's `attempt_id` is permanently, structurally invalid for this row. It does not matter whether the old worker wakes up one second later or twenty minutes later: its `UPDATE ... WHERE id = %s AND current_attempt_id = %s` matches zero rows, every time, forever, for that specific attempt. This isn't a race being *managed* — it's a race whose losing side is made permanently, provably incapable of mattering.

**The specific adversarial test that proves this directly** (#11 above): construct a case, let a first attempt begin, force a reclaim (simulating genuine staleness), let a *second* attempt complete and write a real result — then have the *first* attempt attempt its own final write, using its original, now-invalid `attempt_id`. Assert the row's `commercial_position` still matches the second attempt's result, untouched. This is the test that would fail immediately if the fencing were even slightly wrong, and it's the one I'd run first once implementation begins.

---

## 8. What remains fundamentally impossible to guarantee — stated honestly, not softened

1. **No heartbeat system can achieve true zero false-positive certainty.** There is always some grace-period window where a genuinely-alive-but-momentarily-delayed worker *could* be reclaimed. This isn't a bug to fix; it's a real limit shared by every real distributed system. What this design does is shrink that window from "any point past a large cumulative guess" to "no check-in during one bounded, defensible stage-gap" — dramatically reducing likelihood, not claiming impossibility.
2. **A false-positive reclaim still wastes real LLM cost**, even though it can no longer corrupt data. The old attempt's work is thrown away safely, not free.
3. **A database itself being unreachable at the exact moment of a heartbeat or final write** is outside what any application-level design can protect against.
4. **Detection today is reactive, not proactive.** Nothing currently sweeps for stale jobs in the background — staleness is only discovered when someone polls or submits again. A fully proactive system would need a periodic sweep/scheduler, which is a real, larger infrastructure addition I'm not scoping into this fix unless you want it separately.

## Schema changes required
- `current_attempt_id UUID`
- `last_heartbeat_at TIMESTAMPTZ`
- `current_stage TEXT`
- `reasoning_started_at` stays, now used only for display ("elapsed: 3m 42s"), no longer the staleness determinant.
- New field on the evidence model (not the decisions table): `SupplierEvidence.production_history_status: ProductionHistoryStatus` enum, for the Material Caveat Ledger.

## Deployment implications
One more idempotent `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` migration, same safe pattern as every prior change tonight. No new infrastructure (no queue, no scheduler) — this stays within the current in-process `BackgroundTasks` model, deliberately, to avoid a much larger architectural jump you haven't asked for.

---

Stopping here, as instructed. Waiting for your direction before any code is written.
