# Cashbackmedvisa — Meta catalog ads · Agency handoff

A ready-to-run **Meta (Facebook/Instagram) catalog ad** that showcases the Cashbackmedvisa
partners as a **live, auto-updating feed**. Each partner becomes one branded card; Meta renders
them in **Carousel** and **Collection** ads. This package contains everything to launch.

---

## What's in the package

| Path | What it is |
|---|---|
| `feed/catalog.csv` | **The Meta product feed.** One row per partner. This is the file Meta ingests. |
| `feed/catalog.xml` | Same data as XML (RSS/`g:`) — use if you prefer XML over CSV. |
| `images/` | **157 ready creatives** — every partner in 1:1, 4:5 and 9:16, plus 4 Collection covers (1080 px, JPEG). |
| `images/_preview.html` | Open in a browser to see the cards as a mock Carousel + Collection. |
| `source/` + `.github/` | The build pipeline that regenerates the feed + images from live data (for refreshes). |
| `README.md`, `HOSTING.md` | Deeper technical reference. |

Each card is **photo + partner logo + "X % CASHBACK" tag + "Få cashback hos {Brand}, og i 2000+
andre butikker" + tiny disclaimer**, baked in. Cards intentionally have **no CTA button** — in both
Collection and Carousel ads Meta renders one large CTA below the grid (see Step 4). The `_cover_*`
images are the **Collection cover** in the light-blue "Få penge tilbage i +2.000 butikker" style.

---

## Step 1 — Host the feed + images (required first)

Meta pulls the feed and images from public URLs, so they must be online. The image URLs in
`catalog.csv` currently point at a placeholder (`…/gh/OWNER/REPO@…`). Pick one:

**Recommended — GitHub + jsDelivr (free, auto-refresh).** Push this folder to a **public** GitHub
repo, set `CDN_BASE = "<owner>/<repo>"` in `source/metalib.py`, then rebuild once
(`cd source && python3 build-feed.py && python3 build-images.py`). The included GitHub Action
rebuilds **daily** so prices/partners stay current. Full steps in `HOSTING.md`.

**Or — your own CDN / first-party host.** Upload `images/` and `catalog.csv` to any HTTPS host that
sends `Access-Control-Allow-Origin: *`, then point the image URLs at it (edit `cdn()` in
`source/metalib.py` and rebuild, or find-and-replace the base URL in `catalog.csv`).

> Quickest path: tell us the repo/host and we'll hand back a `catalog.csv` with live, working URLs.

---

## Step 2 — Create the catalog + feed in Commerce Manager

1. **Commerce Manager → Catalogs → Create catalog** → type **E-commerce**.
2. **Data sources → Add items → Scheduled feed** → paste the public `catalog.csv` URL →
   schedule **Daily** (set ~1–2 h after the feed rebuilds).
3. Check the **Issues** tab → fix until 0 errors (should be clean — the feed is pre-validated).

---

## Step 3 — Product sets (the two ad groupings)

In the catalog → **Product sets → Create set**, filter on `custom_label_0`:

- **"Højeste cashback"** → `custom_label_0 = highest`
- **"Mest populære"** → `custom_label_0 = popular`

These update automatically on every daily refresh. (`custom_label_1` = cashback shown, `2` =
category, `3` = online/physical, `4` = numeric % — available for extra targeting.)

---

## Step 4 — Build the ads

In Ads Manager, create **Catalog (Advantage+) ads** on a product set, as **Carousel** and/or
**Collection**. For **Collection**, use the `images/_cover_<tier>_*` file as the cover — the product
grid fills below it and Meta shows the ad's CTA button under the grid. Set that **CTA button to
"Hent appen gratis"** (or "Tilmeld dig gratis"): it's the single large CTA for the whole ad, which is
why the individual cards carry no CTA of their own.

**⚠️ One must-do:** in the ad creative template, **turn the price element OFF.** Every item's feed
price is `0.00 DKK` (a partner has no price); the real cashback value is baked into the card image
and lives in `custom_label_1`. Leaving the price element on would show "0,00 kr".

---

## Asset specs (already met)

- Ratios: **1:1** (`image_link`, primary), **4:5** + **9:16** (`additional_image_link`). All 1080 px, JPEG, < 8 MB.
- Safe zones respected for 9:16; logo + cashback + CTA sit in the central area.

## Refreshing / editing

- Re-run `cd source && python3 build-feed.py && python3 build-images.py` (or let the daily Action do it).
- Curate which partners appear / pin order: edit `source/curate.json` (see `README.md`).
- Image filenames are content-hashed, so a changed rate/logo produces a new URL Meta re-fetches —
  no manual cache busting.

## Questions for us
- The repo/host to finalize live URLs (Step 1).
- CTA wording is **"Tilmeld dig gratis"** — say if you want "Hent appen gratis" instead.
- Logos are the partners' own ~260 px assets; we can hand-source sharper SVGs for top partners on request.
