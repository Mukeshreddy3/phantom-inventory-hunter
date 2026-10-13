"""Tests for the deterministic reconciliation engine."""
import json
import sqlite3
from pathlib import Path

from phantom_hunter.generator import Gen
from phantom_hunter import reconcile


def _gen(tmp_path: Path, do_inject: bool = True):
    db = tmp_path / "t.db"
    Gen(seed=42).run(db, tmp_path / "labels", do_inject=do_inject)
    return db


def _gt(db):
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    rows = [dict(r) for r in conn.execute("SELECT * FROM ground_truth")]
    conn.close()
    return rows


def test_clean_baseline_reconciles_to_zero(tmp_path):
    db = _gen(tmp_path, do_inject=False)
    discs = reconcile.run(db)
    assert discs == [], f"expected no discrepancies, got {len(discs)}"


def test_recall_on_engine_detectable_categories(tmp_path):
    """Every injected discrepancy the engine *can* see must be flagged."""
    db = _gen(tmp_path)
    discs = reconcile.run(db)
    by_key = {}
    for d in discs:
        by_key.setdefault((d["category"], d["sku"], d["lot_code"]), []).append(d)

    missed = []
    for g in _gt(db):
        if g["expected_engine"] == "none_m1":
            continue  # label contradictions need vision (M2)
        key = (g["expected_engine"], g["sku"], g["lot_code"])
        if g["expected_engine"] == "wrong_bin":
            hit = any(d["category"] == "wrong_bin" and d["pallet_id"] == g["pallet_id"]
                      for d in discs)
        else:
            hit = key in by_key
        if not hit:
            missed.append((g["id"], g["category"]))
    assert not missed, f"engine missed injected discrepancies: {missed}"


def test_value_at_risk_math_on_failed_message(tmp_path):
    db = _gen(tmp_path)
    discs = reconcile.run(db)
    conn = sqlite3.connect(db)
    g = [r for r in _gt(db) if r["category"] == "failed_message"][0]
    lot_qty = conn.execute("SELECT qty_produced FROM lots WHERE lot_code=?",
                           (g["lot_code"],)).fetchone()[0]
    unit_cost = conn.execute("SELECT unit_cost FROM sku_master WHERE sku=?",
                             (g["sku"],)).fetchone()[0]
    conn.close()
    d = next(x for x in discs
             if x["category"] == "qty_mismatch" and x["lot_code"] == g["lot_code"])
    assert d["value_at_risk"] == round(lot_qty * unit_cost, 2)
    assert d["erp_qty"] == 0
    assert d["wms_qty"] == round(lot_qty, 2)


def test_cutoff_gap_is_low_severity_and_explained(tmp_path):
    db = _gen(tmp_path)
    discs = reconcile.run(db)
    gaps = [d for d in discs if d["category"] == "cutoff_gap"]
    assert len(gaps) == 5
    for d in gaps:
        assert d["severity"] == "low"
        assert d["detail"]["pending_messages"], "cutoff gap must cite the pending message"


def test_qty_mismatch_carries_integration_evidence(tmp_path):
    db = _gen(tmp_path)
    discs = reconcile.run(db)
    mm = [d for d in discs if d["category"] == "qty_mismatch"]
    assert mm
    # at least the failed/duplicate ones must cite non-delivered messages
    cited = [d for d in mm if d["detail"].get("evidence_messages")]
    assert cited, "qty mismatches should carry integration-log evidence"


def test_wrong_uom_hint_present(tmp_path):
    db = _gen(tmp_path)
    discs = reconcile.run(db)
    conn = sqlite3.connect(db)
    gt_lots = {r["lot_code"] for r in _gt(db) if r["category"] == "wrong_uom"}
    conn.close()
    hits = [d for d in discs
            if d["category"] == "qty_mismatch" and d["lot_code"] in gt_lots]
    assert len(hits) == len(gt_lots)
    for d in hits:
        assert d["detail"].get("unconverted_uom_txns"), \
            "wrong-UOM mismatch should hint at the unconverted txn"


def test_discrepancies_persisted(tmp_path):
    db = _gen(tmp_path)
    discs = reconcile.run(db)
    conn = sqlite3.connect(db)
    n = conn.execute("SELECT COUNT(*) FROM discrepancies").fetchone()[0]
    conn.close()
    assert n == len(discs) > 0


def test_expired_lots_flagged_with_writeoff_value(tmp_path):
    db = _gen(tmp_path)
    discs = reconcile.run(db)
    exp = [d for d in discs if d["category"] == "expired_available"]
    assert len(exp) == 6
    for d in exp:
        assert d["value_at_risk"] > 0
        assert "expiry_date" in d["detail"]
