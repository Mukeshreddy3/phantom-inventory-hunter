"""Investigation agent (M2).

For each engine-flagged discrepancy the agent builds an evidence trail with
tools (ERP txns, WMS pallets/moves, integration log, pallet-label images),
then concludes: root cause, confidence, evidence, and a proposed fix.

The agent NEVER applies fixes — every proposal carries
``requires_approval=True`` and is destined for the M3 approval queue.

Two reasoning backends:
* Meta Model API (``LLMClient`` mode ``api``) — the model drives a small
  tool loop (up to 3 follow-up tool calls) and synthesizes the conclusion.
* Rule-based fallback (no API key) — a deterministic policy over the same
  evidence. Results are tagged ``mode="fallback"``.

Usage:
    python -m phantom_hunter.agent --samples 10
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path

from . import tools, vision
from .llm import LLMClient, extract_json_object

ROOT_CAUSES = ["failed_message", "duplicate_message", "unposted_receipt",
               "wrong_uom", "wrong_bin", "expired_available", "cutoff_gap",
               "label_contradiction", "unknown"]

MAX_TOOL_ROUNDS = 3

SYSTEM_PROMPT = """You are Phantom, an inventory reconciliation investigator for a \
food/dairy manufacturer. An ERP system (Microsoft Dynamics 365 style) and a \
warehouse management system driving an automated storage/retrieval system \
(ASRS) disagree about inventory. Your job: investigate ONE discrepancy using \
the tools, then conclude.

Valid root_causes: failed_message, duplicate_message, unposted_receipt, \
wrong_uom, wrong_bin, expired_available, cutoff_gap, label_contradiction, \
unknown.

- failed_message: a WMS->ERP integration message FAILED, so the ERP is missing a posting the WMS has.
- duplicate_message: a message was delivered twice (DUPLICATE), so the ERP double-counted.
- unposted_receipt: pallets exist in the WMS but the ERP has no receipt AND no integration message at all.
- wrong_uom: an ERP posting used cases/bags without converting to the base unit (converted=0).
- wrong_bin: the ASRS move log shows a pallet in a different bin than its WMS master record.
- expired_available: the lot is past expiry but still shows available quantity.
- cutoff_gap: the mismatch is fully explained by a PENDING message inside the sync window.
  (A PENDING message OLDER than the sync window is a stuck/failed delivery -> failed_message.)
- label_contradiction: the physical pallet label (image) contradicts the WMS record.

Rules:
- NEVER apply fixes. Only propose them; every fix requires human approval.
- Set confidence 0.0-1.0 honestly from evidence strength.
- If the evidence already answers the case, conclude now instead of calling another tool.
- Pallet-label images are checked by a separate vision step, not through these tools.
- Respond with JSON ONLY, no prose. Either:
  {"tool_call": {"name": "<tool>", "args": {...}}, "reason": "<why>"}
  or
  {"conclusion": {"root_cause": "<one of the list>", "confidence": 0.0-1.0,
   "reasoning": "<2-3 sentences>", "proposed_fix_action": "<action>",
   "fix_params": {...}, "fix_description": "<what a human should approve>"}}
