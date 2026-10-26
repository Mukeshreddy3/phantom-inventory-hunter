"""Pallet-label vision (M2 agent's label_contradiction catch).

The text investigation loop cannot read images: its tool calls carry text
arguments only. Label reading therefore runs as its own step. The model
reads a pallet's label photo through the Meta Model API image input and
the read is compared field by field against the WMS pallet record. A
mismatch on lot, quantity, or bin is a ``label_contradiction`` diagnosis
whose fix (quarantine for relabel) requires human approval, like every
other proposed fix.

Ground truth is NEVER an input here. It is consulted only by the
``--score`` output path, exactly like ``eval.py`` scores investigations.

Vision honestly requires an API key. Without one, every entry point
raises a clear error instead of guessing from filenames or metadata.

Usage:
    python -m phantom_hunter.vision --db data/phantom.db --labels data/labels
    python -m phantom_hunter.vision --pallet PLT-000123 --score
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path

from . import tools
from .llm import LLMClient, extract_json_object

LABEL_PROMPT = """Read this warehouse pallet label image. Return JSON ONLY, no prose:
{"sku": "<sku>", "lot_code": "<lot>", "qty": <number>, "uom": "<unit>",
 "expiry": "<YYYY-MM-DD>", "location": "<bin>", "pallet_id": "<pallet id>"}.
