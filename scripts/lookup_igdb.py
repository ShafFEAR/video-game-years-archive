"""Look up covers and summaries on IGDB (https://www.igdb.com) for the games
that came from Wikipedia's category pages.

scrape_categories.py adds ~17,000 games that have an infobox but no artwork
and no description. IGDB has both for many of them, so this searches IGDB for
each game by exact name inside a three-year release window and keeps a match
only when it is safe: the release year, the developer/publisher and the
platforms have to agree well enough, and no equally good rival may exist.
Same-name games are everywhere (Doom 1993/2016, Wipeout, Tennis...), and a
wrong cover on an entry is worse than none, so when in doubt it keeps nothing.

Output: data/igdb_lookup/{year}.json maps each article title to its IGDB record,
or to null when nothing safe was found (so reruns don't ask again).
generate_site.py attaches the records at render time. Cover art is hotlinked
from IGDB's image CDN, not copied. Needs the same free Twitch credentials as
fetch_igdb.py (see the top of that file); IGDB's free tier is for non-commercial
use and expects attribution, which the README and index.html provide.

Usage:
  python scripts/lookup_igdb.py                  # every year, resumable (~15,000 requests' worth of names, 10 per request)
  python scripts/lookup_igdb.py 1995 2005        # just those years
  python scripts/lookup_igdb.py --limit 40       # at most 40 games per year (to try it out)
  python scripts/lookup_igdb.py --refresh        # look up everything again
  python scripts/lookup_igdb.py --dry-run        # show what would be asked; no network, no credentials
A full run is ~2,000 requests (about an hour). To go faster, run several copies on
different years (IGDB allows 4 requests a second; one copy uses under 1) with
--no-reconcile, then finish with one `--reconcile-only`. That review pass (it also
runs at the end of a normal run) re-scores every stored match with the current rules,
applies data/igdb_lookup_exclude.json, and drops IGDB games that two different
articles both claimed.
"""
import argparse
import json
import os
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, str(Path(__file__).resolve().parent))
import fetch_igdb as F
import sources
from titles import norm_title

ROOT = Path(__file__).resolve().parent.parent
LOOKUP_DIR = ROOT / "data" / "igdb_lookup"
# Matches a person has looked at and rejected: [{"year": 2011, "wiki_title": "Project M", "reason": "..."}]
EXCLUDE_PATH = ROOT / "data" / "igdb_lookup_exclude.json"
LOG_DIR = ROOT / "logs"

BATCH = 10        # names per multiquery request (IGDB's maximum)
CANDIDATES = 10   # games kept per name
# Base games, standalone expansions, mods (a few Wikipedia articles are about
# mods), remakes, remasters and expanded editions.
LOOKUP_TYPES = (0, 4, 5, 8, 9, 10)
MIN_SCORE = 3     # exact release year alone is enough; one year off needs a second signal
MARGIN = 2        # the best candidate must beat the runner-up by this much
STRONG_SCORE = 6  # year + developer (or platforms) all agree
KEEP = ("igdb_id", "title", "url", "first_release_date", "platforms", "all_platforms", "genres", "developer",
        "publisher", "summary", "cover_url", "rating", "rating_count", "game_type")


def quote(text):
    """An Apicalypse string literal."""
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def where_clause(entry, field="name"):
    start = F.year_bounds(entry["year"] - 1)[0]
    end = F.year_bounds(entry["year"] + 1)[1]
    types = ",".join(str(t) for t in LOOKUP_TYPES)
    return (f"{field} ~ {quote(entry['title'])} & first_release_date >= {start} & first_release_date < {end}"
            f" & game_type = ({types}) & version_parent = null")


def single_query(entry, field="name"):
    return f"fields {F.FIELDS},game_type; where {where_clause(entry, field)}; limit {CANDIDATES};"


def multi_query(batch, field="name"):
    return "\n".join(
        f'query games "q{i}" {{ fields {F.FIELDS},game_type; where {where_clause(entry, field)}; limit {CANDIDATES}; }};'
        for i, entry in enumerate(batch)
    )


def _companies(*texts):
    keys = set()
    for text in texts:
        for part in (text or "").split(","):
            key = norm_title(part)
            if key:
                keys.add(key)
    return keys


