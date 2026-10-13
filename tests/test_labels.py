"""Tests for pallet-label image generation."""
import json
import sqlite3
from pathlib import Path

from PIL import Image

from phantom_hunter.generator import Gen


def _gen(tmp_path: Path):
    db = tmp_path / "t.db"
    labels = tmp_path / "labels"
    Gen(seed=42).run(db, labels, do_inject=True)
    return db, labels


def test_label_images_exist_and_are_valid_png(tmp_path):
    _, labels = _gen(tmp_path)
    pngs = list(labels.glob("*.png"))
    assert len(pngs) >= 40
    for p in pngs[:10]:
        with Image.open(p) as im:
            im.verify()
        with Image.open(p) as im:
            assert im.size == (480, 320)


def test_contradiction_labels_exist_and_differ(tmp_path):
    db, labels = _gen(tmp_path)
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    rows = [dict(r) for r in conn.execute(
        "SELECT * FROM ground_truth WHERE category='label_contradiction'")]
    conn.close()
    assert len(rows) == 5
    for r in rows:
        p = labels / f"{r['pallet_id']}.png"
        assert p.exists(), f"missing label image for {r['pallet_id']}"
        d = json.loads(r["detail"])
        assert d["label_value"] != d["system_value"], \
            "contradiction label must actually differ from system data"
