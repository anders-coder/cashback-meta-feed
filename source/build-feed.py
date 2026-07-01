#!/usr/bin/env python3
"""
build-feed.py - Fetch the Cashbackmedvisa partner data from the website's
SvelteKit data endpoint, decode the devalue format, and emit a Meta-spec
product catalog feed plus the JSON the image builder consumes:

  ../feed/catalog.csv       Meta scheduled product feed (primary; one row/partner)
  ../feed/catalog.xml       Meta product feed, RSS 2.0 + g: namespace (secondary)
  ../feed/partners.json     curated highest/popular sets (drives build-images.py)
  ../feed/partners-all.json full pool with tier flags

Run:  cd source && python3 build-feed.py
No third-party deps (urllib + stdlib json only). Shares metalib.py with build-images.py.
"""
import json, re, ssl, sys, os, csv, html, urllib.request, urllib.parse, datetime
from xml.sax.saxutils import escape as xml_escape
import metalib

# Path-robust: works in the source/ tree (writes ../feed) OR a flat feed-only repo
# (build-feed.py + curate.json + feed/ at the root, e.g. the public hosting repo).
_HERE = os.path.dirname(os.path.abspath(__file__))
_FEED = os.path.join(_HERE, "..", "feed")
if not os.path.isdir(_FEED):
    _FEED = os.path.join(_HERE, "feed")
    os.makedirs(_FEED, exist_ok=True)


def _h(name):
    return os.path.join(_HERE, name)


def _f(name):
    return os.path.join(_FEED, name)

SRC = "https://cashbackmedvisa.dk/se-partnere/__data.json"
# Webshop feeds: the site's own curated highest-cashback / popular / latest lists
ESHOP = "https://cashbackmedvisa.dk/eshop/__data.json"
ESHOP_DETAIL = "https://cashbackmedvisa.dk/eshop/butikker/"
# Physical-store name search (used to resolve handpicked brands not in the webshop feeds)
SEARCH = "https://cashbackmedvisa.dk/find-partnere/__data.json?filter[name]="
RESIZER = "https://images.loyaltykey.com/cashbackapi/"
CARD_W = 400      # hero width for carousel cards
MODAL_W = 640     # hero width for the modal
LOGO_W = 160
TOP_N = 15        # per carousel in partners.json
POP_TARGET = 12   # min cards in handpicked "popular" (auto-fill if pins go offline)
FALLBACK_N = 8    # per carousel baked into the creative

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")


def fetch(url):
    req = urllib.request.Request(url, headers={
        "User-Agent": UA,
        "Accept": "application/json,text/plain,*/*",
        "Accept-Language": "da-DK,da;q=0.9,en;q=0.8",
    })
    last = None
    for attempt in range(3):
        try:
            ctx = ssl.create_default_context()
            return urllib.request.urlopen(req, timeout=15, context=ctx).read().decode("utf-8")
        except Exception as e:
            last = e
            try:
                ctx = ssl._create_unverified_context()
                return urllib.request.urlopen(req, timeout=15, context=ctx).read().decode("utf-8")
            except Exception as e2:
                last = e2
    raise SystemExit(f"fetch failed after retries: {last}")


# ---- devalue (SvelteKit __data.json) decoder ---------------------------------
# A node's `data` is a flat array. Index 0 is the root. Integers inside arrays
# and object values are references (indices) back into the flat array. A bare
# string/number/bool/null at a slot is a literal. Negative ints are specials.
SPECIALS = {-1: None, -2: None, -3: float("nan"), -4: float("inf"),
            -5: float("-inf"), -6: -0.0, -7: None}


