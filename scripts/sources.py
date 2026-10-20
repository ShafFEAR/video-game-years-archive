"""Per-year Wikipedia entries merged from every Wikipedia-derived layer, with
saved enrichment re-attached. Shared by generate_site.py and the enrich_*
scripts so they all see the same entries.

Raw layers (rewritten whenever a scraper reruns; never edited by hand):
  data/index/{year}.json       "YYYY in video games" tables      (scrape_index.py)
  data/lists/{year}.json       "List of video games released in YYYY" (scrape_lists.py)
  data/categories/{year}.json  "Category:YYYY video games" members + infobox data (scrape_categories.py)
Enrichment store:
  data/enriched/{year}.json    entries carrying Steam/RAWG data   (enrich_*.py)

load_year() merges the table and list layers, then copies whatever enrichment
was saved onto the matching entries by normalized title. Re-scraping a layer
(cleaner titles, newly found entries) therefore neither loses enrichment nor
leaves the new entries invisible -- which is what happened while an enriched
file doubled as a stale snapshot of the whole entry list.

load_all() then adds the category layer, which is far bigger than the others
(every game with its own article) but has the least detail per game: only the
games the other layers don't already hold are added, and they never lend
platforms to games that are held.
"""
import json
import re
from collections import OrderedDict, defaultdict
from pathlib import Path

from titles import norm_title, strip_disambiguator, union_regions

ROOT = Path(__file__).resolve().parent.parent
INDEX_DIR = ROOT / "data" / "index"
LISTS_DIR = ROOT / "data" / "lists"
CATEGORIES_DIR = ROOT / "data" / "categories"
ENRICHED_DIR = ROOT / "data" / "enriched"

# Category members that are about something else: "Rampo (film)", "Exile (1995 video game series)".
_NOT_A_GAME_RE = re.compile(
    r"\((?:[^()]*\s)?(?:film|TV series|television series|miniseries|web series|novel|album|band|song|manga|anime|"
    r"comics?|comic book|magazine|musical|soundtrack|company|series|franchise)\)$",
    re.IGNORECASE,
)

ENRICHMENT_KEYS = ("steam", "rawg")
# Identity fields stay as the first-seen entry has them; everything else is
# only filled in when missing.
_NO_FILL = {"year", "section", "title", "wiki_title", "wiki_url", "redlink", "platforms", "platform_breakdown", "region"}


def _read(path):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else []


def available_years():
    """Years the table/list/enrichment layers cover (see all_years for categories too)."""
    return sorted({int(p.stem) for d in (INDEX_DIR, LISTS_DIR, ENRICHED_DIR) for p in d.glob("*.json")})


def all_years():
    return sorted(set(available_years()) | {int(p.stem) for p in CATEGORIES_DIR.glob("*.json")})


def merge_layer(entries, extra):
    """Fold a second Wikipedia article's entries for the same year into
    `entries` (in place). A title already present keeps its data and gains
    the other article's platforms and any fields it lacked; the rest are
    appended."""
    by_key = {norm_title(e["title"]): e for e in entries}
    for new in extra:
        key = norm_title(new["title"])
        existing = by_key.get(key)
        if existing is None:
            entries.append(new)
            by_key[key] = new
            continue
        for plat in new.get("platforms", []):
            if plat not in existing["platforms"]:
                existing["platforms"].append(plat)
        existing.setdefault("platform_breakdown", {}).update(new.get("platform_breakdown", {}))
        region = union_regions(existing.get("region"), new.get("region"))
        if region:
            existing["region"] = region
        if not existing.get("wiki_url") and new.get("wiki_url"):
            existing["wiki_title"], existing["wiki_url"], existing["redlink"] = new["wiki_title"], new["wiki_url"], new["redlink"]
        for field, value in new.items():
            if field not in _NO_FILL and value and not existing.get(field):
                existing[field] = value
    return entries


def load_year(year):
    entries = _read(INDEX_DIR / f"{year}.json")
    merge_layer(entries, _read(LISTS_DIR / f"{year}.json"))
    # Older enriched snapshots can hold the same title twice (one copy with
    # enrichment, one without), so keep whichever copy actually has some.
    saved = {}
    for old in _read(ENRICHED_DIR / f"{year}.json"):
        slot = saved.setdefault(norm_title(old["title"]), {})
        for key in ENRICHMENT_KEYS:
            if key in old and (old[key] or key not in slot):
                slot[key] = old[key]
    for entry in entries:
        entry.update(saved.get(norm_title(entry["title"]), {}))
    return entries


def _wiki_key(title):
    return (title or "").strip().lower()


def load_all():
    """{year: entries} from every layer, in year order.

    A category member is added only when the table/list layers don't already
    hold that game within a year either side (a game's category year is its
    first release, a list's can be a regional one). "Holds" means the same
    normalized title, or a link to the same article. Between category
    members only the article decides: two games can share a title, and a
    redirect page that points at an article already in the archive is a
    second name for it, not a second game."""
    years = OrderedDict((y, load_year(y)) for y in all_years())
    held_titles, held_articles = defaultdict(set), defaultdict(set)
    for year, entries in years.items():
        for entry in entries:
            held_titles[year].add(norm_title(entry["title"]))
            if entry.get("wiki_title"):
                held_articles[year].add(_wiki_key(entry["wiki_title"]))

    def held(year, holder, key):
        return any(key in holder[y] for y in (year - 1, year, year + 1))

    category = {year: _read(CATEGORIES_DIR / f"{year}.json") for year in years}
    for redirects in (False, True):  # real articles first, so a redirect is judged against all of them
        for year, entries in category.items():
            for entry in entries:
                target = entry.get("redirect_to")
                if bool(target) != redirects or _NOT_A_GAME_RE.search(entry["wiki_title"]):
                    continue
                if held(year, held_articles, _wiki_key(entry["wiki_title"])) or held(year, held_titles, norm_title(entry["title"])):
                    continue
                if target and (held(year, held_articles, _wiki_key(target)) or held(year, held_titles, norm_title(strip_disambiguator(target)))):
                    continue
                entry["from_category"] = True
                years[year].append(entry)
                held_articles[year].add(_wiki_key(entry["wiki_title"]))
    return years


def save_enrichment(year, entries):
    ENRICHED_DIR.mkdir(parents=True, exist_ok=True)
    (ENRICHED_DIR / f"{year}.json").write_text(json.dumps(entries, indent=2, ensure_ascii=False), encoding="utf-8")
