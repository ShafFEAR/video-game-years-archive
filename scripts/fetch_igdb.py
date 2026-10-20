"""Add the most notable titles per year from IGDB (https://www.igdb.com).

Wikipedia stopped keeping exhaustive release tables after 2011, so years from
2012 on (and a few thin early ones) only have ~15-25 titles. This fills those
years with the top titles by rating count (and, for not-yet-released years, by
"hypes"), each with platform tags, genres, developer/publisher, a summary and a
cover. Output goes to data/igdb/{year}.json; generate_site.py merges it with
the Wikipedia data at render time, de-duplicating by exact title.

Needs free credentials (IGDB is owned by Twitch, so they come from a Twitch
developer app -- creating the account/app has to be done by you):
  1. Sign in at https://dev.twitch.tv/console (two-factor auth is required).
  2. "Register Your Application": any name, OAuth Redirect URL
     http://localhost, Category "Application Integration", Client Type
     "Confidential".
  3. Open the app's "Manage" page, copy the Client ID and click "New Secret".
  4. Put them in a git-ignored .env file at the repo root (see .env.example)
     or export TWITCH_CLIENT_ID / TWITCH_CLIENT_SECRET.

IGDB's free API tier is for non-commercial use under Twitch's developer terms
and expects attribution (the README and index.html credit IGDB). Cover art is
hotlinked from IGDB's own image CDN instead of being copied into the repo.

Usage:
  python scripts/fetch_igdb.py                    # thin years, top 200 each
  python scripts/fetch_igdb.py --years 2012 2013 --top 50
  python scripts/fetch_igdb.py --dry-run          # print the queries only
  python scripts/fetch_igdb.py --refresh          # re-fetch existing years
Resumable: a year that already has data/igdb/{year}.json is skipped.
"""
import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, str(Path(__file__).resolve().parent))
from platforms import resolve_igdb_platform
from titles import norm_title

ROOT = Path(__file__).resolve().parent.parent
INDEX_DIR = ROOT / "data" / "index"
IGDB_DIR = ROOT / "data" / "igdb"
LOG_DIR = ROOT / "logs"

TOKEN_URL = "https://id.twitch.tv/oauth2/token"
API_URL = "https://api.igdb.com/v4/games"
COVER_URL = "https://images.igdb.com/igdb/image/upload/t_cover_big/{image_id}.jpg"
USER_AGENT = "VideoGameYearsArchiveBot/1.0 (personal research/archival project)"

START_YEAR, END_YEAR = 1990, 2028
SPARSE_THRESHOLD = 100  # years with fewer Wikipedia titles than this get filled in
DEFAULT_TOP = 200
DEFAULT_MIN_RATINGS = 5
UPCOMING_CAP = 100
DELAY = 0.35  # IGDB allows ~4 requests/second; stay well under it

# Base games, standalone expansions, remakes, remasters and expanded editions.
# (game_type uses the same numbering as the older, now-deprecated `category`.)
KEEP_TYPES = (0, 4, 8, 9, 10)

FIELDS = (
    "name,slug,url,first_release_date,summary,total_rating,total_rating_count,hypes,"
    "genres.name,platforms.name,release_dates.y,release_dates.platform.name,"
    "cover.image_id,involved_companies.developer,involved_companies.publisher,"
    "involved_companies.company.name"
)

# Tried in order until IGDB accepts one: the current schema first, then
# progressively simpler ones in case a field name has changed.
VARIANTS = (
    {"type_field": "game_type", "version_parent": True},
    {"type_field": "game_type", "version_parent": False},
    {"type_field": "category", "version_parent": True},
    {"type_field": "category", "version_parent": False},
    {"type_field": None, "version_parent": False},
)


class BadQuery(Exception):
    """IGDB rejected the query itself (HTTP 400), e.g. an unknown field."""


def load_env():
    """Credentials come from the environment or a git-ignored .env file."""
    env_path = ROOT / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


