"""Title normalization shared by fetch_igdb.py and generate_site.py."""
import re
import unicodedata


def norm_title(title):
    """Exact-match key for a game title: accents folded, "&" read as "and",
    case/punctuation/spacing dropped -- so "Pokémon: Red" and "Pokemon Red"
    compare equal but nothing else does.

    Deliberately NOT fuzzy. An earlier Steam-matching attempt accepted one
    title merely *containing* the other and conflated sequels and spin-offs
    with their base games ("Civilization II" vs "Civilization III Complete",
    "Dungeon Keeper" vs "Dungeon Keeper 2"); a numbered sequel differs from
    its original by as little as one character, so only equality is safe.
    """
    text = unicodedata.normalize("NFKD", title or "")
    text = text.encode("ascii", "ignore").decode("ascii").lower().replace("&", " and ")
    key = re.sub(r"[^a-z0-9]+", "", text)
    # Titles with no ASCII letters at all (e.g. purely Japanese) would all
    # collapse to "" and falsely match each other -- fall back to the raw text.
    return key or (title or "").strip().lower()
