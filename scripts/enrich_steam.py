"""Enrich the Wikipedia-scraped index with Steam store links + header art
for titles available on Steam, using Steam's own public Storefront API --
no API key needed (unlike RAWG). This is used instead of scraping SteamDB:
SteamDB's own FAQ asks that people not crawl the site and use Steam's API
for this kind of thing instead, which is what this script does.

Steam's appdetails endpoint is unofficial-but-public and aggressively
throttles bulk use, so this only queries it for entries that plausibly are
on Steam (tagged "Windows" by the Wikipedia scrape) and paces requests
conservatively. Expect a full run across every Windows-tagged title to take
a while -- it's meant to be left running, not to finish in a minute.

Resumable: matches are cached in data/steam_cache.json keyed by search
title, and images are deduped by Steam appid, so re-running only fetches
what's missing. Layers onto any existing data/enriched/{year}.json (e.g. one
enrich_rawg.py already wrote to) rather than overwriting it.
"""
import json
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
CACHE_PATH = ROOT / "data" / "steam_cache.json"
LOG_DIR = ROOT / "logs"

SEARCH_URL = "https://store.steampowered.com/api/storesearch/"
DETAILS_URL = "https://store.steampowered.com/api/appdetails"
HEADERS = {
    "User-Agent": "VideoGameYearsArchiveBot/1.0 (personal research/archival project)"
}

SESSION = requests.Session()
SESSION.headers.update(HEADERS)

DELAY = 1.5


def load_cache():
    if CACHE_PATH.exists():
        return json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    return {}


def save_cache(cache):
    CACHE_PATH.write_text(json.dumps(cache, indent=2, ensure_ascii=False), encoding="utf-8")


def search_store(title, retries=3):
    """Ranked candidates from Steam's own store search box -- the
    ISteamApps/GetAppList endpoint this used to rely on for an exact-name
    lookup has been discontinued (no longer appears in Steam's own
    discoverable API list as of this writing), and storesearch is a better
    fit anyway: relevance-ranked instead of requiring an exact title match."""
    params = {"term": title, "cc": "us", "l": "en"}
    for attempt in range(retries):
        try:
            resp = SESSION.get(SEARCH_URL, params=params, timeout=20)
        except requests.RequestException:
            time.sleep(3)
            continue
        if resp.status_code == 429:
            time.sleep(30)
            continue
        if resp.status_code != 200:
            return None
        try:
            return resp.json().get("items") or []
        except ValueError:
            return None
    return None


def fetch_appdetails(appid, retries=3):
    params = {"appids": appid, "cc": "us", "l": "en"}
    for attempt in range(retries):
        try:
            resp = SESSION.get(DETAILS_URL, params=params, timeout=20)
        except requests.RequestException:
            time.sleep(3)
            continue
        if resp.status_code == 429:
            time.sleep(30)
            continue
        if resp.status_code != 200:
            return None
        try:
            data = resp.json()
        except ValueError:
            return None
        entry = data.get(str(appid)) or {}
        if not entry.get("success"):
            return None
        return entry.get("data") or {}
    return None


def download_image(url, appid):
    if not url:
        return None
    ext = ".png" if url.lower().endswith(".png") else ".jpg"
    dest = IMAGES_DIR / f"steam-{appid}{ext}"
    if dest.exists():
        return str(dest.relative_to(ROOT)).replace("\\", "/")
    try:
        resp = SESSION.get(url, timeout=30)
        resp.raise_for_status()
        dest.write_bytes(resp.content)
        return str(dest.relative_to(ROOT)).replace("\\", "/")
    except requests.RequestException:
        return None


def parse_release_year(release_date_field):
    date_str = (release_date_field or {}).get("date") or ""
    m = re.search(r"(19|20)\d{2}", date_str)
    return int(m.group()) if m else None


def _loose_name_match(query, candidate_name):
    """True if the two titles are the same once punctuation/case is
    stripped, or one contains the other (handles Steam's own subtitle
    formatting, e.g. "Title - Subtitle" vs Wikipedia's "Title: Subtitle").

    A remaster/definitive-edition re-release (this is why "2021 in video
    games" lists it at all) very often reuses the original game's Steam
    listing rather than getting a new appid, so Steam reports that
    listing's *original* release year -- e.g. "Disco Elysium - The Final
    Cut" shows 2019 (the base game), not 2021 (this re-release). Rather
    than rejecting that as a year mismatch, trust an exact/near-exact name
    match over the year when the two disagree."""
    def norm(s):
        return re.sub(r"[^a-z0-9]+", "", (s or "").lower())
    q, c = norm(query), norm(candidate_name)
    return bool(q) and bool(c) and (q in c or c in q)


def main(limit_years=None, platform_filter="Windows"):
    ENRICHED_DIR.mkdir(parents=True, exist_ok=True)
    IMAGES_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    cache = load_cache()
    unmatched = []

    year_files = sorted(INDEX_DIR.glob("*.json"), key=lambda p: int(p.stem))
    if limit_years:
        year_files = [p for p in year_files if int(p.stem) in limit_years]

    total_candidates = 0
    total_queried = 0

    for yf in year_files:
        year = int(yf.stem)
        enriched_path = ENRICHED_DIR / f"{year}.json"
        source = enriched_path if enriched_path.exists() else yf
        entries = json.loads(source.read_text(encoding="utf-8"))
        changed = False
        for entry in entries:
            if platform_filter and platform_filter not in entry.get("platforms", []):
                continue
            if entry.get("steam"):
                continue
            total_candidates += 1
            cache_key = entry["title"].strip().lower()
            if cache_key in cache:
                result = cache[cache_key]
            else:
                candidates = search_store(entry["title"]) or []
                time.sleep(DELAY)
                result = None
                for cand in candidates[:5]:
                    appid = cand["id"]
                    details = fetch_appdetails(appid)
                    total_queried += 1
                    time.sleep(DELAY)
                    if not details or details.get("type") != "game":
                        continue  # skip DLC/soundtrack/demo listings
                    release_year = parse_release_year(details.get("release_date"))
                    year_fits = not release_year or abs(release_year - year) <= 1
                    if not year_fits and not _loose_name_match(entry["title"], details.get("name")):
                        continue
                    result = {
                        "appid": appid,
                        "name": details.get("name"),
                        "short_description": details.get("short_description"),
                        "image_path": download_image(details.get("header_image"), appid),
                        "genres": [g["description"] for g in details.get("genres") or []],
                        "release_date": (details.get("release_date") or {}).get("date"),
                        "site_url": f"https://store.steampowered.com/app/{appid}",
                        "year_match": year_fits,
                    }
                    break
                cache[cache_key] = result
                if total_queried % 20 == 0 and total_queried:
                    save_cache(cache)
                    print(f"...{total_queried} Steam appdetails queries so far (year {year})")
            entry["steam"] = result
            changed = True
            if not result:
                unmatched.append({"year": year, "title": entry["title"]})
        if changed:
            enriched_path.write_text(json.dumps(entries, indent=2, ensure_ascii=False), encoding="utf-8")
            matched = sum(1 for e in entries if e.get("steam"))
            print(f"{year}: {matched} titles matched to a Steam store page")
        save_cache(cache)

    (LOG_DIR / "unmatched_steam.json").write_text(
        json.dumps(unmatched, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"\nDone. {total_candidates} candidates checked, {total_queried} appdetails queries, "
          f"{len(unmatched)} unmatched.")


if __name__ == "__main__":
    years_arg = None
    if len(sys.argv) > 1:
        years_arg = {int(y) for y in sys.argv[1:]}
    main(years_arg)
