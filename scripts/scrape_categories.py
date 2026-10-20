"""Scrape Wikipedia's "Category:YYYY video games" pages into data/categories/.

Every video game with its own English Wikipedia article sits in the category
for its release year, so this is the most complete list of *notable* games per
year -- far larger than the tables in "YYYY in video games" (thin before 2000,
gone after 2011) or the "List of video games released in YYYY" articles
(2012+, which also list games without articles). Comparing the two showed
~16,000 games with articles that the rest of the archive was missing.

Two phases, both resumable:
  1. members    (default)       the category's articles -> data/categories/{year}.json
  2. --infoboxes                fill in developer, publisher, genre, platforms
                                and release date from each article's
                                {{Infobox video game}}, 50 articles per request

A category page lists titles only, so phase 2 is what makes the entries
useful (and lets the console filter work on them). The infobox lists *all*
platforms a game ever reached, so platforms that launched after the game's
year are dropped (see platforms.available_in_year) -- the raw list is kept in
`platforms_all`.

Phase 2 skips games the year tables and release lists already hold (they'd
never be added, see sources.load_all), notes articles that are really
#REDIRECT pages (`redirect_to`), and keeps the fetched infobox text in the
git-ignored .cache/infoboxes/{year}.json so that improving the parser or the
platform aliases only needs `--reparse`, not another trip to Wikipedia.
Interrupted runs resume where they stopped.

Usage:
  python scripts/scrape_categories.py                 # phase 1, all years
  python scripts/scrape_categories.py --infoboxes     # phase 2, all years (~1 minute per year)
  python scripts/scrape_categories.py 1995 2005 --infoboxes
  python scripts/scrape_categories.py --reparse       # offline: re-read cached infoboxes
Phase 2 also writes logs/unknown_infobox_platforms.json: platform names the
infobox listed that platforms.py doesn't know yet.
Text extracted here is Wikipedia data (CC BY-SA, reuse with attribution).
"""
import argparse
import json
import re
import sys
import time
from pathlib import Path
from urllib.parse import quote

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, str(Path(__file__).resolve().parent))
import infobox as I
import sources
from platforms import available_in_year, resolve_wiki_platform
from titles import norm_title, strip_disambiguator
from wiki import api_get

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "data" / "categories"
LOG_DIR = ROOT / "logs"
CACHE_DIR = ROOT / ".cache" / "infoboxes"  # git-ignored raw infobox wikitext (one file per year), so parsing can be refined offline
BATCH = 50  # articles per revisions request

START_YEAR, END_YEAR = 1990, 2028
DELAY = 1.5  # seconds between API requests; Wikipedia throttles faster unauthenticated clients


def article_url(article):
    return "https://en.wikipedia.org/wiki/" + quote(article.replace(" ", "_"), safe="/:@!$&'()*+,;=-._~")


def category_members(category):
    """(article titles, subcategory titles) of a category, following paging."""
    pages, subs, cont = [], [], {}
    while True:
        data = api_get({
            "action": "query", "list": "categorymembers", "cmtitle": category, "cmlimit": 500,
            "cmtype": "page|subcat", "cmnamespace": "0|14", "format": "json", **cont,
        }, retries=10)
        if data is None:
            raise RuntimeError(f"Wikipedia API kept failing on {category} (rate limited?)")
        for member in data["query"]["categorymembers"]:
            (pages if member["ns"] == 0 else subs).append(member["title"])
        time.sleep(DELAY)
        if "continue" not in data:
            return pages, subs
        cont = data["continue"]


def year_articles(year):
    """Articles for a year: its category plus the "Upcoming video games
    scheduled for YYYY" subcategory some future years keep theirs in."""
    pages, subs = category_members(f"Category:{year} video games")
    for sub in subs:
        if "Upcoming video games scheduled" in sub:
            pages += category_members(sub)[0]
    # "List of ..." pages are articles about lists, not games.
    return list(dict.fromkeys(p for p in pages if not p.startswith("List of ")))


