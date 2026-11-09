"""Hearsay brand assets.

Concept: a speech bubble ("what was said") in which sound-wave bars turn into lines of text
("written down") on an indigo-to-violet tile.

Outputs (assets/):
  icon.ico                 multi-size Windows icon (simplified glyph at 16-32 px)
  icon.png                 1024 px app icon (used in the UI sidebar)
  logo/hearsay-icon.svg    scalable icon
  logo/hearsay-icon-1024.png
  logo/hearsay-logo-light.png / -dark.png   horizontal lockup with wordmark + tagline
Everything is drawn at 4x and downsampled for smooth edges.
"""
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "assets"
LOGO = OUT / "logo"
OUT.mkdir(exist_ok=True)
LOGO.mkdir(exist_ok=True)

# brand palette
VIOLET = (124, 108, 255)    # #7C6CFF  tile top-left
INDIGO = (59, 47, 201)      # #3B2FC9  tile bottom-right
INK = (76, 62, 224)         # #4C3EE0  glyph colour inside the bubble
TEXT_DARK = (20, 20, 43)    # #14142B
TEXT_LIGHT = (240, 240, 250)
MUTED_DARK = (104, 106, 130)
MUTED_LIGHT = (152, 154, 178)
SS = 4  # supersampling factor
TAGLINE = "Every word, on the record."


def lerp(a, b, t):
    return tuple(int(round(a[i] + (b[i] - a[i]) * t)) for i in range(3))


def diagonal_gradient(n, c1, c2):
    """Top-left c1 -> bottom-right c2, built small and upscaled (smooth, fast)."""
    small = 256
    g = Image.new("RGB", (small, small))
    px = g.load()
    for y in range(small):
        for x in range(small):
            px[x, y] = lerp(c1, c2, (x + y) / (2 * (small - 1)))
    return g.resize((n, n), Image.BICUBIC)


def rounded_mask(n, radius):
    m = Image.new("L", (n, n), 0)
    ImageDraw.Draw(m).rounded_rectangle([0, 0, n - 1, n - 1], radius=radius, fill=255)
    return m


def bubble_mask(n):
    """Speech bubble: rounded body + a tail curving out of the lower-left."""
    m = Image.new("L", (n, n), 0)
    d = ImageDraw.Draw(m)
    x0, y0, x1, y1 = 0.195 * n, 0.235 * n, 0.805 * n, 0.665 * n
    d.rounded_rectangle([x0, y0, x1, y1], radius=0.15 * n, fill=255)
    # tail: a wide wedge growing out of the lower-left of the body
    # left edge stays flush with the body (x = 0.195) until it tapers into the tip - no step
    d.polygon([(0.195 * n, 0.42 * n), (0.47 * n, 0.645 * n), (0.207 * n, 0.835 * n), (0.195 * n, 0.72 * n)],
              fill=255)
    # blur + re-threshold = rounded tip and a smooth fillet where the tail meets the body,
    # with crisp edges (the 4x supersampling provides the anti-aliasing)
    m = m.filter(ImageFilter.GaussianBlur(n * 0.016))
    return m.point(lambda v: 255 if v >= 128 else 0)


def glyph_mask(n, simple=False):
    """Sound bars -> text lines, cut out of the bubble."""
    m = Image.new("L", (n, n), 0)
    d = ImageDraw.Draw(m)
    cy = 0.45 * n
    if simple:
        bw, gap = 0.085 * n, 0.055 * n
        heights = [0.13, 0.25, 0.17]
        total = 3 * bw + 2 * gap
        x = 0.5 * n - total / 2
        for h in heights:
            d.rounded_rectangle([x, cy - h * n / 2, x + bw, cy + h * n / 2], radius=bw / 2, fill=255)
            x += bw + gap
        return m
    bw, gap = 0.048 * n, 0.03 * n
    heights = [0.10, 0.205, 0.145]
    x = 0.272 * n
    for h in heights:
        d.rounded_rectangle([x, cy - h * n / 2, x + bw, cy + h * n / 2], radius=bw / 2, fill=255)
        x += bw + gap
    lx = x + 0.03 * n
    lh, lg = 0.048 * n, 0.034 * n
    widths = [0.215, 0.15, 0.19]
    y = cy - (3 * lh + 2 * lg) / 2
    for i, w in enumerate(widths):
        d.rounded_rectangle([lx, y, lx + w * n, y + lh], radius=lh / 2, fill=255 if i != 1 else 165)
        y += lh + lg
    return m


