# Cashbackmedvisa — Meta catalog ads (live partner feed)

A **live, self-updating Meta (Facebook/Instagram) catalog ad** that showcases the
Cashbackmedvisa partner brands — the Meta equivalent of the Kayzen "V3 partner
showcase" endcard. One catalog item per partner, branded "Confect-style" images
baked locally, served to Meta as a **scheduled product feed**.

## How Meta catalog ads work (≠ Kayzen)

Meta does **not** take an interactive HTML/MRAID creative. Instead:

1. You create a **product catalog** in [Meta Commerce Manager](https://business.facebook.com/commerce).
2. You connect a **scheduled feed URL** (a CSV) that Meta re-pulls daily — **this is the "live" part**.
3. Meta renders the items into **Carousel** and **Collection** ad formats.
4. To make items look designed instead of raw photos, we bake brand overlays
   (logo + cashback badge + Visa frame) into each item's image — the same thing
   [Confect](https://www.confect.io) does, here done for free with Pillow.

The partner data, curation, and image artwork all refresh automatically on a
daily GitHub Action — you only touch Meta again if you change the *ad*, not the data.

## What this repo produces

| File | Purpose |
|---|---|
| `feed/catalog.csv` | **Primary Meta product feed** (one row per partner). Point Commerce Manager's scheduled feed here. |
| `feed/catalog.xml` | Same data as RSS 2.0 + `g:` (optional alternative format). |
| `feed/partners.json` / `partners-all.json` | Curated sets + full universe; drive the image builder and the preview. |
| `images/<slug>_<hash>_{1x1,4x5,9x16}.jpg` | Branded partner cards in the 3 Meta ratios. `image_link` / `additional_image_link`. |
| `images/_cover_{highest,popular}_{1x1,9x16}.jpg` | Collection-ad cover images. |
| `images/_preview.html` | Local mock of the Collection + Carousel ad. |

## Build it

```bash
cd source
python3 build-feed.py      # live fetch -> feed/catalog.csv + catalog.xml + partners*.json  (stdlib only)
python3 build-images.py    # downloads heroes/logos -> branded images + covers + preview.json  (needs Pillow)
```

Install Pillow once: `pip install -r requirements.txt`.

Preview the creative locally:

```bash
cd images && python3 -m http.server 8124   # then open http://localhost:8124/_preview.html
```

## Feed schema (partner → Meta field)

One row per partner. Meta requires `id, title, description, availability,
condition, price, link, image_link` + `brand`. A partner has no price, so
`price = "0.00 DKK"` and **the price element is turned off in the ad creative**
(the real cashback value lives in the baked image badge + `custom_label_1`).

`custom_label_0` is the spine: **`highest` | `popular` | `catalog`** — it drives
the two Meta product sets. Other labels: `1` = cashback display (`"5 %"`/`"300 kr"`),
`2` = category, `3` = `online`/`physical`, `4` = zero-padded numeric % (sortable).

## Set it up in Meta (once)

1. **Commerce Manager → Catalogs → Create catalog** (type: E-commerce).
2. **Data Sources → Add items → Scheduled feed** → paste the `catalog.csv`
   jsDelivr URL (see [HOSTING.md](HOSTING.md)) → schedule **daily** (~08:00, after the Action runs).
   Use the feed debugger / **Issues** tab to confirm 0 errors.
3. **Product Sets → Create set**:
   - "Højeste cashback" → filter `custom_label_0 is equal to highest`
   - "Mest populære" → filter `custom_label_0 is equal to popular`
4. **Ads Manager → Sales/Traffic → Catalog ads** → choose a product set → build a
   **Carousel** and/or **Collection** ad. In the creative template, **turn the price
   element OFF** (our image carries the cashback value). Use the `_cover_*` image as
   the Collection cover.

## Curation

`source/curate.json` (copied from the Kayzen project, applied every build):
`exclude` / `pin_highest` / `pin_popular`, matched by name, slug, or a full
`…/eshop/butikker/<slug>/<uuid>` link. Pins flow straight into the Meta product
sets via `custom_label_0`. A handpicked "popular" auto-fills so it is never empty.

## Live refresh

`.github/workflows/feed.yml` runs both scripts **daily** (and on-demand) and commits
`feed/` + `images/`. Image filenames are content-hashed, so a cashback change yields
a new URL Meta re-fetches; the CSV URL is purged from jsDelivr after each commit.
See [HOSTING.md](HOSTING.md) for the one required setting (`CDN_BASE`).
