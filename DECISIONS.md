# DECISIONS.md

Running log of design decisions. Newest first.

## M5 (2026-10-13)

29. **Architecture diagram is generated, not drawn** (`docs/architecture.py`,
    PIL, zero deps) — re-runnable, versioned, matches the dashboard palette.
30. **Showcase is a real injection, not a mock.** `showcase.py` builds a
    fresh world, injects the $48K expired rack-14 lot through the same code
    path as every other discrepancy (ERP receipt posted, 6 pallets, label
    image, ground-truth row), then runs the real engine → agent → queue →
    approval → eval pipeline on it. If the pipeline breaks, the demo
    breaks — no theater.
31. **README is the submission front page.** Problem, 3-minute demo,
    quickstart, architecture, layout, milestones, license — everything a
    judge needs in one scroll. Screenshots committed under docs/.
32. **MIT license**, copyright Mukesh Reddy Chinreddy.

## M4 (2026-10-13)

25. **Dashboard on stdlib only** (`http.server` + plain HTML/JS, no
    framework, no new pip deps). JSON API backs: summary, discrepancy
    list/detail, approval queue, approve/reject POSTs, eval, label images.
    `make dashboard` serves on :8000. Hash deep-links (#eval) for demo use.
26. **Eval honesty rules.** Accuracy = investigated root causes vs injected
    ground truth, per category + misses list. The stale-cutoff escalation
    (M3 decision 20) is accepted as correct only when the PENDING message
    was actually older than the 60-min window at investigation time —
    checked from the message timestamp, not assumed. `label_contradiction`
    is reported as vision-only/out-of-scope with the reason stated, not
    silently dropped.
27. **"Value reconciled"** = sum of value-at-risk over APPROVED
    investigations (root cause found, fix approved by a human). Open risk
    vs reconciled value are the two headline numbers.
28. **Screenshots as evidence.** `docs/dash-main.png`, `docs/dash-eval.png`
    captured headless during M4 for the milestone report and later the
    hackathon submission.

## M3 (2026-10-13)

19. **Streaming = resume + gen_day.** `Gen.resume()` restores seq counters,
    the SKU catalog, and the simulated clock from the DB, then re-seeds the
    RNG (seed+7919) so the stream doesn't replay baseline draws. Each
    streamed day ships old lots first (keeps new lots clean for injection),
    then produces 6–12 new lots and injects 0–2 discrepancies.
20. **Emergent escalation: stale PENDING → failed_message.** A cutoff_gap is
    only a timing gap inside the 60-min sync window. Once the loop's clock
    moves past it, the engine re-flags it as a real qty_mismatch (new
    disc_key → reinvestigated) and the agent diagnoses the stuck message as
    a failed delivery (confidence 0.80, fix: resend). The 5 baseline cutoff
    gaps escalating on day 3 of the demo proved the behavior end-to-end.
21. **Dedupe by natural key** (`category|sku|lot_code|pallet_id`), not by
    engine D-ids (regenerated each run). A discrepancy is investigated once
    ever; category changes (like the escalation above) legitimately
    re-trigger investigation.
22. **Priority = value_at_risk × expiry boost** (1.5× for expired lots,
    1.25× for lots expiring within 7 days). The queue is always
    highest-priority-first.
23. **Repeat grouping via the investigations table itself** — no separate
    memory table. A new investigation links `repeat_group` to the earliest
    prior investigation with the same (root_cause, sku). Past root causes
    are literally past rows.
24. **Approve/reject only touch the investigations row.** Even an APPROVED
    fix is never applied by the agent — applying it is the ERP/WMS's job.
    A test hashes all business tables across decisions to prove it.

## M2 (2026-10-13)

12. **Meta Model API adapter (llm.py).** OpenAI-compatible `POST
    {base}/chat/completions` with Bearer key, base URL
    `https://api.meta.ai/v1`, model `muse-spark-1.3` — per public docs
    (dev.meta.ai/docs) as of 2026-10-13. Re-verify endpoint + model list at
    hackathon kickoff (Oct 26); everything is env-overridable
    (`META_MODEL_API_BASE`, `META_MODEL_SMALL/LARGE`) with no code changes.
13. **Rule-based fallback, honestly labeled.** No `META_MODEL_API_KEY` → the
    agent investigates with a deterministic policy over the same evidence.
    Every result carries `mode: api|fallback` and the console says which —
    API and fallback runs are never confused.
14. **ReAct-lite, not full ReAct.** Core evidence (discrepancy, lot,
    integration log) is gathered deterministically (free, no tokens); the
    model then drives up to 3 follow-up tool calls via a JSON-only protocol
    before concluding. A fully model-driven loop is deferred — this keeps
    token spend near zero while proving the reasoning + evidence trail.
15. **Model routing.** `META_MODEL_SMALL` for routine steps, `META_MODEL_LARGE`
    for hard cases (vision reads, value-at-risk > $20K). Both default to
    `muse-spark-1.3` until the hackathon model list is confirmed — no invented
    model names.
16. **Budget instrumentation from day one.** Disk cache keyed by request hash
    + `token_usage.jsonl` with per-call tokens and estimated USD
    (muse-spark-1.3 Standard: $1.25/$4.25 per 1M in/out). Demo spend so far:
    $0.0000 of the $150 budget.
17. **Agent is read-only, provably.** Tools open SQLite with `mode=ro`;
    `build_fix()` only *describes* fixes with `requires_approval=True`.
    A test hashes the DB before/after investigations to prove zero writes.
18. **Demo sample picker** round-robins ground-truth root causes by
    value-at-risk so `make agent` always covers all 7 DB-detectable
    categories. Result: 10/10 root-cause accuracy vs ground truth (fallback).

## M1 (2026-10-13)

1. **Baseline-then-mutate injection.** The generator first builds a fully
   consistent world (ERP and WMS agree on every lot), then injects
   discrepancies as mutations. This guarantees the engine has zero false
   positives on the clean baseline (tested) and every injection is a true
   positive with a known root cause.
2. **Fixed time window (2026-09-14 → 2026-10-13) + fixed seed 42.**
   Deterministic output: same seed → identical DB. "Now" is simulated as
   2026-10-13 11:00 PT so cutoff-gap timing is reproducible.
3. **Engine flags, agent diagnoses.** The deterministic engine outputs
   *mismatch categories* (`qty_mismatch`, `cutoff_gap`, `wrong_bin`,
   `expired_available`); it does NOT guess root causes. The M2 LLM agent maps
   a `qty_mismatch` to `failed_message` / `duplicate_message` /
   `unposted_receipt` / `wrong_uom` using tools. This keeps the engine
   trustworthy and gives the agent a real job.
4. **Engine still attaches cheap evidence.** For each qty mismatch the engine
   pulls related non-delivered integration messages (and unconverted-UOM
   txns) into the discrepancy's `detail` JSON — free context for the M2 agent.
5. **Cutoff gaps are first-class, low severity.** A mismatch fully explained by
   a PENDING message inside the 60-min sync window is categorized
   `cutoff_gap` (low), not a real discrepancy — mirrors how analysts treat
   timing noise.
6. **Wrong-bin via move-log cross-check.** The ASRS move log (`wms_moves`) is
   the source of truth; a pallet whose `wms_pallets.location` disagrees with
   its latest move destination is stale. Deterministic, no vision needed.
7. **Label contradictions are M2-only** (`expected_engine='none_m1'`). The M1
   engine cannot read images by design; 5 contradiction labels are the vision
   agent's catch in M2.
8. **Value at risk** = |ERP−WMS| × unit cost for qty mismatches;
   full lot value for expired lots (write-off exposure); full pallet value for
   wrong-bin (unfindable inventory). Severity bands: ≥$10K high, ≥$1K medium.
9. **Meta Model API plan (M2):** an `LLMClient` that uses the Meta Model API
   when `META_MODEL_API_KEY` is set, with a documented deterministic
   rule-based fallback so the demo runs without a key. Smallest model for
   routine investigation steps; larger model only for hard cases. Responses
   cached; token usage logged per run (budget: <$150 in credits).
10. **Cursor-reuse trap (bug found in M1):** reusing one sqlite3 cursor for an
    inner query while iterating an outer query on the same cursor silently
    kills the outer iteration after one row. Always `fetchall()` the outer
    query first.
11. **gt() detail-nesting trap (bug found in M1):** passing `detail={...}` as a
    kwarg into a `**detail` collector nests it one level deep. Unwrap in `gt()`.
