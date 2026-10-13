"""Long-running loop + approval queue (M3).

The loop runs ticks. Each tick:
  1. optionally streams new synthetic world activity (new production days),
  2. re-runs the deterministic reconciliation,
  3. picks up NEW discrepancies (deduped by natural key),
  4. prioritizes them (dollar value + expiry risk),
  5. investigates each with the M2 agent,
  6. files the result in the approval queue, grouped with past repeat
     root causes.

The agent NEVER applies fixes. ``approve``/``reject`` only record the
human's decision on the queue — business tables are untouched.

Usage:
    python -m phantom_hunter.runner --once            # single tick, no streaming
    python -m phantom_hunter.runner --days 3         # 3 ticks, 1 streamed day each
    python -m phantom_hunter.runner --queue          # show approval queue
    python -m phantom_hunter.runner --approve INV-0003 --note "resent"
    python -m phantom_hunter.runner --reject INV-0004 --note "not a real issue"
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import date, datetime
from pathlib import Path

from . import reconcile, tools
from .agent import InvestigationAgent
from .generator import Gen
from .llm import LLMClient
from .schema import create_schema


def disc_key(d: dict) -> str:
    return f"{d['category']}|{d['sku']}|{d['lot_code']}|{d['pallet_id'] or ''}"


def priority_score(db_path: Path, d: dict, now: datetime) -> float:
    """Dollar value at risk, boosted by expiry risk."""
    score = d["value_at_risk"]
    if d["category"] == "expired_available":
        score *= 1.5
    elif d["sku"] and d["lot_code"]:
        lot = tools.get_lot(db_path, d["sku"], d["lot_code"])["lot"]
        if lot and lot.get("expiry_date"):
            days_left = (date.fromisoformat(lot["expiry_date"]) - now.date()).days
            if 0 <= days_left <= 7:
                score *= 1.25  # expiring within a week: investigate sooner
    return round(score, 2)


class Loop:
    def __init__(self, db_path: Path, label_dir: Path, llm: LLMClient | None = None):
        self.db_path = Path(db_path)
        self.label_dir = Path(label_dir)
        conn = sqlite3.connect(self.db_path)
        create_schema(conn)  # idempotent; ensures investigations table exists
        conn.close()
        self.agent = InvestigationAgent(self.db_path, self.label_dir,
                                        llm or LLMClient(data_dir=self.db_path.parent))

    # -- clock --------------------------------------------------------------- #
    def now(self) -> datetime:
        conn = sqlite3.connect(self.db_path)
        try:
            v = conn.execute("SELECT value FROM meta WHERE key='generated_at'").fetchone()
            return datetime.fromisoformat(v[0]) if v else datetime.now()
        finally:
            conn.close()

    # -- tick ---------------------------------------------------------------- #
    def tick(self, stream_days: int = 0, inject_per_day: int = 1,
             max_investigations: int | None = None) -> dict:
        streamed = None
        if stream_days > 0:
            g = Gen.resume(self.db_path, self.label_dir)
            streamed = g.stream_days(self.db_path, self.label_dir, stream_days,
                                     inject_per_day=inject_per_day)
        now = self.now()
        discs = reconcile.run(self.db_path, now=now)

        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            seen = {r[0] for r in conn.execute("SELECT disc_key FROM investigations")}
            fresh = [d for d in discs if disc_key(d) not in seen]
            fresh.sort(key=lambda d: priority_score(self.db_path, d, now), reverse=True)
            if max_investigations is not None:
                fresh = fresh[:max_investigations]

            investigated, repeats = [], 0
            for d in fresh:
                inv = self.agent.investigate(d["id"])
                inv_id = self._file(conn, d, inv, now)
                investigated.append(inv_id)
                if inv.get("_repeat_group"):
                    repeats += 1
            conn.commit()
        finally:
            conn.close()
        return {"streamed": streamed, "discrepancies": len(discs),
                "new": len(fresh), "investigated": investigated, "repeats": repeats,
                "now": now.isoformat()}

    def _file(self, conn, d: dict, inv: dict, now: datetime) -> str:
        n = conn.execute("SELECT COUNT(*) FROM investigations").fetchone()[0]
        inv_id = f"INV-{n + 1:04d}"
        # repeat grouping: link to the earliest investigation with same root cause + SKU
        row = conn.execute(
            """SELECT id, repeat_group FROM investigations
               WHERE root_cause=? AND sku=? ORDER BY investigated_at LIMIT 1""",
            (inv["root_cause"], d["sku"])).fetchone()
        repeat_group = None
        if row:
            repeat_group = row["repeat_group"] or row["id"]
            inv["_repeat_group"] = repeat_group
        conn.execute(
            """INSERT INTO investigations
               (id, disc_key, discrepancy_id, detected_at, investigated_at,
                category, sku, lot_code, pallet_id, value_at_risk, priority,
                root_cause, confidence, evidence, proposed_fix, agent_mode,
                status, repeat_group)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (inv_id, disc_key(d), d["id"], d["detected_at"], now.isoformat(),
             d["category"], d["sku"], d["lot_code"], d["pallet_id"],
             d["value_at_risk"], priority_score(self.db_path, d, now),
             inv["root_cause"], inv["confidence"], json.dumps(inv["evidence"]),
             json.dumps(inv["proposed_fix"]), inv["mode"],
             "PENDING_APPROVAL", repeat_group))
        return inv_id

    # -- approval queue -------------------------------------------------------- #
    def queue(self, status: str | None = None) -> list[dict]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            q = ("SELECT id, discrepancy_id, category, sku, lot_code, value_at_risk, "
                 "priority, root_cause, confidence, proposed_fix, agent_mode, status, "
                 "decided_at, decide_note, repeat_group FROM investigations")
            args: list = []
            if status:
                q += " WHERE status=?"
                args.append(status)
            q += " ORDER BY priority DESC"
            return [dict(r) for r in conn.execute(q, args)]
        finally:
            conn.close()

    def _decide(self, inv_id: str, status: str, note: str) -> dict:
        # NOTE: decision only touches the investigations row — the agent never
        # applies fixes to business tables, approved or not.
        conn = sqlite3.connect(self.db_path)
        try:
            r = conn.execute("SELECT status FROM investigations WHERE id=?",
                             (inv_id,)).fetchone()
            if not r:
                raise ValueError(f"unknown investigation {inv_id}")
            if r[0] != "PENDING_APPROVAL":
                raise ValueError(f"{inv_id} already decided ({r[0]})")
            conn.execute(
                "UPDATE investigations SET status=?, decided_at=?, decide_note=? WHERE id=?",
                (status, datetime.now().isoformat(), note, inv_id))
            conn.commit()
            return {"id": inv_id, "status": status, "note": note}
        finally:
            conn.close()

    def approve(self, inv_id: str, note: str = "") -> dict:
        return self._decide(inv_id, "APPROVED", note)

    def reject(self, inv_id: str, note: str = "") -> dict:
        return self._decide(inv_id, "REJECTED", note)

    def summary(self) -> dict:
        conn = sqlite3.connect(self.db_path)
        try:
            by_status = dict(conn.execute(
                "SELECT status, COUNT(*) FROM investigations GROUP BY status").fetchall())
            by_cause = dict(conn.execute(
                "SELECT root_cause, COUNT(*) FROM investigations GROUP BY root_cause").fetchall())
            repeats = conn.execute(
                "SELECT COUNT(*) FROM investigations WHERE repeat_group IS NOT NULL"
            ).fetchone()[0]
            return {"by_status": by_status, "by_cause": by_cause,
                    "repeat_links": repeats}
        finally:
            conn.close()


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def _print_tick(res: dict, tick_no: int | None = None) -> None:
    head = f"[tick {tick_no}] " if tick_no else "[tick] "
    s = res["streamed"]
    stream_txt = (f"streamed {s['days_streamed']}d ({s['new_lots']} new lots, "
                  f"{s['injected']} injected) | " if s else "")
    print(f"{head}{stream_txt}{res['discrepancies']} discrepancies, "
          f"{res['new']} new investigated ({res['repeats']} repeats)")


