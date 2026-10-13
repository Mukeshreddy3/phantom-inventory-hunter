"""Synthetic ERP + WMS/ASRS data generator with injected discrepancy ground truth.

Strategy: build a fully consistent baseline (ERP and WMS agree everywhere),
then inject known discrepancy types as mutations. Every injection writes a
ground_truth row so M4 evaluation can score the agent's root-cause accuracy.

Deterministic: same SEED -> identical database.

Usage:
    python -m phantom_hunter.generator [--db PATH] [--seed N] [--no-inject]
"""
from __future__ import annotations

import argparse
import json
import random
import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path

from .schema import create_schema

SEED = 42
N_SKUS = 200
DAYS = 30
START_DATE = date(2026, 9, 14)          # fixed window -> reproducible
END_DATE = START_DATE + timedelta(days=DAYS - 1)
NOW = datetime(2026, 10, 13, 11, 0, 0)  # simulated "now" (cutoff-gap logic)
WAREHOUSE = "WH-01"

PRODUCTS = [  # (name, category, base_uom, alt_uom, alt_factor, cost_lo, cost_hi, shelf_lo, shelf_hi)
    ("Cheddar Cheese Block", "Cheese", "LB", "CS", 40, 2.6, 3.6, 120, 180),
    ("White Cheddar Block", "Cheese", "LB", "CS", 40, 2.9, 3.9, 120, 180),
    ("Mozzarella Loaf", "Cheese", "LB", "CS", 40, 2.4, 3.2, 90, 120),
    ("Pepper Jack Block", "Cheese", "LB", "CS", 40, 2.7, 3.5, 120, 150),
    ("Monterey Jack Block", "Cheese", "LB", "CS", 40, 2.6, 3.4, 120, 150),
    ("Swiss Cheese Block", "Cheese", "LB", "CS", 40, 3.1, 4.2, 150, 180),
    ("Provolone Log", "Cheese", "LB", "CS", 40, 2.8, 3.8, 90, 120),
    ("Parmesan Wedge", "Cheese", "LB", "CS", 24, 5.5, 8.0, 180, 240),
    ("Cream Cheese", "Cheese", "LB", "CS", 36, 2.2, 3.0, 60, 90),
    ("String Cheese", "Cheese", "LB", "CS", 30, 3.4, 4.6, 90, 120),
    ("Salted Butter", "Butter", "LB", "CS", 36, 2.8, 3.8, 90, 120),
    ("Unsalted Butter", "Butter", "LB", "CS", 36, 2.8, 3.8, 90, 120),
    ("Butter Oil", "Butter", "LB", "DR", 400, 3.2, 4.4, 180, 240),
    ("Ghee", "Butter", "LB", "CS", 36, 4.5, 6.5, 180, 270),
    ("Nonfat Dry Milk", "Milk Powder", "LB", "BG", 50, 1.6, 2.4, 180, 270),
    ("Whole Milk Powder", "Milk Powder", "LB", "BG", 55, 2.0, 3.0, 180, 240),
    ("Buttermilk Powder", "Milk Powder", "LB", "BG", 50, 1.8, 2.6, 150, 210),
    ("Heavy Cream Powder", "Milk Powder", "LB", "BG", 50, 3.0, 4.2, 150, 210),
    ("Whey Protein Concentrate 80%", "Whey", "LB", "BG", 50, 2.2, 3.4, 180, 270),
    ("Whey Protein Isolate 90%", "Whey", "LB", "BG", 44, 5.0, 7.5, 180, 270),
    ("Edible Lactose", "Whey", "LB", "BG", 50, 1.2, 1.9, 240, 365),
    ("Demineralized Whey", "Whey", "LB", "BG", 50, 1.4, 2.2, 180, 270),
    ("Milk Protein Concentrate 70%", "Protein", "KG", "BG", 25, 6.0, 9.0, 180, 270),
    ("Micellar Casein", "Protein", "KG", "BG", 20, 8.0, 12.0, 180, 270),
    ("Yogurt Powder", "Cultured", "LB", "BG", 50, 2.6, 3.8, 120, 180),
    ("Sour Cream Powder", "Cultured", "LB", "BG", 50, 2.4, 3.6, 120, 180),
    ("Feta Cheese", "Cheese", "LB", "CS", 30, 3.8, 5.2, 90, 120),
    ("Gouda Wheel", "Cheese", "LB", "CS", 24, 4.2, 6.0, 150, 210),
    ("Blue Cheese", "Cheese", "LB", "CS", 24, 4.8, 6.8, 120, 180),
    ("Ice Cream Mix", "Frozen", "LB", "BG", 50, 1.9, 2.8, 120, 180),
]

