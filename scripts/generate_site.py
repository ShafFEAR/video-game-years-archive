"""Generate the browsable site (README index, one Markdown page per year,
one Markdown page per platform, and an interactive HTML filter page) from
the scraped/enriched JSON data. Safe to re-run any time -- it only reads
data/ and rewrites README.md, years/*.md, platforms/*.md,
data/all_games.json, data/web/*.js and index.html.

The Wikipedia layers (year tables, release lists, category pages) and any
saved Steam/RAWG enrichment are merged by sources.load_all(), so cover
art/synopses show up the moment enrich_rawg.py and/or enrich_steam.py have
been run. data/igdb/{year}.json (written by fetch_igdb.py) is merged in at
render time: titles Wikipedia doesn't have are added, and ones it does have
gain IGDB's cover/summary.

Pages GitHub would refuse to render (a year or platform too big for one
Markdown file) are split into an index plus smaller pages; index.html loads
one data/web/{year}.js at a time rather than carrying every title inline.
"""
import json
import re
import shutil
import sys
from collections import Counter, OrderedDict, defaultdict
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, str(Path(__file__).resolve().parent))
import sources
from platforms import available_in_year, slugify
from titles import norm_title

ROOT = Path(__file__).resolve().parent.parent
IGDB_DIR = ROOT / "data" / "igdb"
LOOKUP_DIR = ROOT / "data" / "igdb_lookup"
YEARS_DIR = ROOT / "years"
PLATFORMS_DIR = ROOT / "platforms"
# GitHub stops rendering Markdown files somewhere around 512 KB; stay well under.
PLATFORM_PAGE_LIMIT = 400_000
YEAR_PAGE_LIMIT = 400_000


def load_all_years():
    by_year = sources.load_all()
    for entries in by_year.values():
        for entry in entries:
            entry["source"] = "wikipedia"
    return by_year


def igdb_entry(rec):
    """An IGDB title Wikipedia doesn't have, shaped like a Wikipedia-scraped
    entry so every renderer below treats the two alike."""
    release_date = rec.get("release_date_text")
    if rec.get("status") == "upcoming" and (rec.get("first_release_date") or "").endswith("-12-31"):
        # IGDB files "sometime this year" under December 31; showing that as
        # an exact date would claim precision it doesn't have.
        release_date = f"{rec['year']} (date TBA)"
    return {
        "year": rec["year"],
        "section": "IGDB notable releases",
        "title": rec["title"],
        "wiki_title": None,
        "wiki_url": None,
        "redlink": None,
        "platform_breakdown": {},
        "platforms": rec["platforms"],
        "developer": rec.get("developer"),
        "publisher": rec.get("publisher"),
        "genre": ", ".join(rec["genres"]) or None,
        "release_date": release_date,
        "release_label": "Expected" if rec.get("status") == "upcoming" else "Released",
        "source": "igdb",
        "igdb": rec,
    }


def apply_lookups(by_year):
    """Attach the IGDB records scripts/lookup_igdb.py verified (by name, year,
    developer and platforms) for games that came from Wikipedia's category
    pages, which have no cover or summary of their own. An entry with no
    platform tag borrows IGDB's, minus platforms that didn't exist yet in the
    game's year. Returns how many entries got a record."""
    attached = 0
    for year, entries in by_year.items():
        path = LOOKUP_DIR / f"{year}.json"
        if not path.exists():
            continue
        found = json.loads(path.read_text(encoding="utf-8"))
        for entry in entries:
            rec = found.get(entry.get("wiki_title") or "") if entry.get("from_category") else None
            if not isinstance(rec, dict):
                continue
            entry["igdb"] = rec
            if not entry["platforms"]:
                entry["platforms"] = available_in_year(rec["platforms"], entry["year"])
            attached += 1
    return attached


