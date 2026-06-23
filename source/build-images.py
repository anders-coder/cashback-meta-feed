#!/usr/bin/env python3
"""
build-images.py - generate branded "Confect-style" catalog images, one set per
partner, in the three Meta aspect ratios, plus a Collection cover per tier.

Reads ../feed/partners-all.json (written by build-feed.py) and ../feed/partners.json
(the curated highest/popular sets used for the covers), downloads each partner's
hero + logo, and bakes:

  partner card:   white card, rounded hero photo with the partner logo on it,
                  a big "X % CASHBACK" pill, a per-brand value line, a wide CTA,
                  and a tiny disclaimer. Flattened to JPEG.
  ../images/<slug>_<hash>_1x1.jpg    1080x1080   -> Meta image_link
  ../images/<slug>_<hash>_4x5.jpg    1080x1350   -> additional_image_link
  ../images/<slug>_<hash>_9x16.jpg   1080x1920   -> additional_image_link
  ../images/_cover_<tier>_<ratio>.jpg            -> Collection ad cover

Filenames are content-hashed (metalib.img_base) so a cashback/artwork change yields
a new URL and Meta re-fetches. Rendering is idempotent: a file that already exists
is skipped; stale files no longer referenced are pruned.

Run:  cd source && python3 build-images.py
Deps: Pillow (see ../requirements.txt). Shares metalib.py with build-feed.py.
"""
import io
import json
import os
import re
import ssl
import subprocess
import urllib.request

from PIL import Image, ImageDraw, ImageFont, ImageFilter

import metalib

_HERE = os.path.dirname(os.path.abspath(__file__))
_FEED = os.path.join(_HERE, "..", "feed")
if not os.path.isdir(_FEED):
    _FEED = os.path.join(_HERE, "feed")
_IMG = os.path.join(_HERE, "..", "images")
if not os.path.isdir(os.path.dirname(os.path.abspath(_IMG))):
    _IMG = os.path.join(_HERE, "images")
os.makedirs(_IMG, exist_ok=True)

# ---- brand identity (matches the Kayzen creatives) ---------------------------
BLUE = (20, 52, 203)          # Visa #1434cb
BLUE_D = (12, 30, 120)        # darker shade for gradients
INK = (27, 36, 64)
GREY = (122, 131, 166)
WHITE = (255, 255, 255)
PANEL = (238, 243, 255)       # light blue panel
BORDER = (213, 220, 238)
LBLUE = (199, 228, 247)       # design-team endcard background (pale sky blue)
MUTED = (143, 178, 214)       # muted "Cashback" in the header lockup
INKD = (24, 26, 34)           # near-black headline

FB = os.path.join(_HERE, "font-Bold.woff2")
FM = os.path.join(_HERE, "font-Medium.woff2")
FR = os.path.join(_HERE, "font-Regular.woff2")
_FCACHE = {}


def font(path, size):
    key = (path, size)
    if key not in _FCACHE:
        _FCACHE[key] = ImageFont.truetype(path, size)
    return _FCACHE[key]


UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
_DL = {}


def _curl(url):
    """Fallback fetch via the system curl (handles TLS the old macOS LibreSSL in
    the stock python3 rejects; on CI urllib already works)."""
    try:
        r = subprocess.run(["curl", "-fsSL", "--max-time", "25", "-A", UA, url],
                           capture_output=True, timeout=30)
        return r.stdout if (r.returncode == 0 and r.stdout) else None
    except Exception:
        return None


def download(url):
    """Fetch an image URL -> PIL.Image (RGBA), with retry + memo. None on failure."""
    if not url:
        return None
    if url in _DL:
        return _DL[url]
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "image/*,*/*"})
    data = None
    for ctx in (ssl.create_default_context(), ssl._create_unverified_context()):
        try:
            data = urllib.request.urlopen(req, timeout=20, context=ctx).read()
            break
        except Exception:
            continue
    if not data:
        data = _curl(url)
    im = None
    if data:
        try:
            im = Image.open(io.BytesIO(data)).convert("RGBA")
            im.load()
        except Exception:
            im = None
    _DL[url] = im
    return im


