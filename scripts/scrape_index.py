"""Scrape Wikipedia's per-year video game release lists (1990-present) into
structured JSON, including a per-title platform list for filtering.

Source: https://en.wikipedia.org/wiki/List_of_years_in_video_games and each
"<year> in video games" article linked from it. Text extracted here is
Wikipedia prose/table data (CC BY-SA, reuse with attribution) -- no images
are touched in this script.

Each year's article mixes several kinds of tables (the actual release list,
but also sales charts, "Game of the Year" awards, Metacritic top-10s, etc.
that re-list the same titles). Only the canonical release-list table is used
as the source of entries -- identified by having a title column, a release
date/month column, and at least one platform-ish column -- so award/sales
tables are intentionally skipped rather than producing duplicate entries.
"""
import json
import re
import sys
import time
from collections import OrderedDict
from pathlib import Path
from urllib.parse import unquote

import requests
from bs4 import BeautifulSoup

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, str(Path(__file__).resolve().parent))
from platforms import is_platform_column, split_platform_cell, resolve_platform

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "data" / "index"
LOG_DIR = ROOT / "logs"

API_URL = "https://en.wikipedia.org/w/api.php"
HEADERS = {
    "User-Agent": "VideoGameYearsArchiveBot/1.0 (personal research/archival project)"
}

SESSION = requests.Session()
SESSION.headers.update(HEADERS)

START_YEAR = 1990
END_YEAR = 2028

HEADER_MAP = {
    "title": "title",
    "game": "title",
    "release date": "release_date",
    "release date(s)": "release_date",
    "release": "release_date",
    "month": "release_date",
    "platform": "platform",
    "platform(s)": "platform",
    "developer": "developer",
    "developer(s)": "developer",
    "publisher": "publisher",
    "publisher(s)": "publisher",
    "developer / publisher": "developer_publisher",
    "developer/publisher": "developer_publisher",
    "genre": "genre",
    "genre(s)": "genre",
}

REF_HEADERS = {"ref", "ref.", "refs", "reference", "references"}


def fetch_year_page(year, retries=4):
    params = {
        "action": "parse",
        "page": f"{year} in video games",
        "prop": "text",
        "format": "json",
        "redirects": 1,
    }
    for attempt in range(retries):
        try:
            resp = SESSION.get(API_URL, params=params, timeout=30)
            data = resp.json()
        except (requests.RequestException, ValueError):
            time.sleep(3 * (attempt + 1))
            continue
        if "error" in data:
            # "missingtitle" means the article genuinely doesn't exist --
            # anything else (rate limiting, transient API hiccups) is worth
            # retrying rather than logging the year as missing.
            if data["error"].get("code") == "missingtitle":
                return None
            time.sleep(3 * (attempt + 1))
            continue
        return data["parse"]["text"]["*"]
    return None


def expand_table(table):
    """Expand a wikitable's <tr> rows into a rectangular grid of cell tags,
    honoring rowspan/colspan so columns stay aligned across rows."""
    rows = table.find_all("tr")
    grid = []
    active_spans = []  # [{col, remaining, cell}]
    for tr in rows:
        cells = tr.find_all(["th", "td"], recursive=False)
        row = {}
        for span in active_spans:
            row[span["col"]] = span["cell"]
        occupied = set(row.keys())
        col = 0
        new_spans = []
        for cell in cells:
            while col in occupied:
                col += 1
            colspan = _safe_span(cell, "colspan")
            rowspan = _safe_span(cell, "rowspan")
            for i in range(colspan):
                row[col + i] = cell
                occupied.add(col + i)
                if rowspan > 1:
                    new_spans.append({"col": col + i, "remaining": rowspan - 1, "cell": cell})
            col += colspan
        kept = []
        for span in active_spans:
            span["remaining"] -= 1
            if span["remaining"] > 0:
                kept.append(span)
        active_spans = kept + new_spans
        width = max(row.keys(), default=-1) + 1
        grid.append([row.get(i) for i in range(width)])
    return grid