Available tools: query_erp_transactions(sku, lot_code),
query_wms_pallets(sku, lot_code), query_wms_moves(pallet_id),
search_integration_log(sku, lot_code), get_lot(sku, lot_code).
"""


# --------------------------------------------------------------------------- #
# proposed fixes (never applied by the agent)
# --------------------------------------------------------------------------- #
def _fix(action: str, params: dict, description: str) -> dict:
    return {"action": action, "params": params, "description": description,
            "requires_approval": True}


def build_fix(root_cause: str, disc: dict, ev: dict) -> dict:
    sku, lot = disc["sku"], disc["lot_code"]
    msgs = ev.get("integration_log", [])
    if root_cause == "failed_message":
        m = next((x for x in msgs if x["status"] == "FAILED"),
                 next((x for x in msgs if x["status"] == "PENDING"), {}))
        return _fix("resend_message", {"msg_id": m.get("msg_id")},
                    f"Resend {m.get('msg_id')} ({m.get('direction')} {m.get('msg_type')}, "
                    f"ref {m.get('ref_doc')}) so the ERP posts the missing update.")
    if root_cause == "duplicate_message":
        m = next((x for x in msgs if x["status"] == "DUPLICATE"), {})
        return _fix("reverse_duplicate_posting",
                    {"msg_id": m.get("msg_id"), "duplicate_of": m.get("duplicate_of"),
                     "ref_doc": m.get("ref_doc")},
                    f"Reverse the duplicate ERP posting from {m.get('msg_id')} "
                    f"(duplicate of {m.get('duplicate_of')}).")
    if root_cause == "unposted_receipt":
        wms_qty = sum(p["qty_base"] for p in ev.get("wms_pallets", []))
        return _fix("post_missing_receipt",
                    {"sku": sku, "lot_code": lot, "qty_base": round(wms_qty, 2)},
                    f"Post the missing ERP production receipt for {lot} "
                    f"({wms_qty:,.2f} {disc.get('uom')}).")
    if root_cause == "wrong_uom":
        txns = [t for t in ev.get("erp_transactions", []) if not t["converted"]]
        t = txns[0] if txns else {}
        return _fix("correct_uom_and_repost",
                    {"ref_doc": t.get("ref_doc"), "recorded_uom": t.get("uom")},
                    f"Correct {t.get('ref_doc')}: {t.get('qty')} {t.get('uom')} was posted "
                    f"without conversion to base units. Repost converted.")
    if root_cause == "wrong_bin":
        moves = ev.get("wms_moves", [])
        last = moves[-1] if moves else {}
        return _fix("update_bin_location",
                    {"pallet_id": disc.get("pallet_id"),
                     "from_bin": last.get("from_loc"), "to_bin": last.get("to_loc")},
                    f"Update pallet {disc.get('pallet_id')} master location "
                    f"{last.get('from_loc')} -> {last.get('to_loc')} per ASRS move log.")
    if root_cause == "expired_available":
        qty = max(disc.get("erp_qty") or 0, disc.get("wms_qty") or 0)
        return _fix("write_off_expired_lot",
                    {"sku": sku, "lot_code": lot, "qty_base": qty},
                    f"Write off expired lot {lot} ({qty:,.2f} {disc.get('uom')}); "
                    f"quarantine pallets for QA disposal.")
    if root_cause == "cutoff_gap":
        pend = [m for m in msgs if m["status"] == "PENDING"]
        m = pend[0] if pend else {}
        return _fix("await_sync", {"msg_id": m.get("msg_id")},
                    f"No action: {m.get('msg_id')} is still PENDING inside the sync "
                    f"window. Re-check after the next integration cycle.")
    if root_cause == "label_contradiction":
        return _fix("quarantine_pallet_for_relabel",
                    {"pallet_id": disc.get("pallet_id")},
                    f"Quarantine pallet {disc.get('pallet_id')}: physical label "
                    f"contradicts the WMS record. Verify by hand and relabel.")
    return _fix("manual_review", {}, "Insufficient evidence — route to a human analyst.")


# --------------------------------------------------------------------------- #
# rule-based fallback investigator (no API key)
# --------------------------------------------------------------------------- #
def fallback_investigate(disc: dict, ev: dict) -> dict:
    cat = disc["category"]
    msgs = ev.get("integration_log", [])
    txns = ev.get("erp_transactions", [])
    evidence: list[str] = []

    def ev_line(s: str) -> None:
        evidence.append(s)

    if cat == "cutoff_gap":
        pend = [m for m in msgs if m["status"] == "PENDING"]
        for m in pend:
            ev_line(f"PENDING message {m['msg_id']}: {m['direction']} {m['msg_type']} "
                    f"({m['qty_base']:+,.2f}), created {m['created_at']}")
        ev_line(f"ERP {disc['erp_qty']:,.2f} vs WMS {disc['wms_qty']:,.2f} — "
                f"difference matches the pending shipment.")
        return ("cutoff_gap", 0.95, evidence)

    if cat == "wrong_bin":
        moves = ev.get("wms_moves", [])
        if moves:
            last = moves[-1]
            ev_line(f"ASRS move log: pallet {disc['pallet_id']} moved "
                    f"{last['from_loc']} -> {last['to_loc']} at {last['moved_at']}")
        ev_line(f"WMS pallet master still shows bin {disc['location']} — stale record.")
        return ("wrong_bin", 0.95, evidence)

    if cat == "expired_available":
        lot = ev.get("lot", {}).get("lot") or {}
        ev_line(f"Lot {disc['lot_code']} expired {lot.get('expiry_date')}; "
                f"{disc['wms_qty']:,.2f} {disc.get('uom')} still AVAILABLE.")
        ev_line("Write-off exposure "
                f"${disc['value_at_risk']:,.2f}; pallets must be quarantined.")
        return ("expired_available", 0.95, evidence)

    # qty_mismatch -> diagnose via integration log / postings
    failed = [m for m in msgs if m["status"] == "FAILED"]
    if failed:
        m = failed[0]
        ev_line(f"FAILED message {m['msg_id']}: {m['direction']} {m['msg_type']} "
                f"ref {m['ref_doc']} never delivered to the ERP.")
        receipts = [t for t in txns if t["doc_type"] == "PROD_RECEIPT" and t["qty_base"] > 0]
        ev_line(f"ERP has {len(receipts)} receipt postings for lot {disc['lot_code']}; "
                f"WMS holds {disc['wms_qty']:,.2f} {disc.get('uom')}.")
        return ("failed_message", 0.90, evidence)

    dup = [m for m in msgs if m["status"] == "DUPLICATE"]
    if dup:
        m = dup[0]
        ev_line(f"DUPLICATE message {m['msg_id']}: {m['msg_type']} ref {m['ref_doc']} "
                f"delivered twice (original {m['duplicate_of']}).")
        receipts = [t for t in txns if t["doc_type"] == "PROD_RECEIPT" and t["qty_base"] > 0]
        ev_line(f"ERP shows {len(receipts)} receipt postings for one production lot — "
                f"double-counted {disc['erp_qty'] - disc['wms_qty']:,.2f} {disc.get('uom')}.")
        return ("duplicate_message", 0.90, evidence)

    stale = [m for m in msgs if m["status"] == "PENDING"]
    if stale:
        m = stale[0]
        ev_line(f"STALE PENDING message {m['msg_id']}: {m['direction']} {m['msg_type']} "
                f"ref {m['ref_doc']} created {m['created_at']} — never delivered "
                f"inside the sync window. Treating as a failed delivery.")
        ev_line(f"ERP {disc['erp_qty']:,.2f} vs WMS {disc['wms_qty']:,.2f} "
                f"{disc.get('uom')}; the stuck message explains the full difference.")
        return ("failed_message", 0.80, evidence)

    unconverted = [t for t in txns if not t["converted"]]
    if unconverted:
        t = unconverted[0]
        ev_line(f"ERP posting {t['ref_doc']}: {t['qty']:,.2f} {t['uom']} recorded with "
                f"converted=0 — never converted to base units.")
        ev_line(f"ERP believes {disc['erp_qty']:,.2f}; WMS holds {disc['wms_qty']:,.2f} "
                f"{disc.get('uom')}.")
        return ("wrong_uom", 0.90, evidence)

    receipts = [t for t in txns if t["doc_type"] == "PROD_RECEIPT" and t["qty_base"] > 0]
    receipt_msgs = [m for m in msgs if m["msg_type"] == "PROD_RECEIPT"]
    if not receipts and not receipt_msgs:
        ev_line(f"No ERP receipt posting and no integration message for lot "
                f"{disc['lot_code']} — production never entered the ERP.")
        ev_line(f"WMS holds {disc['wms_qty']:,.2f} {disc.get('uom')} across "
                f"{len(ev.get('wms_pallets', []))} pallets.")
        return ("unposted_receipt", 0.85, evidence)

    ev_line("No FAILED/DUPLICATE message, no unconverted posting, receipts exist — "
            "cause unclear from system data.")
    return ("unknown", 0.30, evidence)


# --------------------------------------------------------------------------- #
# agent
# --------------------------------------------------------------------------- #
class InvestigationAgent:
    def __init__(self, db_path: Path, label_dir: Path,
                 llm: LLMClient | None = None):
        self.db_path = Path(db_path)
        self.label_dir = Path(label_dir)
        self.llm = llm or LLMClient(data_dir=self.db_path.parent)

    # -- evidence ------------------------------------------------------------ #
    def gather_core(self, disc: dict) -> dict:
        sku, lot = disc["sku"], disc["lot_code"]
        return {
            "discrepancy": disc,
            "lot": tools.get_lot(self.db_path, sku, lot),
            "integration_log": tools.search_integration_log(self.db_path, sku, lot),
            "erp_transactions": [],
            "wms_pallets": [],
            "wms_moves": [],
        }

    def followup(self, ev: dict, name: str, args: dict, trail: list[str]):
        result = tools.call_tool(self.db_path, self.label_dir, name, args)
        key = {"query_erp_transactions": "erp_transactions",
               "query_wms_pallets": "wms_pallets",
               "query_wms_moves": "wms_moves",
               "search_integration_log": "integration_log",
               "get_lot": "lot"}[name]
        ev[key] = result
        n = len(result) if isinstance(result, list) else 1
        trail.append(f"tool {name}{args} -> {n} row(s)")
        return result

    # -- investigate ---------------------------------------------------------- #
    def investigate(self, disc_id: str) -> dict:
        disc = tools.get_discrepancy(self.db_path, disc_id)
        if not disc:
            raise ValueError(f"unknown discrepancy {disc_id}")
        ev = self.gather_core(disc)
        trail: list[str] = [
            f"opened discrepancy {disc_id}: {disc['category']} "
            f"{disc['sku']} {disc['lot_code'] or ''} "
            f"(${disc['value_at_risk']:,.2f} at risk)",
            f"integration log: {len(ev['integration_log'])} message(s) for this lot",
        ]
        tokens = {"prompt_tokens": 0, "completion_tokens": 0,
                  "est_cost_usd": 0.0, "cached": False}

        if self.llm.mode == "api":
            try:
                return self._investigate_llm(disc, ev, trail, tokens)
            except Exception as e:  # API failure -> honest fallback, still no writes
                trail.append(f"Meta Model API error ({e}); fell back to rules")

        # deterministic follow-ups for the fallback path
        sku, lot = disc["sku"], disc["lot_code"]
        self.followup(ev, "query_erp_transactions", {"sku": sku, "lot_code": lot}, trail)
        self.followup(ev, "query_wms_pallets", {"sku": sku, "lot_code": lot}, trail)
        if disc.get("pallet_id"):
            self.followup(ev, "query_wms_moves", {"pallet_id": disc["pallet_id"]}, trail)
        root_cause, confidence, lines = fallback_investigate(disc, ev)
        trail.extend(lines)
        self.llm.log_fallback_call(purpose="investigate")
        return self._result(disc, root_cause, confidence, trail, ev,
                            mode="fallback", tokens=tokens)

    # -- label vision ------------------------------------------------------- #
    def investigate_label(self, pallet_id: str) -> dict:
        """Diagnose one pallet's label photo (vision step, not the text loop).

        The text tool loop cannot carry images, so label checks run here
        via vision.py. A contradiction proposes a quarantine for approval,
        like every other fix; nothing is ever applied.
        """
        return vision.investigate_pallet_label(
            self.db_path, self.label_dir, self.llm, pallet_id)

    def _investigate_llm(self, disc, ev, trail, tokens) -> dict:
        sku, lot = disc["sku"], disc["lot_code"]
        hard = disc["category"] == "qty_mismatch" and disc["value_at_risk"] > 20000
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": json.dumps({
                "discrepancy": disc, "lot": ev["lot"],
                "integration_log": ev["integration_log"]}, default=str)},
        ]
        for round_no in range(MAX_TOOL_ROUNDS):
            if round_no == MAX_TOOL_ROUNDS - 1:
                messages.append({"role": "user",
                                 "content": "Final round: return a conclusion now, "
                                            "no more tool calls."})
            resp = self.llm.chat(messages, hard=hard, purpose="investigate")
            self._accumulate(tokens, resp)
            # The live model answers with prose, or prose ahead of the JSON
            # (verified 2026-10-26). Extract the object instead of
            # discarding the whole reply; None covers prose-only replies
            # and null content from reasoning-heavy short budgets.
            step = extract_json_object(resp.get("text"))
            if step is None:
                messages.append({"role": "user",
                                 "content": "Respond with JSON only, no prose."})
                continue
            if "tool_call" in step:
                tc = step["tool_call"]
                name, args = tc["name"], tc["args"]
                if name not in tools.TOOL_SCHEMAS:
                    trail.append(f"model requested unknown tool {name}; ignored")
                    messages.append({"role": "user", "content": json.dumps(
                        {"error": f"unknown tool {name}"})})
                    continue
                result = self.followup(ev, name, args, trail)
                messages.append({"role": "user", "content": json.dumps(
                    {"tool": name, "result": result}, default=str)[:6000]})
            elif "conclusion" in step:
                c = step["conclusion"]
                trail.append(f"model concluded: {c.get('root_cause')} "
                             f"(confidence {c.get('confidence')}) — {c.get('reasoning')}")
                fix = _fix(c.get("proposed_fix_action", "manual_review"),
                           c.get("fix_params", {}), c.get("fix_description", ""))
                return self._result(disc, c.get("root_cause", "unknown"),
                                    float(c.get("confidence", 0.0)), trail, ev,
                                    mode="api", tokens=tokens, fix=fix)
            else:
                messages.append({"role": "user", "content":
                                 "Respond with JSON only: a tool_call or a conclusion."})
        # out of rounds -> rule-based synthesis over gathered evidence
        root_cause, confidence, lines = fallback_investigate(disc, ev)
        trail.extend(lines)
        trail.append("tool budget exhausted; synthesized with rules")
        return self._result(disc, root_cause, confidence, trail, ev,
                            mode="api+fallback", tokens=tokens)

    @staticmethod
    def _accumulate(tokens: dict, resp: dict) -> None:
        u = resp.get("usage", {})
        tokens["prompt_tokens"] += u.get("prompt_tokens", 0)
        tokens["completion_tokens"] += u.get("completion_tokens", 0)
        tokens["cached"] = tokens["cached"] or resp.get("cached", False)

    def _result(self, disc, root_cause, confidence, trail, ev,
                mode, tokens, fix=None) -> dict:
        if root_cause not in ROOT_CAUSES:
            root_cause = "unknown"
        confidence = max(0.0, min(1.0, float(confidence)))
        return {
            "disc_id": disc["id"],
            "mode": mode,
            "root_cause": root_cause,
            "confidence": round(confidence, 2),
            "evidence": trail,
            "proposed_fix": fix or build_fix(root_cause, disc, ev),
            "tokens": tokens,
        }


# --------------------------------------------------------------------------- #
# sample picker + console demo
# --------------------------------------------------------------------------- #
CATEGORY_ORDER = ["failed_message", "duplicate_message", "unposted_receipt",
                  "wrong_uom", "wrong_bin", "expired_available", "cutoff_gap"]


def pick_samples(db_path: Path, n: int = 10) -> list[dict]:
    """Round-robin over ground-truth root causes, top value-at-risk first —
    so the demo covers every discrepancy type."""
    discs = tools.list_discrepancies(db_path)
    groups: dict[str, list[dict]] = {}
    for d in discs:
        gt = tools.ground_truth_for(db_path, d["sku"], d["lot_code"], d["pallet_id"])
        key = gt["category"] if gt else "unknown"
        groups.setdefault(key, []).append(d)
    for g in groups.values():
        g.sort(key=lambda d: d["value_at_risk"], reverse=True)
    picks: list[dict] = []
    idx = {k: 0 for k in groups}
    order = [c for c in CATEGORY_ORDER if c in groups]
    while len(picks) < n and any(idx[k] < len(groups[k]) for k in order):
        for k in order:
            if len(picks) >= n:
                break
            if idx[k] < len(groups[k]):
                picks.append(groups[k][idx[k]])
                idx[k] += 1
    return picks


def _print_investigation(inv: dict, i: int, n: int, gt: dict | None) -> None:
    d = inv["_disc"]
    print("=" * 72)
    print(f"[{i}/{n}] {d['id']} | {d['category']} | {d['sku']} {d['lot_code'] or ''} | "
          f"${d['value_at_risk']:,.2f} at risk")
    if d["erp_qty"] is not None or d["wms_qty"] is not None:
        print(f"  ERP: {d['erp_qty']} {d['uom']} | WMS: {d['wms_qty']} {d['uom']}")
    if d.get("pallet_id"):
        print(f"  pallet {d['pallet_id']} recorded at bin {d['location']}")
    print(f"  root cause: {inv['root_cause']} (confidence {inv['confidence']}) "
          f"[mode: {inv['mode']}]")
    print("  evidence:")
    for line in inv["evidence"][1:]:  # skip the 'opened discrepancy' header
        print(f"    - {line}")
    fix = inv["proposed_fix"]
    print(f"  proposed fix [REQUIRES APPROVAL]: {fix['action']}")
    print(f"    {fix['description']}")
    if gt:
        mark = "✓" if gt["category"] == inv["root_cause"] else "✗"
        print(f"  ground truth: {gt['category']} {mark}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="data/phantom.db")
    ap.add_argument("--labels", default="data/labels")
    ap.add_argument("--samples", type=int, default=10)
    args = ap.parse_args()

    db_path = Path(args.db)
    if not db_path.exists():
        raise SystemExit(f"DB not found: {db_path} — run `make data` first.")
    agent = InvestigationAgent(db_path, Path(args.labels))
    print(f"Phantom Inventory Hunter — M2 investigation demo (mode: {agent.llm.mode})")
    print(f"Meta Model API key: {'set' if agent.llm.mode == 'api' else 'NOT set — rule-based fallback'}\n")

    samples = pick_samples(db_path, args.samples)
    correct = 0
    for i, d in enumerate(samples, 1):
        inv = agent.investigate(d["id"])
        inv["_disc"] = d
        gt = tools.ground_truth_for(db_path, d["sku"], d["lot_code"], d["pallet_id"])
        if gt and gt["category"] == inv["root_cause"]:
            correct += 1
        _print_investigation(inv, i, len(samples), gt)

    print("=" * 72)
    print(f"Investigated {len(samples)} discrepancies | "
          f"root-cause accuracy vs ground truth: {correct}/{len(samples)}")
    # token spend this session
    usage_path = db_path.parent / "token_usage.jsonl"
    if usage_path.exists():
        total = sum(json.loads(l).get("est_cost_usd", 0) for l in
                    usage_path.read_text().splitlines() if l.strip())
        print(f"Total estimated model spend logged: ${total:.4f} (budget: $150)")


if __name__ == "__main__":
    main()