def bump(url, w):
    """Rewrite the resizer ?width=N so we fetch hi-res art (fit() never upscales,
    so a 160 px logo can't fill a big chip — request it bigger instead)."""
    if not url:
        return url
    return re.sub(r"([?&]width=)\d+", r"\g<1>" + str(w), url)


# ---- geometry helpers --------------------------------------------------------
def cover(im, w, h):
    """Scale + center-crop to exactly fill (w, h)."""
    iw, ih = im.size
    if iw == 0 or ih == 0:
        return Image.new("RGB", (w, h), PANEL)
    sc = max(w / iw, h / ih)
    nw, nh = max(1, int(iw * sc + 0.5)), max(1, int(ih * sc + 0.5))
    im = im.convert("RGB").resize((nw, nh), Image.LANCZOS)
    x, y = (nw - w) // 2, (nh - h) // 2
    return im.crop((x, y, x + w, y + h))


def round_mask(size, rad):
    m = Image.new("L", size, 0)
    ImageDraw.Draw(m).rounded_rectangle((0, 0, size[0] - 1, size[1] - 1), radius=rad, fill=255)
    return m


def paste_rounded(base, im, box, rad):
    x, y, w, h = box
    im = cover(im, w, h)
    base.paste(im, (x, y), round_mask((w, h), rad))


def trim_alpha(im):
    bb = im.split()[3].getbbox()
    return im.crop(bb) if bb else im


def fit(im, bw, bh):
    im = im.copy()
    im.thumbnail((bw, bh), Image.LANCZOS)
    return im


def fit_up(im, bw, bh, max_scale=2.2):
    """Scale to fill the box, ALLOWING upscaling up to max_scale (the partner
    logos are only ~260 px native, so thumbnail-only can't enlarge them). The cap
    keeps a small source from getting too soft."""
    iw, ih = im.size
    if iw == 0 or ih == 0:
        return im
    sc = min(min(bw / iw, bh / ih), max_scale)
    return im.resize((max(1, round(iw * sc)), max(1, round(ih * sc))), Image.LANCZOS)


def mean_lum(im):
    """Mean luminance of the opaque pixels of an RGBA logo (0..255)."""
    small = im.convert("RGBA").resize((32, 32))
    px = small.load()
    tot, n = 0, 0
    for yy in range(32):
        for xx in range(32):
            r, g, b, a = px[xx, yy]
            if a > 40:
                tot += 0.299 * r + 0.587 * g + 0.114 * b
                n += 1
    return tot / n if n else 255


def text_w(d, txt, f):
    return d.textlength(txt, font=f)


def ctext(d, cx, y, txt, f, fill):
    d.text((cx - text_w(d, txt, f) / 2, y), txt, font=f, fill=fill)


def wrap(d, txt, f, maxw, maxlines=2):
    out, cur = [], ""
    for wd in (txt or "").split():
        t = (cur + " " + wd).strip()
        if text_w(d, t, f) <= maxw:
            cur = t
        else:
            out.append(cur)
            cur = wd
            if len(out) == maxlines:
                break
    if cur and len(out) < maxlines:
        out.append(cur)
    if out and text_w(d, out[-1], f) > maxw:                # ellipsize last line
        while out[-1] and text_w(d, out[-1] + "…", f) > maxw:
            out[-1] = out[-1][:-1]
        out[-1] += "…"
    return out


def vgradient(w, h, top, bot):
    col = Image.new("RGB", (1, h))
    px = col.load()
    for y in range(h):
        t = y / max(1, h - 1)
        px[0, y] = tuple(round(top[i] + (bot[i] - top[i]) * t) for i in range(3))
    return col.resize((w, h))


