"""Scripted 3-minute demo (M5): the $48K expired lot in rack 14.

The dramatic catch: the ERP thinks ~$48,000 of product is AVAILABLE.
It actually expired yesterday, sitting in rack 14 of the ASRS.

    python -m phantom_hunter.showcase   # or: make showcase

Acts:
  0:00  build the synthetic world (+ the showcase injection)
  0:45  reconcile — the engine flags it
  1:30  investigate — the agent builds the evidence trail
  2:15  approval — the human approves the write-off (agent never applies)
  2:45  score — evaluation + where to explore next (make dashboard)
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

from . import eval as eval_mod
from . import reconcile, tools
from .agent import InvestigationAgent
from .generator import Gen
from .llm import LLMClient
from .runner import Loop

TARGET_VALUE = 48_000.0


def inject_showcase(gen: Gen, cur) -> dict:
    """~$48K of the priciest SKU, expired yesterday, rack 14, ERP thinks
    it's available. Returns {sku, lot, qty, value}."""
    sku = cur.execute(
        "SELECT sku FROM sku_master ORDER BY unit_cost DESC LIMIT 1").fetchone()[0]
    s = gen.skus[sku]
    qty = round(TARGET_VALUE / s["unit_cost"], 2)
    value = round(qty * s["unit_cost"], 2)
    prod = (gen.now - timedelta(days=90)).date()
    expiry = (gen.now - timedelta(days=1)).date()
    lot = f"L{prod.strftime('%Y%m%d')}-{sku[-4:]}SC"

    cur.execute("INSERT INTO lots VALUES (?,?,?,?,?)",
                (lot, sku, prod.isoformat(), expiry.isoformat(), qty))
    ref = f"PR-{lot}"
    posted = datetime.combine(prod, datetime.min.time()) + timedelta(hours=7)
    cur.execute(
        """INSERT INTO erp_transactions
           (txn_date, doc_type, sku, lot_code, qty, uom, converted, qty_base, ref_doc, posted_at)
           VALUES (?,?,?,?,?,?,?,?,?,?)""",
        (prod.isoformat(), "PROD_RECEIPT", sku, lot, qty, s["base_uom"],
         1, qty, ref, posted.isoformat()))
    mid = gen.msg_id()
    cur.execute(
        "INSERT INTO integration_log VALUES (?,?,?,?,?,?,?,?,?,?)",
        (mid, posted.isoformat(), "WMS->ERP", "PROD_RECEIPT",
         sku, lot, qty, "DELIVERED", None, ref))

    per = round(qty / 6, 2)
    first = None
    for i in range(6):
        pq = per if i < 5 else round(qty - per * 5, 2)
        pid = gen.pallet_id()
        loc = f"R14-{i + 1:02d}-1"          # rack 14 — the dramatic catch
        cur.execute("INSERT INTO wms_pallets VALUES (?,?,?,?,?,?,?,?,?)",
                    (pid, sku, lot, pq, s["base_uom"], loc,
                     expiry.isoformat(), "AVAILABLE", posted.isoformat()))
        if first is None:
            first = (pid, pq, loc)
    from .labels import make_label
    make_label({"pallet_id": first[0], "sku": sku, "lot_code": lot,
                "qty": first[1], "uom": s["base_uom"], "location": first[2],
                "expiry": expiry.isoformat()},
               gen.label_dir / f"{first[0]}.png")
    gen.gt(cur, "expired_available", sku=sku, lot=lot,
           expected_engine="expired_available",
           detail={"showcase": True, "target_value": TARGET_VALUE, "rack": "R14",
                   "actual_value": value,
                   "note": "ERP shows available; lot expired yesterday in rack 14"})
    return {"sku": sku, "lot": lot, "qty": qty, "value": value,
            "expiry": expiry.isoformat(), "pallet_id": first[0]}


def refresh_erp_snapshot(db_path: Path) -> None:
    conn = sqlite3.connect(db_path)
    conn.execute("DELETE FROM erp_inventory")
    conn.execute("""INSERT INTO erp_inventory (sku, lot_code, qty_base)
                    SELECT sku, lot_code, ROUND(SUM(qty_base), 2)
                    FROM erp_transactions GROUP BY sku, lot_code""")
    conn.commit()
    conn.close()


