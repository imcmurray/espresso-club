#!/usr/bin/env python3
"""Generate a printable sign for Phase 0 — the "tape it on the wall" experiment.

The sign has:
- A big QR code of either a Lightning Address or a static bolt12 offer.
- Suggested contribution amounts.
- A short note that you (Ian) own the machine and provide the consumables.

Output: signs/espresso-sign.png  (and .pdf if you have reportlab).

Usage:
    python3 scripts/make_sign.py --address ian@walletofsatoshi.com \\
        --owner Ian --output signs/espresso-sign.png
"""

from __future__ import annotations

import argparse
from pathlib import Path

import qrcode
from PIL import Image, ImageDraw, ImageFont


def render_sign(*, address: str, owner: str, output: Path,
                size: tuple[int, int] = (1240, 1754)) -> None:
    """Render an A4-portrait-ish PNG sign at 150 DPI."""
    W, H = size
    bg = (255, 251, 244)
    fg = (32, 24, 18)
    accent = (192, 133, 82)

    img = Image.new("RGB", (W, H), bg)
    draw = ImageDraw.Draw(img)

    title_font = _font(96)
    subtitle_font = _font(48)
    body_font = _font(40)
    small_font = _font(32)

    y = 80
    draw.text((W // 2, y), "ESPRESSO CLUB", fill=accent,
              font=title_font, anchor="mm")
    y += 110

    draw.text((W // 2, y), "☕", fill=fg, font=_font(140), anchor="mm")
    y += 180

    draw.text((W // 2, y),
              f"Owned and stocked by {owner}.",
              fill=fg, font=subtitle_font, anchor="mm")
    y += 70
    draw.text((W // 2, y),
              "Beans, milk, creamer, water — all on me.",
              fill=fg, font=body_font, anchor="mm")
    y += 80
    draw.text((W // 2, y),
              "If you'd like to chip in:",
              fill=fg, font=body_font, anchor="mm")
    y += 80

    # QR
    qr = qrcode.QRCode(box_size=14, border=2)
    qr.add_data(address)
    qr.make(fit=True)
    qr_img = qr.make_image(fill_color="black", back_color=bg).convert("RGB")
    qw, qh = qr_img.size
    img.paste(qr_img, ((W - qw) // 2, y))
    y += qh + 30

    draw.text((W // 2, y), address, fill=fg, font=body_font, anchor="mm")
    y += 100

    draw.text((W // 2, y),
              "Suggested: $5/week · $20/month · or whatever you think a cup is worth",
              fill=fg, font=small_font, anchor="mm")
    y += 50
    draw.text((W // 2, y),
              "Lightning only — no fees, instant.",
              fill=accent, font=small_font, anchor="mm")
    y += 100

    draw.text((W // 2, y),
              "Want a tap-card account? See /onboard or ask Ian.",
              fill=(120, 100, 80), font=small_font, anchor="mm")

    output.parent.mkdir(parents=True, exist_ok=True)
    img.save(output, format="PNG", dpi=(150, 150))
    print(f"wrote {output}")


def _font(size: int) -> ImageFont.ImageFont:
    """Load a system font that's likely to exist; fall back to default."""
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
    ]
    for path in candidates:
        if Path(path).exists():
            try:
                return ImageFont.truetype(path, size)
            except OSError:
                continue
    return ImageFont.load_default()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--address", required=True,
                    help="Lightning Address or bolt12 offer to encode in the QR")
    ap.add_argument("--owner", default="the office's resident barista")
    ap.add_argument("--output", default="signs/espresso-sign.png", type=Path)
    args = ap.parse_args()
    render_sign(address=args.address, owner=args.owner, output=args.output)


if __name__ == "__main__":
    main()
