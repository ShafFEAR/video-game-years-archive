"""Scrape Wikipedia's "List of video games released in YYYY" articles.

From 2012 on, Wikipedia keeps the exhaustive month-by-month release lists in
separate articles (e.g. "List of video games released in 2014") instead of in
"2014 in video games", whose release tables stop at 2011 -- which is why
scrape_index.py alone finds only ~15-25 titles per year after that. The list
articles use the same table shape (release date, title, platform codes decoded
by a Legend table, genre, developer, publisher), so parsing is shared with
scrape_index.py.

Output goes to data/lists/{year}.json; generate_site.py merges it with the
other sources at render time, de-duplicating by exact title. Text extracted
here is Wikipedia table data (CC BY-SA, reuse with attribution).

Usage:
  python scripts/scrape_lists.py              # every year that has a list article
  python scripts/scrape_lists.py 2014 2022    # just those years
  python scripts/scrape_lists.py --refresh    # re-fetch years already scraped
Resumable: a year with an existing data/lists/{year}.json is skipped.
"""
import argparse
import json
import sys
import time
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, str(Path(__file__).resolve().parent))
import scrape_index as SI
from wiki import api_get, fetch_page_html

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "data" / "lists"
LOG_DIR = ROOT / "logs"

TITLE = "List of video games released in {year}"
START_YEAR, END_YEAR = 1990, 2028
DELAY = 2.0  # these articles are large (1-2 MB of HTML); be gentle


def years_with_lists(years):
    """Years that have a list article: one batched existence check per 40."""
    found = set()
    for i in range(0, len(years), 40):
        chunk = years[i:i + 40]
        data = api_get({
            "action": "query", "redirects": 1, "format": "json",
            "titles": "|".join(TITLE.format(year=y) for y in chunk),
        })
        if data is None:
            raise SystemExit("Wikipedia API kept failing (rate limited?); try again in a few minutes.")
        redirects = {r["from"]: r["to"] for r in data["query"].get("redirects", [])}
        pages = {p["title"]: p for p in data["query"]["pages"].values()}
        for year in chunk:
            title = TITLE.format(year=year)
            title = redirects.get(title, title)
            if title in pages and "missing" not in pages[title]:
                found.add(year)
        time.sleep(0.5)
    return found


def main(argv=None):
    parser = argparse.ArgumentParser(description="Scrape Wikipedia's per-year video game release lists.")
    parser.add_argument("years", type=int, nargs="*", help="years to scrape (default: every year with a list article)")
    parser.add_argument("--refresh", action="store_true", help="re-fetch years that already have data")
    args = parser.parse_args(argv)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    candidates = args.years or list(range(START_YEAR, END_YEAR + 1))
    available = sorted(years_with_lists(candidates))
    print(f"List articles exist for {len(available)} years: {available}", flush=True)

    summary_path = LOG_DIR / "lists_summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8")) if summary_path.exists() else {}

    for year in available:
        out_path = OUT_DIR / f"{year}.json"
        if out_path.exists() and not args.refresh:
            print(f"{year}: already scraped, skipping (use --refresh to redo)")
            continue
        title = TITLE.format(year=year)
        html, status = fetch_page_html(title)
        if status != "ok":
            print(f"{year}: could not fetch ({status}); rerun later to retry", flush=True)
            continue
        entries, found_table = SI.parse_html(year, html)
        for entry in entries:
            entry["source_article"] = title
        out_path.write_text(json.dumps(entries, indent=2, ensure_ascii=False), encoding="utf-8")
        summary[str(year)] = len(entries)
        tagged = sum(1 for e in entries if e["platforms"])
        print(f"{year}: {len(entries)} titles ({tagged} with a platform tag){'' if found_table else '  [no release table found!]'}", flush=True)
        time.sleep(DELAY)

    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
    (LOG_DIR / "unknown_list_platform_codes.json").write_text(
        json.dumps(sorted(SI.UNKNOWN_PLATFORM_CODES), indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"\nDone. Unknown platform codes seen: {len(SI.UNKNOWN_PLATFORM_CODES)} (see logs/unknown_list_platform_codes.json).")


if __name__ == "__main__":
    main()
