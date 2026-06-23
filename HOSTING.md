# Hosting the live feed (GitHub Action → jsDelivr)

Meta pulls the catalog from a public URL on a schedule. We host it free on a public
GitHub repo and serve it through jsDelivr (CORS + global CDN, no infra).

## One required setting

The feed's `image_link`s point at jsDelivr, so the CDN must know your repo.
Edit **`source/metalib.py`**:

```python
CDN_BASE = "your-github-owner/your-repo"   # e.g. "loyaltykey/cashback-meta-feed"
```

Then rebuild once (`cd source && python3 build-feed.py && python3 build-images.py`)
so the URLs in `catalog.csv` resolve. The `${{ github.repository }}` purge step in
the workflow figures out the repo on its own.

## Steps

1. Push **this folder as the repo root** to a **public** GitHub repo
   (any account works — jsDelivr only needs the repo to be public).
2. **Settings → Actions → General** → allow workflows + **Read and write permissions**.
3. The included `.github/workflows/feed.yml` runs daily (and via *Actions → Run workflow*):
   `build-feed.py` → `build-images.py` → commits `feed/` + `images/` → purges the CSV from jsDelivr.
4. Your public URLs:

   ```
   Feed (give this to Meta):
   https://cdn.jsdelivr.net/gh/<OWNER>/<REPO>@main/feed/catalog.csv

   Images (referenced by the feed automatically):
   https://cdn.jsdelivr.net/gh/<OWNER>/<REPO>@main/images/<slug>_<hash>_1x1.jpg
   ```

5. **Commerce Manager → Data Sources → Scheduled feed** → paste the `catalog.csv`
   URL → fetch **daily** (set the time ~1–2 h after the Action's 06:00 UTC run).

## Caching notes (matters for "live")

- jsDelivr caches `@main` for ~12 h. Fine for a daily feed.
- **Images**: filenames are content-hashed (`<slug>_<hash>_…`). When a partner's
  cashback rate or artwork changes, the hash → the URL changes → Meta re-fetches a
  fresh image. No stale-image problem, no purge needed for images.
- **CSV/XML**: reuse the same URL, so the workflow calls the jsDelivr **purge API**
  after each commit to refresh them quickly.
- Stale images no longer in the feed are pruned from `images/` on every build.

## Alternative: first-party on cashbackmedvisa.dk

Hand to Loyalty Key: run `build-feed.py` (+ `build-images.py`) on a daily cron,
publish `catalog.csv` and `/images/` under the domain with
`Access-Control-Allow-Origin: *`, set `CDN_BASE` to that base path, and point
Meta's scheduled feed there instead. Keeps everything first-party.
