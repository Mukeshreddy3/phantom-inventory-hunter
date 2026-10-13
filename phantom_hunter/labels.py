"""Synthetic pallet-label image generator (PIL).

Produces warehouse-style pallet labels: SKU, description-ish header, lot,
quantity + UOM, expiry date, bin location, pallet id and a fake barcode.
A few labels are generated with contradicting data (see generator
_label_contradiction) to give the M2 vision agent something to catch.
"""
from __future__ import annotations

import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

W, H = 480, 320


def _font(size: int):
    # DejaVu ships with most Linuxes; fall back to the PIL default.
    for path in ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
                 "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _barcode(draw: ImageDraw.ImageDraw, x0: int, y0: int, w: int, h: int, seed: int):
    rng = random.Random(seed)
    x = x0
    while x < x0 + w:
        bw = rng.choice([2, 3, 4, 6])
        if rng.random() < 0.55:
            draw.rectangle([x, y0, x + bw, y0 + h], fill="black")
        x += bw + rng.choice([1, 2, 3])


def make_label(data: dict, out_path: Path, contradict: bool = False) -> Path:
    """data keys: pallet_id, sku, lot_code, qty, uom, location, expiry."""
    img = Image.new("RGB", (W, H), "white")
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, W, H], outline="black", width=6)
    d.rectangle([0, 0, W, 64], fill="black")
    d.text((16, 12), "PHANTOM DAIRY  •  PALLET LABEL", font=_font(22), fill="white")

    y = 84
    rows = [
        ("SKU", str(data["sku"])),
        ("LOT", str(data["lot_code"])),
        ("QTY", f"{data['qty']} {data['uom']}"),
        ("EXPIRY", str(data["expiry"])),
        ("BIN", str(data["location"])),
        ("PALLET", str(data["pallet_id"])),
    ]
    for k, v in rows:
        d.text((16, y), k, font=_font(16), fill=(110, 110, 110))
        d.text((120, y - 4), v, font=_font(24), fill="black")
        y += 34

    _barcode(d, 16, H - 52, W - 32, 36, seed=hash(data["pallet_id"]) % (2 ** 31))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(out_path)
    return out_path