# Injection plan: (ground-truth category, count)
INJECTION_PLAN = [
    ("failed_message", 6),
    ("duplicate_message", 4),
    ("unposted_receipt", 4),
    ("wrong_uom", 4),
    ("wrong_bin", 5),
    ("expired_available", 6),
    ("cutoff_gap", 5),
    ("label_contradiction", 5),
]


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def _bin(rng: random.Random) -> str:
    return f"R{rng.randint(1, 20):02d}-{rng.randint(1, 30):02d}-{rng.randint(1, 4)}"


class Gen:
    def __init__(self, seed: int = SEED):
        self.rng = random.Random(seed)
        self.seed = seed
        self.now = NOW                      # simulated clock; advanced by stream_days()
        self._pallet_seq = 0
        self._msg_seq = 0
        self._gt_seq = 0
        self.skus: dict[str, dict] = {}
        self.clean_lots: list[dict] = []   # lots with no shipments/adjustments (injection pool)
        self.label_dir: Path | None = None

    # -- id makers ---------------------------------------------------------- #
    def pallet_id(self) -> str:
        self._pallet_seq += 1
        return f"PLT-{self._pallet_seq:06d}"

    def msg_id(self) -> str:
        self._msg_seq += 1
        return f"MSG-{self._msg_seq:06d}"

    def gt_id(self) -> str:
        self._gt_seq += 1
        return f"GT-{self._gt_seq:04d}"

    def gt(self, cur, category, sku=None, lot=None, pallet=None,
           expected_engine="qty_mismatch", **detail):
        gid = self.gt_id()
        # callers pass detail={...} as a kwarg; unwrap it so the JSON is flat
        extra = detail.pop("detail", None) or {}
        payload = {**extra, **detail}
        cur.execute(
            "INSERT INTO ground_truth VALUES (?,?,?,?,?,?,?)",
            (gid, category, sku, lot, pallet, expected_engine, json.dumps(payload)),
        )
        return gid

    # -- catalog ------------------------------------------------------------ #
    def gen_skus(self, cur):
        for i in range(N_SKUS):
            p = PRODUCTS[i % len(PRODUCTS)]
            sku = f"{p[0][:3].upper().replace(' ', '')}-{i:04d}"
            cur.execute(
                "INSERT INTO sku_master VALUES (?,?,?,?,?,?,?,?)",
                (sku, f"{p[0]} {p[3]} of {p[4]}{p[2]}", p[1], p[2], p[3], p[4],
                 round(self.rng.uniform(p[5], p[6]), 2),
                 self.rng.randint(p[7], p[8])),
            )
            self.skus[sku] = {
                "sku": sku, "base_uom": p[2], "alt_uom": p[3],
                "alt_factor": p[4],
                "unit_cost": cur.execute(
                    "SELECT unit_cost FROM sku_master WHERE sku=?", (sku,)).fetchone()[0],
                "shelf_life_days": cur.execute(
                    "SELECT shelf_life_days FROM sku_master WHERE sku=?", (sku,)).fetchone()[0],
            }

    # -- baseline ----------------------------------------------------------- #
    def gen_baseline(self, cur):
        """Consistent baseline: ERP and WMS agree on every lot."""
        for sku, s in self.skus.items():
            n_lots = self.rng.randint(1, 4)
            for li in range(n_lots):
                prod = START_DATE + timedelta(days=self.rng.randint(0, DAYS - 8))
                expiry = prod + timedelta(days=s["shelf_life_days"])
                qty = round(self.rng.uniform(500, 8000), 2)
                lot = f"L{prod.strftime('%Y%m%d')}-{sku[-4:]}{li}"
                cur.execute(
                    "INSERT INTO lots VALUES (?,?,?,?,?)",
                    (lot, sku, prod.isoformat(), expiry.isoformat(), qty))

                ref = f"PR-{lot}"
                posted = datetime.combine(prod, datetime.min.time()) + timedelta(hours=7)
                cur.execute(
                    """INSERT INTO erp_transactions
                       (txn_date, doc_type, sku, lot_code, qty, uom, converted, qty_base, ref_doc, posted_at)
                       VALUES (?,?,?,?,?,?,?,?,?,?)""",
                    (prod.isoformat(), "PROD_RECEIPT", sku, lot, qty, s["base_uom"],
                     1, qty, ref, posted.isoformat()))
                mid = self.msg_id()
                cur.execute(
                    "INSERT INTO integration_log VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (mid, posted.isoformat(), "WMS->ERP", "PROD_RECEIPT",
                     sku, lot, qty, "DELIVERED", None, ref))

                # WMS pallets for the lot
                remaining = qty
                first_pallet = True
                while remaining > 0.01:
                    pq = round(min(remaining, self.rng.uniform(200, 1000)), 2)
                    remaining -= pq
                    pid = self.pallet_id()
                    loc = _bin(self.rng)
                    cur.execute(
                        """INSERT INTO wms_pallets
                           VALUES (?,?,?,?,?,?,?,?,?)""",
                        (pid, sku, lot, pq, s["base_uom"], loc,
                         expiry.isoformat(), "AVAILABLE",
                         posted.isoformat()))
                    first_pallet = False

                # shipments (only for some lots -> others stay "clean" for injection)
                shipped_total = 0.0
                has_activity = False
                if self.rng.random() < 0.62:
                    has_activity = True
                    n_ship = self.rng.randint(1, 3)
                    for si in range(n_ship):
                        ship_qty = round(qty * self.rng.uniform(0.08, 0.30), 2)
                        ship_qty = min(ship_qty, qty - shipped_total)
                        if ship_qty <= 0:
                            break
                        shipped_total += ship_qty
                        sdate = prod + timedelta(days=self.rng.randint(1, 6))
                        if sdate > END_DATE:
                            sdate = END_DATE
                        soref = f"SO-{lot}-{si}"
                        sposted = datetime.combine(sdate, datetime.min.time()) + timedelta(hours=16)
                        cur.execute(
                            """INSERT INTO erp_transactions
                               (txn_date, doc_type, sku, lot_code, qty, uom, converted, qty_base, ref_doc, posted_at)
                               VALUES (?,?,?,?,?,?,?,?,?,?)""",
                            (sdate.isoformat(), "SALES_SHIP", sku, lot, -ship_qty,
                             s["base_uom"], 1, -ship_qty, soref, sposted.isoformat()))
                        smid = self.msg_id()
                        cur.execute(
                            "INSERT INTO integration_log VALUES (?,?,?,?,?,?,?,?,?,?)",
                            (smid, sposted.isoformat(), "WMS->ERP", "SHIP_CONFIRM",
                             sku, lot, -ship_qty, "DELIVERED", None, soref))
                        self._consume_pallets(cur, sku, lot, ship_qty)

                # small spoilage adjustments on some lots
                if self.rng.random() < 0.12:
                    has_activity = True
                    adj = -round(qty * self.rng.uniform(0.01, 0.03), 2)
                    adate = prod + timedelta(days=self.rng.randint(2, 9))
                    if adate > END_DATE:
                        adate = END_DATE
                    aref = f"ADJ-{lot}"
                    aposted = datetime.combine(adate, datetime.min.time()) + timedelta(hours=10)
                    cur.execute(
                        """INSERT INTO erp_transactions
                           (txn_date, doc_type, sku, lot_code, qty, uom, converted, qty_base, ref_doc, posted_at)
                           VALUES (?,?,?,?,?,?,?,?,?,?)""",
                        (adate.isoformat(), "ADJUSTMENT", sku, lot, adj,
                         s["base_uom"], 1, adj, aref, aposted.isoformat()))
                    amid = self.msg_id()
                    cur.execute(
                        "INSERT INTO integration_log VALUES (?,?,?,?,?,?,?,?,?,?)",
                        (amid, aposted.isoformat(), "ERP->WMS", "INVENTORY_ADJUST",
                         sku, lot, adj, "DELIVERED", None, aref))
                    self._consume_pallets(cur, sku, lot, -adj)

                if not has_activity:
                    self.clean_lots.append({"sku": sku, "lot": lot, "qty": qty,
                                            "unit_cost": s["unit_cost"]})

        # ERP snapshot
        cur.execute("DELETE FROM erp_inventory")
        cur.execute("""
            INSERT INTO erp_inventory (sku, lot_code, qty_base)
            SELECT sku, lot_code, ROUND(SUM(qty_base), 2)
            FROM erp_transactions GROUP BY sku, lot_code""")

    def _consume_pallets(self, cur, sku, lot, qty):
        """FIFO consume qty from a lot's pallets (shipments / spoilage)."""
        rows = cur.execute(
            """SELECT pallet_id, qty_base FROM wms_pallets
               WHERE sku=? AND lot_code=? AND qty_base > 0
               ORDER BY created_at, pallet_id""", (sku, lot)).fetchall()
        need = qty
        for pid, pq in rows:
            if need <= 0:
                break
            take = min(pq, need)
            need -= take
            newq = round(pq - take, 2)
            if newq <= 0.005:
                cur.execute("DELETE FROM wms_pallets WHERE pallet_id=?", (pid,))
            else:
                cur.execute("UPDATE wms_pallets SET qty_base=? WHERE pallet_id=?",
                            (newq, pid))

    # -- injections ---------------------------------------------------------- #
    def inject(self, cur):
        rng = self.rng
        pool = self.clean_lots[:]
        rng.shuffle(pool)
        if len(pool) < 40:
            raise RuntimeError(f"injection pool too small: {len(pool)}")

        def take():
            return pool.pop()

        for category, n in INJECTION_PLAN:
            for _ in range(n):
                getattr(self, f"_inj_{category}")(cur, take(), rng)

    # 1. integration message failed -> ERP never got the receipt
    def _inj_failed_message(self, cur, L, rng):
        cur.execute("DELETE FROM erp_transactions WHERE ref_doc=?", (f"PR-{L['lot']}",))
        mid = self.msg_id()
        cur.execute(
            "INSERT INTO integration_log VALUES (?,?,?,?,?,?,?,?,?,?)",
            (mid, self.now.isoformat(), "WMS->ERP", "PROD_RECEIPT", L["sku"], L["lot"],
             L["qty"], "FAILED", None, f"PR-{L['lot']}"))
        self.gt(cur, "failed_message", sku=L["sku"], lot=L["lot"],
                detail={"msg_id": mid, "note": "WMS->ERP PROD_RECEIPT failed; ERP missing receipt"})

    # 2. duplicate message -> ERP double-posted the receipt
    def _inj_duplicate_message(self, cur, L, rng):
        orig = cur.execute(
            "SELECT msg_id FROM integration_log WHERE ref_doc=? AND status='DELIVERED'",
            (f"PR-{L['lot']}",)).fetchone()[0]
        mid = self.msg_id()
        cur.execute(
            "INSERT INTO integration_log VALUES (?,?,?,?,?,?,?,?,?,?)",
            (mid, self.now.isoformat(), "WMS->ERP", "PROD_RECEIPT", L["sku"], L["lot"],
             L["qty"], "DUPLICATE", orig, f"PR-{L['lot']}"))
        cur.execute(
            """INSERT INTO erp_transactions
               (txn_date, doc_type, sku, lot_code, qty, uom, converted, qty_base, ref_doc, posted_at)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (self.now.date().isoformat(), "PROD_RECEIPT", L["sku"], L["lot"], L["qty"],
             self.skus[L["sku"]]["base_uom"], 1, L["qty"],
             f"PR-{L['lot']}", self.now.isoformat()))
        self.gt(cur, "duplicate_message", sku=L["sku"], lot=L["lot"],
                detail={"msg_id": mid, "duplicate_of": orig,
                        "note": "receipt applied twice in ERP"})

    # 3. production happened, receipt never created in ERP, no message at all
    def _inj_unposted_receipt(self, cur, L, rng):
        cur.execute("DELETE FROM erp_transactions WHERE ref_doc=?", (f"PR-{L['lot']}",))
        cur.execute("DELETE FROM integration_log WHERE ref_doc=?", (f"PR-{L['lot']}",))
        self.gt(cur, "unposted_receipt", sku=L["sku"], lot=L["lot"],
                detail={"note": "pallets exist in WMS; no ERP receipt and no integration message"})

    # 4. receipt posted in cases/bags but conversion never applied
    def _inj_wrong_uom(self, cur, L, rng):
        s = self.skus[L["sku"]]
        alt_qty = round(L["qty"] / s["alt_factor"], 2)
        cur.execute(
            """UPDATE erp_transactions SET qty=?, uom=?, converted=0, qty_base=?
               WHERE ref_doc=?""",
            (alt_qty, s["alt_uom"], alt_qty, f"PR-{L['lot']}"))
        self.gt(cur, "wrong_uom", sku=L["sku"], lot=L["lot"],
                detail={"recorded_uom": s["alt_uom"], "recorded_qty": alt_qty,
                        "true_base_qty": L["qty"], "factor": s["alt_factor"],
                        "note": f"posted {alt_qty} {s['alt_uom']} without converting to {s['base_uom']}"})

    # 5. pallet moved in the ASRS but the pallet record still shows the old bin
    def _inj_wrong_bin(self, cur, L, rng):
        row = cur.execute(
            "SELECT pallet_id, location FROM wms_pallets WHERE lot_code=? LIMIT 1",
            (L["lot"],)).fetchone()
        pid, old_loc = row
        new_loc = _bin(rng)
        while new_loc == old_loc:
            new_loc = _bin(rng)
        cur.execute(
            "INSERT INTO wms_moves (pallet_id, from_loc, to_loc, moved_at, synced) VALUES (?,?,?,?,1)",
            (pid, old_loc, new_loc,
             (self.now - timedelta(hours=rng.randint(2, 30))).isoformat()))
        # NOTE: wms_pallets.location deliberately NOT updated -> stale record
        self.gt(cur, "wrong_bin", sku=L["sku"], lot=L["lot"], pallet=pid,
                expected_engine="wrong_bin",
                detail={"recorded_bin": old_loc, "true_bin": new_loc,
                        "note": "ASRS moved the pallet; WMS pallet record not updated"})

    # 6. lot is past expiry but still shows AVAILABLE with qty > 0
    def _inj_expired_available(self, cur, L, rng):
        past = (self.now.date() - timedelta(days=rng.randint(3, 21))).isoformat()
        cur.execute("UPDATE lots SET expiry_date=? WHERE lot_code=?", (past, L["lot"]))
        cur.execute(
            "UPDATE wms_pallets SET expiry_date=?, status='AVAILABLE' WHERE lot_code=?",
            (past, L["lot"]))
        self.gt(cur, "expired_available", sku=L["sku"], lot=L["lot"],
                expected_engine="expired_available",
                detail={"expiry_date": past,
                        "note": "lot expired but still shows available in WMS/ERP"})

    # 7. shipment inside the sync window: WMS done, ERP message still PENDING
    def _inj_cutoff_gap(self, cur, L, rng):
        ship_qty = round(L["qty"] * rng.uniform(0.05, 0.15), 2)
        self._consume_pallets(cur, L["sku"], L["lot"], ship_qty)
        mid = self.msg_id()
        created = self.now - timedelta(minutes=rng.randint(5, 20))
        cur.execute(
            "INSERT INTO integration_log VALUES (?,?,?,?,?,?,?,?,?,?)",
            (mid, created.isoformat(), "WMS->ERP", "SHIP_CONFIRM", L["sku"],
             L["lot"], -ship_qty, "PENDING", None, f"SO-{L['lot']}-cutoff"))
        self.gt(cur, "cutoff_gap", sku=L["sku"], lot=L["lot"],
                expected_engine="cutoff_gap",
                detail={"msg_id": mid, "pending_qty": -ship_qty,
                        "note": "shipment inside sync window; ERP message still pending"})

    # 8. pallet label image contradicts system data (M2 agent's catch via vision)
    def _inj_label_contradiction(self, cur, L, rng):
        from .labels import make_label
        row = cur.execute(
            "SELECT pallet_id, sku, lot_code, qty_base, location, expiry_date FROM wms_pallets "
            "WHERE lot_code=? ORDER BY qty_base DESC LIMIT 1", (L["lot"],)).fetchone()
        pid, sku, lot, qty, loc, exp = row
        field = rng.choice(["lot_code", "qty", "location"])
        label_data = {"pallet_id": pid, "sku": sku, "lot_code": lot, "qty": qty,
                      "uom": self.skus[sku]["base_uom"], "location": loc, "expiry": exp}
        if field == "lot_code":
            other = cur.execute(
                "SELECT lot_code FROM lots WHERE sku=? AND lot_code!=? LIMIT 1",
                (sku, lot)).fetchone()
            label_data["lot_code"] = other[0] if other else lot + "-X"
        elif field == "qty":
            label_data["qty"] = round(qty * rng.choice([0.5, 1.5]), 2)
        else:
            label_data["location"] = _bin(rng)
        make_label(label_data, self.label_dir / f"{pid}.png", contradict=True)
        self.gt(cur, "label_contradiction", sku=sku, lot=lot, pallet=pid,
                expected_engine="none_m1",
                detail={"field": field, "label_value": str(label_data[field]),
                        "system_value": str({"lot_code": lot, "qty": qty,
                                             "location": loc}[field]),
                        "note": "physical label contradicts WMS record; needs image reading"})

    # -- driver -------------------------------------------------------------- #
    def run(self, db_path: Path, label_dir: Path, do_inject: bool = True):
        self.label_dir = label_dir
        label_dir.mkdir(parents=True, exist_ok=True)
        if db_path.exists():
            db_path.unlink()
        conn = sqlite3.connect(db_path)
        create_schema(conn)
        cur = conn.cursor()
        self.gen_skus(cur)
        self.gen_baseline(cur)
        if do_inject:
            self.inject(cur)
        # refresh ERP snapshot after injections
        cur.execute("DELETE FROM erp_inventory")
        cur.execute("""
            INSERT INTO erp_inventory (sku, lot_code, qty_base)
            SELECT sku, lot_code, ROUND(SUM(qty_base), 2)
            FROM erp_transactions GROUP BY sku, lot_code""")
        cur.execute("INSERT INTO meta VALUES (?,?)", ("seed", str(self.seed)))
        cur.execute("INSERT INTO meta VALUES (?,?)", ("generated_at", self.now.isoformat()))
        cur.execute("INSERT INTO meta VALUES (?,?)", ("injected", str(do_inject)))
        conn.commit()

        # label images for a sample of pallets (clean ones)
        from .labels import make_label
        rows = cur.execute(
            """SELECT pallet_id, sku, lot_code, qty_base, location, expiry_date
               FROM wms_pallets ORDER BY pallet_id LIMIT 40""").fetchall()
        made = 0
        for pid, sku, lot, qty, loc, exp in rows:
            p = label_dir / f"{pid}.png"
            if p.exists():      # contradiction labels already made during injection
                continue
            make_label({"pallet_id": pid, "sku": sku, "lot_code": lot, "qty": qty,
                        "uom": self.skus[sku]["base_uom"], "location": loc,
                        "expiry": exp}, p)
            made += 1
        conn.commit()
        counts = {t: cur.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                  for t in ("sku_master", "lots", "erp_transactions", "wms_pallets",
                            "wms_moves", "integration_log", "ground_truth")}
        counts["labels"] = len(list(label_dir.glob("*.png")))
        conn.close()
        return counts

    # -- streaming (M3: the world keeps moving) -------------------------------- #
    @classmethod
    def resume(cls, db_path: Path, label_dir: Path, seed: int | None = None) -> "Gen":
        """Re-open an existing DB and continue its simulated clock."""
        g = cls(seed=seed if seed is not None else SEED)
        # re-seed so the stream doesn't replay the baseline's random draws
        g.rng = random.Random((seed if seed is not None else SEED) + 7919)
        g.label_dir = Path(label_dir)
        conn = sqlite3.connect(db_path)
        meta = dict(conn.execute("SELECT key, value FROM meta").fetchall())
        g.now = datetime.fromisoformat(meta["generated_at"])

        def max_seq(table, col, prefix):
            r = conn.execute(
                f"SELECT MAX(CAST(SUBSTR({col}, {len(prefix) + 1}) AS INTEGER)) FROM {table}"
            ).fetchone()[0]
            return r or 0

        g._pallet_seq = max_seq("wms_pallets", "pallet_id", "PLT-")
        g._msg_seq = max_seq("integration_log", "msg_id", "MSG-")
        g._gt_seq = max_seq("ground_truth", "id", "GT-")
        for r in conn.execute("SELECT sku, base_uom, alt_uom, alt_factor, unit_cost,"
                              " shelf_life_days FROM sku_master"):
            g.skus[r[0]] = {"sku": r[0], "base_uom": r[1], "alt_uom": r[2],
                            "alt_factor": r[3], "unit_cost": r[4],
                            "shelf_life_days": r[5]}
        conn.close()
        return g

    def gen_day(self, cur, day: date, pool: list[dict]) -> None:
        """Simulate one business day: shipments/adjustments on old lots, then
        fresh production. New lots are appended to `pool` (all clean)."""
        rng = self.rng
        # 1. shipments against existing stock (old lots only -> new lots stay clean)
        for _ in range(rng.randint(3, 8)):
            row = cur.execute(
                """SELECT sku, lot_code, SUM(qty_base) AS q FROM wms_pallets
                   WHERE lot_code IN (SELECT lot_code FROM lots WHERE production_date < ?)
                   GROUP BY sku, lot_code HAVING q > 50
                   ORDER BY RANDOM() LIMIT 1""", (day.isoformat(),)).fetchone()
            if not row:
                break
            sku, lot, q = row
            ship_qty = round(q * rng.uniform(0.05, 0.20), 2)
            soref = f"SO-{lot}-{day.strftime('%m%d')}-{rng.randint(10, 99)}"
            sposted = datetime.combine(day, datetime.min.time()) + timedelta(hours=16)
            s = self.skus[sku]
            cur.execute(
                """INSERT INTO erp_transactions
                   (txn_date, doc_type, sku, lot_code, qty, uom, converted, qty_base, ref_doc, posted_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (day.isoformat(), "SALES_SHIP", sku, lot, -ship_qty,
                 s["base_uom"], 1, -ship_qty, soref, sposted.isoformat()))
            smid = self.msg_id()
            cur.execute(
                "INSERT INTO integration_log VALUES (?,?,?,?,?,?,?,?,?,?)",
                (smid, sposted.isoformat(), "WMS->ERP", "SHIP_CONFIRM",
                 sku, lot, -ship_qty, "DELIVERED", None, soref))
            self._consume_pallets(cur, sku, lot, ship_qty)

        # 2. fresh production
        for _ in range(rng.randint(6, 12)):
            sku = rng.choice(list(self.skus))
            s = self.skus[sku]
            expiry = day + timedelta(days=s["shelf_life_days"])
            qty = round(rng.uniform(500, 8000), 2)
            for attempt in range(20):  # unique lot code
                lot = f"L{day.strftime('%Y%m%d')}-{sku[-4:]}{rng.randint(0, 99):02d}"
                if not cur.execute("SELECT 1 FROM lots WHERE lot_code=?",
                                   (lot,)).fetchone():
                    break
            else:
                continue
            cur.execute("INSERT INTO lots VALUES (?,?,?,?,?)",
                        (lot, sku, day.isoformat(), expiry.isoformat(), qty))
            ref = f"PR-{lot}"
            posted = datetime.combine(day, datetime.min.time()) + timedelta(hours=7)
            cur.execute(
                """INSERT INTO erp_transactions
                   (txn_date, doc_type, sku, lot_code, qty, uom, converted, qty_base, ref_doc, posted_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (day.isoformat(), "PROD_RECEIPT", sku, lot, qty, s["base_uom"],
                 1, qty, ref, posted.isoformat()))
            mid = self.msg_id()
            cur.execute(
                "INSERT INTO integration_log VALUES (?,?,?,?,?,?,?,?,?,?)",
                (mid, posted.isoformat(), "WMS->ERP", "PROD_RECEIPT",
                 sku, lot, qty, "DELIVERED", None, ref))
            remaining = qty
            while remaining > 0.01:
                pq = round(min(remaining, rng.uniform(200, 1000)), 2)
                remaining -= pq
                cur.execute(
                    "INSERT INTO wms_pallets VALUES (?,?,?,?,?,?,?,?,?)",
                    (self.pallet_id(), sku, lot, pq, s["base_uom"], _bin(rng),
                     expiry.isoformat(), "AVAILABLE", posted.isoformat()))
            pool.append({"sku": sku, "lot": lot, "qty": qty,
                         "unit_cost": s["unit_cost"]})

    def stream_days(self, db_path: Path, label_dir: Path, days: int,
                    inject_per_day: int = 1,
                    categories: list[str] | None = None) -> dict:
        """Advance the simulated world `days` days. Returns a summary."""
        db_path = Path(db_path)
        self.label_dir = Path(label_dir)
        self.label_dir.mkdir(parents=True, exist_ok=True)
        cats = categories or ["failed_message", "duplicate_message",
                              "unposted_receipt", "wrong_uom", "wrong_bin",
                              "expired_available", "cutoff_gap"]
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        start = self.now.date()
        new_lots, injected = 0, 0
        for i in range(1, days + 1):
            day = start + timedelta(days=i)
            self.now = datetime.combine(day, datetime.min.time()) + timedelta(hours=23, minutes=59)
            pool: list[dict] = []
            self.gen_day(cur, day, pool)
            new_lots += len(pool)
            for _ in range(min(inject_per_day, len(pool))):
                L = pool.pop(self.rng.randrange(len(pool)))
                cat = cats[self.rng.randrange(len(cats))]
                getattr(self, f"_inj_{cat}")(cur, L, self.rng)
                injected += 1
        cur.execute("DELETE FROM erp_inventory")
        cur.execute("""
            INSERT INTO erp_inventory (sku, lot_code, qty_base)
            SELECT sku, lot_code, ROUND(SUM(qty_base), 2)
            FROM erp_transactions GROUP BY sku, lot_code""")
        cur.execute("INSERT OR REPLACE INTO meta VALUES (?,?)",
                    ("generated_at", self.now.isoformat()))
        conn.commit()
        conn.close()
        return {"days_streamed": days, "new_lots": new_lots,
                "injected": injected, "now": self.now.isoformat()}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="data/phantom.db")
    ap.add_argument("--labels", default="data/labels")
    ap.add_argument("--seed", type=int, default=SEED)
    ap.add_argument("--no-inject", action="store_true")
    args = ap.parse_args()
    g = Gen(seed=args.seed)
    counts = g.run(Path(args.db), Path(args.labels), do_inject=not args.no_inject)
    print(json.dumps(counts, indent=2))


if __name__ == "__main__":
    main()
