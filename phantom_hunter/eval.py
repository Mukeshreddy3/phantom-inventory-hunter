"""Evaluation (M4): score the agent's root-cause accuracy against the
injected ground truth.

A diagnosis counts as correct when it matches the injected category, with
one principled exception: a ``cutoff_gap`` injection whose PENDING message
went stale (older than the 60-minute sync window at investigation time) is
*correctly* re-diagnosed as ``failed_message`` — a stuck delivery really is
a failed delivery. The eval accepts that mapping only when the message age
supports it.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

from . import tools

STALE_WINDOW = timedelta(minutes=60)


def _stale_pending(conn, sku: str, lot_code: str, investigated_at: str) -> bool:
    row = conn.execute(
        """SELECT created_at FROM integration_log
           WHERE sku=? AND lot_code=? AND status='PENDING'
           ORDER BY created_at LIMIT 1""", (sku, lot_code)).fetchone()
    if not row:
        return False
    age = datetime.fromisoformat(investigated_at) - datetime.fromisoformat(row[0])
    return age > STALE_WINDOW


def is_correct(conn, inv: dict, gt: dict | None) -> bool | None:
    """True/False vs ground truth; None when no ground truth exists."""
    if not gt:
        return None
    if inv["root_cause"] == gt["category"]:
        return True
    if (gt["category"] == "cutoff_gap" and inv["root_cause"] == "failed_message"
            and _stale_pending(conn, inv["sku"], inv["lot_code"],
                               inv["investigated_at"])):
        return True
    return False


def evaluate(db_path: Path) -> dict:
    db_path = Path(db_path)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        invs = [dict(r) for r in conn.execute("SELECT * FROM investigations")]
        total, correct = 0, 0
        per: dict[str, dict] = {}
        misses: list[dict] = []
        for inv in invs:
            gt = tools.ground_truth_for(db_path, inv["sku"], inv["lot_code"],
                                        inv["pallet_id"])
            verdict = is_correct(conn, inv, gt)
            if verdict is None:
                continue
            total += 1
            truth = gt["category"]
            bucket = per.setdefault(truth, {"n": 0, "correct": 0})
            bucket["n"] += 1
            if verdict:
                correct += 1
                bucket["correct"] += 1
            else:
                misses.append({"inv_id": inv["id"], "sku": inv["sku"],
                               "lot_code": inv["lot_code"],
                               "diagnosed": inv["root_cause"], "truth": truth,
                               "confidence": inv["confidence"]})
        for b in per.values():
            b["accuracy"] = round(b["correct"] / b["n"], 3) if b["n"] else 0.0
        return {
            "total_evaluated": total,
            "correct": correct,
            "accuracy": round(correct / total, 3) if total else 0.0,
            "per_category": per,
            "misses": misses,
            "note": ("label_contradiction is vision-only: the deterministic engine "
                     "cannot flag it, so it never reaches the agent in this pipeline."),
        }
    finally:
        conn.close()


def main() -> None:
    import argparse, json
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="data/phantom.db")
    args = ap.parse_args()
    print(json.dumps(evaluate(Path(args.db)), indent=2))


if __name__ == "__main__":
    main()