def make_deref(flat):
    cache = {}

    def deref(idx, _stack):
        if isinstance(idx, int):
            if idx < 0:
                return SPECIALS.get(idx, None)
            if idx in cache:
                return cache[idx]
            if idx in _stack:           # cycle guard
                return None
            v = flat[idx]
            _stack = _stack | {idx}
            if isinstance(v, list):
                if v and isinstance(v[0], str):
                    # typed value e.g. ["Date", i] / ["Set", ...] -> best effort
                    if len(v) == 2 and isinstance(v[1], int):
                        out = deref(v[1], _stack)
                    else:
                        out = [deref(x, _stack) for x in v[1:]]
                else:
                    out = [deref(x, _stack) for x in v]
            elif isinstance(v, dict):
                out = {k: deref(val, _stack) for k, val in v.items()}
            else:
                out = v
            cache[idx] = out
            return out
        return idx

    return lambda i: deref(i, frozenset())


def decode(raw):
    doc = json.loads(raw)
    nodes = doc.get("nodes", [])
    for node in nodes:
        if isinstance(node, dict) and isinstance(node.get("data"), list):
            flat = node["data"]
            root = make_deref(flat)(0)
            if isinstance(root, dict) and ("sectionsMiddle" in root or "sectionsTop" in root):
                return root
    # fallback: last node with data
    for node in reversed(nodes):
        if isinstance(node, dict) and isinstance(node.get("data"), list):
            return make_deref(node["data"])(0)
    raise SystemExit("could not locate partner data node")


# ---- field extraction --------------------------------------------------------
def g(d, *path, default=None):
    cur = d
    for p in path:
        if isinstance(cur, dict) and p in cur:
            cur = cur[p]
        else:
            return default
    return cur if cur is not None else default


def hero_url(raw, width, fmt="jpg"):
    # NOTE: the resizer returns AVIF whenever the client Accept header allows it,
    # EVEN with quality= set. Only &format=jpg|png reliably forces a format.
    # We force jpg for heroes (max WebView compatibility) and png for logos (alpha).
    if not raw or not isinstance(raw, str):
        return ""
    m = re.search(r"(locations/images/[^?\s]+\.(?:jpg|jpeg|png|webp|avif))", raw, re.I)
    path = ("cashbackapi/" + m.group(1)) if m else None
    if not path:
        return ""
    return ("https://images.loyaltykey.com/" + path +
            "?quality=85&width=" + str(width) + "&format=" + fmt)


