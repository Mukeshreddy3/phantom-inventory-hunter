# DECISIONS.md

Running log of design decisions. Newest first.

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
