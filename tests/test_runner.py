"""Tests for the M3 long-running loop + approval queue."""
import hashlib
import json
import sqlite3
from datetime import datetime

import pytest

from phantom_hunter import reconcile, tools
from phantom_hunter.agent import InvestigationAgent
from phantom_hunter.generator import Gen
from phantom_hunter.llm import LLMClient
from phantom_hunter.runner import Loop, disc_key, priority_score


@pytest.fixture()
def loop(tmp_path):
    db = tmp_path / "t.db"
    Gen(seed=42).run(db, tmp_path / "labels", do_inject=True)
    llm = LLMClient(data_dir=tmp_path)
    return Loop(db, tmp_path / "labels", llm=llm)


def _business_hash(db_path):
    conn = sqlite3.connect(db_path)
    h = hashlib.sha256()
    for t in ("erp_transactions", "erp_inventory", "wms_pallets",
              "integration_log", "wms_moves"):
        for row in conn.execute(f"SELECT * FROM {t} ORDER BY 1"):
            h.update(repr(row).encode())
    conn.close()
    return h.hexdigest()


def test_first_tick_investigates_everything(loop):
    res = loop.tick()
    assert res["streamed"] is None
    assert res["discrepancies"] == 34
    assert res["new"] == 34
    assert len(res["investigated"]) == 34
    q = loop.queue()
    assert len(q) == 34
    assert {r["status"] for r in q} == {"PENDING_APPROVAL"}


def test_second_tick_dedupes(loop):
    loop.tick()
    res = loop.tick()
    assert res["new"] == 0
    assert res["investigated"] == []


def test_streaming_advances_world_and_adds_new(loop):
    loop.tick()
    before = loop.now()
    res = loop.tick(stream_days=2, inject_per_day=2)
    assert res["streamed"]["days_streamed"] == 2
    assert res["streamed"]["injected"] == 4
    # 4 injected + 5 baseline cutoff_gaps that aged out of the 60-min sync
    # window and escalated to real qty_mismatches (new disc_key -> reinvestigated)
    assert res["new"] == 9
    assert loop.now() > before


def test_stale_pending_escalates_to_failed_message(loop):
    loop.tick()
    loop.tick(stream_days=2, inject_per_day=0)
    conn = sqlite3.connect(loop.db_path)
    conn.row_factory = sqlite3.Row
    try:
        escalated = [dict(r) for r in conn.execute(
            """SELECT i.sku, i.lot_code, i.root_cause, g.category AS gt_category
               FROM investigations i JOIN ground_truth g
                 ON g.sku = i.sku AND g.lot_code = i.lot_code
               WHERE g.category = 'cutoff_gap' AND i.category = 'qty_mismatch'""")]
    finally:
        conn.close()
    assert len(escalated) == 5
    assert {e["root_cause"] for e in escalated} == {"failed_message"}


def test_queue_sorted_by_priority_desc(loop):
    loop.tick()
    q = loop.queue()
    pris = [r["priority"] for r in q]
    assert pris == sorted(pris, reverse=True)


def test_expired_lots_get_priority_boost(loop):
    loop.tick()
    q = {r["id"]: r for r in loop.queue()}
    exp = [r for r in q.values() if r["category"] == "expired_available"]
    assert exp
    for r in exp:
        assert r["priority"] == round(r["value_at_risk"] * 1.5, 2)


def test_repeat_root_causes_are_grouped(loop):
    loop.tick()
    first = loop.queue()[0]
    # simulate the same failure recurring on a different lot next week
    conn = sqlite3.connect(loop.db_path)
    conn.row_factory = sqlite3.Row
    fake_disc = {"id": "D-9999", "detected_at": datetime.now().isoformat(),
                 "category": first["category"], "sku": first["sku"],
                 "lot_code": "L20990101-XXXX00", "pallet_id": None,
                 "value_at_risk": 123.45}
    fake_inv = {"root_cause": first["root_cause"], "confidence": 0.9,
                "evidence": ["x"], "proposed_fix": {"action": "a"}, "mode": "fallback"}
    new_id = loop._file(conn, fake_disc, fake_inv, loop.now())
    conn.commit()
    row = conn.execute("SELECT repeat_group FROM investigations WHERE id=?",
                       (new_id,)).fetchone()
    conn.close()
    # linked to the earliest investigation with the same root cause + SKU
    assert row[0] is not None
    assert row[0] != new_id


def test_approve_and_reject(loop):
    loop.tick()
    q = loop.queue()
    a, b = q[0]["id"], q[1]["id"]
    assert loop.approve(a, note="resent the message")["status"] == "APPROVED"
    assert loop.reject(b, note="false positive")["status"] == "REJECTED"
    s = loop.summary()["by_status"]
    assert s["APPROVED"] == 1 and s["REJECTED"] == 1
    assert s["PENDING_APPROVAL"] == len(q) - 2
    with pytest.raises(ValueError):
        loop.approve(a)  # already decided


def test_decisions_never_touch_business_tables(loop):
    loop.tick()
    before = _business_hash(loop.db_path)
    q = loop.queue()
    loop.approve(q[0]["id"])
    loop.reject(q[1]["id"], note="nope")
    assert _business_hash(loop.db_path) == before


def test_unknown_investigation_decision_raises(loop):
    loop.tick()
    with pytest.raises(ValueError):
        loop.approve("INV-9999")


def test_disc_key_is_stable():
    d = {"category": "qty_mismatch", "sku": "S", "lot_code": "L", "pallet_id": None}
    assert disc_key(d) == disc_key(dict(d))
    d2 = dict(d, pallet_id="PLT-1")
    assert disc_key(d2) != disc_key(d)