def strip_html(s):
    if not s or not isinstance(s, str):
        return ""
    s = re.sub(r"<[^>]+>", " ", s)
    s = html.unescape(s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def clip(s, n=240):
    s = (s or "").strip()
    if len(s) <= n:
        return s
    return s[:n].rsplit(" ", 1)[0].rstrip(" ,.;:-") + "…"


def parse_location(loc):
    """Build our compact card entry from a raw location object (same shape in
    both the /se-partnere sections and the /find-partnere catalog search)."""
    rate = g(loc, "rewards", "standard", "rate")
    enabled = g(loc, "rewards", "standard", "enabled", default=True)
    fv = g(loc, "rewards", "first_visit", "rate")
    fv_en = g(loc, "rewards", "first_visit", "enabled", default=False)
    return {
        "id": loc.get("uuid") or loc.get("id"),
        "slug": g(loc, "slug", default="") or g(loc, "brand", "slug", default="") or "",
        "n": g(loc, "name", default="") or g(loc, "brand", "name", default=""),
        "cat": g(loc, "category", "name", default="") or g(loc, "type", default=""),
        "type": g(loc, "type", default=""),
        "pct": int(rate) if (enabled and isinstance(rate, (int, float))) else None,
        "cb": (f"{int(rate)} %" if (enabled and isinstance(rate, (int, float)) and rate) else ""),
        "pctfv": int(fv) if (fv_en and isinstance(fv, (int, float))) else None,
        "hero": hero_url(g(loc, "images", "hero"), CARD_W),
        "hero2x": hero_url(g(loc, "images", "hero"), MODAL_W),
        "logo": hero_url(g(loc, "images", "logo"), LOGO_W, "png") or hero_url(g(loc, "images", "alt_logo"), LOGO_W, "png"),
        "loc": g(loc, "cashback_location_type", "value", default=""),
        "note": g(loc, "cashback_location_type", "description", default="") or "",
        "foll": g(loc, "brand", "follows_count", default=0) or 0,
        "desc": clip(g(loc, "short_description", default="") or strip_html(g(loc, "description", default=""))),
        "url": g(loc, "url", default=""),
        "_sections": set(),
        "_prio": 9999,
        "_order": 0,
    }


def collect(root):
    sections = root.get("sectionsMiddle")
    if isinstance(sections, dict) and isinstance(sections.get("data"), list):
        sections = sections["data"]
    if not isinstance(sections, list):
        sections = []

    by_uuid = {}
    order = 0
    for si, sec in enumerate(sections):
        if not isinstance(sec, dict):
            continue
        stype = sec.get("type")
        sname = sec.get("name") or ""
        prio = sec.get("priority", si)
        locs = sec.get("locations")
        if isinstance(locs, dict) and isinstance(locs.get("data"), list):
            locs = locs["data"]
        if not isinstance(locs, list):
            continue
        for loc in locs:
            if not isinstance(loc, dict):
                continue
            uuid = loc.get("uuid") or loc.get("id")
            if not uuid:
                continue
            entry = by_uuid.get(uuid)
            if entry is None:
                entry = parse_location(loc)
                entry["_order"] = order
                order += 1
                by_uuid[uuid] = entry
            entry["_sections"].add(sname)
            entry["_prio"] = min(entry["_prio"], prio if isinstance(prio, (int, float)) else si)
    return list(by_uuid.values())


POP_BOOST = ("Populære", "Popul", "Nyheder")


def pop_score(p):
    boost = 0
    for s in p["_sections"]:
        if any(k.lower() in (s or "").lower() for k in POP_BOOST):
            boost += 1_000_000
    return (boost + (p["foll"] or 0), -(p["_prio"] or 0))


def is_restaurant(cat):
    c = (cat or "").lower()
    return any(k in c for k in ("restaurant", "café", "cafe", "spise", "mad"))


def balanced_popular(partners, n, max_per_cat=3, restaurant_cap=2):
    """Popularity-driven (follower counts) but capped per category so retail,
    mode, skønhed, elektronik etc. get represented instead of a wall of
    restaurants. Falls back to ignoring caps if too few qualify."""
    ranked = sorted(partners, key=pop_score, reverse=True)
    out, counts = [], {}
    for p in ranked:
        cat = p["cat"] or "?"
        cap = restaurant_cap if is_restaurant(cat) else max_per_cat
        if counts.get(cat, 0) >= cap:
            continue
        out.append(p)
        counts[cat] = counts.get(cat, 0) + 1
        if len(out) >= n:
            return out
    seen = {p["id"] for p in out}
    for p in ranked:
        if p["id"] not in seen:
            out.append(p)
            if len(out) >= n:
                break
    return out


def public(p):
    return {k: p.get(k) for k in ("id", "slug", "n", "cat", "pct", "cb", "pctfv", "hero", "hero2x",
                                  "logo", "loc", "note", "foll", "desc", "url")}


# ---- handpicking / curation --------------------------------------------------
# "Hard" unicode whitespace that rich-text editors (Docs/TextEdit) inject into the
# indentation: NBSP, en/em/thin spaces, ideographic space, BOM/ZWNBSP. These are
# invalid JSON whitespace and would crash json.load — normalize them to a plain space.
_BAD_WS = re.compile("[   -   　﻿]")


def _load_json_lenient(path):
    with open(path, encoding="utf-8-sig") as f:      # utf-8-sig also strips a leading BOM
        text = f.read()
    fixed = _BAD_WS.sub(" ", text)
    if fixed != text:
        print(f"  NOTE: normalized {len(_BAD_WS.findall(text))} non-standard "
              f"whitespace char(s) in {os.path.basename(path)} (invalid JSON) — "
              "edit it in a plain-text editor to avoid this.")
    return json.loads(fixed)


def load_curate():
    """curate.json lets you override the automatic ranking. Match partners by
    `slug` (preferred, stable) or exact name. All keys are optional:
      { "exclude": [...], "pin_highest": [...], "pin_popular": [...] }
    Pinned partners appear first (in the order listed); the rest auto-fills."""
    try:
        c = _load_json_lenient(_h("curate.json"))
    except FileNotFoundError:
        return {"exclude": [], "pin_highest": [], "pin_popular": []}
    return {
        "exclude": [str(x).strip().lower() for x in c.get("exclude", []) if str(x).strip()],
        "pin_highest": [str(x).strip() for x in c.get("pin_highest", []) if str(x).strip()],
        "pin_popular": [str(x).strip() for x in c.get("pin_popular", []) if str(x).strip()],
    }


def key_match(p, k):
    k = k.strip().lower()
    return bool(k) and (k == (p.get("slug") or "").lower() or k == (p["n"] or "").lower())


def find_partner(partners, k):
    for p in partners:                       # exact slug / exact name only
        if key_match(p, k):
            return p
    return None


def merge(pins, auto, n):
    seen, out = set(), []
    for p in list(pins) + list(auto):
        if not p or p["id"] in seen:
            continue
        seen.add(p["id"])
        out.append(p)
        if len(out) >= n:
            break
    return out


def fetch_soft(url):
    try:
        return fetch(url)
    except BaseException:
        return None


def resolve_by_name(name):
    """Resolve a pinned brand from the FULL catalog via /find-partnere search.
    Returns the best-matching parsed partner, or None."""
    raw = fetch_soft(SEARCH + urllib.parse.quote(name))
    if not raw:
        return None
    try:
        doc = json.loads(raw)
    except Exception:
        return None
    root = None
    for node in doc.get("nodes", []):
        if isinstance(node, dict) and isinstance(node.get("data"), list):
            r = make_deref(node["data"])(0)
            if isinstance(r, dict) and "locations" in r:
                root = r
                break
    if not root:
        return None
    locs = root.get("locations")
    if isinstance(locs, dict):
        locs = locs.get("data")
    if not isinstance(locs, list):
        return None
    parsed = [parse_location(l) for l in locs
              if isinstance(l, dict) and (l.get("uuid") or l.get("id"))]
    if not parsed:
        return None
    norm = lambda s: re.sub(r"[^a-z0-9]", "", (s or "").lower())
    nq = norm(name)
    for p in parsed:                         # exact (ignoring spaces/punct)
        if nq and norm(p["n"]) == nq:
            return p
    if len(nq) >= 4:                         # only fuzzy-match longer queries
        for p in parsed:
            if norm(p["n"]).startswith(nq) or nq in norm(p["n"]):
                return p
    return None                              # short/ambiguous -> report not found


_norm = lambda s: re.sub(r"[^a-z0-9]", "", (s or "").lower())


def find_local(pool, name):
    """Match a brand name against an in-memory pool by normalized name/slug:
    exact first, then prefix, then contains (len>=3). Small/curated pools only."""
    nq = _norm(name)
    if not nq:
        return None
    for p in pool:
        if _norm(p["n"]) == nq or _norm(p.get("slug")) == nq:
            return p
    for p in pool:
        if _norm(p["n"]).startswith(nq):
            return p
    if len(nq) >= 3:
        for p in pool:
            if nq in _norm(p["n"]):
                return p
    return None


def parse_shop(s, catmap):
    """Build our compact card entry from a /eshop webshop object (schema differs
    from the location schema: customer_commission + currency, logo, background_image)."""
    cur = s.get("currency") or ""
    comm = s.get("customer_commission")
    pct = int(comm) if (cur == "%" and isinstance(comm, (int, float)) and comm) else None
    if pct:
        cb = f"{pct} %"
    elif isinstance(comm, (int, float)) and comm and cur in ("DKK", "kr"):
        cb = f"{int(comm)} kr"
    else:
        cb = s.get("fixed_cashback_text") or ""
    slug = s.get("slug") or ""
    uuid = s.get("uuid")
    return {
        "id": uuid,
        "slug": slug,
        "n": s.get("name") or "",
        "cat": catmap.get(s.get("categoryId"), "Webshop"),
        "type": "webshop",
        "pct": pct,
        "cb": cb,
        "pctfv": None,
        "hero": hero_url(s.get("background_image"), CARD_W),
        "hero2x": hero_url(s.get("background_image"), MODAL_W),
        "logo": hero_url(s.get("logo"), LOGO_W, "png"),
        "loc": "online",
        "note": "",
        "foll": 0,
        "desc": clip(strip_html(s.get("description"))),
        "url": (ESHOP_DETAIL + slug + "/" + uuid) if (slug and uuid) else "",
        "_sections": set(),
        "_prio": 9999,
        "_order": 0,
    }


def fetch_eshop():
    """Fetch the webshop landing data: site-curated highest/popular/latest lists."""
    doc = json.loads(fetch(ESHOP))
    root = None
    for node in doc.get("nodes", []):
        if isinstance(node, dict) and isinstance(node.get("data"), list):
            r = make_deref(node["data"])(0)
            if isinstance(r, dict) and "shops_popular" in r:
                root = r
                break
    if not root:
        raise SystemExit("could not load /eshop webshop data")

    def lst(key):
        v = root.get(key)
        if isinstance(v, dict):
            v = v.get("data")
        return v if isinstance(v, list) else []

    catmap = {c.get("id"): c.get("name") for c in lst("categories") if isinstance(c, dict)}
    parse = lambda key: [parse_shop(s, catmap) for s in lst(key) if isinstance(s, dict)]
    return {"highest": parse("shops_highest_cashback"),
            "popular": parse("shops_popular"),
            "latest": parse("shops_latest"),
            "catmap": catmap}


UUID_RE = r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"


def resolve_eshop_link(url, catmap):
    """Resolve a webshop from a /eshop/butikker/<slug>/<uuid> link (authoritative)."""
    m = re.search(r"/eshop/butikker/([^/?#]+)/(" + UUID_RE + ")", url)
    if not m:
        return None
    slug, uuid = m.group(1), m.group(2)
    raw = fetch_soft(f"https://cashbackmedvisa.dk/eshop/butikker/{slug}/{uuid}/__data.json")
    if not raw:
        return None
    try:
        doc = json.loads(raw)
    except Exception:
        return None
    for node in doc.get("nodes", []):
        if isinstance(node, dict) and isinstance(node.get("data"), list):
            r = make_deref(node["data"])(0)
            if isinstance(r, dict) and "shopData" in r:
                data = r["shopData"]
                if isinstance(data, dict):
                    data = data.get("data")
                shop = data[0] if (isinstance(data, list) and data and isinstance(data[0], dict)) \
                    else (data if isinstance(data, dict) else None)
                if isinstance(shop, dict) and shop.get("uuid"):
                    return parse_shop(shop, catmap)
    return None


def resolve_location_uuid(uuid):
    """Resolve a physical-store partner by its location-uuid (e.g. from a card link)."""
    for base in (SRC, SEARCH.split("?")[0]):
        raw = fetch_soft(base + "?location-uuid=" + uuid)
        if not raw:
            continue
        try:
            doc = json.loads(raw)
        except Exception:
            continue
        for node in doc.get("nodes", []):
            if isinstance(node, dict) and isinstance(node.get("data"), list):
                r = make_deref(node["data"])(0)
                found = [None]

                def scan(o):
                    if found[0] is not None:
                        return
                    if isinstance(o, dict):
                        if o.get("uuid") == uuid and ("rewards" in o or "images" in o):
                            found[0] = o
                            return
                        for v in o.values():
                            scan(v)
                    elif isinstance(o, list):
                        for x in o[:80]:
                            scan(x)

                scan(r)
                if found[0]:
                    return parse_location(found[0])
    return None


# ---- Meta product feed -------------------------------------------------------
# One row per partner brand. Meta's e-commerce catalog requires id/title/
# description/availability/condition/price/link/image_link + one of brand/gtin/mpn
# (we use brand). A partner has no price -> price="0.00 DKK" (spec-valid) and the
# price element is turned OFF in the ad creative template; the real cashback value
# lives in the baked image badge and custom_label_1.
META_COLS = ["id", "title", "description", "availability", "condition", "price",
             "link", "image_link", "additional_image_link", "brand", "product_type",
             "custom_label_0", "custom_label_1", "custom_label_2",
             "custom_label_3", "custom_label_4"]


def _link(p):
    # Every link MUST stay on cashbackmedvisa.dk. Webshop partners already carry a
    # /eshop/butikker/<slug>/<uuid> URL; physical-store partners sometimes carry the
    # brand's OWN external site (e.g. https://www.synoptik.dk/) — rewrite those to a
    # find-partnere search so the click lands on the cashback page, not the shop.
    u = (p.get("url") or "").strip()
    if u.startswith("/"):
        u = "https://cashbackmedvisa.dk" + u
    host = urllib.parse.urlparse(u).netloc.lower()
    if u.startswith("https://") and (host == "cashbackmedvisa.dk"
                                     or host.endswith(".cashbackmedvisa.dk")):
        return u
    # Fallback: search find-partnere by brand name ("Synoptik.dk" -> "Synoptik").
    # No filter[type] -> the page opens on the "Alle" tab so every match (butikker
    # AND webshops) shows; filtering to a single type could hide relevant results.
    q = re.sub(r"\.dk$", "", (p.get("n") or "").strip(), flags=re.I).strip()
    if q:
        return "https://cashbackmedvisa.dk/find-partnere?filter[s]=" + urllib.parse.quote(q)
    return "https://cashbackmedvisa.dk/"


def meta_row(p, tier):
    n = (p.get("n") or "").strip()
    cb = (p.get("cb") or "").strip()
    title = (f"{n} — {cb} cashback" if cb else f"{n} — cashback med Visa")[:150]
    desc = (p.get("desc") or "").strip() or f"Optjen {cb or 'cashback'} hos {n} med dit Visa-kort."
    if p.get("pctfv"):
        desc = f"{desc} Ny kunde: +{p['pctfv']} %."
    pct = p.get("pct")
    return {
        "id": (p.get("id") or metalib.img_base(p))[:100],
        "title": title,
        "description": desc[:5000],
        "availability": "in stock",
        "condition": "new",
        "price": "0.00 DKK",
        "link": _link(p),
        "image_link": metalib.img_url(p, "1x1"),
        "additional_image_link": [metalib.img_url(p, "4x5"), metalib.img_url(p, "9x16")],
        "brand": n[:100],
        "product_type": (p.get("cat") or "")[:750],
        "custom_label_0": tier,                  # highest | popular | catalog (drives product sets)
        "custom_label_1": cb,                    # "5 %" / "300 kr"
        "custom_label_2": (p.get("cat") or ""),
        "custom_label_3": (p.get("loc") or ""),  # online | physical
        "custom_label_4": (f"{int(pct):02d}" if isinstance(pct, (int, float)) else "00"),
    }


def build_meta_rows(universe, hid, pid):
    seen, rows = set(), []
    for p in universe:
        pidv = p.get("id")
        if not pidv or pidv in seen:
            continue
        seen.add(pidv)
        tier = "highest" if pidv in hid else ("popular" if pidv in pid else "catalog")
        rows.append(meta_row(p, tier))
    return rows


_PRICE_RE = re.compile(r"^\d+\.\d{2} [A-Z]{3}$")


def validate_rows(rows):
    req = ("id", "title", "description", "availability", "condition", "price",
           "link", "image_link", "brand")
    errs, seen = [], set()
    for r in rows:
        for k in req:
            if not str(r.get(k) or "").strip():
                errs.append(f"{r.get('id')}: missing required '{k}'")
        if r["id"] in seen:
            errs.append(f"duplicate id '{r['id']}'")
        seen.add(r["id"])
        if not _PRICE_RE.match(r["price"]):
            errs.append(f"{r['id']}: bad price '{r['price']}'")
        for k in ("link", "image_link"):
            if not str(r.get(k, "")).startswith("https://"):
                errs.append(f"{r['id']}: {k} not https")
        if r["availability"] not in ("in stock", "out of stock"):
            errs.append(f"{r['id']}: bad availability")
        if r["condition"] not in ("new", "refurbished", "used"):
            errs.append(f"{r['id']}: bad condition")
        if len(r["title"]) > 150:
            errs.append(f"{r['id']}: title > 150 chars")
        if len(r["brand"]) > 100:
            errs.append(f"{r['id']}: brand > 100 chars")
    if errs:
        for e in errs[:30]:
            print("  FEED ERROR:", e)
        raise SystemExit(f"feed validation failed: {len(errs)} error(s)")


def write_meta_csv(rows, path):
    with open(path, "w", newline="", encoding="utf-8") as f:      # UTF-8, no BOM
        w = csv.writer(f)
        w.writerow(META_COLS)
        for r in rows:
            w.writerow([",".join(r[c]) if isinstance(r[c], list) else r[c]
                        for c in META_COLS])


def write_meta_xml(rows, path, title):
    def el(tag, val):
        return f"    <g:{tag}>{xml_escape(str(val))}</g:{tag}>"
    out = ['<?xml version="1.0" encoding="utf-8"?>',
           '<rss version="2.0" xmlns:g="http://base.google.com/ns/1.0">',
           "  <channel>",
           f"    <title>{xml_escape(title)}</title>",
           "    <link>https://cashbackmedvisa.dk/</link>",
           f"    <description>{xml_escape(title)}</description>"]
    for r in rows:
        out.append("  <item>")
        for c in META_COLS:
            if c == "additional_image_link":          # repeat the tag per URL (RSS convention)
                for u in r[c]:
                    out.append(el(c, u))
            else:
                out.append(el(c, r[c]))
        out.append("  </item>")
    out += ["  </channel>", "</rss>", ""]
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(out))