# ---- shared brand bits -------------------------------------------------------
def lockup(d, cx, y, s):
    """Text wordmark: 'Cashback | VISA'."""
    f = font(FB, int(40 * s))
    a, b = "Cashback", "VISA"
    wa, wb = text_w(d, a, f), text_w(d, b, f)
    gap, bar = int(18 * s), int(3 * s)
    x = cx - (wa + gap * 2 + bar + wb) / 2
    d.text((x, y), a, font=f, fill=INK)
    x += wa + gap
    d.rectangle((x, y + int(4 * s), x + bar, y + f.getbbox("H")[3]), fill=(138, 180, 233))
    x += bar + gap
    d.text((x, y), b, font=font(FB, int(42 * s)), fill=BLUE)


def badge(base, cx, cy, cb, s):
    """Cashback focal pill: big value + small 'CASHBACK' label, blue, drop shadow.
    The two-line text block is measured and centred so the padding is symmetric."""
    d = ImageDraw.Draw(base)
    big = font(FB, int(108 * s))
    lab = font(FB, int(31 * s))
    val = cb or "Cashback"
    label = "CASHBACK"
    vb, lb = big.getbbox(val), lab.getbbox(label)
    vw, vh = text_w(d, val, big), vb[3] - vb[1]
    lw, lh = text_w(d, label, lab), lb[3] - lb[1]
    gap = int(10 * s)
    pad_x, pad_y = int(76 * s), int(46 * s)
    block_h = vh + gap + lh
    w = int(max(vw, lw) + pad_x * 2)
    h = int(block_h + pad_y * 2)
    x0, y0 = int(cx - w / 2), int(cy - h / 2)
    # shadow
    sh = Image.new("RGBA", base.size, (0, 0, 0, 0))
    ImageDraw.Draw(sh).rounded_rectangle((x0, y0 + int(8 * s), x0 + w, y0 + h + int(8 * s)),
                                         radius=h // 2, fill=(10, 22, 80, 110))
    sh = sh.filter(ImageFilter.GaussianBlur(int(12 * s)))
    base.paste(sh, (0, 0), sh)
    d.rounded_rectangle((x0, y0, x0 + w, y0 + h), radius=h // 2, fill=BLUE)
    d.text((cx - vw / 2, y0 + pad_y - vb[1]), val, font=big, fill=WHITE)
    d.text((cx - lw / 2, y0 + pad_y + vh + gap - lb[1]), label, font=lab, fill=(176, 197, 255))


def cta(base, cx, cy, s, txt="Tilmeld dig gratis"):
    """Text-hugging CTA pill (used by the collection cover)."""
    d = ImageDraw.Draw(base)
    f = font(FB, int(42 * s))
    tw = text_w(d, txt, f)
    bb = f.getbbox(txt)
    th = bb[3] - bb[1]
    w, h = int(tw + 104 * s), int(96 * s)
    d.rounded_rectangle((cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2), radius=h // 2, fill=BLUE)
    d.text((cx - tw / 2, cy - th / 2 - bb[1]), txt, font=f, fill=WHITE)


def _chip_shadow(base, x0, y0, chip_w, chip_h, rad, s):
    sh = Image.new("RGBA", base.size, (0, 0, 0, 0))
    ImageDraw.Draw(sh).rounded_rectangle((x0, y0 + int(10 * s), x0 + chip_w, y0 + chip_h + int(10 * s)),
                                         radius=rad, fill=(10, 22, 80, 95))
    sh = sh.filter(ImageFilter.GaussianBlur(int(15 * s)))
    base.paste(sh, (0, 0), sh)


def logo_chip(base, p, cx, cy, maxw, maxh, s, shadow=False):
    """A rounded chip that HUGS the logo (so the logo reads big regardless of its
    aspect ratio): white panel for dark logos, blue for light logos. `shadow=True`
    floats it over the hero photo. Bold name fallback if the logo is missing."""
    logo = download(bump(p.get("logo"), 700))
    d = ImageDraw.Draw(base)
    pad = int(40 * s)
    rad = int(30 * s)
    if logo is not None:
        logo = trim_alpha(logo)
        lg = fit_up(logo, int(maxw), int(maxh))
        lw_, lh_ = lg.size
        chip_w, chip_h = lw_ + pad * 2, lh_ + pad * 2
        x0, y0 = int(cx - chip_w / 2), int(cy - chip_h / 2)
        if shadow:
            _chip_shadow(base, x0, y0, chip_w, chip_h, rad, s)
        chip_bg = BLUE if mean_lum(logo) > 200 else WHITE
        d.rounded_rectangle((x0, y0, x0 + chip_w, y0 + chip_h), radius=rad, fill=chip_bg)
        base.paste(lg, (int(cx - lw_ / 2), int(cy - lh_ / 2)), lg)
    else:
        f = font(FB, int(64 * s))
        name = p.get("n") or ""
        tw = text_w(d, name, f)
        chip_w, chip_h = int(tw + 80 * s), int(108 * s)
        x0, y0 = int(cx - chip_w / 2), int(cy - chip_h / 2)
        if shadow:
            _chip_shadow(base, x0, y0, chip_w, chip_h, rad, s)
        d.rounded_rectangle((x0, y0, x0 + chip_w, y0 + chip_h), radius=rad, fill=WHITE)
        ctext(d, cx, cy - f.getbbox("Hg")[3] / 2, name, f, INK)


def cta_wide(base, cy, s, w, bh, txt="Tilmeld dig gratis", side=0.10):
    """Big, very-rounded, wide Visa-blue CTA (styled after the endcard's
    'Hent appen gratis' button). Width adapts to the card; `bh` sets the height;
    text scales to the button height and auto-fits the width."""
    d = ImageDraw.Draw(base)
    x0, x1 = int(w * side), int(w * (1 - side))
    bw = x1 - x0
    y0, y1 = int(cy - bh / 2), int(cy + bh / 2)
    d.rounded_rectangle((x0, y0, x1, y1), radius=bh // 2, fill=BLUE)
    fs = int(bh * 0.40)
    f = font(FB, fs)
    while text_w(d, txt, f) > bw - int(70 * s) and fs > 22:
        fs -= 2
        f = font(FB, fs)
    bb = f.getbbox(txt)
    d.text((w / 2 - text_w(d, txt, f) / 2, cy - (bb[3] - bb[1]) / 2 - bb[1]), txt, font=f, fill=WHITE)


def value_tokens(brand):
    """Tokens for 'Få cashback hos <brand-bold>, og i 2000+ andre butikker'.
    Each token = [word, is_bold, space_before]."""
    toks = []

    def add(text, bold, lead):
        for i, wd in enumerate(text.split(" ")):
            if wd:
                toks.append([wd, bold, lead if i == 0 else True])

    add("Få cashback hos", False, False)
    add(brand or "os", True, True)
    toks.append([",", False, False])               # comma hugs the brand
    add("og i 2000+ andre butikker", False, True)
    return toks


def draw_rich(base, cx, y, line_h, toks, fr_, fb_, maxw, fill, maxlines=2):
    """Centre-wrapped mixed-weight text. toks = [[word, is_bold, space_before], ...]."""
    d = ImageDraw.Draw(base)
    fonts = {True: fb_, False: fr_}
    sp = d.textlength(" ", font=fr_)
    for t in toks:
        t.append(d.textlength(t[0], font=fonts[t[1]]))     # t[3] = word width
    lines, cur, cur_w = [], [], 0
    for t in toks:
        add_w = (sp if (cur and t[2]) else 0) + t[3]
        if cur and cur_w + add_w > maxw and len(lines) < maxlines - 1:
            lines.append(cur)
            cur, cur_w = [t], t[3]
        else:
            cur.append(t)
            cur_w += add_w
    if cur:
        lines.append(cur)
    for li, line in enumerate(lines):
        tot = sum((sp if (i and t[2]) else 0) + t[3] for i, t in enumerate(line))
        x = cx - tot / 2
        yy = y + li * line_h
        for i, t in enumerate(line):
            if i and t[2]:
                x += sp
            d.text((x, yy), t[0], font=fonts[t[1]], fill=fill)
            x += t[3]


DISC = ("Programmet er drevet af Loyalty Key A/S. Med cashback optjener du 1-40 % af det betalte "
        "beløb hos udvalgte forretninger, når du betaler med Visa. Brugerbetingelser gælder.")


def disclaimer(base, w, h, s):
    """Tiny legal line pinned to the bottom edge of every card."""
    d = ImageDraw.Draw(base)
    f = font(FR, int(17 * s))
    lh = int(22 * s)
    lines = wrap(d, DISC, f, w - int(70 * s), maxlines=3)
    y = h - int(22 * s) - len(lines) * lh
    for i, ln in enumerate(lines):
        ctext(d, w / 2, y + i * lh, ln, f, (170, 178, 200))


# ---- partner card ------------------------------------------------------------
# No per-card CTA: in Collection/Carousel ads Meta renders one large CTA button
# below the grid, so the cards are just photo + logo + cashback + value + disclaimer.
HERO_FRAC = {"1x1": 0.62, "4x5": 0.64, "9x16": 0.68}
VALUE_FS = {"1x1": 40, "4x5": 46, "9x16": 56}          # value line gets bigger on taller cards


def render_card(p, ratio):
    w, h = metalib.RATIOS[ratio]
    s = w / 1080.0
    base = Image.new("RGB", (w, h), WHITE)
    d = ImageDraw.Draw(base)
    margin = int(28 * s)

    # hero photo band (rounded)
    hero_h = int(h * HERO_FRAC[ratio])
    hero = download(bump(p.get("hero2x"), 1080)) or download(bump(p.get("hero"), 1080))
    if hero is not None:
        paste_rounded(base, hero, (margin, margin, w - 2 * margin, hero_h - margin), int(36 * s))
    else:
        d.rounded_rectangle((margin, margin, w - margin, hero_h - margin), radius=int(36 * s), fill=PANEL)

    # large partner logo on the hero (no 'cashback med VISA' label)
    hero_zone = hero_h - margin
    logo_chip(base, p, w / 2, margin + int(hero_zone * 0.50),
              int(w * 0.74), int(hero_zone * 0.54), s, shadow=True)

    # white block: big cashback pill (straddles photo) -> value line -> tiny disclaimer
    lower_top = hero_h
    lower_h = h - lower_top

    badge(base, w / 2, lower_top + int(lower_h * 0.12), p.get("cb") or "Cashback", s)

    fs = VALUE_FS[ratio]
    fr_ = font(FR, int(fs * s))
    fb_ = font(FB, int(fs * s))
    sub_y = lower_top + int(lower_h * 0.52)
    line_h = int((fs + 13) * s)
    draw_rich(base, w / 2, sub_y, line_h, value_tokens(p.get("n") or ""),
              fr_, fb_, w - int(96 * s), GREY)

    disclaimer(base, w, h, s)
    return base


# ---- collection cover --------------------------------------------------------
COVER_TITLE = {"highest": "Højeste cashback", "popular": "Mest populære"}


def render_cover(tier, partners, ratio):
    """Collection-ad cover in the light-blue endcard style: 'Cashback | VISA'
    header + the two-tone 'Få penge tilbage i +2.000 butikker' headline. Meta
    renders the product grid + the large CTA button below this cover."""
    w, h = metalib.RATIOS[ratio]
    s = w / 1080.0
    base = Image.new("RGB", (w, h), LBLUE)
    d = ImageDraw.Draw(base)

    # 'Cashback | VISA' header — muted 'Cashback', blue 'VISA', centred
    f = font(FB, int(52 * s))
    a, b = "Cashback", "VISA"
    wa, wb = text_w(d, a, f), text_w(d, b, f)
    gap, bar = int(26 * s), int(4 * s)
    hy = int(h * 0.12)
    x = w / 2 - (wa + gap * 2 + bar + wb) / 2
    d.text((x, hy), a, font=f, fill=MUTED)
    x += wa + gap
    d.rectangle((x, hy + int(8 * s), x + bar, hy + f.getbbox("H")[3]), fill=MUTED)
    x += bar + gap
    d.text((x, hy), b, font=font(FB, int(54 * s)), fill=BLUE)

    # two-tone headline (blue line + near-black line)
    hf = font(FB, int(100 * s))
    cy = int(h * (0.34 if ratio == "9x16" else 0.40))
    lh = int(112 * s)
    ctext(d, w / 2, cy, "Få penge tilbage", hf, BLUE)
    ctext(d, w / 2, cy + lh, "i +2.000 butikker", hf, INKD)

    # tier label (distinguishes the two covers)
    ctext(d, w / 2, cy + lh * 2 + int(22 * s), COVER_TITLE.get(tier, ""),
          font(FB, int(40 * s)), MUTED)
    return base


# ---- driver ------------------------------------------------------------------
def save(img, name):
    out = os.path.join(_IMG, name)
    img.save(out, "JPEG", quality=90, optimize=True)
    return out


def main():
    with open(os.path.join(_FEED, "partners-all.json"), encoding="utf-8") as f:
        partners = json.load(f)["partners"]
    with open(os.path.join(_FEED, "partners.json"), encoding="utf-8") as f:
        sets = json.load(f)

    expected = set()
    manifest = []
    rendered = skipped = 0
    for p in partners:
        imgs = {}
        for ratio in metalib.RATIOS:
            name = metalib.img_name(p, ratio)
            imgs[ratio] = name
            expected.add(name)
            out = os.path.join(_IMG, name)
            if os.path.exists(out):
                skipped += 1
                continue
            save(render_card(p, ratio), name)
            rendered += 1
        tier = "highest" if p.get("inHighest") else ("popular" if p.get("inPopular") else "catalog")
        manifest.append({"n": p.get("n"), "cb": p.get("cb"), "cat": p.get("cat"),
                         "tier": tier, "imgs": imgs})
        print(f"  card {p.get('n','?')[:28]:<28} {p.get('cb') or '-':>7}")

    covers = {}
    for tier in ("highest", "popular"):
        covers[tier] = {}
        for ratio in ("1x1", "9x16"):
            name = metalib.cover_name(tier, ratio)
            expected.add(name)
            covers[tier][ratio] = name
            save(render_cover(tier, sets.get(tier, []), ratio), name)
    print(f"covers: highest + popular  (1x1 + 9x16)")

    # preview manifest consumed by _preview.html (local filenames, no hashing in JS)
    with open(os.path.join(_IMG, "preview.json"), "w", encoding="utf-8") as f:
        json.dump({"partners": manifest, "covers": covers}, f, ensure_ascii=False, indent=1)

    # prune stale images no longer referenced by the current feed
    pruned = 0
    for fn in os.listdir(_IMG):
        if fn.endswith(".jpg") and fn not in expected:
            os.remove(os.path.join(_IMG, fn))
            pruned += 1

    biggest = max((os.path.getsize(os.path.join(_IMG, fn)) for fn in os.listdir(_IMG)
                   if fn.endswith(".jpg")), default=0)
    print(f"\nimages: {len(expected)} expected  ({rendered} rendered, {skipped} cached, "
          f"{pruned} pruned)  biggest={biggest // 1024} KB  CDN_BASE={metalib.CDN_BASE}")


if __name__ == "__main__":
    main()
