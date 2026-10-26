"""Evidence tools for the investigation agent (M2).

Every tool is READ-ONLY (``mode=ro`` connections). The agent may inspect
anything; it may never write. Tools return JSON-serializable dicts/lists.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path


def _connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _rows(cur) -> list[dict]:
    return [dict(r) for r in cur.fetchall()]


# --------------------------------------------------------------------------- #
# tools
# --------------------------------------------------------------------------- #
def get_discrepancy(db_path: Path, disc_id: str) -> dict | None:
    """Fetch one engine-flagged discrepancy by id."""
    conn = _connect(db_path)
    try:
        r = conn.execute("SELECT * FROM discrepancies WHERE id=?", (disc_id,)).fetchone()
        return dict(r) if r else None
    finally:
        conn.close()


def list_discrepancies(db_path: Path, category: str | None = None) -> list[dict]:
    """List open discrepancies, optionally filtered, top value at risk first."""
    conn = _connect(db_path)
    try:
        q = "SELECT * FROM discrepancies WHERE status='OPEN'"
        args: list = []
        if category:
            q += " AND category=?"
            args.append(category)
        q += " ORDER BY value_at_risk DESC"
        return _rows(conn.execute(q, args))
    finally:
        conn.close()


def get_lot(db_path: Path, sku: str, lot_code: str) -> dict:
    """Lot master row + SKU cost/UOM context."""
    conn = _connect(db_path)
    try:
        lot = conn.execute("SELECT * FROM lots WHERE lot_code=?", (lot_code,)).fetchone()
        sku_r = conn.execute("SELECT * FROM sku_master WHERE sku=?", (sku,)).fetchone()
        return {"lot": dict(lot) if lot else None,
                "sku": dict(sku_r) if sku_r else None}
    finally:
        conn.close()


def query_erp_transactions(db_path: Path, sku: str, lot_code: str) -> list[dict]:
    """All ERP postings for a SKU/lot — receipts, shipments, adjustments."""
    conn = _connect(db_path)
    try:
        return _rows(conn.execute(
            """SELECT txn_date, doc_type, qty, uom, converted, qty_base, ref_doc, posted_at
               FROM erp_transactions WHERE sku=? AND lot_code=? ORDER BY posted_at""",
            (sku, lot_code)))
    finally:
        conn.close()


def query_wms_pallets(db_path: Path, sku: str, lot_code: str) -> list[dict]:
    """Physical pallets the WMS believes exist for a SKU/lot."""
    conn = _connect(db_path)
    try:
        return _rows(conn.execute(
            """SELECT pallet_id, qty_base, uom, location, expiry_date, status
               FROM wms_pallets WHERE sku=? AND lot_code=? ORDER BY pallet_id""",
            (sku, lot_code)))
    finally:
        conn.close()


def get_pallet(db_path: Path, pallet_id: str) -> dict | None:
    """One WMS pallet row by id (the system side of a label comparison)."""
    conn = _connect(db_path)
    try:
        r = conn.execute("SELECT * FROM wms_pallets WHERE pallet_id=?",
                         (pallet_id,)).fetchone()
        return dict(r) if r else None
    finally:
        conn.close()


def query_wms_moves(db_path: Path, pallet_id: str) -> list[dict]:
    """ASRS move history for one pallet (source of truth for bin location)."""
    conn = _connect(db_path)
    try:
        return _rows(conn.execute(
            """SELECT from_loc, to_loc, moved_at, synced FROM wms_moves
               WHERE pallet_id=? ORDER BY moved_at""", (pallet_id,)))
    finally:
        conn.close()


def search_integration_log(db_path: Path, sku: str, lot_code: str) -> list[dict]:
    """Integration messages touching a SKU/lot — incl. FAILED/DUPLICATE/PENDING."""
    conn = _connect(db_path)
    try:
        return _rows(conn.execute(
            """SELECT msg_id, created_at, direction, msg_type, qty_base, status,
                      duplicate_of, ref_doc
               FROM integration_log WHERE sku=? AND lot_code=? ORDER BY created_at""",
            (sku, lot_code)))
    finally:
        conn.close()


def label_image_path(label_dir: Path, pallet_id: str) -> Path | None:
    """Filesystem path of a pallet's label photo, if one was captured."""
    p = Path(label_dir) / f"{pallet_id}.png"
    return p if p.exists() else None


def ground_truth_for(db_path: Path, sku: str | None, lot_code: str | None,
                     pallet_id: str | None = None) -> dict | None:
    """Injected ground truth for evaluation (NOT shown to the agent)."""
    conn = _connect(db_path)
    try:
        if pallet_id:
            r = conn.execute("SELECT * FROM ground_truth WHERE pallet_id=?",
                             (pallet_id,)).fetchone()
        else:
            r = conn.execute(
                "SELECT * FROM ground_truth WHERE sku=? AND lot_code=?",
                (sku, lot_code)).fetchone()
        return dict(r) if r else None
    finally:
        conn.close()


TOOL_SCHEMAS = {
    "query_erp_transactions": ["sku", "lot_code"],
    "query_wms_pallets": ["sku", "lot_code"],
    "query_wms_moves": ["pallet_id"],
    "search_integration_log": ["sku", "lot_code"],
    "get_lot": ["sku", "lot_code"],
}
"""Tool names the LLM may request, with required args (M2 agentic loop)."""


def call_tool(db_path: Path, label_dir: Path, name: str, args: dict):
    if name == "query_erp_transactions":
        return query_erp_transactions(db_path, args["sku"], args["lot_code"])
    if name == "query_wms_pallets":
        return query_wms_pallets(db_path, args["sku"], args["lot_code"])
    if name == "query_wms_moves":
        return query_wms_moves(db_path, args["pallet_id"])
    if name == "search_integration_log":
        return search_integration_log(db_path, args["sku"], args["lot_code"])
    if name == "get_lot":
        return get_lot(db_path, args["sku"], args["lot_code"])
    raise ValueError(f"unknown tool: {name}")
