"""Tests for the vision path (label_contradiction catch).

The fake LLM returns canned label reads, so no API key is needed. Ground
truth is used only to pick test fixtures and to score, never as an
input to the diagnosis under test.
"""
import json
import sqlite3
from pathlib import Path

import pytest

from phantom_hunter import reconcile, tools, vision
from phantom_hunter.generator import Gen
from phantom_hunter.llm import extract_json_object


class FakeLLM:
    """Queued canned replies; mode api unless told otherwise."""

    def __init__(self, texts, mode="api"):
        self._texts = list(texts)
        self.mode = mode

    def chat(self, messages, **kwargs):
        text = self._texts.pop(0)
        return {"text": text, "model": "fake",
                "usage": {"prompt_tokens": 10, "completion_tokens": 20},
                "cached": False, "mode": self.mode}


@pytest.fixture()
def db(tmp_path):
    p = tmp_path / "t.db"
    Gen(seed=42).run(p, tmp_path / "labels", do_inject=True)
    reconcile.run(p)
    return p, tmp_path / "labels"


def _contra_pallet(db):
    conn = sqlite3.connect(db)
    try:
        r = conn.execute("SELECT pallet_id, detail FROM ground_truth "
                         "WHERE category='label_contradiction' LIMIT 1").fetchone()
    finally:
        conn.close()
    assert r, "no label_contradiction injection"
    return r[0], json.loads(r[1])


def _clean_pallet(db, label_dir):
    """A pallet with a label photo and no label_contradiction ground truth."""
    conn = sqlite3.connect(db)
    try:
        contra = {r[0] for r in conn.execute(
            "SELECT pallet_id FROM ground_truth "
            "WHERE category='label_contradiction'")}
    finally:
        conn.close()
    for png in sorted(label_dir.glob("*.png")):
        if png.stem not in contra and tools.get_pallet(db, png.stem):
            return png.stem
    raise AssertionError("no clean labelled pallet")


def _read_for(db, pallet_id, override_field=None, override_value=None):
    row = tools.get_pallet(db, pallet_id)
    read = {"sku": row["sku"], "lot_code": row["lot_code"],
            "qty": row["qty_base"], "uom": row["uom"],
            "expiry": row["expiry_date"], "location": row["location"],
            "pallet_id": pallet_id}
    if override_field:
        read[override_field] = override_value
    return read


def test_read_label_parses_prose_prefixed_json(db):
    _, label_dir = db
    png = sorted(label_dir.glob("*.png"))[0]
    fake = FakeLLM(['Reading the label now.{"sku": "X", "lot_code": "L"}'])
    out = vision.read_label(fake, png)
    assert out["read"]["sku"] == "X"
    assert out["mode"] == "api"


def test_read_label_requires_api_key(db):
    _, label_dir = db
    png = sorted(label_dir.glob("*.png"))[0]
    with pytest.raises(RuntimeError, match="requires an API key"):
        vision.read_label(FakeLLM(['{"sku": "X"}'], mode="fallback"), png)


def test_compare_finds_each_contradiction_field():
    pallet = {"lot_code": "L1", "qty_base": 100.0, "location": "R01-01-1"}
    base = {"lot_code": "L1", "qty": 100.0, "location": "R01-01-1"}
    assert vision.compare_label(base, pallet) == []
    assert vision.compare_label({**base, "lot_code": "L2"}, pallet) == [
        {"field": "lot_code", "label_value": "L2", "system_value": "L1"}]
    assert vision.compare_label({**base, "qty": 50.0}, pallet) == [
        {"field": "qty", "label_value": "50.0", "system_value": "100.0"}]
    assert vision.compare_label({**base, "location": "R02-02-2"}, pallet) == [
        {"field": "location", "label_value": "R02-02-2",
         "system_value": "R01-01-1"}]
    # tiny float noise is not a contradiction
    assert vision.compare_label({**base, "qty": 100.005}, pallet) == []


def test_investigate_label_contradiction(db):
    db_path, label_dir = db
    pid, detail = _contra_pallet(db_path)
    read = _read_for(db_path, pid, detail["field"], detail["label_value"])
    fake = FakeLLM([json.dumps(read)])
    result = vision.investigate_pallet_label(db_path, label_dir, fake, pid)
    assert result["status"] == "contradiction"
    assert result["root_cause"] == "label_contradiction"
    assert [m["field"] for m in result["mismatches"]] == [detail["field"]]
    assert result["proposed_fix"]["action"] == "quarantine_pallet_for_relabel"
    assert result["proposed_fix"]["requires_approval"] is True


def test_investigate_label_match(db):
    db_path, label_dir = db
    pid = _clean_pallet(db_path, label_dir)
    fake = FakeLLM([json.dumps(_read_for(db_path, pid))])
    result = vision.investigate_pallet_label(db_path, label_dir, fake, pid)
    assert result["status"] == "match"
    assert result["root_cause"] is None
    assert result["mismatches"] == []


def test_investigate_label_no_image(db):
    db_path, label_dir = db
    conn = sqlite3.connect(db_path)
    try:
        have = {p.stem for p in label_dir.glob("*.png")}
        row = conn.execute("SELECT pallet_id FROM wms_pallets").fetchone()
        pids = [r[0] for r in conn.execute("SELECT pallet_id FROM wms_pallets")]
    finally:
        conn.close()
    pid = next(p for p in pids if p not in have)
    result = vision.investigate_pallet_label(
        db_path, label_dir, FakeLLM([]), pid)
    assert result["status"] == "no_label_image"


def test_scan_scores_only_with_ground_truth(db):
    db_path, label_dir = db
    pid, detail = _contra_pallet(db_path)
    read = _read_for(db_path, pid, detail["field"], detail["label_value"])
    fake = FakeLLM([json.dumps(read)])
    report = vision.scan_labels(db_path, label_dir, fake, pallet=pid, score=True)
    assert report["scanned"] == 1
    assert report["contradictions"] == 1
    assert report["scored"] == {"correct": 1, "total": 1}
    assert report["results"][0]["score"] == "correct"


def test_scan_requires_api_key(db):
    db_path, label_dir = db
    with pytest.raises(RuntimeError, match="requires an API key"):
        vision.scan_labels(db_path, label_dir, FakeLLM([], mode="fallback"),
                           limit=1)