class IGDBClient:
    def __init__(self, client_id, client_secret, session=None):
        self.client_id = client_id
        self.client_secret = client_secret
        self.session = session or requests.Session()
        self.session.headers.update({"User-Agent": USER_AGENT, "Accept": "application/json"})
        self.token = None

    def authenticate(self):
        # Credentials go in the POST body, not the URL, so they never end up
        # in logs or error messages.
        resp = self.session.post(
            TOKEN_URL,
            data={
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "grant_type": "client_credentials",
            },
            timeout=30,
        )
        if resp.status_code != 200:
            try:
                message = resp.json().get("message", "")
            except ValueError:
                message = ""
            raise SystemExit(
                f"Twitch rejected the credentials (HTTP {resp.status_code}: {message}). "
                "Check TWITCH_CLIENT_ID / TWITCH_CLIENT_SECRET."
            )
        self.token = resp.json()["access_token"]

    def query(self, body, retries=4):
        for attempt in range(retries):
            if not self.token:
                self.authenticate()
            headers = {"Client-ID": self.client_id, "Authorization": f"Bearer {self.token}"}
            try:
                resp = self.session.post(API_URL, data=body.encode("utf-8"), headers=headers, timeout=60)
            except requests.RequestException:
                time.sleep(3 * (attempt + 1))
                continue
            if resp.status_code == 401:
                self.token = None  # expired or revoked: fetch a fresh one and retry
                continue
            if resp.status_code == 429 or resp.status_code >= 500:
                time.sleep(5 * (attempt + 1))
                continue
            if resp.status_code == 400:
                raise BadQuery(resp.text[:300])
            resp.raise_for_status()
            time.sleep(DELAY)
            return resp.json()
        raise RuntimeError("IGDB request failed after retries")


def build_query(where, sort, limit, variant):
    fields = FIELDS + (f",{variant['type_field']}" if variant["type_field"] else "")
    clauses = list(where)
    if variant["type_field"]:
        clauses.append(f"{variant['type_field']} = ({','.join(str(t) for t in KEEP_TYPES)})")
    if variant["version_parent"]:
        clauses.append("version_parent = null")
    return f"fields {fields}; where {' & '.join(clauses)}; sort {sort}; limit {limit};"


def year_bounds(year):
    start = int(datetime(year, 1, 1, tzinfo=timezone.utc).timestamp())
    end = int(datetime(year + 1, 1, 1, tzinfo=timezone.utc).timestamp())
    return start, end


def year_queries(year, now_ts, top, min_ratings):
    """(status, where-clauses, sort, limit) per query: already-released titles
    are ranked by rating count, not-yet-released ones by hype."""
    start, end = year_bounds(year)
    queries = []
    if start < now_ts:
        queries.append((
            "released",
            [f"first_release_date >= {start}", f"first_release_date < {min(end, now_ts)}",
             f"total_rating_count >= {min_ratings}"],
            "total_rating_count desc", top,
        ))
    if end > now_ts:
        queries.append((
            "upcoming",
            [f"first_release_date >= {max(start, now_ts)}", f"first_release_date < {end}", "hypes >= 1"],
            "hypes desc", min(top, UPCOMING_CAP),
        ))
    return queries


def _dedupe(items):
    seen, out = set(), []
    for item in items:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out


def normalize_game(game, year, status, unknown_platforms):
    """One raw IGDB game -> the compact record stored in data/igdb/{year}.json."""
    release = datetime.fromtimestamp(game["first_release_date"], tz=timezone.utc) if game.get("first_release_date") else None

    # The platform filter means "released on X in this year", but IGDB's
    # `platforms` lists every platform a game ever reached (later ports
    # included) -- so prefer the platforms with a release dated this year.
    in_year = []
    for rd in game.get("release_dates") or []:
        name = (rd.get("platform") or {}).get("name")
        if rd.get("y") == year and name:
            in_year.append(name)
    every = [p["name"] for p in game.get("platforms") or [] if p.get("name")]
    platforms = _dedupe(resolve_igdb_platform(n, unknown_platforms) for n in (in_year or every))

    developers, publishers = [], []
    for ic in game.get("involved_companies") or []:
        name = (ic.get("company") or {}).get("name")
        if not name:
            continue
        if ic.get("developer"):
            developers.append(name)
        if ic.get("publisher"):
            publishers.append(name)

    cover_id = (game.get("cover") or {}).get("image_id")
    game_type = game.get("game_type", game.get("category"))
    if isinstance(game_type, dict):
        game_type = game_type.get("id")
    rating = game.get("total_rating")
    return {
        "igdb_id": game["id"],
        "title": game["name"],
        "slug": game.get("slug"),
        "url": game.get("url") or (f"https://www.igdb.com/games/{game['slug']}" if game.get("slug") else None),
        "year": year,
        "status": status,
        "first_release_date": release.date().isoformat() if release else None,
        "release_date_text": f"{release:%B} {release.day}, {release.year}" if release else None,
        "platforms": platforms,
        "all_platforms": _dedupe(resolve_igdb_platform(n, unknown_platforms) for n in every),
        "genres": [g["name"] for g in game.get("genres") or [] if g.get("name")],
        "developer": ", ".join(_dedupe(developers)) or None,
        "publisher": ", ".join(_dedupe(publishers)) or None,
        "summary": (game.get("summary") or "").strip() or None,
        "cover_url": COVER_URL.format(image_id=cover_id) if cover_id else None,
        "rating_count": game.get("total_rating_count") or 0,
        "rating": round(rating, 1) if rating is not None else None,
        "hypes": game.get("hypes") or 0,
        "game_type": game_type,
    }