def _print_queue(rows: list[dict]) -> None:
    if not rows:
        print("queue empty")
        return
    print(f"{'ID':9} {'PRIORITY':>10} {'ROOT CAUSE':17} {'SKU'}")
    for r in rows:
        flag = f" [repeat of {r['repeat_group']}]" if r["repeat_group"] else ""
        print(f"{r['id']:9} {r['priority']:>10,.2f} {r['root_cause']:17} "
              f"{r['sku']}{flag}")
        fix = json.loads(r["proposed_fix"])
        print(f"          fix: {fix['action']} — {fix['description'][:90]}")
        print(f"          status: {r['status']}" +
              (f" | note: {r['decide_note']}" if r["decide_note"] else ""))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="data/phantom.db")
    ap.add_argument("--labels", default="data/labels")
    ap.add_argument("--once", action="store_true", help="single tick, no streaming")
    ap.add_argument("--days", type=int, default=0,
                    help="run N ticks, streaming 1 day per tick")
    ap.add_argument("--stream", type=int, default=0,
                    help="stream N days on a single tick")
    ap.add_argument("--inject-per-day", type=int, default=1)
    ap.add_argument("--max-inv", type=int, default=None)
    ap.add_argument("--queue", action="store_true")
    ap.add_argument("--approve", metavar="INV-ID")
    ap.add_argument("--reject", metavar="INV-ID")
    ap.add_argument("--note", default="")
    args = ap.parse_args()

    db_path = Path(args.db)
    if not db_path.exists():
        raise SystemExit(f"DB not found: {db_path} — run `make data` first.")
    loop = Loop(db_path, Path(args.labels))

    if args.approve:
        print(loop.approve(args.approve, args.note))
        return
    if args.reject:
        print(loop.reject(args.reject, args.note))
        return
    if args.queue:
        _print_queue(loop.queue())
        s = loop.summary()
        print(f"\nby status: {s['by_status']} | by root cause: {s['by_cause']} | "
              f"repeat links: {s['repeat_links']}")
        return

    if args.days > 0:
        for t in range(1, args.days + 1):
            res = loop.tick(stream_days=1, inject_per_day=args.inject_per_day,
                            max_investigations=args.max_inv)
            _print_tick(res, t)
    else:
        res = loop.tick(stream_days=args.stream, inject_per_day=args.inject_per_day,
                        max_investigations=args.max_inv)
        _print_tick(res)
    s = loop.summary()
    print(f"investigations by status: {s['by_status']}")


if __name__ == "__main__":
    main()
