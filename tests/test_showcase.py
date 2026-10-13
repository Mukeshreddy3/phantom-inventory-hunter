"""Tests for the M5 scripted demo: the $48K expired lot in rack 14."""
import sqlite3

from phantom_hunter import reconcile, tools
from phantom_hunter.agent import InvestigationAgent
from phantom_hunter.generator import Gen
from phantom_hunter.llm import LLMClient
from phantom_hunter.showcase import inject_showcase, refresh_erp_snapshot


def _showcase_db(tmp_path):
    db = tmp_path / "s.db"
    labels = tmp_path / "sl"
    gen = Gen(seed=7)
    gen.run(db, labels, do_inject=True)
    conn = sqlite3.connect(db)
    sc = inject_showcase(gen, conn.cursor())
    conn.commit()
    conn.close()
    refresh_erp_snapshot(db)
    return db, labels, sc


def test_showcase_discrepancy_value_and_rack(tmp_path):
    db, labels, sc = _showcase_db(tmp_path)
    discs = reconcile.run(db)
    hits = [d for d in discs if d["lot_code"] == sc["lot"]]
    assert len(hits) == 1
    d = hits[0]
    assert d["category"] == "expired_available"
    assert d["severity"] == "high"
    assert 47_000 <= d["value_at_risk"] <= 49_000
    assert d["erp_qty"] > 0  # ERP thinks it's available
    pallets = tools.query_wms_pallets(db, sc["sku"], sc["lot"])
    assert len(pallets) == 6
    assert all(p["location"].startswith("R14-") for p in pallets)
    assert all(p["status"] == "AVAILABLE" for p in pallets)


def test_showcase_agent_diagnoses_and_label_exists(tmp_path):
    db, labels, sc = _showcase_db(tmp_path)
    discs = reconcile.run(db)
    d = next(x for x in discs if x["lot_code"] == sc["lot"])
    agent = InvestigationAgent(db, labels, LLMClient(data_dir=tmp_path))
    inv = agent.investigate(d["id"])
    assert inv["root_cause"] == "expired_available"
    assert inv["proposed_fix"]["action"] == "write_off_expired_lot"
    assert inv["proposed_fix"]["requires_approval"] is True
    assert (labels / f"{sc['pallet_id']}.png").exists()