def main():
    cur = load_curate()
    excl = set(cur["exclude"])

    # --- primary source: site-curated WEBSHOP feeds (highest / popular / latest)
    es = fetch_eshop()
    catmap = es["catmap"]
    eshop_pool = merge(es["highest"] + es["popular"] + es["latest"], [], 9999)  # dedup
    # --- secondary: physical-store sources, only to resolve handpicked brands ----
    raw = fetch(SRC)
    with open(_h("feed-raw.json"), "w", encoding="utf-8") as f:
        f.write(raw)
    locations = collect(decode(raw))
    print(f"webshops: {len(eshop_pool)} (curated)  physical: {len(locations)}  "
          f"(curate: {len(excl)} excl, {len(cur['pin_highest'])} pin-H, {len(cur['pin_popular'])} pin-P)")

    def excluded(p):
        return (p.get("slug") or "").lower() in excl or (p["n"] or "").lower() in excl

    def resolve(key):
        k = key.strip()
        if "/eshop/butikker/" in k:               # authoritative webshop link
            return resolve_eshop_link(k, catmap), "eshop link"
        m = re.search(UUID_RE, k)
        if m and (k.lower().startswith("http") or len(k) <= 40):  # link / bare uuid
            return resolve_location_uuid(m.group(0)), "location-uuid"
        p = find_local(eshop_pool, k)             # by name: webshop feeds
        if p:
            return p, "webshop"
        p = find_local(locations, k)              # landing physical set
        if p:
            return p, "butik (lokal)"
        return resolve_by_name(k), "butik (katalog)"  # physical catalog search

    def resolve_pins(keys, label):
        out = []
        for k in keys:
            p, src = resolve(k)
            if p and not excluded(p):
                print(f"  + {label} '{k[:46]}' -> {p['n']} ({p.get('cb') or '?'}) [{src}]")
                out.append(p)
            else:
                print(f"  ! {label} '{k[:46]}' UNAVAILABLE -> auto-filled from curated feed")
        return out

    # Never-empty fallback pools (site-curated, deduped) for auto top-up.
    pop_fallback = [p for p in merge(es["popular"] + es["highest"] + es["latest"], [], 99)
                    if not excluded(p)]
    high_fallback = [p for p in es["highest"] if not excluded(p)]  # site already curates these

    # Højeste cashback = site-curated webshop list (pins first if any), never empty.
    pin_h = resolve_pins(cur["pin_highest"], "highest")
    highest = merge(pin_h, high_fallback, TOP_N)

    # Mest populære = handpicked list; auto-fill from curated feed up to POP_TARGET.
    if cur["pin_popular"]:
        pin_p = resolve_pins(cur["pin_popular"], "popular")
        target = max(POP_TARGET, len(pin_p))
        popular = merge(pin_p, pop_fallback, target)
    else:
        popular = pop_fallback[:TOP_N]

    feed = {
        "v": 1,
        "generated": datetime.datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
        "title": "Optjen cashback med dit Visa-kort – i over 2.000 butikker",
        "highest": [public(p) for p in highest],
        "popular": [public(p) for p in popular],
    }
    with open(_f("partners.json"), "w", encoding="utf-8") as f:
        json.dump(feed, f, ensure_ascii=False, separators=(",", ":"))

    # ---- feed universe = highest ∪ popular ∪ curated pool, minus exclusions ---
    # This single deduped list drives BOTH the Meta rows AND partners-all.json
    # (which build-images.py renders), so the feed's image_link URLs and the
    # generated image files always correspond 1:1. Order: highest, popular, pool.
    hid = {p["id"] for p in highest}
    pid = {p["id"] for p in popular}
    cat_sorted = sorted(eshop_pool, key=lambda x: (x["n"] or "").lower())
    universe, seen = [], set()
    for p in (highest + popular + cat_sorted):
        if excluded(p) or not p.get("id") or p["id"] in seen:
            continue
        seen.add(p["id"])
        universe.append(p)

    catalog = []
    for p in universe:
        o = public(p)
        o["inHighest"], o["inPopular"] = p["id"] in hid, p["id"] in pid
        catalog.append(o)
    with open(_f("partners-all.json"), "w", encoding="utf-8") as f:
        json.dump({"generated": feed["generated"], "partners": catalog},
                  f, ensure_ascii=False, separators=(",", ":"))

    # ---- Meta product feed: catalog.csv (primary) + catalog.xml (secondary) ---
    # tier (custom_label_0) is derived from hid/pid and drives the Meta product sets.
    rows = build_meta_rows(universe, hid, pid)
    validate_rows(rows)
    write_meta_csv(rows, _f("catalog.csv"))
    write_meta_xml(rows, _f("catalog.xml"), feed["title"])
    n_high = sum(1 for r in rows if r["custom_label_0"] == "highest")
    n_pop = sum(1 for r in rows if r["custom_label_0"] == "popular")
    print(f"\ncatalog feed: {len(rows)} rows  (highest={n_high}  popular={n_pop}  "
          f"catalog={len(rows) - n_high - n_pop})  CDN_BASE={metalib.CDN_BASE}")

    size = len(json.dumps(feed, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
    print(f"highest: {len(highest)}  popular: {len(popular)}  partners.json={size} bytes")
    print("Højeste cashback:", ", ".join(f"{p['n']} {p.get('cb')}" for p in highest[:6]))
    print("Mest populære:   ", ", ".join(f"{p['n']} {p.get('cb')}" for p in popular))
    if not highest or not popular:
        raise SystemExit("ERROR: a carousel is empty")


if __name__ == "__main__":
    main()