def member_entry(year, article):
    return {
        "year": year,
        "section": f"Category:{year} video games",
        "title": strip_disambiguator(article),
        "wiki_title": article,
        "wiki_url": article_url(article),
        "redlink": False,
        "platform_breakdown": {},
        "platforms": [],
        "source_article": f"Category:{year} video games",
    }


def run_members(years, refresh):
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    summary_path = LOG_DIR / "categories_summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8")) if summary_path.exists() else {}
    for year in years:
        out_path = OUT_DIR / f"{year}.json"
        if out_path.exists() and not refresh:
            print(f"{year}: already listed, skipping (use --refresh to redo)")
            continue
        try:
            articles = year_articles(year)
        except RuntimeError as exc:
            print(f"{year}: {exc}; rerun later", flush=True)
            continue
        entries = [member_entry(year, a) for a in articles]
        # --refresh must not throw away infobox data already gathered.
        if out_path.exists():
            old = {e["wiki_title"]: e for e in json.loads(out_path.read_text(encoding="utf-8"))}
            entries = [old.get(e["wiki_title"], e) for e in entries]
        out_path.write_text(json.dumps(entries, indent=2, ensure_ascii=False), encoding="utf-8")
        summary[str(year)] = len(entries)
        print(f"{year}: {len(entries)} articles", flush=True)
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")


def cache_path(year):
    return CACHE_DIR / f"{year}.json"


