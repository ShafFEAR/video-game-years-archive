"""Per-year Wikipedia entries merged from every Wikipedia-derived layer, with
saved enrichment re-attached. Shared by generate_site.py and the enrich_*
scripts so they all see the same entries.

Raw layers (rewritten whenever a scraper reruns; never edited by hand):
  data/index/{year}.json     "YYYY in video games" tables      (scrape_index.py)
  data/lists/{year}.json     "List of video games released in YYYY" (scrape_lists.py)
Enrichment store:
  data/enriched/{year}.json  entries carrying Steam/RAWG data   (enrich_*.py)

load_year() merges the raw layers, then copies whatever enrichment was saved
onto the matching entries by normalized title. Re-scraping a layer (cleaner
titles, newly found entries) therefore neither loses enrichment nor leaves
the new entries invisible -- which is what happened while an enriched file
doubled as a stale snapshot of the whole entry list.
"""
import json
from pathlib import Path

from titles import norm_title, union_regions

ROOT = Path(__file__).resolve().parent.parent
INDEX_DIR = ROOT / "data" / "index"
LISTS_DIR = ROOT / "data" / "lists"
ENRICHED_DIR = ROOT / "data" / "enriched"

ENRICHMENT_KEYS = ("steam", "rawg")
# Identity fields stay as the first-seen entry has them; everything else is
# only filled in when missing.
_NO_FILL = {"year", "section", "title", "wiki_title", "wiki_url", "redlink", "platforms", "platform_breakdown", "region"}


def _read(path):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else []


def available_years():
    return sorted({int(p.stem) for d in (INDEX_DIR, LISTS_DIR, ENRICHED_DIR) for p in d.glob("*.json")})


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


def save_enrichment(year, entries):
    ENRICHED_DIR.mkdir(parents=True, exist_ok=True)
    (ENRICHED_DIR / f"{year}.json").write_text(json.dumps(entries, indent=2, ensure_ascii=False), encoding="utf-8")
