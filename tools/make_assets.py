"""Generate assets/icon.ico and assets/splash.png (run before building)."""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "assets"
OUT.mkdir(exist_ok=True)
TOP, BOTTOM = (108, 108, 240), (74, 74, 200)


def gradient(size, top, bottom):
    w, h = size
    img = Image.new("RGBA", size)
    px = img.load()
    for y in range(h):
        t = y / max(h - 1, 1)
        c = tuple(int(top[i] + (bottom[i] - top[i]) * t) for i in range(3)) + (255,)
        for x in range(w):
            px[x, y] = c
    return img


def icon_image(n=1024):
    base = gradient((n, n), TOP, BOTTOM)
    mask = Image.new("L", (n, n), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, n - 1, n - 1], radius=int(n * 0.23), fill=255)
    img = Image.new("RGBA", (n, n), (0, 0, 0, 0))
    img.paste(base, (0, 0), mask)
    d = ImageDraw.Draw(img)
    white = (255, 255, 255, 255)
    soft = (255, 255, 255, 150)
    # sound-wave bars on the left
    bars = [0.16, 0.30, 0.22, 0.38, 0.18]
    bw, gap, x0, cy = n * 0.045, n * 0.03, n * 0.16, n * 0.5
    for i, hgt in enumerate(bars):
        x = x0 + i * (bw + gap)
        d.rounded_rectangle([x, cy - n * hgt / 2, x + bw, cy + n * hgt / 2], radius=bw / 2, fill=white)
    # transcript lines on the right
    lx = n * 0.52
    widths = [0.32, 0.26, 0.32, 0.20]
    lh, lg = n * 0.055, n * 0.06
    y = n * 0.5 - (len(widths) * lh + (len(widths) - 1) * lg) / 2
    for i, wd in enumerate(widths):
        d.rounded_rectangle([lx, y, lx + n * wd, y + lh], radius=lh / 2, fill=white if i % 2 == 0 else soft)
        y += lh + lg
    return img


def font(size, bold=False):
    for name in (["segoeuib.ttf", "seguisb.ttf"] if bold else ["segoeui.ttf"]):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def splash():
    w, h = 640, 340
    img = gradient((w, h), (30, 31, 44), (17, 18, 24)).convert("RGB")
    d = ImageDraw.Draw(img)
    ic = icon_image(512).resize((112, 112), Image.LANCZOS)
    img.paste(ic, (48, 76), ic)
    d.text((186, 82), "Transcript Extractor", font=font(40, True), fill=(236, 237, 243))
    d.text((188, 138), "YouTube & video files → clean transcripts", font=font(20), fill=(150, 153, 172))
    d.rounded_rectangle([48, 262, w - 48, 266], radius=2, fill=(52, 53, 70))
    d.rounded_rectangle([48, 262, 230, 266], radius=2, fill=(108, 108, 240))
    img.save(OUT / "splash.png")


if __name__ == "__main__":
    big = icon_image(1024)
    big.save(OUT / "icon.png")
    big.save(OUT / "icon.ico", sizes=[(s, s) for s in (16, 20, 24, 32, 40, 48, 64, 128, 256)])
    splash()
    print("assets written to", OUT)
