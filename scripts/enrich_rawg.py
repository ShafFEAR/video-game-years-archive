"""Enrich the Wikipedia-scraped index with RAWG synopsis + cover art.

RAWG's API (https://rawg.io/apidocs) is built for third-party apps to
display this data (search, description, background_image), so like AniList/
Kitsu for the anime archive, this is fine to cache locally and redistribute
with attribution.

Requires a free API key: sign up at https://rawg.io/apidocs (instant, no
approval wait) and set the RAWG_API_KEY environment variable before running.
That signup step has to happen on your end -- account creation isn't
something this project can automate.

Resumable: results are cached in data/rawg_cache.json keyed by search title,
and images are deduped by RAWG id, so re-running only fetches what's
missing. Layers onto any existing data/enriched/{year}.json (e.g. one
enrich_steam.py already wrote to) rather than overwriting it.
"""
import json
import os
import re
import sys
import time
from pathlib import Path

import requests

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent.parent
INDEX_DIR = ROOT / "data" / "index"
ENRICHED_DIR = ROOT / "data" / "enriched"
IMAGES_DIR = ROOT / "images"
CACHE_PATH = ROOT / "data" / "rawg_cache.json"
LOG_DIR = ROOT / "logs"

API_URL = "https://api.rawg.io/api/games"
HEADERS = {
    "User-Agent": "VideoGameYearsArchiveBot/1.0 (personal research/archival project)"
}

SESSION = requests.Session()
SESSION.headers.update(HEADERS)

DELAY = 1.0


def load_cache():
    if CACHE_PATH.exists():
        return json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    return {}


def save_cache(cache):
    CACHE_PATH.write_text(json.dumps(cache, indent=2, ensure_ascii=False), encoding="utf-8")


def api_key():
    key = os.environ.get("RAWG_API_KEY")
    if not key:
        raise SystemExit(
            "RAWG_API_KEY is not set. Get a free key at https://rawg.io/apidocs "
            "and run: RAWG_API_KEY=yourkey python scripts/enrich_rawg.py"
        )
    return key


def search_candidates(title, key, retries=3):
    params = {"key": key, "search": title, "page_size": 5}
    for attempt in range(retries):
        try:
            resp = SESSION.get(API_URL, params=params, timeout=20)
        except requests.RequestException:
            time.sleep(3)
            continue
        if resp.status_code == 429:
            time.sleep(20)
            continue
        if resp.status_code >= 500:
            time.sleep(5)
            continue
        if resp.status_code != 200:
            print(f"  RAWG returned {resp.status_code}: {resp.text[:200]}")
            return None
        try:
            data = resp.json()
        except ValueError:
            return None
        return data.get("results") or []
    return None


def fetch_details(rawg_id, key, retries=3):
    for attempt in range(retries):
        try:
            resp = SESSION.get(f"{API_URL}/{rawg_id}", params={"key": key}, timeout=20)
        except requests.RequestException:
            time.sleep(3)
            continue
        if resp.status_code == 429:
            time.sleep(20)
            continue
        if resp.status_code != 200:
            return {}
        try:
            return resp.json()
        except ValueError:
            return {}
    return {}


def pick_best_match(candidates, expected_year):
    """First candidate whose release year is within 1 of expected_year;
    RAWG's own relevance ranking already puts the most likely title first,
    so this just guards against that top hit being an unrelated
    remake/reboot released in a different year."""
    for c in candidates:
        released = c.get("released") or ""
        year = int(released[:4]) if released[:4].isdigit() else None
        if year and abs(year - expected_year) <= 1:
            return c, True
    return (candidates[0], False) if candidates else (None, False)


def download_image(url, rawg_id):
    if not url:
        return None
    ext = ".png" if url.lower().endswith(".png") else ".jpg"
    dest = IMAGES_DIR / f"rawg-{rawg_id}{ext}"
    if dest.exists():
        return str(dest.relative_to(ROOT)).replace("\\", "/")
    try:
        resp = SESSION.get(url, timeout=30)
        resp.raise_for_status()
        dest.write_bytes(resp.content)
        return str(dest.relative_to(ROOT)).replace("\\", "/")
    except requests.RequestException:
        return None


def main(limit_years=None):
    key = api_key()
    ENRICHED_DIR.mkdir(parents=True, exist_ok=True)
    IMAGES_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    cache = load_cache()
    unmatched = []

    year_files = sorted(INDEX_DIR.glob("*.json"), key=lambda p: int(p.stem))
    if limit_years:
        year_files = [p for p in year_files if int(p.stem) in limit_years]

    total_entries = 0
    total_queried = 0

    for yf in year_files:
        year = int(yf.stem)
        enriched_path = ENRICHED_DIR / f"{year}.json"
        source = enriched_path if enriched_path.exists() else yf
        entries = json.loads(source.read_text(encoding="utf-8"))
        for entry in entries:
            total_entries += 1
            if entry.get("rawg"):
                continue  # already enriched by a previous run
            search_title = entry.get("wiki_title") or entry["title"]
            cache_key = search_title.strip().lower()
            if cache_key in cache:
                candidates = cache[cache_key]
            else:
                candidates = search_candidates(search_title, key)
                total_queried += 1
                if candidates is not None:
                    cache[cache_key] = candidates
                time.sleep(DELAY)
                if total_queried % 25 == 0:
                    save_cache(cache)
                    print(f"...{total_queried} RAWG queries so far (year {year})")
            if not candidates:
                entry["rawg"] = None
                unmatched.append({"year": year, "title": entry["title"]})
                continue
            best, year_match = pick_best_match(candidates, year)
            if not best:
                entry["rawg"] = None
                unmatched.append({"year": year, "title": entry["title"]})
                continue
            details = fetch_details(best["id"], key)
            time.sleep(DELAY)
            image_path = download_image(best.get("background_image"), best["id"])
            entry["rawg"] = {
                "rawg_id": best["id"],
                "name": best.get("name"),
                "description": (details.get("description_raw") or "").strip() or None,
                "released": best.get("released"),
                "genres": [g["name"] for g in best.get("genres") or []],
                "platforms": [p["platform"]["name"] for p in best.get("platforms") or []],
                "metacritic": best.get("metacritic"),
                "image_path": image_path,
                "site_url": f"https://rawg.io/games/{best.get('slug')}" if best.get("slug") else None,
                "year_match": year_match,
            }
        enriched_path.write_text(json.dumps(entries, indent=2, ensure_ascii=False), encoding="utf-8")
        matched = sum(1 for e in entries if e.get("rawg"))
        print(f"{year}: wrote {len(entries)} enriched entries ({matched} with RAWG data)")
        save_cache(cache)

    (LOG_DIR / "unmatched_rawg.json").write_text(
        json.dumps(unmatched, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"\nDone. {total_entries} total entries, {total_queried} new RAWG queries, {len(unmatched)} unmatched.")


if __name__ == "__main__":
    years_arg = None
    if len(sys.argv) > 1:
        years_arg = {int(y) for y in sys.argv[1:]}
    main(years_arg)