def merge_igdb(by_year):
    """Fold data/igdb/ into the Wikipedia-sourced years; returns the merged
    years and how many titles were newly added.

    A title already in the Wikipedia data -- same year or either neighbor,
    since IGDB dates a game by its earliest release anywhere while a year's
    Wikipedia article often lists the regional one -- is matched by exact
    normalized title. It keeps its Wikipedia platform tags (IGDB's platform
    list is per-game, not per-year; an entry with none borrows IGDB's) and
    gains IGDB's cover/summary as enrichment. Everything else becomes a new
    entry -- unless lookup_igdb.py already attached that very IGDB game to a
    Wikipedia entry under another name ("Lemmings 3D" for "3D Lemmings")."""
    apply_lookups(by_year)
    records = {}
    for path in sorted(IGDB_DIR.glob("*.json"), key=lambda p: int(p.stem)):
        records[int(path.stem)] = json.loads(path.read_text(encoding="utf-8"))
    if not records:
        return by_year, 0

    existing = defaultdict(dict)  # normalized title -> {year: entry}
    claimed = set()               # IGDB ids already attached to a Wikipedia entry
    for year, entries in by_year.items():
        for entry in entries:
            existing[norm_title(entry["title"])].setdefault(year, entry)
            if entry.get("igdb"):
                claimed.add(entry["igdb"].get("igdb_id"))

    added = 0
    for year, recs in records.items():
        for rec in recs:
            key = norm_title(rec["title"])
            match = next((existing[key][y] for y in (year, year - 1, year + 1) if y in existing.get(key, {})), None)
            if match is not None:
                match.setdefault("igdb", rec)
                if not match["platforms"]:
                    # No platform tag means the console filter can't find it; borrow
                    # IGDB's, minus platforms that didn't exist yet in the game's year.
                    match["platforms"] = available_in_year(rec["platforms"], match["year"])
                continue
            if rec.get("igdb_id") in claimed:
                continue
            entry = igdb_entry(rec)
            by_year.setdefault(year, []).append(entry)
            existing[key][year] = entry
            added += 1
    return OrderedDict(sorted(by_year.items())), added


def get_enrichment(entry):
    """Normalize whichever enrichment sources are present (RAWG, Steam
    and/or IGDB) into one shape for rendering. RAWG is preferred for the
    description/genres, since it covers every platform rather than just
    Steam/Windows titles, then Steam, then IGDB; every source's store/page
    link is surfaced on its own, and cover art falls back the same way."""
    rawg = entry.get("rawg")
    steam = entry.get("steam")
    igdb = entry.get("igdb")
    if not rawg and not steam and not igdb:
        return None
    image_path = (rawg or {}).get("image_path") or (steam or {}).get("image_path") or (igdb or {}).get("cover_url")
    description, description_source = None, None
    for label, text in (
        ("RAWG", (rawg or {}).get("description")),
        ("Steam", (steam or {}).get("short_description")),
        ("IGDB", (igdb or {}).get("summary")),
    ):
        if text:
            description, description_source = text, label
            break
    genres = (rawg or {}).get("genres") or (steam or {}).get("genres") or (igdb or {}).get("genres") or []
    links = []
    if rawg and rawg.get("site_url"):
        links.append(("RAWG", rawg["site_url"]))
    if steam and steam.get("site_url"):
        links.append(("Steam", steam["site_url"]))
    if igdb and igdb.get("url"):
        links.append(("IGDB", igdb["url"]))
    return {
        "image_path": image_path,
        "description": description,
        "description_source": description_source,
        "genres": genres,
        "links": links,
    }


def escape_md(text):
    if not text:
        return ""
    return str(text).replace("|", "\\|").replace("\n", " ").strip()


