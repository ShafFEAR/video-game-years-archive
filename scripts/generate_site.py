"""Generate the browsable site (README index, one Markdown page per year,
one Markdown page per platform, and an interactive HTML filter page) from
the scraped/enriched JSON data. Safe to re-run any time -- it only reads
data/index/ (and data/enriched/ when present) and rewrites README.md,
years/*.md, platforms/*.md, data/all_games.json, and index.html.

Automatically picks up cover art/synopses the moment enrich_rawg.py and/or
enrich_steam.py have been run: each year prefers data/enriched/{year}.json
over data/index/{year}.json when it exists, so nothing here needs to change
once enrichment data shows up. Likewise data/igdb/{year}.json (written by
fetch_igdb.py) is merged in at render time: titles Wikipedia doesn't have
are added, and ones it does have gain IGDB's cover/summary.
"""
import json
import sys
from collections import OrderedDict, defaultdict
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, str(Path(__file__).resolve().parent))
from platforms import slugify
from titles import norm_title

ROOT = Path(__file__).resolve().parent.parent
INDEX_DIR = ROOT / "data" / "index"
ENRICHED_DIR = ROOT / "data" / "enriched"
IGDB_DIR = ROOT / "data" / "igdb"
YEARS_DIR = ROOT / "years"
PLATFORMS_DIR = ROOT / "platforms"


def load_all_years():
    by_year = OrderedDict()
    years = {int(p.stem) for p in INDEX_DIR.glob("*.json")} | {int(p.stem) for p in ENRICHED_DIR.glob("*.json")}
    for year in sorted(years):
        enriched_path = ENRICHED_DIR / f"{year}.json"
        source = enriched_path if enriched_path.exists() else INDEX_DIR / f"{year}.json"
        by_year[year] = json.loads(source.read_text(encoding="utf-8"))
        for entry in by_year[year]:
            entry["source"] = "wikipedia"
    return by_year


def igdb_entry(rec):
    """An IGDB title Wikipedia doesn't have, shaped like a Wikipedia-scraped
    entry so every renderer below treats the two alike."""
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
        "release_date": rec.get("release_date_text"),
        "source": "igdb",
        "igdb": rec,
    }


def merge_igdb(by_year):
    """Fold data/igdb/ into the Wikipedia-sourced years; returns the merged
    years and how many titles were newly added.

    A title already in the Wikipedia data -- same year or either neighbor,
    since IGDB dates a game by its earliest release anywhere while a year's
    Wikipedia article often lists the regional one -- is matched by exact
    normalized title. It keeps its Wikipedia platform tags (IGDB's platform
    list is per-game, not per-year) and just gains IGDB's cover/summary as
    enrichment. Everything else becomes a new entry."""
    records = {}
    for path in sorted(IGDB_DIR.glob("*.json"), key=lambda p: int(p.stem)):
        records[int(path.stem)] = json.loads(path.read_text(encoding="utf-8"))
    if not records:
        return by_year, 0

    existing = defaultdict(dict)  # normalized title -> {year: entry}
    for year, entries in by_year.items():
        for entry in entries:
            existing[norm_title(entry["title"])].setdefault(year, entry)

    added = 0
    for year, recs in records.items():
        for rec in recs:
            key = norm_title(rec["title"])
            match = next((existing[key][y] for y in (year, year - 1, year + 1) if y in existing.get(key, {})), None)
            if match is not None:
                match.setdefault("igdb", rec)
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


def render_entry(entry, show_year=False):
    lines = []
    title = entry.get("title") or "(untitled)"
    lines.append(f"### {escape_md(title)}")
    lines.append("")

    enrichment = get_enrichment(entry)
    if enrichment and enrichment["image_path"]:
        # Both years/*.md and platforms/*.md live one level below the repo
        # root, same as years/ did in the anime archive, so a local image
        # under images/ is always "../" from here regardless of which page
        # is rendering. IGDB covers are hotlinked absolute URLs instead.
        src = enrichment["image_path"]
        if not src.startswith("http"):
            src = "../" + src
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
    if entry.get("release_date"):
        meta_bits.append(f"**Released:** {escape_md(entry['release_date'])}")
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