def load_cache(year):
    path = cache_path(year)
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def save_cache(year, cache):
    """Write via a temp file so an interrupted run can't leave a truncated cache."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    tmp = cache_path(year).with_suffix(".tmp")
    tmp.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
    tmp.replace(cache_path(year))


def fetch_infoboxes(titles):
    """{article: {"box": infobox wikitext or "", "head": the start of the text
    when there is no infobox (enough to spot a redirect), "missing": True if
    the article is gone}} for one batch."""
    data = api_get({
        "action": "query", "prop": "revisions", "rvprop": "content", "rvslots": "main", "rvsection": 0,
        "titles": "|".join(titles), "format": "json", "formatversion": 2,
    }, retries=10)
    if data is None:
        raise RuntimeError("Wikipedia API kept failing while fetching infoboxes (rate limited?)")
    out = {}
    for page in data["query"]["pages"]:
        if page.get("missing"):
            out[page["title"]] = {"box": "", "head": "", "missing": True}
            continue
        revision = (page.get("revisions") or [{}])[0]
        text = revision.get("slots", {}).get("main", {}).get("content", "")
        box = I.find_infobox(text) or ""
        out[page["title"]] = {"box": box, "head": "" if box else text[:500]}
    # a title the API normalized differently would otherwise be refetched forever
    for title in titles:
        out.setdefault(title, {"box": "", "head": "", "missing": True})
    return out


def apply_infobox(entry, cached, unknown_platforms):
    """Fill an entry from its cached infobox (or note that there isn't one).
    Starts from a clean slate so reparsing with a better parser can't leave
    stale values behind."""
    for field in ("developer", "publisher", "genre", "release_date", "platforms_all", "redirect_to"):
        entry.pop(field, None)
    entry["platforms"] = []
    entry["infobox_done"] = True
    target = I.redirect_target(cached.get("head"))
    if target:
        # A redirect page that happens to sit in the category. Its target's
        # infobox may describe a different game (a sequel redirecting to its
        # series, say), so don't borrow it -- just remember where it points.
        entry["redirect_to"] = target
        return
    box = cached.get("box")
    if not box:
        return
    params = I.parse_params(box)
    for name, limit in (("developer", 4), ("publisher", 4), ("genre", 3)):
        value = ", ".join(I.names(I.field(params, name), limit=limit, drop_bold=name != "genre"))
        if value:
            entry[name] = value
    display_date, per_platform, _ = I.release_info(I.field(params, "released"), entry["year"])
    if display_date:
        entry["release_date"] = display_date

    all_platforms, unknown = [], set()
    for group in I.platform_groups(I.field(params, "platforms")):
        name = next((resolve_wiki_platform(alt) for alt in group if resolve_wiki_platform(alt)), None)
        if name:
            if name not in all_platforms:
                all_platforms.append(name)
        elif 3 <= len(group[0]) <= 40:
            unknown.add(group[0])  # a linked platform also shows up as plain text, so count it once
    for name in unknown:
        unknown_platforms[name] = unknown_platforms.get(name, 0) + 1
    released_years = {}
    for label, year in per_platform.items():
        name = resolve_wiki_platform(label)
        if name:
            released_years[name] = min(year, released_years.get(name, 9999))
            if name not in all_platforms:
                all_platforms.append(name)
    entry["platforms_all"] = all_platforms
    entry["platforms"] = available_in_year(all_platforms, entry["year"], released_years)


def held_elsewhere():
    """Per year: the normalized titles and article titles the other layers
    (the year tables and release lists) already hold -- no point fetching an
    infobox for a game the archive has, since it would never be added."""
    keys, wiki = {}, {}
    for year in sources.available_years():
        entries = sources.load_year(year)
        keys[year] = {norm_title(e["title"]) for e in entries}
        wiki[year] = {e["wiki_title"].strip().lower() for e in entries if e.get("wiki_title")}
    return keys, wiki


def run_infoboxes(years, reparse):
    keys, wiki = held_elsewhere()
    unknown_platforms = {}

    def held(entry):
        y = entry["year"]
        return any(norm_title(entry["title"]) in keys.get(yy, ()) or entry["wiki_title"].strip().lower() in wiki.get(yy, ())
                   for yy in (y - 1, y, y + 1))

    for year in years:
        out_path = OUT_DIR / f"{year}.json"
        if not out_path.exists():
            continue
        entries = json.loads(out_path.read_text(encoding="utf-8"))
        cache = load_cache(year)
        if reparse:  # offline: redo whatever was already fetched
            wanted = [e for e in entries if e["wiki_title"] in cache]
        else:
            wanted = [e for e in entries if not e.get("infobox_done") and not held(e)]
        to_fetch = [e["wiki_title"] for e in wanted if e["wiki_title"] not in cache]
        try:
            for i in range(0, len(to_fetch), BATCH):
                cache.update(fetch_infoboxes(to_fetch[i:i + BATCH]))
                save_cache(year, cache)
                time.sleep(DELAY)
        except RuntimeError as exc:
            print(f"{year}: {exc}; progress is saved, rerun to continue", flush=True)
            break
        for entry in wanted:
            if entry["wiki_title"] in cache:
                apply_infobox(entry, cache[entry["wiki_title"]], unknown_platforms)
        out_path.write_text(json.dumps(entries, indent=2, ensure_ascii=False), encoding="utf-8")
        tagged = sum(1 for e in wanted if e.get("platforms"))
        print(f"{year}: {len(wanted)} infoboxes read ({len(to_fetch)} fetched), {tagged} with a platform tag, "
              f"{sum(1 for e in entries if held(e))} already held elsewhere", flush=True)

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    ranked = dict(sorted(unknown_platforms.items(), key=lambda kv: -kv[1])[:400])
    (LOG_DIR / "unknown_infobox_platforms.json").write_text(json.dumps(ranked, indent=2, ensure_ascii=False), encoding="utf-8")


def main(argv=None):
    parser = argparse.ArgumentParser(description="Scrape Wikipedia's per-year video game categories.")
    parser.add_argument("years", type=int, nargs="*", help="years to process (default: all)")
    parser.add_argument("--refresh", action="store_true", help="re-list years that already have data")
    parser.add_argument("--infoboxes", action="store_true", help="phase 2: fetch infobox details for listed articles")
    parser.add_argument("--reparse", action="store_true", help="re-apply the parser to cached infoboxes (no network)")
    args = parser.parse_args(argv)
    years = args.years or list(range(START_YEAR, END_YEAR + 1))
    if args.infoboxes or args.reparse:
        run_infoboxes(years, args.reparse)
    else:
        run_members(years, args.refresh)


if __name__ == "__main__":
    main()
