"""Generate docs/architecture.png — system architecture diagram (PIL, no deps)."""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

W, H = 1240, 760
BG = (15, 20, 32)
PANEL = (24, 32, 50)
LINE = (90, 169, 255)
TXT = (232, 237, 247)
DIM = (147, 161, 189)
ACCENT = (90, 169, 255)
GREEN = (74, 222, 128)
WARN = (251, 191, 36)


def _font(size: int, bold: bool = True):
    name = "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"
    for p in (f"/usr/share/fonts/truetype/dejavu/{name}",):
        try:
            return ImageFont.truetype(p, size)
        except OSError:
            continue
    return ImageFont.load_default()


def box(d, xy, w, h, title, lines, accent=ACCENT):
    x, y = xy
    d.rounded_rectangle([x, y, x + w, y + h], radius=14, fill=PANEL,
                        outline=accent, width=2)
    d.text((x + 16, y + 12), title, font=_font(20), fill=TXT)
    yy = y + 44
    for ln in lines:
        d.text((x + 16, yy), ln, font=_font(15, bold=False), fill=DIM)
        yy += 24


def arrow(d, x1, y1, x2, y2, label=""):
    d.line([x1, y1, x2, y2], fill=LINE, width=3)
    # head
    s = 10
    if x2 > x1:
        d.polygon([(x2, y2), (x2 - s, y2 - 6), (x2 - s, y2 + 6)], fill=LINE)
    elif y2 > y1:
        d.polygon([(x2, y2), (x2 - 6, y2 - s), (x2 + 6, y2 - s)], fill=LINE)
    if label:
        d.text(((x1 + x2) / 2 + 8, (y1 + y2) / 2 - 22), label,
               font=_font(13, bold=False), fill=DIM)


def main():
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    d.text((40, 24), "Phantom Inventory Hunter — architecture",
           font=_font(28), fill=TXT)
    d.text((40, 62), "synthetic ERP/WMS world · deterministic reconcile · agentic investigation · human approval",
           font=_font(16, bold=False), fill=DIM)

    # top row: world -> data -> engine
    box(d, (40, 120), 300, 170, "1 · Synthetic world",
        ["generator.py", "200 SKUs · 30 days", "ERP txns · WMS pallets", "integration log", "8 injected root causes"])
    box(d, (400, 120), 300, 170, "2 · SQLite",
        ["schema.py", "erp_*/wms_*/lots", "integration_log", "ground_truth", "discrepancies"])
    box(d, (760, 120), 440, 170, "3 · Reconcile engine",
        ["reconcile.py — deterministic", "qty / bin / expiry / cutoff checks", "value-at-risk + severity", "evidence hints attached"])
    arrow(d, 340, 205, 400, 205)
    arrow(d, 700, 205, 760, 205)

    # middle: agent
    box(d, (400, 350), 440, 210, "4 · Investigation agent",
        ["agent.py — ReAct-lite loop", "tools: ERP/WMS/log/label reads", "Meta Model API (muse-spark-1.3)", "rule fallback, mode-tagged", "root cause · evidence · fix proposal"])
    arrow(d, 980, 290, 980, 350, "discrepancies")

    # bottom row: queue + dashboard, loop
    box(d, (40, 350), 300, 210, "5 · Approval queue",
        ["runner.py", "human approves/rejects", "agent NEVER applies fixes", "repeat-cause grouping"], accent=WARN)
    box(d, (900, 350), 300, 210, "6 · Dashboard",
        ["dashboard.py + eval.py", "value-at-risk ranking", "evidence + label images", "accuracy vs ground truth"], accent=GREEN)
    # agent -> queue: horizontal line just below both boxes
    d.line([620, 578, 190, 578], fill=LINE, width=3)
    d.polygon([(190, 578), (200, 572), (200, 584)], fill=LINE)
    d.text((360, 584), "investigations", font=_font(13, bold=False), fill=DIM)
    # queue -> dashboard: route under the agent box
    d.line([190, 596, 1050, 596], fill=LINE, width=3)
    d.line([1050, 596, 1050, 560], fill=LINE, width=3)
    d.polygon([(1050, 560), (1044, 570), (1056, 570)], fill=LINE)
    d.text((560, 600), "queue API", font=_font(13, bold=False), fill=DIM)

    # long-running loop band
    d.rounded_rectangle([40, 624, 1200, 700], radius=14, outline=LINE, width=2)
    d.text((64, 640), "LONG-RUNNING LOOP — stream days → reconcile → dedupe → prioritize ($ × expiry) → investigate → queue",
           font=_font(17), fill=TXT)
    d.text((64, 668), "stale PENDING messages escalate to failed deliveries · token cache + $ budget log · 100% synthetic data",
           font=_font(14, bold=False), fill=DIM)

    out = Path(__file__).resolve().parent / "architecture.png"
    img.save(out)
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
