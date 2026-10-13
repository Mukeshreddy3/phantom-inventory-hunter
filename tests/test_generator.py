"""Tests for the synthetic data generator."""
import json
import sqlite3
from pathlib import Path

from phantom_hunter.generator import Gen, N_SKUS, INJECTION_PLAN


def _gen(tmp_path: Path, seed: int = 42, do_inject: bool = True):
    db = tmp_path / "t.db"
    labels = tmp_path / "labels"
    g = Gen(seed=seed)
    counts = g.run(db, labels, do_inject=do_inject)
    return db, labels, counts


def _gt_rows(db):
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    rows = [dict(r) for r in conn.execute("SELECT * FROM ground_truth")]
    conn.close()
    return rows


def test_catalog_size(tmp_path):
    db, _, counts = _gen(tmp_path)
    assert counts["sku_master"] == N_SKUS
    assert counts["lots"] > N_SKUS          # 1-4 lots per SKU
    assert counts["erp_transactions"] > 0
    assert counts["wms_pallets"] > 0
    assert counts["integration_log"] > 0


def test_deterministic(tmp_path):
    _, _, c1 = _gen(tmp_path / "a", seed=42)
    _, _, c2 = _gen(tmp_path / "b", seed=42)
    assert c1 == c2
    r1 = sorted((r["id"], r["category"]) for r in _gt_rows(tmp_path / "a" / "t.db"))
    r2 = sorted((r["id"], r["category"]) for r in _gt_rows(tmp_path / "b" / "t.db"))
    assert r1 == r2


def test_all_injection_types_present(tmp_path):
    db, _, _ = _gen(tmp_path)
    rows = _gt_rows(db)
    by_cat: dict[str, int] = {}
    for r in rows:
        by_cat[r["category"]] = by_cat.get(r["category"], 0) + 1
    for cat, n in INJECTION_PLAN:
        assert by_cat.get(cat) == n, f"{cat}: expected {n}, got {by_cat.get(cat)}"


def test_injection_details_are_json(tmp_path):
    db, _, _ = _gen(tmp_path)
    for r in _gt_rows(db):
        d = json.loads(r["detail"])
        assert isinstance(d, dict) and d  # non-empty JSON object


def test_failed_message_removes_erp_receipt_but_keeps_wms(tmp_path):
    db, _, _ = _gen(tmp_path)
    conn = sqlite3.connect(db)
    rows = _gt_rows(db)
    fm = [r for r in rows if r["category"] == "failed_message"]
    assert fm
    r = fm[0]
    erp_n = conn.execute(
        "SELECT COUNT(*) FROM erp_transactions WHERE ref_doc=?", (f"PR-{r['lot_code']}",)
    ).fetchone()[0]
    wms_q = conn.execute(
        "SELECT SUM(qty_base) FROM wms_pallets WHERE lot_code=?", (r["lot_code"],)
    ).fetchone()[0]
    n_failed = conn.execute(
        "SELECT COUNT(*) FROM integration_log WHERE ref_doc=? AND status='FAILED'",
        (f"PR-{r['lot_code']}",)
    ).fetchone()[0]
    conn.close()
    assert erp_n == 0            # ERP never got it
    assert wms_q and wms_q > 0   # WMS has the pallets
    assert n_failed == 1         # the FAILED message is in the log


def test_wrong_bin_move_logged_but_location_stale(tmp_path):
    db, _, _ = _gen(tmp_path)
    conn = sqlite3.connect(db)
    rows = [r for r in _gt_rows(db) if r["category"] == "wrong_bin"]
    assert rows
    r = rows[0]
    d = json.loads(r["detail"])
    loc = conn.execute("SELECT location FROM wms_pallets WHERE pallet_id=?",
                       (r["pallet_id"],)).fetchone()[0]
    true = conn.execute(
        "SELECT to_loc FROM wms_moves WHERE pallet_id=? ORDER BY moved_at DESC LIMIT 1",
        (r["pallet_id"],)).fetchone()[0]
    conn.close()
    assert loc == d["recorded_bin"]      # stale
    assert true == d["true_bin"]         # move log has the truth
    assert loc != true


def test_clean_baseline_has_no_ground_truth(tmp_path):
    db, _, counts = _gen(tmp_path, do_inject=False)
    assert counts["ground_truth"] == 0