def render_entry(entry, show_year=False, root="../"):
    lines = []
    title = entry.get("title") or "(untitled)"
    lines.append(f"### {escape_md(title)}")
    lines.append("")

    enrichment = get_enrichment(entry)
    if enrichment and enrichment["image_path"]:
        # years/*.md and platforms/*.md live one level below the repo root
        # (same as years/ did in the anime archive), so a local image under
        # images/ is "../" from there; the per-year pages of a split
        # platform sit one level deeper and pass root="../../". IGDB covers
        # are hotlinked absolute URLs instead.
        src = enrichment["image_path"]
        if not src.startswith("http"):
            src = root + src
        lines.append(f'<img src="{src}" alt="{escape_md(title)} cover" width="200">')
        lines.append("")

    meta_bits = []
    if show_year:
        meta_bits.append(f"**Year:** {entry['year']}")
    if entry.get("platforms"):
        meta_bits.append(f"**Platforms:** {escape_md(', '.join(entry['platforms']))}")
    if entry.get("developer"):
        meta_bits.append(f"**Developer:** {escape_md(entry['developer'])}")
    if entry.get("developer_publisher"):
        meta_bits.append(f"**Developer/Publisher:** {escape_md(entry['developer_publisher'])}")
    if entry.get("publisher"):
        meta_bits.append(f"**Publisher:** {escape_md(entry['publisher'])}")
    genre_text = entry.get("genre") or (", ".join(enrichment["genres"]) if enrichment and enrichment["genres"] else None)
    if genre_text:
        meta_bits.append(f"**Genre:** {escape_md(genre_text)}")
    if entry.get("type") and entry["type"] not in ("Original", "Full release"):
        meta_bits.append(f"**Type:** {escape_md(entry['type'])}")
    if entry.get("release_date"):
        when = escape_md(entry["release_date"])
        if entry.get("region"):
            when += f" ({escape_md(entry['region'])})"
        meta_bits.append(f"**{entry.get('release_label', 'Released')}:** {when}")
    if meta_bits:
        lines.append(" &nbsp;|&nbsp; ".join(meta_bits))
        lines.append("")

    if enrichment and enrichment["description"]:
        lines.append(f"> {escape_md(enrichment['description'])}")
        lines.append(">")
        lines.append(f"> _Synopsis source: {enrichment['description_source']}_")
        lines.append("")

    links = []
    if entry.get("wiki_url") and not entry.get("redlink"):
        links.append(f"[Wikipedia]({entry['wiki_url']})")
    if enrichment:
        links.extend(f"[{label}]({url})" for label, url in enrichment["links"])
    if links:
        lines.append(" · ".join(links))
        lines.append("")
    lines.append("---")
    lines.append("")
    return "\n".join(lines)


QUARTERS = {1: "January–March", 2: "April–June", 3: "July–September", 4: "October–December"}
_MONTHS = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}


def entry_quarter(entry):
    """1-4 from the release date text ("January 2", "March 4, 2014"), or None
    when it has no month ("2028 (date TBA)", "Q3", blank)."""
    match = re.match(r"\s*([A-Za-z]{3})", entry.get("release_date") or "")
    month = _MONTHS.get(match.group(1).lower()) if match else None
    return (month - 1) // 3 + 1 if month else None


