"""Title cleanup and normalization shared by the scrapers, fetch_igdb.py,
sources.py and generate_site.py."""
import re
import unicodedata

# Footnote/reference markers that survive text extraction as "[ a ]", "[ 83 ]",
# "[ nb 1 ]" -- not two-letter bracket text like "[HD]", which is a real title.
FOOTNOTE_RE = re.compile(r"\s*\[\s*(?:nb\s+\d+|\d{1,3}|[A-Za-z])\s*\]")

# Region tags Wikipedia's lists append to a title when a release is regional,
# e.g. "Picross S7 (NA)", "Rhythm Thief (EU/AU)", or in older articles
# "Dark Cloud (Japan)".
_REGION_WORDS = {"japan": "JP", "north america": "NA", "europe": "EU", "australia": "AU",
                 "worldwide": "WW", "asia": "AS", "korea": "KR", "china": "CN"}
_REGIONS = r"(?:NA|EU|JP|AU|WW|PAL|UK|KR|CN|AS|Japan|North America|Europe|Australia|Worldwide|Asia|Korea|China)"
REGION_TAG_RE = re.compile(r"\s*\(\s*%s(?:\s*[/,&]\s*%s)*\s*\)\s*$" % (_REGIONS, _REGIONS), re.IGNORECASE)


# The parenthetical Wikipedia adds to an article title to tell games apart:
# "Alien (video game)", "Doom (2016 video game)", "Wipeout (1995 video game)".
DISAMBIGUATOR_RE = re.compile(r"\s*\([^()]*(?:game|video)[^()]*\)$", re.IGNORECASE)


def strip_disambiguator(title):
    return DISAMBIGUATOR_RE.sub("", title or "")


def strip_footnotes(text):
    return FOOTNOTE_RE.sub("", text or "").strip()


def split_region_tag(title):
    """"Far Cry 3 (NA)" -> ("Far Cry 3", "NA"); "Rhythm Thief (EU/AU)" ->
    ("Rhythm Thief", "EU/AU"); a title with no trailing region tag comes back
    unchanged with None."""
    match = REGION_TAG_RE.search(title or "")
    if not match:
        return title, None
    inner = match.group(0).strip().strip("()").strip()
    codes = [_REGION_WORDS.get(part.strip().lower(), part.strip().upper()) for part in re.split(r"[/,&]", inner)]
    return title[:match.start()].strip(), "/".join(dict.fromkeys(codes))


def union_regions(*regions):
    """Combine region strings ("NA", "EU/AU") into one de-duplicated "NA/EU/AU"."""
    codes = [c for r in regions if r for c in r.split("/")]
    return "/".join(dict.fromkeys(codes)) or None


def norm_title(title):
    """Exact-match key for a game title: footnote markers and a trailing region
    tag dropped, accents folded, "&" read as "and", case/punctuation/spacing
    removed -- so "Pokémon: Red [ a ]" and "Pokemon Red" compare equal but
    nothing else does.

    Deliberately NOT fuzzy. An earlier Steam-matching attempt accepted one
    title merely *containing* the other and conflated sequels and spin-offs
    with their base games ("Civilization II" vs "Civilization III Complete",
    "Dungeon Keeper" vs "Dungeon Keeper 2"); a numbered sequel differs from
    its original by as little as one character, so only equality is safe.
    """
    cleaned = REGION_TAG_RE.sub("", strip_footnotes(title))
    text = unicodedata.normalize("NFKD", cleaned)
    text = text.encode("ascii", "ignore").decode("ascii").lower().replace("&", " and ")
    key = re.sub(r"[^a-z0-9]+", "", text)
    # Titles with no ASCII letters at all (e.g. purely Japanese) would all
    # collapse to "" and falsely match each other -- fall back to the raw text.
    return key or cleaned.strip().lower()
