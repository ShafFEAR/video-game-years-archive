"""Polite Wikipedia API access shared by the scrapers.

Wikipedia rate-limits sustained bursts with HTTP 429. Treating that as an
ordinary failure used to surface as years spuriously logged as "no article",
so this helper honors Retry-After and backs off instead of giving up.
"""
import time

import requests

API_URL = "https://en.wikipedia.org/w/api.php"
USER_AGENT = "VideoGameYearsArchiveBot/1.0 (personal research/archival project)"

SESSION = requests.Session()
SESSION.headers.update({"User-Agent": USER_AGENT})


def _retry_after(resp, default):
    raw = resp.headers.get("Retry-After", "")
    return int(raw) if raw.isdigit() else default


def api_get(params, retries=6, timeout=90):
    """GET the MediaWiki API; parsed JSON, or None if every retry failed."""
    for attempt in range(retries):
        try:
            resp = SESSION.get(API_URL, params=params, timeout=timeout)
        except requests.RequestException:
            time.sleep(3 * (attempt + 1))
            continue
        if resp.status_code == 429 or resp.status_code >= 500:
            time.sleep(min(_retry_after(resp, 5 * (attempt + 1)), 90))
            continue
        try:
            return resp.json()
        except ValueError:
            time.sleep(3 * (attempt + 1))
    return None


def fetch_page_html(title, attempts=4):
    """Rendered HTML of an article as (html, status): "ok", "missing" (no
    such article) or "failed" (kept erroring -- e.g. rate limiting -- so the
    caller shouldn't mistake it for a missing page)."""
    for attempt in range(attempts):
        data = api_get({"action": "parse", "page": title, "prop": "text", "format": "json", "redirects": 1})
        if data is None:
            continue
        if "error" in data:
            if data["error"].get("code") == "missingtitle":
                return None, "missing"
            time.sleep(3 * (attempt + 1))
            continue
        return data["parse"]["text"]["*"], "ok"
    return None, "failed"