def sparse_years(threshold):
    years = []
    for year in range(START_YEAR, END_YEAR + 1):
        path = INDEX_DIR / f"{year}.json"
        count = len(json.loads(path.read_text(encoding="utf-8"))) if path.exists() else 0
        if count < threshold:
            years.append(year)
    return years


def fetch_year(client, year, now_ts, top, min_ratings, state, unknown_platforms):
    records = []
    for status, where, sort, limit in year_queries(year, now_ts, top, min_ratings):
        while True:
            variant = VARIANTS[state["variant"]]
            try:
                games = client.query(build_query(where, sort, limit, variant))
                break
            except BadQuery as exc:
                if state["variant"] + 1 >= len(VARIANTS):
                    raise SystemExit(f"IGDB rejected every query variant; last error: {exc}")
                state["variant"] += 1
                print(f"  IGDB rejected the query ({exc}); retrying with a simpler variant", flush=True)
        for game in games:
            if not game.get("name"):
                continue
            record = normalize_game(game, year, status, unknown_platforms)
            # Belt and braces: the where-clause already filters by type.
            if record["game_type"] is not None and record["game_type"] not in KEEP_TYPES:
                continue
            records.append(record)

    # One card per game, and one per title: keep the better-rated of any
    # same-title pair (usually a remaster/edition sharing the original's name).
    best = {}
    for rec in records:
        key = norm_title(rec["title"])
        current = best.get(key)
        if current is None or (rec["rating_count"], rec["hypes"]) > (current["rating_count"], current["hypes"]):
            best[key] = rec
    kept = sorted(
        best.values(),
        key=lambda r: (r["status"] != "released", -r["rating_count"], -r["hypes"], r["title"].lower()),
    )
    return kept


def main(argv=None, client=None):
    parser = argparse.ArgumentParser(description="Add notable titles per year from IGDB.")
    parser.add_argument("--years", type=int, nargs="*", help="years to fetch (default: years Wikipedia covers thinly)")
    parser.add_argument("--all", action="store_true", help="fetch every year in range, not just thin ones")
    parser.add_argument("--top", type=int, default=DEFAULT_TOP, help="max released titles per year")
    parser.add_argument("--min-ratings", type=int, default=DEFAULT_MIN_RATINGS, help="min rating count for released titles")
    parser.add_argument("--refresh", action="store_true", help="re-fetch years that already have data")
    parser.add_argument("--dry-run", action="store_true", help="print the queries; no network, no credentials")
    args = parser.parse_args(argv)

    years = args.years or (list(range(START_YEAR, END_YEAR + 1)) if args.all else sparse_years(SPARSE_THRESHOLD))
    now_ts = int(time.time())

    if args.dry_run:
        print(f"Would fetch {len(years)} years: {years}")
        for year in years:
            for status, where, sort, limit in year_queries(year, now_ts, args.top, args.min_ratings):
                print(f"{year} [{status}] {build_query(where, sort, limit, VARIANTS[0])}")
        return

    IGDB_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    if client is None:
        load_env()
        client_id, client_secret = os.environ.get("TWITCH_CLIENT_ID"), os.environ.get("TWITCH_CLIENT_SECRET")
        if not client_id or not client_secret:
            raise SystemExit(
                "Set TWITCH_CLIENT_ID and TWITCH_CLIENT_SECRET (environment variables or a git-ignored "
                ".env file at the repo root). See the top of this file for how to get free credentials."
            )
        client = IGDBClient(client_id, client_secret)

    summary_path = LOG_DIR / "igdb_summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8")) if summary_path.exists() else {}
    unknown_platforms = set()
    state = {"variant": 0}

    for year in years:
        out_path = IGDB_DIR / f"{year}.json"
        if out_path.exists() and not args.refresh:
            print(f"{year}: already fetched, skipping (use --refresh to redo)")
            continue
        records = fetch_year(client, year, now_ts, args.top, args.min_ratings, state, unknown_platforms)
        out_path.write_text(json.dumps(records, indent=2, ensure_ascii=False), encoding="utf-8")
        summary[str(year)] = len(records)
        print(f"{year}: {len(records)} titles", flush=True)

    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
    (LOG_DIR / "unknown_igdb_platforms.json").write_text(
        json.dumps(sorted(unknown_platforms), indent=2, ensure_ascii=False), encoding="utf-8"
    )
    if state["variant"] == len(VARIANTS) - 1:
        print("Warning: IGDB accepted no game-type filter, so DLC/expansions may be mixed in.")
    print(f"\nDone. Unknown IGDB platform names: {len(unknown_platforms)} (see logs/unknown_igdb_platforms.json).")


if __name__ == "__main__":
    main()