def icon(size=1024, simple=False):
    n = size * SS
    tile = diagonal_gradient(n, VIOLET, INDIGO).convert("RGBA")
    # soft highlight in the upper-left for depth
    glow = Image.new("L", (n, n), 0)
    ImageDraw.Draw(glow).ellipse([-0.35 * n, -0.45 * n, 0.75 * n, 0.55 * n], fill=70)
    glow = glow.filter(ImageFilter.GaussianBlur(n * 0.12))
    tile = Image.composite(Image.new("RGBA", (n, n), (255, 255, 255, 255)), tile, glow)
    out = Image.new("RGBA", (n, n), (0, 0, 0, 0))
    out.paste(tile, (0, 0), rounded_mask(n, int(0.225 * n)))

    bub = bubble_mask(n)
    if not simple:
        # gentle drop shadow under the bubble
        sh = bub.filter(ImageFilter.GaussianBlur(n * 0.025))
        sh = ImageChops.offset(sh, 0, int(0.018 * n)).point(lambda v: int(v * 0.30))
        out = Image.composite(Image.new("RGBA", (n, n), (25, 18, 110, 255)), out, sh)
    out = Image.composite(Image.new("RGBA", (n, n), (255, 255, 255, 255)), out, bub)
    g = glyph_mask(n, simple)
    ink = Image.new("RGBA", (n, n), INK + (255,))
    out = Image.composite(ink, out, g)
    # keep the tile's rounded transparency
    alpha = rounded_mask(n, int(0.225 * n))
    out.putalpha(ImageChops.multiply(out.getchannel("A"), alpha))
    return out.resize((size, size), Image.LANCZOS)


def font(px, weight="Semibold Display"):
    try:
        f = ImageFont.truetype("SegUIVar.ttf", px)
        f.set_variation_by_name(weight)
        return f
    except Exception:
        return ImageFont.truetype("seguisb.ttf" if "Semibold" in weight or "Bold" in weight else "segoeui.ttf", px)


def lockup(dark: bool):
    s = SS
    H = 640 * s
    ic = icon(1024).resize((int(H * 0.86),) * 2, Image.LANCZOS)
    word_f = font(300 * s, "Semibold Display")
    tag_f = font(66 * s, "Regular Text")
    tmp = ImageDraw.Draw(Image.new("RGB", (10, 10)))
    wb = tmp.textbbox((0, 0), "Hearsay", font=word_f)
    tb = tmp.textbbox((0, 0), TAGLINE, font=tag_f)
    pad = 60 * s
    gap = 70 * s
    W = pad + ic.width + gap + max(wb[2], tb[2]) + pad
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    img.paste(ic, (pad, (H - ic.height) // 2), ic)
    d = ImageDraw.Draw(img)
    x = pad + ic.width + gap
    word_h = wb[3] - wb[1]
    tag_h = tb[3] - tb[1]
    block = word_h + 46 * s + tag_h
    y = (H - block) // 2
    d.text((x - wb[0], y - wb[1]), "Hearsay", font=word_f, fill=TEXT_LIGHT if dark else TEXT_DARK)
    d.text((x - tb[0] + 6 * s, y + word_h + 46 * s - tb[1]), TAGLINE, font=tag_f,
           fill=MUTED_LIGHT if dark else MUTED_DARK)
    return img.resize((W // s, H // s), Image.LANCZOS)


SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1024 1024" width="1024" height="1024">
  <defs>
    <linearGradient id="tile" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0" stop-color="#7C6CFF"/><stop offset="1" stop-color="#3B2FC9"/>
    </linearGradient>
    <radialGradient id="glow" cx="0.2" cy="0.05" r="0.7">
      <stop offset="0" stop-color="#fff" stop-opacity="0.28"/><stop offset="1" stop-color="#fff" stop-opacity="0"/>
    </radialGradient>
    <filter id="shadow" x="-20%" y="-20%" width="140%" height="160%">
      <feDropShadow dx="0" dy="18" stdDeviation="22" flood-color="#19126E" flood-opacity="0.35"/>
    </filter>
  </defs>
  <rect width="1024" height="1024" rx="230" fill="url(#tile)"/>
  <rect width="1024" height="1024" rx="230" fill="url(#glow)"/>
  <g fill="#fff" filter="url(#shadow)">
    <rect x="200" y="241" width="624" height="440" rx="154"/>
    <path d="M218 520 L466 655 L238 825 Z" stroke="#fff" stroke-width="34" stroke-linejoin="round"/>
  </g>
  <g fill="#4C3EE0">
    <rect x="279" y="410" width="49" height="102" rx="24.5"/>
    <rect x="359" y="356" width="49" height="210" rx="24.5"/>
    <rect x="439" y="387" width="49" height="148" rx="24.5"/>
    <rect x="549" y="384" width="220" height="49" rx="24.5"/>
    <rect x="549" y="468" width="154" height="49" rx="24.5" fill-opacity="0.65"/>
    <rect x="549" y="552" width="195" height="49" rx="24.5"/>
  </g>
</svg>
"""


if __name__ == "__main__":
    big = icon(1024)
    big.save(OUT / "icon.png")
    big.save(LOGO / "hearsay-icon-1024.png")
    (LOGO / "hearsay-icon.svg").write_text(SVG, encoding="utf-8")
    # Windows icon: detailed glyph from 48 px up, simplified glyph below
    frames = {s: (icon(s, simple=s <= 32)) for s in (16, 20, 24, 32, 40, 48, 64, 128, 256)}
    frames[256].save(OUT / "icon.ico", sizes=[(s, s) for s in frames],
                     append_images=[frames[s] for s in frames if s != 256])
    lockup(False).save(LOGO / "hearsay-logo-light.png")
    lockup(True).save(LOGO / "hearsay-logo-dark.png")
    print("assets written to", OUT)