def _same_company(a, b):
    """"Sega" ~ "Sega Corporation", "Origin" ~ "Origin Systems" (prefixes of 4+ letters)."""
    if a == b:
        return True
    short, long_ = sorted((a, b), key=len)
    return len(short) >= 4 and long_.startswith(short)


# Platforms the two sources file under different names for the same hardware:
# IGDB calls a 1995 DOS game "PC (Microsoft Windows)", Wikipedia says MS-DOS;
# a Facebook game is a "Browser" game there; PC Engine CD games are PC Engine games.
_FAMILIES = {
    "MS-DOS": ("PC",), "Windows": ("PC",), "Linux": ("PC",), "macOS": ("PC",), "Steam": ("PC",),
    "Browser": ("web",), "Facebook": ("web",),
    "Mobile phone": ("mobile",), "iOS": ("mobile",), "Android": ("mobile",), "Windows Phone": ("mobile",),
    "Windows Mobile": ("mobile",), "BlackBerry OS": ("mobile",), "Fire OS": ("mobile",),
    "PC Engine": ("PC Engine",), "PC Engine CD": ("PC Engine",), "SuperGrafx": ("PC Engine",),
    "Oculus Rift": ("VR", "PC"), "SteamVR": ("VR", "PC"), "Oculus VR": ("VR",), "Meta Quest": ("VR",),
    "Gear VR": ("VR",), "Daydream": ("VR",), "PlayStation VR": ("VR",), "PlayStation VR2": ("VR",),
}


def _platform_families(platforms):
    return {family for name in platforms for family in _FAMILIES.get(name, (name,))}


def score(entry, rec):
    """How well an IGDB record agrees with the Wikipedia entry it was found for."""
    gap = abs(int(rec["first_release_date"][:4]) - entry["year"])
    points = 3 if gap == 0 else 1 if gap == 1 else 0
    mine = _companies(entry.get("developer"), entry.get("publisher"))
    theirs = _companies(rec.get("developer"), rec.get("publisher"))
    if any(_same_company(a, b) for a in mine for b in theirs):
        points += 3
    ours = _platform_families(entry.get("platforms_all") or [])
    there = _platform_families(rec.get("all_platforms") or [])
    if ours and there:
        if ours & there:
            points += 2
        elif norm_title(rec["title"]) != norm_title(entry["title"]):
            # Found only under an alternative name AND on other platforms: the codename or
            # port of some other game ("Unreal Championship" is on IGDB's Unreal Tournament 2003).
            return -1
        else:
            points -= 2  # a different game with the same name usually lives on other platforms
    return points


def choose(entry, records):
    """(outcome, record, score). Outcome is "matched", "no_candidates",
    "weak" (best candidate doesn't agree enough) or "ambiguous" (a rival is
    nearly as good)."""
    scored = sorted(
        ((score(entry, rec), rec) for rec in records if rec.get("first_release_date")),
        key=lambda pair: (-pair[0], pair[1].get("game_type") != 0, -(pair[1].get("rating_count") or 0)),
    )
    if not scored:
        return "no_candidates", None, 0
    best, rec = scored[0]
    if best < MIN_SCORE:
        return "weak", None, best
    if len(scored) > 1 and best - scored[1][0] < MARGIN:
        # IGDB sometimes holds one game twice (a base game and an "expanded" entry with the same
        # name and developer). Two strong, identically named candidates are the same game, so the
        # more popular one will do; a tie between weaker candidates is a real ambiguity.
        twin = scored[1][1]
        if not (best >= STRONG_SCORE and norm_title(twin["title"]) == norm_title(rec["title"])):
            return "ambiguous", None, best
    return "matched", rec, best


def search(client, batch, field="name"):
    """Raw IGDB candidates for each entry of a batch; None for an entry IGDB could not parse."""
    try:
        blocks = client.query(multi_query(batch, field), url=F.MULTIQUERY_URL)
    except F.BadQuery:
        # One title IGDB can't parse spoils the whole batch: ask one by one so only that one is lost.
        out = []
        for entry in batch:
            try:
                out.append(client.query(single_query(entry, field)))
            except F.BadQuery:
                out.append(None)
        return out
    by_name = {block["name"]: block.get("result") or [] for block in blocks}
    return [by_name.get(f"q{i}", []) for i in range(len(batch))]


