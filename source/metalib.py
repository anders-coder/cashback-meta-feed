#!/usr/bin/env python3
"""
metalib.py - tiny shared helper used by BOTH build-feed.py and build-images.py
so they agree on image filenames / URLs without a build-order dependency.

stdlib only (build-feed.py runs in CI with no third-party deps).

The image filename is content-hashed from the fields that determine the rendered
image (name, cashback text, first-visit bonus, source hero + logo URLs). When a
partner's cashback rate or artwork changes, the hash changes, so the CDN URL
changes too -> Meta is forced to re-fetch the new image (defeats jsDelivr/Meta
image caching, which would otherwise pin the stale picture to the old URL).
"""
import hashlib
import re

# Set this to "<github-owner>/<repo>" of the PUBLIC repo you push this project to.
# Until then the URLs are still valid https (they just won't resolve), so local
# builds + feed validation pass. See HOSTING.md.
CDN_BASE = "anders-coder/cashback-meta-feed"

# Three Meta-supported aspect ratios. 1x1 is the canonical image_link; the other
# two ride along as additional_image_link for vertical placements.
RATIOS = {
    "1x1": (1080, 1080),   # Feed / canonical catalog image  -> image_link
    "4x5": (1080, 1350),   # Feed (mobile)                   -> additional_image_link
    "9x16": (1080, 1920),  # Stories / Reels                 -> additional_image_link
}
PRIMARY = "1x1"


def cdn():
    return "https://cdn.jsdelivr.net/gh/" + CDN_BASE + "@main"


def slugify(s):
    s = re.sub(r"[^a-z0-9]+", "-", (s or "").lower()).strip("-")
    return s or "partner"


def img_hash(p):
    """Deterministic 8-hex digest of the inputs that change the rendered image."""
    key = "|".join(str(p.get(k) or "") for k in
                   ("slug", "n", "cb", "pctfv", "hero2x", "logo"))
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:8]


def img_base(p):
    return slugify(p.get("slug") or p.get("n")) + "_" + img_hash(p)


def img_name(p, ratio):
    return img_base(p) + "_" + ratio + ".jpg"


def img_url(p, ratio):
    return cdn() + "/images/" + img_name(p, ratio)


def cover_name(tier, ratio):
    return "_cover_" + tier + "_" + ratio + ".jpg"


def cover_url(tier, ratio):
    return cdn() + "/images/" + cover_name(tier, ratio)
