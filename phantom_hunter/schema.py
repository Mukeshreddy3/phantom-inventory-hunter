"""SQLite schema for Phantom Inventory Hunter (M1: synthetic data + reconcile)."""
from __future__ import annotations

DDL = """
CREATE TABLE IF NOT EXISTS sku_master (
    sku         TEXT PRIMARY KEY,
    description TEXT NOT NULL,
    category    TEXT NOT NULL,
    base_uom    TEXT NOT NULL,          -- LB or KG
    alt_uom     TEXT NOT NULL,          -- CS / BG (case / bag)
    alt_factor  REAL NOT NULL,          -- base units per 1 alt unit
    unit_cost   REAL NOT NULL,          -- $ per base unit
    shelf_life_days INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS lots (
    lot_code       TEXT PRIMARY KEY,
    sku            TEXT NOT NULL REFERENCES sku_master(sku),
    production_date TEXT NOT NULL,      -- YYYY-MM-DD
    expiry_date    TEXT NOT NULL,       -- YYYY-MM-DD
    qty_produced   REAL NOT NULL        -- base units
);

CREATE TABLE IF NOT EXISTS erp_transactions (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    txn_date  TEXT NOT NULL,           -- YYYY-MM-DD
    doc_type  TEXT NOT NULL,           -- PROD_RECEIPT | SALES_SHIP | ADJUSTMENT
    sku       TEXT NOT NULL,
    lot_code  TEXT NOT NULL,
    qty       REAL NOT NULL,           -- as recorded (may be in uom below)
    uom       TEXT NOT NULL,           -- base_uom normally; alt_uom on wrong_uom bug
    converted INTEGER NOT NULL DEFAULT 1,  -- 0 => uom conversion was NOT applied (bug)
    qty_base  REAL NOT NULL,           -- effective base-unit qty the ERP believes
    ref_doc   TEXT NOT NULL,
    posted_at TEXT NOT NULL            -- ISO datetime
);
CREATE INDEX IF NOT EXISTS idx_erp_txn_lot ON erp_transactions(sku, lot_code);

-- Snapshot of what the ERP currently believes (derived from erp_transactions).
CREATE TABLE IF NOT EXISTS erp_inventory (
    sku      TEXT NOT NULL,
    lot_code TEXT NOT NULL,
    qty_base REAL NOT NULL,
    PRIMARY KEY (sku, lot_code)
);

CREATE TABLE IF NOT EXISTS wms_pallets (
    pallet_id  TEXT PRIMARY KEY,
    sku        TEXT NOT NULL,
    lot_code   TEXT NOT NULL,
    qty_base   REAL NOT NULL,
    uom        TEXT NOT NULL,
    location   TEXT NOT NULL,          -- ASRS bin, e.g. R14-07-2
    expiry_date TEXT NOT NULL,
    status     TEXT NOT NULL,          -- AVAILABLE | HOLD | EXPIRED
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_pallet_lot ON wms_pallets(sku, lot_code);

-- Bin-to-bin moves. A move row whose to_loc != wms_pallets.location
-- means the pallet record is stale (wrong_bin discrepancy).
CREATE TABLE IF NOT EXISTS wms_moves (
    move_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    pallet_id TEXT NOT NULL,
    from_loc  TEXT NOT NULL,
    to_loc    TEXT NOT NULL,
    moved_at  TEXT NOT NULL,
    synced    INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS integration_log (
    msg_id      TEXT PRIMARY KEY,
    created_at  TEXT NOT NULL,         -- ISO datetime
    direction   TEXT NOT NULL,         -- WMS->ERP | ERP->WMS
    msg_type    TEXT NOT NULL,         -- PROD_RECEIPT | SHIP_CONFIRM | INVENTORY_ADJUST
    sku         TEXT NOT NULL,
    lot_code    TEXT NOT NULL,
    qty_base    REAL NOT NULL,
    status      TEXT NOT NULL,         -- DELIVERED | FAILED | DUPLICATE | PENDING
    duplicate_of TEXT,                 -- msg_id of the original, when DUPLICATE
    ref_doc     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_msg_lot ON integration_log(sku, lot_code);

-- Injected ground truth. Root-cause categories:
--   failed_message | duplicate_message | unposted_receipt | wrong_uom |
--   wrong_bin | expired_available | cutoff_gap | label_contradiction
-- expected_engine: which reconcile.py category should flag it
--   (label_contradiction -> 'none_m1': needs image reading, M2 agent's job)
CREATE TABLE IF NOT EXISTS ground_truth (
    id              TEXT PRIMARY KEY,
    category        TEXT NOT NULL,
    sku             TEXT,
    lot_code        TEXT,
    pallet_id       TEXT,
    expected_engine TEXT NOT NULL,
    detail          TEXT NOT NULL      -- JSON
);

-- Engine output.
CREATE TABLE IF NOT EXISTS discrepancies (
    id            TEXT PRIMARY KEY,
    detected_at   TEXT NOT NULL,
    category      TEXT NOT NULL,       -- qty_mismatch | cutoff_gap | wrong_bin | expired_available
    severity      TEXT NOT NULL,       -- high | medium | low
    sku           TEXT,
    lot_code      TEXT,
    pallet_id     TEXT,
    location      TEXT,
    erp_qty       REAL,
    wms_qty       REAL,
    uom           TEXT,
    unit_cost     REAL,
    value_at_risk REAL NOT NULL,
    detail        TEXT NOT NULL,       -- JSON evidence hints
    status        TEXT NOT NULL DEFAULT 'OPEN'
);

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

-- M3: investigation results + human approval queue.
-- disc_key is the dedupe natural key: category|sku|lot_code|pallet_id.
-- The agent NEVER applies fixes; approve/reject only records the human's
-- decision. repeat_group links repeat root causes (first occurrence's id).
CREATE TABLE IF NOT EXISTS investigations (
    id             TEXT PRIMARY KEY,
    disc_key       TEXT UNIQUE NOT NULL,
    discrepancy_id TEXT NOT NULL,
    detected_at    TEXT NOT NULL,
    investigated_at TEXT NOT NULL,
    category       TEXT NOT NULL,
    sku            TEXT,
    lot_code       TEXT,
    pallet_id      TEXT,
    value_at_risk  REAL NOT NULL,
    priority       REAL NOT NULL,
    root_cause     TEXT NOT NULL,
    confidence     REAL NOT NULL,
    evidence       TEXT NOT NULL,
    proposed_fix   TEXT NOT NULL,
    agent_mode     TEXT NOT NULL,
    status         TEXT NOT NULL DEFAULT 'PENDING_APPROVAL',
    decided_at     TEXT,
    decide_note    TEXT,
    repeat_group   TEXT
);
CREATE INDEX IF NOT EXISTS idx_inv_status ON investigations(status);
"""


def create_schema(conn) -> None:
    conn.executescript(DDL)
    conn.commit()