Copy each field exactly as printed. If a field is unreadable, use null."""

# Fields the operation contradicts (generator._inj_label_contradiction).
# SKU, expiry, and pallet id are reported as read but never scored as
# contradictions: a model misread there would be a false accusation.
COMPARE_FIELDS = ("lot_code", "qty", "location")

QTY_TOLERANCE = 0.01


def _quarantine_fix(pallet_id: str) -> dict:
    """Same shape as agent._fix; kept local to avoid an agent import cycle."""
    return {"action": "quarantine_pallet_for_relabel",
            "params": {"pallet_id": pallet_id},
            "description": f"Quarantine pallet {pallet_id}: physical label "
                           f"contradicts the WMS record. Verify by hand and relabel.",
            "requires_approval": True}


def read_label(llm, image_path: Path, hard: bool = True) -> dict:
    """Read one label photo through the model. Returns the read + usage.

    Raises RuntimeError when no API key is set, and when the model
    returns no parseable label JSON.
    """
    if getattr(llm, "mode", None) != "api":
        raise RuntimeError("vision requires an API key: LLMClient mode is "
                           "fallback (set META_MODEL_API_KEY)")
    messages = [LLMClient.image_message(LABEL_PROMPT, Path(image_path))]
    resp = llm.chat(messages, hard=hard, purpose="vision")
    read = extract_json_object(resp.get("text"))
    if read is None:
        raise RuntimeError("model returned no parseable label JSON")
    return {"read": read, "model": resp.get("model"),
            "usage": resp.get("usage", {}), "cached": resp.get("cached", False),
            "mode": "api"}


def compare_label(read: dict, pallet: dict) -> list[dict]:
    """Field mismatches between a label read and the WMS pallet record."""
    system = {"lot_code": pallet.get("lot_code"),
              "qty": pallet.get("qty_base"),
              "location": pallet.get("location")}
    mismatches = []
    for field in COMPARE_FIELDS:
        label_value, system_value = read.get(field), system[field]
        if label_value is None or system_value is None:
            continue
        if field == "qty":
            try:
                differs = abs(float(label_value) - float(system_value)) > QTY_TOLERANCE
            except (TypeError, ValueError):
                differs = str(label_value) != str(system_value)
        else:
            differs = str(label_value).strip() != str(system_value).strip()
        if differs:
            mismatches.append({"field": field,
                               "label_value": str(label_value),
                               "system_value": str(system_value)})
    return mismatches


def investigate_pallet_label(db_path: Path, label_dir: Path, llm,
                             pallet_id: str) -> dict:
    """Diagnose one pallet's label against its WMS record.

    Status is one of: contradiction, match, no_label_image,
    unknown_pallet. Ground truth plays no part in the diagnosis.
    """
    pallet = tools.get_pallet(db_path, pallet_id)
    if pallet is None:
        return {"pallet_id": pallet_id, "status": "unknown_pallet",
                "root_cause": None, "confidence": 0.0, "mismatches": [],
                "read": None, "system": None, "proposed_fix": None,
                "evidence": [f"no WMS pallet row for {pallet_id}"],
                "mode": getattr(llm, "mode", "fallback")}
    image = tools.label_image_path(label_dir, pallet_id)
    if image is None:
        return {"pallet_id": pallet_id, "status": "no_label_image",
                "root_cause": None, "confidence": 0.0, "mismatches": [],
                "read": None, "system": pallet, "proposed_fix": None,
                "evidence": [f"no label photo for {pallet_id}"],
                "mode": getattr(llm, "mode", "fallback")}
    try:
        out = read_label(llm, image)
    except RuntimeError as e:
        return {"pallet_id": pallet_id, "status": "error",
                "root_cause": None, "confidence": 0.0, "mismatches": [],
                "read": None, "system": pallet, "proposed_fix": None,
                "evidence": [str(e)],
                "mode": getattr(llm, "mode", "fallback")}
    mismatches = compare_label(out["read"], pallet)
    if mismatches:
        detail = "; ".join(f"{m['field']}: label {m['label_value']} vs "
                           f"system {m['system_value']}" for m in mismatches)
        return {"pallet_id": pallet_id, "status": "contradiction",
                "root_cause": "label_contradiction", "confidence": 0.9,
                "mismatches": mismatches, "read": out["read"],
                "system": pallet, "proposed_fix": _quarantine_fix(pallet_id),
                "evidence": [f"label photo {image.name} read by "
                             f"{out['model']}", f"mismatch: {detail}"],
                "mode": "api"}
    return {"pallet_id": pallet_id, "status": "match", "root_cause": None,
            "confidence": 0.9, "mismatches": [], "read": out["read"],
            "system": pallet, "proposed_fix": None,
            "evidence": [f"label photo {image.name} matches the WMS record"],
            "mode": "api"}


def scan_labels(db_path: Path, label_dir: Path, llm, limit: int | None = None,
                pallet: str | None = None, score: bool = False) -> dict:
    """Scan label photos for contradictions. Ground truth only scores.

    Returns {"results": [...], "scanned": n, "contradictions": m,
    "scored": {"correct": x, "total": y} | None}.
    """
    if getattr(llm, "mode", None) != "api":
        raise RuntimeError("vision requires an API key: LLMClient mode is "
                           "fallback (set META_MODEL_API_KEY)")
    if pallet:
        pallet_ids = [pallet]
    else:
        pallet_ids = sorted(p.stem for p in Path(label_dir).glob("*.png"))
    if limit is not None:
        pallet_ids = pallet_ids[:limit]
    results = []
    for pid in pallet_ids:
        try:
            results.append(investigate_pallet_label(db_path, label_dir, llm, pid))
        except RuntimeError as e:
            results.append({"pallet_id": pid, "status": "error",
                            "root_cause": None, "confidence": 0.0,
                            "mismatches": [], "read": None, "system": None,
                            "proposed_fix": None, "evidence": [str(e)],
                            "mode": "api"})
    scored = None
    if score:
        correct = total = 0
        for r in results:
            gt = tools.ground_truth_for(db_path, None, None, r["pallet_id"])
            if gt is None:
                continue
            total += 1
            is_contra = gt["category"] == "label_contradiction"
            if is_contra == (r["status"] == "contradiction"):
                correct += 1
                r["score"] = "correct"
            else:
                r["score"] = "incorrect"
        scored = {"correct": correct, "total": total}
    return {"results": results, "scanned": len(results),
            "contradictions": sum(1 for r in results
                                  if r["status"] == "contradiction"),
            "scored": scored}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="data/phantom.db")
    ap.add_argument("--labels", default="data/labels")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--pallet", default=None)
    ap.add_argument("--score", action="store_true")
    args = ap.parse_args()

    db_path, label_dir = Path(args.db), Path(args.labels)
    if not db_path.exists():
        raise SystemExit(f"DB not found: {db_path} — run `make data` first.")
    llm = LLMClient(data_dir=db_path.parent)
    try:
        report = scan_labels(db_path, label_dir, llm, limit=args.limit,
                             pallet=args.pallet, score=args.score)
    except RuntimeError as e:
        print(f"vision unavailable: {e}")
        raise SystemExit(2)
    for r in report["results"]:
        if r["status"] == "contradiction":
            detail = "; ".join(f"{m['field']}: label {m['label_value']} vs "
                               f"system {m['system_value']}"
                               for m in r["mismatches"])
            line = (f"{r['pallet_id']}: CONTRADICTION ({detail}) | "
                    f"proposed fix [REQUIRES APPROVAL]: "
                    f"quarantine_pallet_for_relabel")
        elif r["status"] == "match":
            line = f"{r['pallet_id']}: match"
        else:
            line = f"{r['pallet_id']}: {r['status']} ({'; '.join(r['evidence'])})"
        if "score" in r:
            line += f" [{r['score']}]"
        print(line)
    print("=" * 72)
    summary = (f"scanned {report['scanned']} | "
               f"contradictions {report['contradictions']}")
    if report["scored"] is not None:
        s = report["scored"]
        summary += f" | scored accuracy {s['correct']}/{s['total']}"
    print(summary)


if __name__ == "__main__":
    main()
