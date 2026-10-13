"""Tests for the M4 dashboard API + evaluation (live stdlib server)."""
import http.client
import json
import sqlite3
import threading

import pytest

from phantom_hunter import eval as eval_mod
from phantom_hunter.dashboard import serve
from phantom_hunter.generator import Gen
from phantom_hunter.llm import LLMClient
from phantom_hunter.runner import Loop


@pytest.fixture(scope="module")
def server(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("web")
    db = tmp / "t.db"
    Gen(seed=42).run(db, tmp / "labels", do_inject=True)
    loop = Loop(db, tmp / "labels", llm=LLMClient(data_dir=tmp))
    loop.tick()
    srv = serve(db, tmp / "labels", 0)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield srv.server_address[0], srv.server_address[1], tmp
    srv.shutdown()
    t.join(timeout=5)


def _get(server, path):
    conn = http.client.HTTPConnection(server[0], server[1], timeout=10)
    conn.request("GET", path)
    r = conn.getresponse()
    body, ctype = r.read(), r.getheader("Content-Type", "")
    conn.close()
    return r.status, json.loads(body) if "application/json" in ctype else body


def _post(server, path, body):
    conn = http.client.HTTPConnection(server[0], server[1], timeout=10)
    data = json.dumps(body).encode()
    conn.request("POST", path, body=data,
                 headers={"Content-Type": "application/json"})
    r = conn.getresponse()
    out = (r.status, json.loads(r.read()))
    conn.close()
    return out


def test_index_serves_html(server):
    status, body = _get(server, "/")
    assert status == 200
    assert b"Phantom Inventory Hunter" in body


def test_static_assets(server):
    for path, marker in (("/app.js", b"loadSummary"), ("/styles.css", b":root")):
        status, body = _get(server, path)
        assert status == 200 and marker in body


def test_summary(server):
    status, s = _get(server, "/api/summary")
    assert status == 200
    assert s["open_count"] == 34
    assert s["investigated"] == 34
    assert s["pending"] == 34
    assert s["value_at_risk_open"] > 400_000
    assert s["accuracy"] == 1.0
    assert len(s["top_root_causes_week"]) > 0


def test_discrepancies_sorted_by_value(server):
    status, rows = _get(server, "/api/discrepancies")
    assert status == 200 and len(rows) == 34
    vals = [r["value_at_risk"] for r in rows]
    assert vals == sorted(vals, reverse=True)
    assert all(r["investigation_id"] for r in rows)


def test_discrepancy_detail(server):
    status, rows = _get(server, "/api/discrepancies")
    disc_id = rows[0]["id"]
    status, d = _get(server, f"/api/discrepancy/{disc_id}")
    assert status == 200
    assert d["discrepancy"]["id"] == disc_id
    inv = d["investigation"]
    assert inv and len(inv["evidence"]) >= 2
    assert inv["proposed_fix"]["requires_approval"] is True
    status, _ = _get(server, "/api/discrepancy/D-9999")
    assert status == 404


def test_eval_endpoint(server):
    status, e = _get(server, "/api/eval")
    assert status == 200
    assert e["accuracy"] == 1.0
    assert e["misses"] == []
    assert set(e["per_category"]) == {"failed_message", "duplicate_message",
                                     "unposted_receipt", "wrong_uom", "wrong_bin",
                                     "expired_available", "cutoff_gap"}


def test_approve_reject_api(server):
    _, queue = _get(server, "/api/queue")
    inv_id = queue[0]["id"]
    status, r = _post(server, f"/api/investigations/{inv_id}/approve",
                      {"note": "api test"})
    assert status == 200 and r["status"] == "APPROVED"
    status, r = _post(server, f"/api/investigations/{inv_id}/approve", {})
    assert status == 400  # already decided
    status, r = _post(server, "/api/investigations/INV-9999/reject", {})
    assert status == 400
    _, s = _get(server, "/api/summary")
    assert s["pending"] == 33 and s["approved"] == 1
    assert s["value_reconciled"] > 0


def test_label_endpoint(server):
    host, port, tmp = server
    png = next((tmp / "labels").glob("*.png"))
    status, body = _get(server, f"/api/labels/{png.name}")
    assert status == 200 and body[:8] == b"\x89PNG\r\n\x1a\n"
    status, _ = _get(server, "/api/labels/PLT-999999.png")
    assert status == 404


def test_is_correct_stale_pending_rule(tmp_path):
    db = tmp_path / "s.db"
    Gen(seed=1).run(db, tmp_path / "l", do_inject=False)
    conn = sqlite3.connect(db)
    conn.execute(
        "INSERT INTO integration_log VALUES (?,?,?,?,?,?,?,?,?,?)",
        ("MSG-1", "2026-10-10T10:00:00", "WMS->ERP", "SHIP_CONFIRM",
         "S", "L", -5.0, "PENDING", None, "SO-1"))
    conn.commit()
    inv = {"root_cause": "failed_message", "sku": "S", "lot_code": "L",
           "investigated_at": "2026-10-13T11:00:00"}
    gt = {"category": "cutoff_gap"}
    assert eval_mod.is_correct(conn, inv, gt) is True   # 3-day-old pending: stuck
    conn.execute("UPDATE integration_log SET created_at='2026-10-13T10:50:00'")
    assert eval_mod.is_correct(conn, inv, gt) is False  # 10-min-old: still a gap
    conn.close()