def _safe_span(cell, attr):
    """cell.get(attr) as an int, tolerating the occasional malformed value
    in the wild (e.g. a stray quote character left over from bad wiki
    markup, like colspan="2'") instead of crashing the whole year's parse."""
    raw = str(cell.get(attr, 1) or 1)
    m = re.match(r"\d+", raw)
    return int(m.group()) if m else 1


def cell_text(cell):
    if cell is None:
        return ""
    return cell.get_text(" ", strip=True)


def cell_link(cell):
    if cell is None:
        return None
    a = cell.find("a", href=True)
    if not a:
        return None
    href = a["href"]
    if not href.startswith("/wiki/"):
        return None
    raw_title = href.split("/wiki/", 1)[1]
    if ":" in raw_title:
        return None  # category/file/etc link, not an article
    is_redlink = "new" in (a.get("class") or [])
    return {
        "title": unquote(raw_title).replace("_", " "),
        "url": "https://en.wikipedia.org" + href,
        "redlink": is_redlink,
    }


def normalize_header(h):
    h = re.sub(r"\[.*?\]", "", h).strip().lower()
    return h


def is_legend_heading(heading):
    return normalize_header(heading) == "legend"


def parse_legend(grid):
    """A Legend table is a grid of repeating (code, full name) pairs with no
    real header row -- flatten every row and pair cells up positionally."""
    legend = {}
    for row in grid:
        texts = [cell_text(c) for c in row]
        for i in range(0, len(texts) - 1, 2):
            code, name = texts[i].strip(), texts[i + 1].strip()
            if code and name:
                legend[code.upper()] = name
    return legend


def is_release_table(mapped_headers, raw_headers):
    has_title = "title" in mapped_headers
    has_date = "release_date" in mapped_headers
    has_platform = "platform" in mapped_headers or any(is_platform_column(h) for h in raw_headers)
    return has_title and has_date and has_platform


def parse_year(year):
    html = fetch_year_page(year)
    if html is None:
        return None, None
    soup = BeautifulSoup(html, "lxml")
    content = soup.find("div", class_="mw-parser-output") or soup
    elements = content.find_all(["h2", "h3", "h4", "table"])

    legend = {}
    entries = []
    found_release_table = False
    current_heading = "Unknown"

    for el in elements:
        if el.name in ("h2", "h3", "h4"):
            headline = el.find(class_="mw-headline")
            current_heading = headline.get_text(strip=True) if headline else el.get_text(strip=True)
            continue
        if "wikitable" not in (el.get("class") or []):
            continue
        grid = expand_table(el)
        if len(grid) < 2:
            continue

        if is_legend_heading(current_heading):
            legend.update(parse_legend(grid))
            continue

        raw_headers = [normalize_header(cell_text(c)) for c in grid[0]]
        mapped = [HEADER_MAP.get(h, h) for h in raw_headers]
        if not is_release_table(mapped, raw_headers):
            continue
        found_release_table = True

        title_idx = mapped.index("title")
        for row in grid[1:]:
            if title_idx >= len(row):
                continue
            title_cell = row[title_idx]
            title_text = cell_text(title_cell)
            if not title_text:
                continue
            link = cell_link(title_cell)
            entry = {
                "year": year,
                "section": current_heading,
                "title": title_text,
                "wiki_title": link["title"] if link else None,
                "wiki_url": link["url"] if link else None,
                "redlink": link["redlink"] if link else None,
            }
            platform_breakdown = OrderedDict()
            platform_tokens = []
            for idx, field in enumerate(mapped):
                if idx >= len(row) or idx == title_idx:
                    continue
                raw_header = raw_headers[idx]
                if raw_header in REF_HEADERS:
                    continue
                text = cell_text(row[idx])
                if field == "platform" or is_platform_column(raw_header):
                    platform_breakdown[raw_headers[idx]] = text
                    platform_tokens.extend(split_platform_cell(text))
                    continue
                if field in entry or not text:
                    continue
                entry[field] = text
            entry["platform_breakdown"] = platform_breakdown
            entry["platforms"] = []
            for tok in platform_tokens:
                name = resolve_platform(tok, legend, UNKNOWN_PLATFORM_CODES)
                if name not in entry["platforms"]:
                    entry["platforms"].append(name)
            entries.append(entry)

    return merge_duplicate_entries(entries), found_release_table


