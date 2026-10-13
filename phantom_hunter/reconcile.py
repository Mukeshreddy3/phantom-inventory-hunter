"""Deterministic reconciliation engine (M1).

Compares ERP inventory vs WMS/ASRS pallet inventory and flags every
SKU/lot/location mismatch with quantities and dollar value at risk.

Engine categories:
  qty_mismatch      ERP and WMS disagree on a lot's quantity (agent diagnoses
                    root cause in M2: failed/duplicate message, unposted
                    receipt, wrong UOM)
  cutoff_gap        mismatch fully explained by a PENDING integration message
                    inside the sync window (low severity, likely self-resolves)
  wrong_bin         pallet's recorded bin != latest ASRS move destination
  expired_available lot past expiry with qty still showing available

Writes results to the `discrepancies` table and returns them as dicts.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

from .generator import NOW

PENDING_WINDOW = timedelta(minutes=60)
TOL = 1e-6


def _severity(value: float) -> str:
    if value >= 10_000:
        return "high"
    if value >= 1_000:
        return "medium"
    return "low"


def run(db_path: Path, now: datetime = NOW) -> list[dict]:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    today = now.date().isoformat()

    cost = {r["sku"]: r["unit_cost"] for r in cur.execute("SELECT sku, unit_cost FROM sku_master")}
    base_uom = {r["sku"]: r["base_uom"] for r in cur.execute("SELECT sku, base_uom FROM sku_master")}

    erp = {(r["sku"], r["lot_code"]): r["qty_base"]
           for r in cur.execute("SELECT sku, lot_code, qty_base FROM erp_inventory")}
    wms_rows = cur.execute(
        """SELECT sku, lot_code, SUM(qty_base) AS q
           FROM wms_pallets GROUP BY sku, lot_code""").fetchall()
    wms = {(r["sku"], r["lot_code"]): r["q"] for r in wms_rows}

    out: list[dict] = []
    seq = 0

    def add(category, sku, lot, pallet_id, location, erp_q, wms_q, detail):
        nonlocal seq
        seq += 1
        unit_cost = cost.get(sku, 0.0)
        if category == "qty_mismatch":
            var = abs((erp_q or 0) - (wms_q or 0)) * unit_cost
        elif category == "cutoff_gap":
            var = abs((erp_q or 0) - (wms_q or 0)) * unit_cost
        elif category == "wrong_bin":
            var = (wms_q or 0) * unit_cost
        elif category == "expired_available":
            var = max(erp_q or 0, wms_q or 0) * unit_cost
        else:
            var = 0.0
        var = round(var, 2)
        sev = "low" if category == "cutoff_gap" else _severity(var)
        out.append({
            "id": f"D-{seq:04d}",
            "detected_at": now.isoformat(),
            "category": category,
            "severity": sev,
            "sku": sku,
            "lot_code": lot,
            "pallet_id": pallet_id,
            "location": location,
            "erp_qty": erp_q,
            "wms_qty": wms_q,
            "uom": base_uom.get(sku),
            "unit_cost": unit_cost,
            "value_at_risk": var,
            "detail": detail,
            "status": "OPEN",
        })

    # ---- 1. quantity reconciliation per (sku, lot) -------------------------- #
    for key in sorted(set(erp) | set(wms)):
        sku, lot = key
        eq, wq = round(erp.get(key, 0.0), 2), round(wms.get(key, 0.0), 2)
        if abs(eq - wq) <= TOL:
            continue
        # explainable by a recent PENDING message? -> cutoff_gap
        pend = cur.execute(
            """SELECT msg_id, msg_type, qty_base, created_at FROM integration_log
               WHERE sku=? AND lot_code=? AND status='PENDING'""", (sku, lot)).fetchall()
        recent = [dict(p) for p in pend
                  if now - datetime.fromisoformat(p["created_at"]) <= PENDING_WINDOW]
        # integration evidence for the M2 investigator
        ev = [dict(r) for r in cur.execute(
            """SELECT msg_id, direction, msg_type, status, ref_doc, duplicate_of
               FROM integration_log
               WHERE sku=? AND lot_code=? AND status != 'DELIVERED'""", (sku, lot))]
        detail = {"evidence_messages": ev}
        if recent:
            detail["pending_messages"] = recent
            add("cutoff_gap", sku, lot, None, None, eq, wq, detail)
        else:
            # wrong-UOM hint is cheap and deterministic: an unconverted alt-UOM txn
            uom_rows = [dict(r) for r in cur.execute(
                """SELECT ref_doc, qty, uom, converted FROM erp_transactions
                   WHERE sku=? AND lot_code=? AND converted=0""", (sku, lot))]
            if uom_rows:
                detail["unconverted_uom_txns"] = uom_rows
            add("qty_mismatch", sku, lot, None, None, eq, wq, detail)

    # ---- 2. wrong bin: stale pallet location vs latest ASRS move ------------ #
    for r in cur.execute(
            """SELECT p.pallet_id, p.sku, p.lot_code, p.location, p.qty_base,
                      (SELECT to_loc FROM wms_moves m
                        WHERE m.pallet_id = p.pallet_id
                        ORDER BY moved_at DESC LIMIT 1) AS true_loc
               FROM wms_pallets p"""):
        if r["true_loc"] and r["true_loc"] != r["location"]:
            add("wrong_bin", r["sku"], r["lot_code"], r["pallet_id"], r["location"],
                None, round(r["qty_base"], 2),
                {"recorded_bin": r["location"], "true_bin": r["true_loc"],
                 "note": "ASRS move log disagrees with pallet master location"})

    # ---- 3. expired lots still showing available ---------------------------- #
    # NOTE: fetchall() first — the loop body reuses `cur`, which would
    # otherwise clobber the live outer result set after the first row.
    expired_lots = cur.execute(
        """SELECT l.sku, l.lot_code, l.expiry_date FROM lots l
           WHERE l.expiry_date < ?""", (today,)).fetchall()
    for r in expired_lots:
        key = (r["sku"], r["lot_code"])
        eq, wq = round(erp.get(key, 0.0), 2), round(wms.get(key, 0.0), 2)
        if eq > 0 or wq > 0:
            avail_pallets = cur.execute(
                "SELECT COUNT(*) c FROM wms_pallets WHERE lot_code=? AND status='AVAILABLE'",
                (r["lot_code"],)).fetchone()["c"]
            if avail_pallets:
                add("expired_available", r["sku"], r["lot_code"], None, None, eq, wq,
                    {"expiry_date": r["expiry_date"],
                     "available_pallets": avail_pallets,
                     "note": "lot expired; still shows available (write-off risk)"})

    # ---- persist ------------------------------------------------------------ #
    cur.execute("DELETE FROM discrepancies")
    for d in out:
        cur.execute(
            """INSERT INTO discrepancies
               (id, detected_at, category, severity, sku, lot_code, pallet_id, location,
                erp_qty, wms_qty, uom, unit_cost, value_at_risk, detail, status)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (d["id"], d["detected_at"], d["category"], d["severity"], d["sku"],
             d["lot_code"], d["pallet_id"], d["location"], d["erp_qty"], d["wms_qty"],
             d["uom"], d["unit_cost"], d["value_at_risk"], json.dumps(d["detail"]),
             d["status"]))
    conn.commit()
    conn.close()
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="data/phantom.db")
    ap.add_argument("--summary", action="store_true")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    discs = run(Path(args.db))
    if args.json:
        print(json.dumps(discs, indent=2, default=str))
    if args.summary or not args.json:
        total = sum(d["value_at_risk"] for d in discs)
        print(f"Discrepancies: {len(discs)} | total value at risk: ${total:,.2f}")
        by_cat: dict[str, int] = {}
        for d in discs:
            by_cat[d["category"]] = by_cat.get(d["category"], 0) + 1
        for c, n in sorted(by_cat.items()):
            print(f"  {c:18s} {n}")
        top = sorted(discs, key=lambda d: d["value_at_risk"], reverse=True)[:5]
        print("Top 5 by value at risk:")
        for d in top:
            print(f"  {d['id']} {d['category']:16s} {d['sku']} {d['lot_code'] or ''} "
                  f"${d['value_at_risk']:,.2f}")


if __name__ == "__main__":
    main()