def read_lookup(path):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def write_lookup(path, found):
    """One article per line, via a temp file so an interrupted run can't truncate the data."""
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"{json.dumps(title, ensure_ascii=False)}: {json.dumps(rec, ensure_ascii=False, separators=(',', ':'))}"
             for title, rec in sorted(found.items(), key=lambda item: item[0])]
    tmp = path.with_suffix(".tmp")
    tmp.write_text("{\n" + ",\n".join(lines) + "\n}\n", encoding="utf-8")
    tmp.replace(path)


def lookup_year(client, year, entries, found, limit, refresh, unknown_platforms, stats, save, now_ts):
    """Look each game up by exact name; the ones IGDB has no candidate for at
    all get a second try under its alternative names (regional titles and
    renames: "3D Lemmings" is "Lemmings 3D" there)."""
    todo = [entry for entry in entries if refresh or entry["wiki_title"] not in found][:limit]
    pending = []  # no exact-name candidate: waiting to be asked about alternative names, ten at a time

    def records_for(entry, games):
        return [
            F.normalize_game(g, entry["year"], "upcoming" if (g.get("first_release_date") or 0) > now_ts else "released",
                             unknown_platforms)
            for g in games if g.get("name")
        ]

    def settle(entry, outcome, rec, points):
        stats[outcome] += 1
        found[entry["wiki_title"]] = dict({key: rec[key] for key in KEEP}, match_score=points) if rec else None

    def ask_alternative_names(final):
        while len(pending) >= BATCH or (final and pending):
            batch, pending[:] = pending[:BATCH], pending[BATCH:]
            for entry, games in zip(batch, search(client, batch, "alternative_names.name")):
                if games is None:
                    settle(entry, "no_candidates", None, 0)
                    continue
                outcome, rec, points = choose(entry, records_for(entry, games))
                if outcome == "matched":
                    stats["matched_by_alternative_name"] += 1
                settle(entry, outcome, rec, points)

    for start in range(0, len(todo), BATCH):
        batch = todo[start:start + BATCH]
        for entry, games in zip(batch, search(client, batch)):
            if games is None:
                stats["error"] += 1
                found[entry["wiki_title"]] = None
                continue
            outcome, rec, points = choose(entry, records_for(entry, games))
            if outcome == "no_candidates":
                pending.append(entry)
            else:
                settle(entry, outcome, rec, points)
        ask_alternative_names(final=False)
        if (start // BATCH) % 10 == 9:
            save()
    ask_alternative_names(final=True)
    save()
    return len(todo)


def reconcile():
    """Re-check the stored results and drop what no longer holds up, without
    asking IGDB again. Returns a Counter of the reasons:
      * "below the current rules" -- the scoring gets tightened from time to
        time; matches made under looser rules are re-scored with today's;
      * "excluded by review" -- listed in data/igdb_lookup_exclude.json, for
        coincidences no rule can see (IGDB's Metroid: Other M carries "Project
        M" as an alternative name, but the article is a Smash Bros. mod);
      * "claimed by two articles" -- an IGDB game two different articles both
        picked is suspect (same-name games in neighbouring years); a claim
        survives only when it is clearly the stronger one."""
    files = {path: read_lookup(path) for path in sorted(LOOKUP_DIR.glob("*.json"))}
    entries = {(year, e["wiki_title"]): e for year, items in candidates_by_year().items() for e in items}
    excluded = set()
    if EXCLUDE_PATH.exists():
        excluded = {(item["year"], item["wiki_title"]) for item in json.loads(EXCLUDE_PATH.read_text(encoding="utf-8"))}
    dropped, changed = Counter(), set()

    def drop(path, title, why):
        files[path][title] = None
        changed.add(path)
        dropped[why] += 1

    for path, found in files.items():
        year = int(path.stem)
        for title, rec in found.items():
            if not rec:
                continue
            if (year, title) in excluded:
                drop(path, title, "excluded by review")
                continue
            entry = entries.get((year, title))
            if entry is None:
                continue
            points = score(entry, rec)
            if points < MIN_SCORE:
                drop(path, title, "below the current rules")
            elif points != rec.get("match_score"):
                rec["match_score"] = points
                changed.add(path)

    claims = defaultdict(list)
    for path, found in files.items():
        for title, rec in found.items():
            if rec:
                claims[rec["igdb_id"]].append((rec.get("match_score", 0), path, title))
    for rows in claims.values():
        if len(rows) < 2:
            continue
        rows.sort(key=lambda row: -row[0])
        winner = rows[0] if rows[0][0] - rows[1][0] >= MARGIN else None
        for row in rows:
            if row is not winner:
                drop(row[1], row[2], "claimed by two articles")
    for path in changed:
        write_lookup(path, files[path])
    return dropped


def describe(dropped):
    return ", ".join(f"{n} {why}" for why, n in sorted(dropped.items())) or "nothing"


def write_summary():
    """logs/igdb_lookup_summary.json: games looked up and matched per year, always recomputed
    from the results themselves so runs in parallel can't clobber each other's numbers."""
    rows = {}
    for path in sorted(LOOKUP_DIR.glob("*.json")):
        found = read_lookup(path)
        rows[path.stem] = {"total": len(found), "matched": sum(1 for rec in found.values() if rec)}
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    (LOG_DIR / "igdb_lookup_summary.json").write_text(json.dumps(rows, indent=2, sort_keys=True), encoding="utf-8")


def candidates_by_year():
    years = sources.load_all()
    return {year: [e for e in entries if e.get("from_category") and e.get("title") and "*" not in e["title"]]
            for year, entries in years.items()}


def main(argv=None, client=None):
    parser = argparse.ArgumentParser(description="Look up IGDB covers and summaries for category-sourced games.")
    parser.add_argument("years", type=int, nargs="*", help="years to look up (default: all)")
    parser.add_argument("--limit", type=int, default=None, help="at most this many games per year in this run")
    parser.add_argument("--refresh", action="store_true", help="look up games that already have a result")
    parser.add_argument("--dry-run", action="store_true", help="show what would be asked; no network, no credentials")
    parser.add_argument("--no-reconcile", action="store_true",
                        help="skip the final check for IGDB games claimed twice (for runs in parallel; finish with --reconcile-only)")
    parser.add_argument("--reconcile-only", action="store_true", help="just run that check on the existing results")
    args = parser.parse_args(argv)

    if args.reconcile_only:
        dropped = reconcile()
        write_summary()
        print(f"Dropped on review: {describe(dropped)}.")
        return

    by_year = candidates_by_year()
    years = [y for y in (args.years or sorted(by_year)) if by_year.get(y)]

    if args.dry_run:
        total = sum(len(by_year[y]) for y in years)
        print(f"Would look up {total} games in {len(years)} years, {BATCH} per request (~{-(-total // BATCH)} requests).")
        if years:
            print(multi_query(by_year[years[0]][:2]))
        return

    if client is None:
        F.load_env()
        client_id, client_secret = os.environ.get("TWITCH_CLIENT_ID"), os.environ.get("TWITCH_CLIENT_SECRET")
        if not client_id or not client_secret:
            raise SystemExit("Set TWITCH_CLIENT_ID and TWITCH_CLIENT_SECRET (see the top of fetch_igdb.py).")
        client = F.IGDBClient(client_id, client_secret)

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    unknown_platforms = set()
    now_ts = int(time.time())

    try:
        for year in years:
            path = LOOKUP_DIR / f"{year}.json"
            found = read_lookup(path)
            stats = Counter()
            asked = lookup_year(client, year, by_year[year], found, args.limit, args.refresh, unknown_platforms, stats,
                                lambda: write_lookup(path, found), now_ts)
            if not asked:
                print(f"{year}: nothing new to look up")
                continue
            print(f"{year}: {asked} looked up -> " + ", ".join(f"{n} {k}" for k, n in sorted(stats.items())), flush=True)
    except RuntimeError as exc:
        print(f"Stopping early: {exc}. Progress is saved; rerun to continue.", flush=True)
    finally:
        write_summary()
        unknown_path = LOG_DIR / "unknown_igdb_platforms.json"
        known = set(json.loads(unknown_path.read_text(encoding="utf-8"))) if unknown_path.exists() else set()
        unknown_path.write_text(json.dumps(sorted(known | unknown_platforms), indent=2, ensure_ascii=False), encoding="utf-8")

    if args.no_reconcile:
        print("\nDone (results not reviewed yet: run with --reconcile-only when every run has finished).")
        return
    dropped = reconcile()
    write_summary()
    matched = sum(1 for p in LOOKUP_DIR.glob("*.json") for rec in read_lookup(p).values() if rec)
    print(f"\nDone. {matched} games matched. Dropped on review: {describe(dropped)}.")


if __name__ == "__main__":
    main()