def merge_duplicate_entries(entries):
    """A year's article can have more than one table that satisfies
    is_release_table() -- e.g. a full month-by-month release list AND a
    smaller "best-reviewed games" chart that also happens to carry a Title +
    Platform + Release date -- so the same game can legitimately get scraped
    twice. Merge same-title rows instead of emitting duplicate cards: union
    their platforms rather than picking one table's version and discarding
    the other's platform info."""
    merged = OrderedDict()
    for entry in entries:
        # Keyed on the plain display title, not wiki_title: the same game
        # can be wikilinked to different disambiguation suffixes from
        # different tables (e.g. "Sacrifice (video game)" from one chart,
        # "Sacrifice (computer game)" -- an old alternate title -- from
        # another), which would otherwise defeat the merge entirely.
        key = entry["title"].strip().lower()
        if key not in merged:
            merged[key] = entry
            continue
        existing = merged[key]
        for plat in entry["platforms"]:
            if plat not in existing["platforms"]:
                existing["platforms"].append(plat)
        existing["platform_breakdown"].update(entry["platform_breakdown"])
        for field, value in entry.items():
            if field in ("platforms", "platform_breakdown"):
                continue
            if not existing.get(field) and value:
                existing[field] = value
    return list(merged.values())


def load_json(path, default):
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return default


UNKNOWN_PLATFORM_CODES = set()


def main(years=None):
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    summary_path = LOG_DIR / "index_summary.json"
    missing_path = LOG_DIR / "missing_years.json"
    unstructured_path = LOG_DIR / "years_without_release_table.json"
    unknown_platforms_path = LOG_DIR / "unknown_platform_codes.json"

    summary = load_json(summary_path, {})
    still_missing = set(load_json(missing_path, []))
    unstructured = set(load_json(unstructured_path, []))

    for year in (years if years else range(START_YEAR, END_YEAR + 1)):
        try:
            entries, found_release_table = parse_year(year)
        except Exception as e:
            print(f"{year}: ERROR {e}")
            still_missing.add(year)
            time.sleep(0.3)
            continue
        if entries is None:
            print(f"{year}: no article found, skipping")
            still_missing.add(year)
            time.sleep(0.3)
            continue
        if not found_release_table:
            print(f"{year}: article found but no structured release table")
            unstructured.add(year)
        out_path = OUT_DIR / f"{year}.json"
        out_path.write_text(json.dumps(entries, indent=2, ensure_ascii=False), encoding="utf-8")
        summary[str(year)] = len(entries)
        still_missing.discard(year)
        unstructured.discard(year) if entries else None
        with_platforms = sum(1 for e in entries if e["platforms"])
        print(f"{year}: {len(entries)} entries ({with_platforms} with a platform tag)")
        time.sleep(0.3)

    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    missing_path.write_text(json.dumps(sorted(still_missing), indent=2), encoding="utf-8")
    unstructured_path.write_text(json.dumps(sorted(unstructured), indent=2), encoding="utf-8")
    unknown_platforms_path.write_text(
        json.dumps(sorted(UNKNOWN_PLATFORM_CODES), indent=2, ensure_ascii=False), encoding="utf-8"
    )
    total = sum(summary.values())
    print(f"\nTotal entries across {len(summary)} years: {total}.")
    print(f"Missing years (no article): {sorted(still_missing)}")
    print(f"Years without a structured release table: {sorted(unstructured)}")
    print(f"Unknown platform codes seen: {len(UNKNOWN_PLATFORM_CODES)} (see {unknown_platforms_path.name})")


if __name__ == "__main__":
    years_arg = None
    if len(sys.argv) > 1:
        years_arg = [int(y) for y in sys.argv[1:]]
    main(years_arg)