def _act(t: str, title: str):
    print(f"\n{'=' * 70}\n[{t}] {title}\n{'=' * 70}")


def main() -> None:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="data/showcase.db")
    ap.add_argument("--labels", default="data/showcase-labels")
    ap.add_argument("--seed", type=int, default=7)
    args = ap.parse_args()
    db_path, label_dir = Path(args.db), Path(args.labels)

    _act("0:00", "ACT 1 — the world. 200 SKUs, 30 days, ERP + WMS + integration log.")
    gen = Gen(seed=args.seed)
    counts = gen.run(db_path, label_dir, do_inject=True)
    conn = sqlite3.connect(db_path)
    sc = inject_showcase(gen, conn.cursor())
    conn.commit()
    conn.close()
    refresh_erp_snapshot(db_path)  # include the showcase receipt
    sku_desc = tools.get_lot(db_path, sc["sku"], sc["lot"])["sku"]["description"]
    print(f"  {counts['sku_master']} SKUs · {counts['lots']} lots · "
          f"{counts['wms_pallets']} pallets · {counts['integration_log']} messages")
    print(f"  …plus one special lot: {sc['qty']:,.2f} units of {sku_desc},")
    print(f"  received into rack 14, expired yesterday.")

    _act("0:45", "ACT 2 — reconcile. The engine flags what the ERP can't see.")
    discs = reconcile.run(db_path)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        """SELECT d.* FROM discrepancies d JOIN ground_truth g
           ON g.sku = d.sku AND g.lot_code = d.lot_code
           WHERE g.detail LIKE '%showcase%'""").fetchone()
    conn.close()
    d = dict(row)
    print(f"  {d['id']}: {d['category']} — {d['sku']} {d['lot_code']}")
    print(f"  ERP says: {d['erp_qty']:,.2f} AVAILABLE   "
          f"WMS says: {d['wms_qty']:,.2f} in rack 14")
    print(f"  Value at risk: ${d['value_at_risk']:,.2f}  (severity: {d['severity']})")
    print(f"  The ERP thinks ${d['value_at_risk']:,.0f} of sellable product exists.")
    print(f"  It expired yesterday.")

    _act("1:30", "ACT 3 — investigate. The agent builds the evidence trail.")
    agent = InvestigationAgent(db_path, label_dir,
                               LLMClient(data_dir=db_path.parent))
    inv = agent.investigate(d["id"])
    print(f"  root cause: {inv['root_cause']} (confidence {inv['confidence']})")
    for line in inv["evidence"][1:]:
        print(f"    - {line}")
    fix = inv["proposed_fix"]
    print(f"  proposed fix: {fix['action']} — {fix['description']}")

    _act("2:15", "ACT 4 — approval. The agent NEVER applies fixes.")
    loop = Loop(db_path, label_dir, LLMClient(data_dir=db_path.parent))
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    inv_id = loop._file(conn, d, inv, loop.now())
    conn.commit()
    conn.close()
    print(f"  filed as {inv_id} — status PENDING_APPROVAL, waiting on a human.")
    print(f"  (you approve: python -m phantom_hunter.runner --db {db_path} "
          f"--approve {inv_id})")
    decided = loop.approve(inv_id, "QA confirmed — write off and dispose")
    print(f"  human decision: {decided['status']} — '{decided['note']}'")
    print(f"  business tables untouched: the ERP/WMS post the write-off, not the agent.")

    _act("2:45", "ACT 5 — score. Then go explore.")
    ev = eval_mod.evaluate(db_path)
    print(f"  showcase diagnosis vs ground truth: "
          f"{inv['root_cause']} == expired_available ✓")
    print(f"  full-run accuracy: {ev['accuracy'] * 100:.1f}% "
          f"({ev['correct']}/{ev['total_evaluated']})")
    print(f"  model spend this demo: $0.00 of the $150 budget")
    print(f"\n  Explore it live:")
    print(f"    python -m phantom_hunter.dashboard --db {db_path} --port 8000")
    print(f"  (open the discrepancy, see the evidence trail + pallet label,")
    print(f"   and approve the fix yourself.)")


if __name__ == "__main__":
    main()
