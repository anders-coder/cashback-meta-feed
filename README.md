# Update: "Nyeste butikker" — a third catalog set

This package updates the **cashback partner catalog pipeline** you already have
(`meta-catalog-ads`) with one addition: a **"Nyeste butikker" (newest shops)** set,
alongside the existing "Højeste cashback" and "Mest populære". It powers a new
**carousel ad of the newest shops** — combining **direct partnership stores and
eShop webshops** in one set, auto-refreshed daily.

Nothing else changed in the feed schema, hosting, or ad setup — everything in the
original package's README/HOSTING still applies.

---

## What's new

| Where | Change |
|---|---|
| `feed/catalog.csv` / `.xml` | Rows can now carry **`custom_label_0 = newest`** (a third tier next to `highest` / `popular` / `catalog`). |
| `feed/partners.json` | New **`newest`** array (the curated set, max 15). |
| `feed/partners-all.json` | Each partner gains an **`inNewest`** flag. |
| `source/build-feed.py` | Builds the newest set (logic below). |
| `source/build-images.py` | Renders cards for the new partners + a `_cover_newest_*` Collection cover. Also a polish fix: partner logos with baked-in white backgrounds now sit on a white chip (no more blue frame around white-box logos). |
| `source/curate.json` | New **`pin_newest`** list (same matching rules as the other pins). |
| `images/_preview.html` | Local preview page has a "Nyeste butikker" tab. |

See `examples/` for rendered samples (cards + the Collection cover).

## How "newest" is selected (automatic, daily)

1. **eShop webshops:** the site's own curated "latest" list.
2. **Direct partners:** the "Nyheder" section of the partner catalog, sorted
   newest-first by their creation date.
3. The two sources are **interleaved** (so both partnership types stay represented),
   de-duplicated by brand, and capped at 15.
4. Partners in the **"Sidste chance"** section (about to leave the program) are excluded.
5. `pin_newest` entries in `curate.json` always go first.

**Tier priority:** a shop that is *also* in "Højeste cashback" or "Mest populære"
keeps that tier (`custom_label_0` holds one value). The build log prints which
newest members were absorbed by a higher tier on every run.

## Deploy (same repo as before)

1. Replace `source/build-feed.py`, `source/build-images.py`, `source/curate.json`
   (and optionally `images/_preview.html`) in the live repo with the versions in
   this package.
2. Trigger the workflow (*Actions → Refresh Meta catalog feed → Run workflow*) or
   wait for the daily run. It rebuilds `feed/` + `images/` including the new set.
3. No Commerce Manager feed changes needed — Meta ingests the same scheduled
   `catalog.csv` URL and picks up the new rows on its next fetch.

## Create the new ad

1. **Commerce Manager → your catalog → Product sets → Create set**
   - Name: **Nyeste butikker**
   - Filter: **`custom_label_0` is equal to `newest`**
2. **Ads Manager → catalog (Advantage+) ad → Carousel** on that product set —
   exactly like the two existing ads. (A `_cover_newest_*.jpg` cover image is also
   generated if you prefer a Collection.)
3. Reminder from the original handoff still applies: **price element OFF** in the
   creative template (items carry `0.00 DKK`; the cashback value is baked into the image).

The set membership updates itself daily — new shops flow in, and shops that stop
being "new" (or leave the program) rotate out, with no ad changes needed.

## Curation

`source/curate.json` → `"pin_newest": []` — pin brands to the front by name, slug,
or full partner link; `exclude` still hides a brand from every set. Re-run
`build-feed.py` (or let the Action run) after editing.
