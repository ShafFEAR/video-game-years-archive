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
    """True if the two titles are identical once punctuation/case/spacing
    is stripped entirely -- e.g. "Title: Subtitle" vs Steam's "Title -
    Subtitle" both normalize to "titlesubtitle" and match here, since a
    colon-vs-dash style difference is the only thing that changed.

    A same-title re-release (this is why "2021 in video games" lists it at
    all) very often reuses the original game's Steam listing rather than
    getting a new appid, so Steam reports that listing's *original* release
    year -- e.g. "Disco Elysium - The Final Cut" shows 2019 (the base
    game), not 2021 (this re-release). Rather than rejecting that as a year
    mismatch, trust an exact name match over the year when the two
    disagree.

    Deliberately EXACT match only, not substring containment: an earlier
    version of this check accepted either title containing the other,
    which sounds like it'd only catch edition-label suffixes but actually
    matched "Civilization II" against "Sid Meier's Civilization III
    Complete" (roman numeral II is a prefix of III) and "Dungeon Keeper"
    against "Dungeon Keeper 2" -- sequels and spin-offs, not re-releases.
    A numbered sequel differs from its base title by as little as one
    character, so no length-difference threshold could separate that case
    from a legitimate "same game, edition suffix added" case; exact
    equality is the only boundary that doesn't need one."""
    def norm(s):
        return re.sub(r"[^a-z0-9]+", "", (s or "").lower())
    q, c = norm(query), norm(candidate_name)
    return bool(q) and q == c


def find_match(title, year, stats=None):
    """Search Steam for `title` and return an enrichment dict for the best
    candidate that plausibly is this `year`'s release, or None. `stats`, if
    given, is a dict with a "queried" counter incremented per appdetails
    call (used for progress logging)."""
    candidates = search_store(title) or []
    time.sleep(DELAY)
    for cand in candidates[:5]:
        appid = cand["id"]
        details = fetch_appdetails(appid)
        if stats is not None:
            stats["queried"] += 1
        time.sleep(DELAY)
        if not details or details.get("type") != "game":
            continue  # skip DLC/soundtrack/demo listings
        release_year = parse_release_year(details.get("release_date"))
        year_fits = not release_year or abs(release_year - year) <= 1
        if not year_fits and not _loose_name_match(title, details.get("name")):
            continue
        return {
            "appid": appid,
            "name": details.get("name"),
            "short_description": details.get("short_description"),
            "image_path": download_image(details.get("header_image"), appid),
            "genres": [g["description"] for g in details.get("genres") or []],
            "release_date": (details.get("release_date") or {}).get("date"),
            "site_url": f"https://store.steampowered.com/app/{appid}",
            "year_match": year_fits,
        }
    return None


def main(limit_years=None, platform_filter="Windows"):
    ENRICHED_DIR.mkdir(parents=True, exist_ok=True)
    IMAGES_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    cache = load_cache()
    unmatched = []
    stats = {"queried": 0}
    total_candidates = 0

    year_files = sorted(INDEX_DIR.glob("*.json"), key=lambda p: int(p.stem))
    if limit_years:
        year_files = [p for p in year_files if int(p.stem) in limit_years]

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
                result = find_match(entry["title"], year, stats)
                cache[cache_key] = result
                if stats["queried"] % 20 == 0 and stats["queried"]:
                    save_cache(cache)
                    print(f"...{stats['queried']} Steam appdetails queries so far (year {year})")
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
    print(f"\nDone. {total_candidates} candidates checked, {stats['queried']} appdetails queries, "
          f"{len(unmatched)} unmatched.")


def revalidate():
    """Re-check every currently-matched entry whose match came from the
    year-mismatch bypass (i.e. _loose_name_match, not a real year fit)
    against the current, stricter version of that check -- added after an
    earlier, more permissive version of it shipped false positives like
    "Civilization II" -> "Sid Meier's Civilization III Complete". Bypasses
    the cache for exactly those entries (a stale cached bad match would
    otherwise just get re-served) and searches fresh."""
    cache = load_cache()
    kept, fixed, reverted = 0, 0, 0

    for yf in sorted(ENRICHED_DIR.glob("*.json"), key=lambda p: int(p.stem)):
        year = int(yf.stem)
        entries = json.loads(yf.read_text(encoding="utf-8"))
        changed = False
        for entry in entries:
            steam = entry.get("steam")
            if not steam or steam.get("year_match"):
                continue  # only re-check entries that used the bypass
            new_result = find_match(entry["title"], year)
            cache_key = entry["title"].strip().lower()
            if new_result and new_result["appid"] == steam["appid"]:
                new_result["year_match"] = True  # now confirmed under the stricter rule
                entry["steam"] = new_result
                cache[cache_key] = new_result
                kept += 1
            elif new_result:
                entry["steam"] = new_result
                cache[cache_key] = new_result
                fixed += 1
            else:
                entry["steam"] = None
                cache[cache_key] = None
                reverted += 1
            changed = True
        if changed:
            yf.write_text(json.dumps(entries, indent=2, ensure_ascii=False), encoding="utf-8")
            save_cache(cache)
            print(f"{year}: revalidated")

    print(f"\nRevalidation done. kept {kept}, fixed-to-different-match {fixed}, reverted-to-unmatched {reverted}.")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "revalidate":
        revalidate()
    else:
        years_arg = None
        if len(sys.argv) > 1:
            years_arg = {int(y) for y in sys.argv[1:]}
        main(years_arg)