def generate_year_page(year, entries):
    from_igdb = sum(1 for e in entries if e.get("source") == "igdb")
    lines = [
        f"# {year} in Video Games",
        "",
        "[← Back to index](../README.md)",
        "",
        f"{len(entries)} titles"
        + (f" ({from_igdb} added from [IGDB](https://www.igdb.com))" if from_igdb else "")
        + f" · [source](https://en.wikipedia.org/wiki/{year}_in_video_games)",
        "",
    ]
    for entry in sorted(entries, key=lambda e: e["title"].lower()):
        lines.append(render_entry(entry))
    YEARS_DIR.mkdir(parents=True, exist_ok=True)
    (YEARS_DIR / f"{year}.md").write_text("\n".join(lines), encoding="utf-8")


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
        (PLATFORMS_DIR / f"{slug}.md").write_text("\n".join(lines), encoding="utf-8")
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
    from_steam = sum(1 for entries in by_year.values() for e in entries if e.get("steam"))

    lines = [
        "# List of Years in Video Games",
        "",
        "An archive of video games organized by year, built from Wikipedia's "
        "[List of years in video games](https://en.wikipedia.org/wiki/List_of_years_in_video_games) "
        "index and each year's article, with every title tagged by platform "
        "so you can filter to just one console's releases for a given year."
        + (" Years Wikipedia covers thinly are topped up with notable titles from [IGDB](https://www.igdb.com)." if from_igdb else ""),
        "",
        f"**{total_entries} titles** across {len(years)} years "
        f"({years[0]}-{years[-1]}), **{tagged}** tagged with at least one platform"
        + (f" ({from_igdb} of the titles were added from IGDB)." if from_igdb else "."),
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

    gap_note = (
        "- Wikipedia stopped maintaining an exhaustive month-by-month release "
        "table on most \"X in video games\" articles after **2011** -- the "
        "sheer volume of releases (digital storefronts, mobile, indies) made "
        "that impractical for editors to keep up by hand. For 2012 onward, "
        "this archive uses whatever curated release/score table each year's "
        "article still maintains (often a \"best-reviewed games\" chart), so "
        "per-year counts drop sharply after 2011 -- that's a real gap in the "
        "source data, not a scraper bug."
    )
    if from_igdb:
        gap_note += (
            " Those thin years are topped up with the most-rated titles IGDB "
            "has for them, so their counts reflect notability, not a "
            "complete release list."
        )
    empty_years_note = (
        "- A handful of years (1990, 1991, 1993, and 2027-2028) have no "
        "structured release table on Wikipedia at all and so contribute no "
        "Wikipedia titles"
        + (" (any titles in those years come from IGDB)." if from_igdb else " here.")
    )

    attribution = [
        "- Year-by-year title listings and platform tags are drawn from "
        "Wikipedia (text available under "
        "[CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/)).",
    ]
    if from_steam:
        attribution.append(
            f"- Steam store links, cover art and descriptions for {from_steam} "
            "titles come from Steam's own public Storefront API "
            "(`scripts/enrich_steam.py`). SteamDB's FAQ says it doesn't allow "
            "scraping, so Steam's API is used instead."
        )
    if from_igdb:
        attribution.append(
            f"- {from_igdb} additional titles, with platform tags, summaries and "
            "cover art, come from [IGDB](https://www.igdb.com) via the "
            "Twitch/IGDB API (`scripts/fetch_igdb.py`), used under IGDB's API "
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
        empty_years_note,
        "- Platform tags come from each article's own abbreviation legend "
        "(e.g. \"PS2\", \"WIN\") plus a curated lookup table for consistency "
        "across years; see `scripts/platforms.py`.",
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

    (ROOT / "data" / "all_games.json").write_text(
        json.dumps(flat, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    years_present = sorted({e["year"] for e in flat})
    platforms_present = sorted({p for e in flat for p in e["platforms"]})
    data_json = json.dumps(flat, ensure_ascii=False, separators=(",", ":"))

    html = HTML_TEMPLATE.format(
        total=len(flat),
        sources="sourced from Wikipedia's year-in-video-games archive" + (" and IGDB" if from_igdb else ""),
        footer=(
            '<footer class="foot">Additional titles, platform tags and cover art from '
            '<a href="https://www.igdb.com" target="_blank" rel="noopener">IGDB.com</a>. '
            'Cover art belongs to its rights-holders.</footer>'
            if from_igdb else ""
        ),
        year_options="\n".join(f'<option value="{y}">{y}</option>' for y in years_present),
        platform_options="\n".join(
            f'<option value="{escape_md(p)}">{escape_md(p)}</option>' for p in platforms_present
        ),
        data_json=data_json,
    )
    (ROOT / "index.html").write_text(html, encoding="utf-8")


HTML_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Video Games by Year</title>
<style>
  :root {{
    color-scheme: light dark;
    --bg: #f7f7f8; --panel: #ffffff; --text: #1a1a1a; --muted: #666666;
    --border: #e2e2e5; --accent: #3b5bfd; --tag-bg: #eef0ff; --tag-text: #33409e;
  }}
  @media (prefers-color-scheme: dark) {{
    :root {{
      --bg: #15161a; --panel: #1e2025; --text: #e9e9ec; --muted: #9a9aa2;
      --border: #303239; --accent: #7d93ff; --tag-bg: #262a44; --tag-text: #b7c0ff;
    }}
  }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0; background: var(--bg); color: var(--text);
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
  }}
  header {{ padding: 32px 24px 16px; max-width: 1000px; margin: 0 auto; }}
  h1 {{ margin: 0 0 4px; font-size: 1.6rem; }}
  .sub {{ color: var(--muted); font-size: 0.9rem; }}
  .controls {{
    max-width: 1000px; margin: 0 auto; padding: 0 24px 16px;
    display: flex; gap: 12px; flex-wrap: wrap; align-items: center;
  }}
  select {{
    padding: 8px 12px; border-radius: 8px; border: 1px solid var(--border);
    background: var(--panel); color: var(--text); font-size: 0.95rem; min-width: 180px;
  }}
  .count {{ color: var(--muted); font-size: 0.9rem; margin-left: auto; }}
  main {{ max-width: 1000px; margin: 0 auto; padding: 0 24px 48px; }}
  .grid {{
    display: grid; grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
    gap: 12px;
  }}
  .card {{
    background: var(--panel); border: 1px solid var(--border); border-radius: 10px;
    padding: 14px 16px; display: flex; gap: 12px;
  }}
  .cover {{
    width: 64px; height: 64px; object-fit: cover; border-radius: 6px; flex-shrink: 0;
  }}
  .card-body {{ min-width: 0; }}
  .card h3 {{ margin: 0 0 6px; font-size: 1rem; }}
  .card h3 a {{ color: var(--text); text-decoration: none; }}
  .card h3 a:hover {{ color: var(--accent); text-decoration: underline; }}
  .meta {{ color: var(--muted); font-size: 0.82rem; margin-bottom: 8px; }}
  .desc {{
    color: var(--muted); font-size: 0.8rem; margin: 6px 0; line-height: 1.4;
    display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden;
  }}
  .tags {{ display: flex; flex-wrap: wrap; gap: 4px; }}
  .tag {{
    background: var(--tag-bg); color: var(--tag-text); border-radius: 999px;
    padding: 2px 9px; font-size: 0.75rem;
  }}
  .empty {{ color: var(--muted); text-align: center; padding: 48px 0; }}
  .foot {{ max-width: 1000px; margin: 0 auto; padding: 0 24px 32px; color: var(--muted); font-size: 0.8rem; }}
  .foot a {{ color: var(--accent); }}
</style>
</head>
<body>
<header>
  <h1>Video Games by Year</h1>
  <div class="sub">{total} titles, {sources}. Filter by year and platform.</div>
</header>
<div class="controls">
  <select id="year"><option value="">All years</option>{year_options}</select>
  <select id="platform"><option value="">All platforms</option>{platform_options}</select>
  <span class="count" id="count"></span>
</div>
<main><div class="grid" id="grid"></div></main>
{footer}
<script>
const DATA = {data_json};
const yearSel = document.getElementById('year');
const platSel = document.getElementById('platform');
const grid = document.getElementById('grid');
const countEl = document.getElementById('count');

function render() {{
  const y = yearSel.value;
  const p = platSel.value;
  const filtered = DATA.filter(function(e) {{
    if (y && String(e.year) !== y) return false;
    if (p && e.platforms.indexOf(p) === -1) return false;
    return true;
  }});
  countEl.textContent = filtered.length + ' title' + (filtered.length === 1 ? '' : 's');
  if (!filtered.length) {{
    grid.innerHTML = '<div class="empty">No titles match that combination.</div>';
    return;
  }}
  grid.innerHTML = filtered.map(function(e) {{
    const titleHtml = e.url
      ? '<a href="' + e.url + '" target="_blank" rel="noopener">' + escapeHtml(e.title) + '</a>'
      : escapeHtml(e.title);
    const metaBits = [e.year];
    if (e.developer) metaBits.push(escapeHtml(e.developer));
    if (e.genre) metaBits.push(escapeHtml(e.genre));
    const tags = e.platforms.map(function(pl) {{
      return '<span class="tag">' + escapeHtml(pl) + '</span>';
    }}).join('');
    const cover = e.image
      ? '<img class="cover" src="' + e.image + '" alt="" loading="lazy" onerror="this.remove()">'
      : '';
    const desc = e.description
      ? '<div class="desc">' + escapeHtml(e.description) + '</div>'
      : '';
    return '<div class="card">' + cover +
      '<div class="card-body"><h3>' + titleHtml + '</h3>' +
      '<div class="meta">' + metaBits.join(' &middot; ') + '</div>' +
      desc +
      '<div class="tags">' + tags + '</div></div></div>';
  }}).join('');
}}

function escapeHtml(s) {{
  return String(s).replace(/[&<>"']/g, function(c) {{
    return {{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}}[c];
  }});
}}

yearSel.addEventListener('change', render);
platSel.addEventListener('change', render);
render();
</script>
</body>
</html>
"""


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
          f"data/all_games.json, and index.html generated.")


if __name__ == "__main__":
    main()