def content_budget(limit):
    """Bytes of entries that fit on a page capped at `limit`, leaving room for its header."""
    return max(limit // 2, limit - 1000)


def paginate(entries, render, limit):
    """Split title-ordered entries into pages whose rendered Markdown stays
    under `limit` bytes: [[(entry, markdown), ...], ...]."""
    pages, current, size = [], [], 0
    for entry in entries:
        text = render(entry)
        n = len(text.encode("utf-8"))
        if current and size + n > limit:
            pages.append(current)
            current, size = [], 0
        current.append((entry, text))
        size += n
    if current:
        pages.append(current)
    return pages


def _initial(entry):
    first = entry["title"].lstrip()[:1].upper()
    return first if first.isalpha() else "#"


def span_label(page):
    """"A–F" for a page of title-ordered entries."""
    first, last = _initial(page[0][0]), _initial(page[-1][0])
    return first if first == last else f"{first}–{last}"


def generate_year_page(year, entries):
    from_igdb = sum(1 for e in entries if e.get("source") == "igdb")
    from_category = sum(1 for e in entries if e.get("from_category"))
    sources_line = f"[source](https://en.wikipedia.org/wiki/{year}_in_video_games)"
    if (sources.LISTS_DIR / f"{year}.json").exists():
        sources_line += f" · [release list](https://en.wikipedia.org/wiki/List_of_video_games_released_in_{year})"
    if (sources.CATEGORIES_DIR / f"{year}.json").exists():
        sources_line += f" · [category](https://en.wikipedia.org/wiki/Category:{year}_video_games)"
    extras = []
    if from_category:
        extras.append(f"{from_category} from Wikipedia's category page")
    if from_igdb:
        extras.append(f"{from_igdb} added from [IGDB](https://www.igdb.com)")
    intro = f"{len(entries)} titles" + (f" ({', '.join(extras)})" if extras else "") + f" · {sources_line}"
    ordered = sorted(entries, key=lambda e: e["title"].lower())
    lines = [f"# {year} in Video Games", "", "[← Back to index](../README.md)", "", intro, ""]
    lines += [render_entry(entry) for entry in ordered]
    page = "\n".join(lines)

    YEARS_DIR.mkdir(parents=True, exist_ok=True)
    page_path = YEARS_DIR / f"{year}.md"
    year_dir = YEARS_DIR / str(year)
    if len(page.encode("utf-8")) <= YEAR_PAGE_LIMIT:
        page_path.write_text(page, encoding="utf-8")
        if year_dir.is_dir():  # left over from when this year was big enough to split
            shutil.rmtree(year_dir)
        return

    # Too big for GitHub to render as one page: years/{year}.md becomes an
    # index (so existing links keep working) with one page per release
    # quarter -- and per title range within a quarter that is still too big
    # (games with no release month all land in one bucket).
    groups = defaultdict(list)
    for entry in ordered:
        groups[entry_quarter(entry)].append(entry)
    index = lines[:4] + [intro, "", "That's too many titles for one page, so it's split by release quarter.", "",
                         "| Release period | Titles |", "|---|---|"]
    if year_dir.is_dir():
        shutil.rmtree(year_dir)  # every page below is rewritten; drop leftovers from an older layout
    year_dir.mkdir()
    for quarter in (1, 2, 3, 4, None):
        if not groups.get(quarter):
            continue
        name = QUARTERS.get(quarter, "No release month listed")
        stem = f"q{quarter}" if quarter else "undated"
        pages = paginate(groups[quarter], lambda e: render_entry(e, root="../../"), content_budget(YEAR_PAGE_LIMIT))
        for number, part in enumerate(pages, 1):
            file_stem = stem if len(pages) == 1 else f"{stem}-{number}"
            label = name if len(pages) == 1 else f"{name}, {span_label(part)}"
            index.append(f"| [{label}]({year}/{file_stem}.md) | {len(part)} |")
            page_lines = [f"# {year} in Video Games — {label}", "",
                          f"[← All of {year}](../{year}.md) · [Back to index](../../README.md)", "",
                          f"{len(part)} titles.", ""]
            page_lines += [text for _, text in part]
            (year_dir / f"{file_stem}.md").write_text("\n".join(page_lines), encoding="utf-8")
    page_path.write_text("\n".join(index) + "\n", encoding="utf-8")


def generate_platform_pages(by_year):
    by_platform = defaultdict(lambda: defaultdict(list))
    for year, entries in by_year.items():
        for entry in entries:
            for plat in entry["platforms"]:
                by_platform[plat][year].append(entry)

    PLATFORMS_DIR.mkdir(parents=True, exist_ok=True)
    platform_meta = {}
    for plat, years in by_platform.items():
        slug = slugify(plat)
        total = sum(len(v) for v in years.values())
        platform_meta[plat] = {"slug": slug, "count": total}
        lines = [
            f"# {plat}",
            "",
            "[← Back to index](../README.md)",
            "",
            f"{total} titles across {len(years)} years in this archive.",
            "",
        ]
        for year in sorted(years.keys(), reverse=True):
            lines.append(f"## {year}")
            lines.append("")
            lines.append(f"[Full {year} page](../years/{year}.md)")
            lines.append("")
            for entry in sorted(years[year], key=lambda e: e["title"].lower()):
                lines.append(render_entry(entry))
        page = "\n".join(lines)
        page_path = PLATFORMS_DIR / f"{slug}.md"
        year_dir = PLATFORMS_DIR / slug

        if len(page.encode("utf-8")) <= PLATFORM_PAGE_LIMIT:
            page_path.write_text(page, encoding="utf-8")
            if year_dir.is_dir():  # left over from when this platform was big enough to split
                shutil.rmtree(year_dir)
            continue

        # Too big for GitHub to render as one page: platforms/{slug}.md
        # becomes an index of years (so existing links keep working) with
        # one page per year under platforms/{slug}/.
        index = lines[:4] + [
            f"{total} titles across {len(years)} years in this archive. That's too many for one "
            "page, so each year has its own.",
            "",
            "| Year | Titles |",
            "|---|---|",
        ]
        if year_dir.is_dir():
            shutil.rmtree(year_dir)  # every page below is rewritten; drop leftovers from an older layout
        year_dir.mkdir()
        for year in sorted(years.keys(), reverse=True):
            ordered = sorted(years[year], key=lambda e: e["title"].lower())
            # A single busy year can still be too big for one page: split it by title range.
            pages = paginate(ordered, lambda e: render_entry(e, root="../../"), content_budget(PLATFORM_PAGE_LIMIT))
            for number, part in enumerate(pages, 1):
                file_stem = str(year) if len(pages) == 1 else f"{year}-{number}"
                label = str(year) if len(pages) == 1 else f"{year}, {span_label(part)}"
                index.append(f"| [{label}]({slug}/{file_stem}.md) | {len(part)} |")
                year_lines = [
                    f"# {plat} — {label}",
                    "",
                    f"[← All {plat} years](../{slug}.md) · [Full {year} page](../../years/{year}.md)",
                    "",
                    f"{len(part)} {plat} titles in {year}.",
                    "",
                ]
                year_lines += [text for _, text in part]
                (year_dir / f"{file_stem}.md").write_text("\n".join(year_lines), encoding="utf-8")
        page_path.write_text("\n".join(index) + "\n", encoding="utf-8")
    return platform_meta


def build_decade_map(years):
    decades = OrderedDict()
    for y in years:
        decade = (y // 10) * 10
        decades.setdefault(decade, []).append(y)
    return decades


def generate_readme(by_year, platform_meta):
    years = sorted(by_year.keys())
    decades = build_decade_map(years)
    total_entries = sum(len(v) for v in by_year.values())
    tagged = sum(1 for entries in by_year.values() for e in entries if e["platforms"])
    from_igdb = sum(1 for entries in by_year.values() for e in entries if e.get("source") == "igdb")
    from_category = sum(1 for entries in by_year.values() for e in entries if e.get("from_category"))
    from_steam = sum(1 for entries in by_year.values() for e in entries if e.get("steam"))
    igdb_matched = sum(1 for entries in by_year.values() for e in entries if e.get("igdb") and e.get("source") != "igdb")

    lines = [
        "# List of Years in Video Games",
        "",
        "An archive of video games organized by year, built from Wikipedia's "
        "[List of years in video games](https://en.wikipedia.org/wiki/List_of_years_in_video_games) "
        "index and each year's article, with every title tagged by platform "
        "so you can filter to just one console's releases for a given year."
        + (" Games with their own Wikipedia article that those tables miss are added from its per-year "
           "[video game categories](https://en.wikipedia.org/wiki/Category:Video_games_by_year)." if from_category else "")
        + (" Years Wikipedia covers thinly are topped up with notable titles from [IGDB](https://www.igdb.com)." if from_igdb else "")
        + (" IGDB also supplies covers and summaries for many of the listed games." if igdb_matched else ""),
        "",
        f"**{total_entries:,} titles** across {len(years)} years "
        f"({years[0]}-{years[-1]}), **{tagged:,}** tagged with at least one platform."
        + (
            " Beyond the year articles' own lists, "
            + " and ".join(
                part for part in (
                    f"{from_category:,} titles come from Wikipedia's category pages" if from_category else "",
                    f"{from_igdb:,} {'from' if from_category else 'titles come from'} IGDB" if from_igdb else "",
                ) if part
            )
            + "."
            if from_category or from_igdb else ""
        ),
        "",
        "**[Open the interactive filter →](index.html)** -- pick a year "
        "and a platform and browse matching titles in the browser (works by "
        "opening the file directly, or via GitHub Pages if you enable it in "
        "the repo settings -- Settings -> Pages -> Deploy from a branch -> "
        "root).",
        "",
    ]
    for decade in sorted(decades.keys()):
        lines.append(f"## {decade}s")
        lines.append("")
        links = [f"[{y}](years/{y}.md)" for y in sorted(decades[decade])]
        lines.append(" · ".join(links))
        lines.append("")

    lines.append("## Browse by platform")
    lines.append("")
    lines.append("| Platform | Titles |")
    lines.append("|---|---|")
    for plat, meta in sorted(platform_meta.items(), key=lambda kv: -kv[1]["count"]):
        lines.append(f"| [{plat}](platforms/{meta['slug']}.md) | {meta['count']} |")
    lines.append("")

    list_years = sorted(int(p.stem) for p in sources.LISTS_DIR.glob("*.json"))
    if list_years:
        gap_note = (
            "- Wikipedia's \"X in video games\" articles carry an exhaustive "
            "month-by-month release table only through **2011**. From "
            f"{list_years[0]} on those lists live in separate \"List of video "
            "games released in X\" articles, which this archive scrapes too "
            "(`scripts/scrape_lists.py`), so those years have hundreds of "
            "titles each. Earlier years rely on the original articles' "
            "tables, which are thinner -- especially in the early 1990s."
        )
    else:
        gap_note = (
            "- Wikipedia stopped maintaining an exhaustive month-by-month release "
            "table on most \"X in video games\" articles after **2011**, so "
            "per-year counts drop sharply after that -- a real gap in the "
            "source data, not a scraper bug."
        )
    if from_category:
        gap_note += (
            " Even so, plenty of games with their own article appear in neither, so the "
            "archive also adds every game in Wikipedia's \"YYYY video games\" categories "
            "that those tables miss (`scripts/scrape_categories.py`)."
        )
    if from_igdb:
        gap_note += (
            " Years that are still thin are topped up with the most-rated "
            "titles IGDB has for them, so their counts reflect notability, "
            "not a complete release list."
        )
    category_note = (
        "- Titles added from the category pages take their developer, publisher, genre, "
        "release date and platforms from the article's infobox. That infobox lists every "
        "platform a game ever reached, so platforms that did not exist yet in the game's year "
        "are dropped -- but a later port to an older platform can still show up under the "
        "original year, and many of these titles have no release month."
        if from_category else None
    )
    category_matched = sum(1 for entries in by_year.values() for e in entries if e.get("from_category") and e.get("igdb"))
    igdb_note = (
        f"- {category_matched:,} of the {from_category:,} games added from the category pages have an IGDB record "
        "(nearly all with a cover, most with a summary). A game gets one only when IGDB holds it under the same (or an "
        "alternative) name in the same or an adjacent year and nothing else fits equally well -- same-name games are "
        "common -- so the rest stay text-only rather than risk showing the wrong game."
        if from_category and category_matched else None
    )
    no_wiki_years = [y for y in years if not any(e.get("source") == "wikipedia" for e in by_year[y])]
    empty_years_note = None
    if no_wiki_years:
        empty_years_note = (
            f"- {', '.join(str(y) for y in no_wiki_years)} "
            f"{'has' if len(no_wiki_years) == 1 else 'have'} no structured release "
            "table on Wikipedia at all and so " + ("contributes" if len(no_wiki_years) == 1 else "contribute") + " no Wikipedia titles"
            + (" (any titles in those years come from IGDB)." if from_igdb else " here.")
        )

    attribution = [
        "- Year-by-year title listings and platform tags are drawn from "
        "Wikipedia's \"X in video games\" articles"
        + (" and, from " + str(list_years[0]) + " on, its \"List of video games released in X\" articles" if list_years else "")
        + (", plus its \"YYYY video games\" category pages and the infobox of each article they list" if from_category else "")
        + " (text available under "
        "[CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/)).",
    ]
    if from_steam:
        attribution.append(
            f"- Steam store links, cover art and descriptions for {from_steam:,} "
            "titles come from Steam's own public Storefront API "
            "(`scripts/enrich_steam.py`). SteamDB's FAQ says it doesn't allow "
            "scraping, so Steam's API is used instead."
        )
    if from_igdb or igdb_matched:
        supplies = []
        if from_igdb:
            supplies.append(f"{from_igdb:,} additional titles, with platform tags, summaries and cover art")
        if igdb_matched:
            supplies.append(
                f"covers, summaries and links for {igdb_matched:,} Wikipedia-sourced titles that it holds under the "
                "same (or an alternative) name and release year"
            )
        attribution.append(
            "- [IGDB](https://www.igdb.com) supplies " + ", plus ".join(supplies) + ". It is used through the "
            "Twitch/IGDB API (`scripts/fetch_igdb.py`, `scripts/lookup_igdb.py`) under IGDB's API "
            "terms for non-commercial purposes. Cover art is hotlinked from "
            "IGDB's image CDN rather than copied here and belongs to its "
            "rights-holders."
        )
    else:
        attribution.append(
            "- `scripts/fetch_igdb.py` can add notable titles for the years "
            "Wikipedia covers thinly from [IGDB](https://www.igdb.com) once "
            "free Twitch developer credentials are supplied (see the top of "
            "the script)."
        )
    attribution.append(
        "- `scripts/enrich_rawg.py` can add cover art and synopses for "
        "every platform from [RAWG](https://rawg.io/apidocs) given a free "
        "API key. Creating the IGDB and RAWG accounts has to happen on the "
        "repo owner's end."
    )
    attribution.append(
        "- This is an unofficial, non-commercial fan archive/index, not "
        "affiliated with Wikipedia, the Wikimedia Foundation, Valve/Steam, "
        "IGDB/Twitch, or RAWG."
    )

    lines += [
        "## Coverage notes",
        "",
        gap_note,
        *([category_note] if category_note else []),
        *([igdb_note] if igdb_note else []),
        *([empty_years_note] if empty_years_note else []),
        "- Platform tags come from each article's own abbreviation legend "
        "(e.g. \"PS2\", \"WIN\") plus a curated lookup table for consistency "
        "across years; see `scripts/platforms.py`.",
        "",
        "## Rebuilding the data",
        "",
        "Each stage reads and writes JSON under `data/`, and every scraper can be "
        "re-run on its own (they take a list of years, and resume or skip what is already there):",
        "",
        "```",
        "python scripts/scrape_index.py                       # \"YYYY in video games\" tables      -> data/index/",
        "python scripts/scrape_lists.py                       # \"List of video games released in YYYY\" -> data/lists/",
        "python scripts/scrape_categories.py                  # \"Category:YYYY video games\" members     -> data/categories/",
        "python scripts/scrape_categories.py --infoboxes      # developer, publisher, genre, platforms for those articles",
        "python scripts/fetch_igdb.py                         # optional: notable titles from IGDB (needs Twitch credentials in .env)",
        "python scripts/lookup_igdb.py                        # optional: IGDB covers and summaries for the category-sourced games",
        "python scripts/generate_site.py                      # README, years/, platforms/, data/web/ and index.html",
        "```",
        "",
        "## Attribution & licensing",
        "",
        *attribution,
        "",
    ]
    (ROOT / "README.md").write_text("\n".join(lines), encoding="utf-8")


def generate_interactive_page(by_year):
    flat = []
    for year, entries in by_year.items():
        for e in entries:
            enrichment = get_enrichment(e)
            flat.append({
                "year": year,
                "title": e["title"],
                "platforms": e["platforms"],
                "developer": e.get("developer") or e.get("developer_publisher"),
                "publisher": e.get("publisher"),
                "genre": e.get("genre") or (", ".join(enrichment["genres"]) if enrichment and enrichment["genres"] else None),
                "release_date": e.get("release_date"),
                "url": (e.get("wiki_url") if not e.get("redlink") else None)
                or (enrichment["links"][0][1] if enrichment and enrichment["links"] else None),
                "image": enrichment["image_path"] if enrichment else None,
                "description": enrichment["description"] if enrichment else None,
                "source": e.get("source"),
            })
    flat.sort(key=lambda e: (e["year"], e["title"].lower()))
    from_igdb = sum(1 for e in flat if e["source"] == "igdb")

    # data/all_games.json: the whole archive in one file, a record per line so diffs stay readable.
    all_games = "[\n" + ",\n".join(json.dumps(rec, ensure_ascii=False) for rec in flat) + "\n]\n"
    (ROOT / "data" / "all_games.json").write_text(all_games, encoding="utf-8")

    # index.html loads one data/web/<year>.js at a time (see page_template.html),
    # so opening the page never has to parse the whole archive.
    web_dir = ROOT / "data" / "web"
    web_dir.mkdir(parents=True, exist_ok=True)
    flat_by_year = defaultdict(list)
    for e in flat:
        flat_by_year[e["year"]].append(e)
    years_meta = []
    for year, recs in flat_by_year.items():
        compact = []
        for e in recs:
            rec = {"t": e["title"], "p": e["platforms"]}
            for key, field in (("d", "developer"), ("u", "publisher"), ("g", "genre"), ("r", "release_date"),
                               ("l", "url"), ("i", "image"), ("s", "description")):
                if e[field]:
                    rec[key] = e[field]
            if "i" in rec:
                # IGDB serves each cover in several sizes; a 64px thumbnail needs the small one.
                rec["i"] = rec["i"].replace("/t_cover_big/", "/t_cover_small/")
            compact.append(rec)
        data = json.dumps(compact, ensure_ascii=False, separators=(",", ":"))
        (web_dir / f"{year}.js").write_text(f"(window.GAMES = window.GAMES || {{}})[{year}] = {data};\n", encoding="utf-8")
        counts = Counter(p for e in recs for p in e["platforms"])
        years_meta.append({"y": year, "n": len(recs), "p": dict(sorted(counts.items()))})
    for stale in web_dir.glob("*.js"):
        if int(stale.stem) not in flat_by_year:
            stale.unlink()

    footer = [
        'Game listings from <a href="https://en.wikipedia.org/wiki/List_of_years_in_video_games" target="_blank" '
        'rel="noopener">Wikipedia</a> (<a href="https://creativecommons.org/licenses/by-sa/4.0/" target="_blank" '
        'rel="noopener">CC BY-SA 4.0</a>).'
    ]
    igdb_used = any(e.get("igdb") for entries in by_year.values() for e in entries)
    if igdb_used:
        footer.append(
            'Cover art, summaries'
            + (', platform tags and additional titles' if from_igdb else '')
            + ' from <a href="https://www.igdb.com" target="_blank" rel="noopener">IGDB.com</a>. '
            'Cover art belongs to its rights-holders.'
        )
    template = (Path(__file__).resolve().parent / "page_template.html").read_text(encoding="utf-8")
    html = (
        template.replace("@@TOTAL@@", f"{len(flat):,}")
        .replace("@@SOURCES@@", "from Wikipedia's video game articles and categories" + (" and IGDB" if igdb_used else ""))
        .replace("@@FOOTER@@", '<footer class="foot">' + " ".join(footer) + "</footer>")
        .replace("@@YEARS_JSON@@", json.dumps(years_meta, ensure_ascii=False, separators=(",", ":")))
    )
    (ROOT / "index.html").write_text(html, encoding="utf-8")


def main():
    by_year, igdb_added = merge_igdb(load_all_years())
    if igdb_added:
        print(f"Merged {igdb_added} titles from IGDB (data/igdb/).")
    platform_meta = generate_platform_pages(by_year)
    for year, entries in by_year.items():
        generate_year_page(year, entries)
        print(f"{year}: page generated ({len(entries)} entries)")
    generate_readme(by_year, platform_meta)
    generate_interactive_page(by_year)
    print(f"\nREADME.md, {len(by_year)} year pages, {len(platform_meta)} platform pages, "
          f"data/all_games.json, data/web/*.js, and index.html generated.")
    for directory in (YEARS_DIR, PLATFORMS_DIR):
        for page in sorted(directory.rglob("*.md")):
            if page.stat().st_size > 450_000:
                print(f"WARNING: {page.relative_to(ROOT)} is {page.stat().st_size // 1024} KB; "
                      "GitHub may not render Markdown files this large.")


if __name__ == "__main__":
    main()
