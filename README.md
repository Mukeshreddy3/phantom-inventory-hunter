# Phantom Inventory Hunter

A long-running AI agent that finds and **explains** inventory mismatches between an
ERP system (think Microsoft Dynamics 365) and a WMS controlling an automated
storage & retrieval system (think Mecalux-style ASRS) — built for the
Meta Global AI Developer Hackathon (Oct 26 – Nov 4, 2026).

Food/dairy manufacturers live this problem daily: the ERP and the WMS each keep
their own inventory records and drift apart through failed integration messages,
duplicate postings, manual adjustments, mislabeled pallets, and timing gaps.
Analysts trace each mismatch by hand. This agent does the investigation
automatically — and **never applies fixes itself**; every proposed fix goes to
a human approval queue.

> **All data is 100% synthetic.** No real company data anywhere.

## Quickstart

```bash
make setup   # create venv + install deps
make demo    # generate data, run reconciliation, print summary
make test    # run the unit test suite
```

One command to see it work: `make demo`.

## How it works

1. **Synthetic data generator** (`phantom_hunter/generator.py`) — builds a
   consistent baseline for ~200 SKUs over 30 days (ERP transactions, WMS
   pallets/bins, integration message log), then injects known discrepancy types
   with ground-truth labels.
2. **Reconciliation engine** (`phantom_hunter/reconcile.py`) — deterministic
   comparison that flags every SKU/lot/location mismatch with quantities and
   dollar value at risk.
3. **Investigation agent** (M2) — uses Meta Model API + tools (query ERP txns,
   query WMS txns, search integration log, read pallet-label images) to build an
   evidence trail per mismatch: root cause, confidence, evidence, proposed fix.
4. **Long-running loop + approval queue** (M3).
5. **Web dashboard + evaluation scores** (M4).

## Discrepancy types (all injected with ground truth)

| Root cause | What happened |
|---|---|
| `failed_message` | WMS→ERP receipt message failed; ERP missing the receipt |
| `duplicate_message` | Receipt message delivered twice; ERP double-counted |
| `unposted_receipt` | Pallets exist in WMS; no ERP receipt and no message at all |
| `wrong_uom` | Receipt posted in cases/bags, conversion to LB/KG never applied |
| `wrong_bin` | ASRS moved the pallet; WMS pallet record still shows the old bin |
| `expired_available` | Lot past expiry but still shows available (write-off risk) |
| `cutoff_gap` | Shipment inside the sync window; ERP message still pending |
| `label_contradiction` | Physical pallet label contradicts the WMS record (vision catch) |

The M1 engine deterministically flags the first seven categories; label
contradictions need image reading and are the M2 agent's job.

## Project layout

```
phantom_hunter/
  schema.py       SQLite DDL (ERP, WMS, integration log, ground truth, discrepancies)
  generator.py    synthetic data + discrepancy injection
  labels.py       pallet-label PNG generator (PIL)
  reconcile.py    deterministic reconciliation engine
tests/            pytest suite (17 tests)
data/             generated DB + label images (gitignored, built by `make data`)
DECISIONS.md      design decisions log
```

## Milestones

- **M1** ✅ Synthetic data generator + reconciliation engine, with unit tests
- **M2** Investigation agent with tools (10 sample discrepancies, console output)
- **M3** Long-running loop + approval queue
- **M4** Dashboard + evaluation scores
- **M5** Polish: README, architecture diagram, scripted 3-minute demo
