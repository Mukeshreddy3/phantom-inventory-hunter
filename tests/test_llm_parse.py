"""Tests for llm.extract_json_object (robustness pass, 2026-10-26).

The live model answers with prose, or prose ahead of the JSON. A strict
json.loads discards those replies whole; the extractor recovers them.
"""
import json

from phantom_hunter.llm import extract_json_object


def test_strict_json_parses():
    assert extract_json_object('{"tool_call": {"name": "get_lot"}}') == {
        "tool_call": {"name": "get_lot"}}


def test_prose_prefix_recovers_object():
    text = ('Investigating the quantity mismatch — checking ERP postings '
            'first.{"tool_call": {"name": "query_erp_transactions", '
            '"args": {"sku": "X", "lot_code": "L"}}}')
    assert extract_json_object(text) == {
        "tool_call": {"name": "query_erp_transactions",
                      "args": {"sku": "X", "lot_code": "L"}}}


def test_prose_suffix_recovers_object():
    assert extract_json_object('{"a": 1} hope this helps') == {"a": 1}


def test_prose_only_returns_none():
    assert extract_json_object(
        "Investigating D-0002 — ERP shows zero against WMS stock.") is None


def test_none_and_empty_return_none():
    assert extract_json_object(None) is None
    assert extract_json_object("") is None


def test_non_object_json_returns_none():
    assert extract_json_object("[1, 2, 3]") is None
    assert extract_json_object('"just a string"') is None


def test_nested_braces_survive_extraction():
    text = 'note: {"conclusion": {"root_cause": "failed_message", "nested": {"x": 1}}}'
    assert extract_json_object(text)["conclusion"]["nested"] == {"x": 1}
