"""Tests for the M2 investigation agent (fallback mode)."""
import hashlib
import json
import os
from pathlib import Path

import pytest

from phantom_hunter import reconcile, tools
from phantom_hunter.agent import InvestigationAgent, pick_samples
from phantom_hunter.generator import Gen
from phantom_hunter.llm import LLMClient


@pytest.fixture()
def db(tmp_path):
    p = tmp_path / "t.db"
    Gen(seed=42).run(p, tmp_path / "labels", do_inject=True)
    reconcile.run(p)
    return p


@pytest.fixture()
def agent(db, tmp_path):
    llm = LLMClient(data_dir=tmp_path)  # keeps token logs out of data/
    assert llm.mode == "fallback"        # no API key in test env
    return InvestigationAgent(db, tmp_path / "labels", llm=llm)


def _disc_for_category(db, category):
    """Top value-at-risk discrepancy whose ground truth is `category`."""
    cands = []
    for d in tools.list_discrepancies(db):
        gt = tools.ground_truth_for(db, d["sku"], d["lot_code"], d["pallet_id"])
        if gt and gt["category"] == category:
            cands.append(d)
    assert cands, f"no discrepancy for {category}"
    return max(cands, key=lambda d: d["value_at_risk"])


@pytest.mark.parametrize("category", [
    "failed_message", "duplicate_message", "unposted_receipt", "wrong_uom",
    "wrong_bin", "expired_available", "cutoff_gap",
])
def test_fallback_diagnoses_each_root_cause(db, agent, category):
    d = _disc_for_category(db, category)
    inv = agent.investigate(d["id"])
    assert inv["root_cause"] == category, (
        f"{d['id']}: diagnosed {inv['root_cause']}, expected {category}\n"
        f"evidence: {inv['evidence']}")
    assert inv["mode"] == "fallback"


def test_investigation_shape(db, agent):
    d = _disc_for_category(db, "failed_message")
    inv = agent.investigate(d["id"])
    assert 0.0 <= inv["confidence"] <= 1.0
    assert len(inv["evidence"]) >= 2
    fix = inv["proposed_fix"]
    assert fix["requires_approval"] is True
    assert fix["action"] and fix["description"]
    assert isinstance(fix["params"], dict)


def test_agent_never_writes_to_db(db, agent, tmp_path):
    before = hashlib.sha256((tmp_path / "t.db").read_bytes()).hexdigest()
    for d in pick_samples(db, 5):
        agent.investigate(d["id"])
    after = hashlib.sha256((tmp_path / "t.db").read_bytes()).hexdigest()
    assert before == after, "agent must never modify the database"


def test_fallback_token_usage_logged(db, agent, tmp_path):
    agent.investigate(_disc_for_category(db, "wrong_bin")["id"])
    log = tmp_path / "token_usage.jsonl"
    assert log.exists()
    entries = [json.loads(l) for l in log.read_text().splitlines() if l.strip()]
    assert entries and all(e["mode"] == "fallback" for e in entries)
    assert all(e["est_cost_usd"] == 0 for e in entries)


def test_pick_samples_covers_all_categories(db):
    picks = pick_samples(db, 10)
    assert len(picks) == 10
    cats = set()
    for d in picks:
        gt = tools.ground_truth_for(db, d["sku"], d["lot_code"], d["pallet_id"])
        cats.add(gt["category"])
    assert {"failed_message", "duplicate_message", "unposted_receipt", "wrong_uom",
            "wrong_bin", "expired_available", "cutoff_gap"} <= cats


def test_unknown_discrepancy_raises(db, agent):
    with pytest.raises(ValueError):
        agent.investigate("D-9999")


def test_llm_client_cache_roundtrip(tmp_path):
    llm = LLMClient(data_dir=tmp_path)
    key = llm._cache_key("m", [{"role": "user", "content": "hi"}])
    assert llm._cache_read(key) is None
    llm._cache_write(key, {"text": "{}", "model": "m"})
    assert llm._cache_read(key)["text"] == "{}"


def test_llm_client_chat_refuses_in_fallback(tmp_path):
    llm = LLMClient(data_dir=tmp_path)
    assert llm.mode == "fallback"
    with pytest.raises(RuntimeError):
        llm.chat([{"role": "user", "content": "hi"}])


class FakeApiLLM:
    """Queued canned replies in api mode (robustness-pass tests)."""

    def __init__(self, texts):
        self._texts = list(texts)
        self.mode = "api"

    def chat(self, messages, **kwargs):
        text = self._texts.pop(0)
        return {"text": text, "model": "fake",
                "usage": {"prompt_tokens": 10, "completion_tokens": 20},
                "cached": False, "mode": "api"}

    def log_fallback_call(self, purpose="investigate"):
        pass


def _conclusion_json(root_cause="failed_message"):
    return json.dumps({"conclusion": {
        "root_cause": root_cause, "confidence": 0.85,
        "reasoning": "Evidence points here.",
        "proposed_fix_action": "resend_message", "fix_params": {},
        "fix_description": "Resend it."}})


def test_api_loop_recovers_prose_and_concludes(db, tmp_path):
    """2026-10-26 live-model shape: prose, then prose+tool_call, then conclude."""
    d = _disc_for_category(db, "failed_message")
    tool_call = json.dumps({"tool_call": {
        "name": "query_erp_transactions",
        "args": {"sku": d["sku"], "lot_code": d["lot_code"]}},
        "reason": "check ERP postings"})
    fake = FakeApiLLM(["Just looking into this.",
                       "Checking ERP postings. " + tool_call,
                       _conclusion_json()])
    agent = InvestigationAgent(db, tmp_path / "labels", llm=fake)
    inv = agent.investigate(d["id"])
    assert inv["mode"] == "api"
    assert inv["root_cause"] == "failed_message"


def test_api_loop_recovers_null_content(db, tmp_path):
    """Null content (reasoning ate a small budget) must nudge, not crash."""
    d = _disc_for_category(db, "failed_message")
    fake = FakeApiLLM([None, _conclusion_json()])
    agent = InvestigationAgent(db, tmp_path / "labels", llm=fake)
    inv = agent.investigate(d["id"])
    assert inv["mode"] == "api"
    assert inv["root_cause"] == "failed_message"
