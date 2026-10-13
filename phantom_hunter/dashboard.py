"""Web dashboard (M4): stdlib HTTP server + JSON API + static frontend.

Endpoints:
  GET  /                          dashboard page
  GET  /api/summary               headline numbers + top root causes
  GET  /api/discrepancies         open discrepancies, value-at-risk first
  GET  /api/discrepancy/<id>      detail: discrepancy + investigation + label
  GET  /api/queue                 approval queue (pending, priority first)
  POST /api/investigations/<id>/approve   {"note": "..."}
  POST /api/investigations/<id>/reject    {"note": "..."}
  GET  /api/eval                  root-cause accuracy vs ground truth
  GET  /api/labels/<pallet>.png   pallet-label image

Usage:
    python -m phantom_hunter.dashboard --port 8000
"""
from __future__ import annotations

import argparse
import json
import mimetypes
import sqlite3
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from . import eval as eval_mod
from . import tools
from .runner import Loop, disc_key

STATIC_DIR = Path(__file__).resolve().parent / "static"


class Handler(BaseHTTPRequestHandler):
    db_path: Path = None          # set by serve()
    label_dir: Path = None        # set by serve()
    server_version = "PhantomDashboard/0.4"

    # -- helpers ------------------------------------------------------------ #
    def _send(self, code: int, payload, content_type="application/json"):
        body = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length", 0) or 0)
        return json.loads(self.rfile.read(length).decode() or "{}")

    def _loop(self) -> Loop:
        from .llm import LLMClient
        return Loop(self.db_path, self.label_dir,
                    LLMClient(data_dir=self.db_path.parent))

    # -- API builders -------------------------------------------------------- #
    def _summary(self) -> dict:
        loop = self._loop()
        now = loop.now()
        discs = tools.list_discrepancies(self.db_path)
        invs = loop.queue(status=None)
        pending = [i for i in invs if i["status"] == "PENDING_APPROVAL"]
        approved = [i for i in invs if i["status"] == "APPROVED"]
        week_ago = (now - timedelta(days=7)).isoformat()
        causes: dict[str, int] = {}
        for i in invs:
            if i["investigated_at"] >= week_ago:
                causes[i["root_cause"]] = causes.get(i["root_cause"], 0) + 1
        top = sorted(causes.items(), key=lambda kv: kv[1], reverse=True)[:5]
        ev = eval_mod.evaluate(self.db_path)
        return {
            "value_at_risk_open": round(sum(d["value_at_risk"] for d in discs), 2),
            "open_count": len(discs),
            "investigated": len(invs),
            "pending": len(pending),
            "approved": len(approved),
            "value_reconciled": round(sum(i["value_at_risk"] for i in approved), 2),
            "top_root_causes_week": [{"cause": c, "count": n} for c, n in top],
            "accuracy": ev["accuracy"],
            "evaluated": ev["total_evaluated"],
            "sim_now": now.isoformat(),
        }

    def _discrepancy_list(self) -> list[dict]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        inv_by_key = {r["disc_key"]: dict(r) for r in
                      conn.execute("SELECT disc_key, id, root_cause, status, priority "
                                   "FROM investigations")}
        conn.close()
        out = []
        for d in tools.list_discrepancies(self.db_path):
            inv = inv_by_key.get(disc_key(d))
            out.append({**d, "detail": json.loads(d["detail"]),
                        "investigation_id": inv["id"] if inv else None,
                        "root_cause": inv["root_cause"] if inv else None,
                        "inv_status": inv["status"] if inv else None})
        return out

    def _discrepancy_detail(self, disc_id: str):
        d = tools.get_discrepancy(self.db_path, disc_id)
        if not d:
            return None
        d = {**d, "detail": json.loads(d["detail"])}
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        inv = conn.execute("SELECT * FROM investigations WHERE disc_key=?",
                           (disc_key(d),)).fetchone()
        conn.close()
        inv_d = None
        if inv:
            inv_d = dict(inv)
            inv_d["evidence"] = json.loads(inv_d["evidence"])
            inv_d["proposed_fix"] = json.loads(inv_d["proposed_fix"])
        label_url = None
        if d.get("pallet_id"):
            p = self.label_dir / f"{d['pallet_id']}.png"
            if p.exists():
                label_url = f"/api/labels/{d['pallet_id']}.png"
        return {"discrepancy": d, "investigation": inv_d, "label_url": label_url}

    # -- routing -------------------------------------------------------------- #
    def do_GET(self):
        path = urlparse(self.path).path
        try:
            if path == "/":
                self._send(200, (STATIC_DIR / "index.html").read_bytes(), "text/html")
            elif path == "/app.js":
                self._send(200, (STATIC_DIR / "app.js").read_bytes(),
                            "application/javascript")
            elif path == "/styles.css":
                self._send(200, (STATIC_DIR / "styles.css").read_bytes(), "text/css")
            elif path == "/api/summary":
                self._send(200, self._summary())
            elif path == "/api/discrepancies":
                self._send(200, self._discrepancy_list())
            elif path.startswith("/api/discrepancy/"):
                d = self._discrepancy_detail(path.rsplit("/", 1)[-1])
                self._send(200 if d else 404, d or {"error": "not found"})
            elif path == "/api/queue":
                self._send(200, self._loop().queue())
            elif path == "/api/eval":
                self._send(200, eval_mod.evaluate(self.db_path))
            elif path.startswith("/api/labels/"):
                p = self.label_dir / path.rsplit("/", 1)[-1]
                if p.suffix == ".png" and p.exists():
                    self._send(200, p.read_bytes(), "image/png")
                else:
                    self._send(404, {"error": "no label image"})
            else:
                self._send(404, {"error": "not found"})
        except BrokenPipeError:
            pass
        except Exception as e:  # noqa: BLE001 — surfaced as JSON for the demo
            self._send(500, {"error": str(e)})

    def do_POST(self):
        path = urlparse(self.path).path
        try:
            parts = path.strip("/").split("/")
            # /api/investigations/<id>/approve|reject
            if (len(parts) == 4 and parts[0] == "api" and parts[1] == "investigations"
                    and parts[3] in ("approve", "reject")):
                inv_id, action = parts[2], parts[3]
                note = self._read_json().get("note", "")
                loop = self._loop()
                try:
                    result = (loop.approve(inv_id, note) if action == "approve"
                              else loop.reject(inv_id, note))
                    self._send(200, result)
                except ValueError as e:
                    self._send(400, {"error": str(e)})
            else:
                self._send(404, {"error": "not found"})
        except BrokenPipeError:
            pass
        except Exception as e:  # noqa: BLE001
            self._send(500, {"error": str(e)})

    def log_message(self, *args):  # quieter logs
        pass


def serve(db_path: Path, label_dir: Path, port: int) -> ThreadingHTTPServer:
    Handler.db_path = Path(db_path)
    Handler.label_dir = Path(label_dir)
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    return server


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="data/phantom.db")
    ap.add_argument("--labels", default="data/labels")
    ap.add_argument("--port", type=int, default=8000)
    args = ap.parse_args()
    db_path = Path(args.db)
    if not db_path.exists():
        raise SystemExit(f"DB not found: {db_path} — run `make data` first.")
    server = serve(db_path, Path(args.labels), args.port)
    print(f"Phantom dashboard at http://127.0.0.1:{args.port}  (Ctrl-C to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
