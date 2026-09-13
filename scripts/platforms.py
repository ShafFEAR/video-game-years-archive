"""Shared platform-code taxonomy used by both scrape_index.py and generate_site.py.

Wikipedia's per-year video game tables key platforms by short codes (PS2, WIN,
N64, ...) defined in a per-page "Legend" table that isn't 100% consistent
across 38 years of independent edits. This module holds a curated map of the
codes actually seen across common console/computer/handheld history so we get
clean, consistent full names and filename slugs -- falling back to whatever
the page's own legend says (cleaned up) for anything not yet curated here.
"""
import re

# code -> canonical display name. Extend this as scrape logs report unknown
# codes (see logs/unknown_platform_codes.json after a scrape run).
PLATFORM_NAMES = {
    # Nintendo
    "NES": "Nintendo Entertainment System", "FC": "Famicom",
    "SNES": "Super Nintendo Entertainment System", "SFC": "Super Famicom",
    "N64": "Nintendo 64", "GC": "GameCube", "WII": "Wii", "WIIU": "Wii U",
    "SWITCH": "Nintendo Switch", "NSW": "Nintendo Switch", "NS": "Nintendo Switch",
    "SWITCH2": "Nintendo Switch 2", "NS2": "Nintendo Switch 2",
    "GB": "Game Boy", "GBC": "Game Boy Color", "GBA": "Game Boy Advance",
    "NDS": "Nintendo DS", "DS": "Nintendo DS", "N3DS": "Nintendo 3DS", "3DS": "Nintendo 3DS",
    "VB": "Virtual Boy",
    # Sega
    "SMS": "Sega Master System", "GEN": "Genesis / Mega Drive", "MD": "Genesis / Mega Drive",
    "SAT": "Sega Saturn", "DC": "Dreamcast", "GG": "Game Gear", "32X": "Sega 32X",
    "SCD": "Sega CD",
    # Sony
    "PS1": "PlayStation", "PSX": "PlayStation", "PS2": "PlayStation 2",
    "PS3": "PlayStation 3", "PS4": "PlayStation 4", "PS5": "PlayStation 5",
    "PSP": "PlayStation Portable", "PSVITA": "PlayStation Vita", "VITA": "PlayStation Vita",
    "PSV": "PlayStation Vita", "PSVR": "PlayStation VR", "PSVR2": "PlayStation VR2",
    # Microsoft
    "XBOX": "Xbox", "X360": "Xbox 360", "XB360": "Xbox 360", "XONE": "Xbox One",
    "XBO": "Xbox One", "XBSX": "Xbox Series X/S", "XSX": "Xbox Series X/S",
    "XSX/S": "Xbox Series X/S", "WP": "Windows Phone",
    # Other consoles/handhelds
    "3DO": "3DO Interactive Multiplayer", "JAG": "Atari Jaguar", "ATARI": "Atari 2600",
    "A2600": "Atari 2600", "A5200": "Atari 5200", "A7800": "Atari 7800",
    "LYNX": "Atari Lynx", "NGPC": "Neo Geo Pocket Color", "NGP": "Neo Geo Pocket",
    "NG": "Neo Geo", "NGCD": "Neo Geo CD", "WS": "WonderSwan", "WSC": "WonderSwan Color",
    "CDI": "CD-i", "OUYA": "Ouya", "GIZMONDO": "Gizmondo", "TG16": "TurboGrafx-16",
    "PCE": "PC Engine", "NGE": "N-Gage",
    # Computers
    "WIN": "Windows", "PC": "Windows", "MAC": "macOS", "LIN": "Linux",
    "DOS": "MS-DOS", "AMI": "Amiga", "ATR": "Atari 8-bit", "ST": "Atari ST",
    "C64": "Commodore 64", "APPII": "Apple II", "MSX": "MSX", "ZX": "ZX Spectrum",
    "BBC": "BBC Micro",
    # Mobile / browser / streaming
    "AND": "Android", "DROID": "Android", "IOS": "iOS", "IPADOS": "iPadOS",
    "BBOS": "BlackBerry OS", "BRW": "Browser", "WEB": "Browser", "BROWSER": "Browser",
    "STADIA": "Stadia", "LUNA": "Amazon Luna", "OUYA2": "Ouya",
    "QUEST": "Meta Quest", "VIVE": "HTC Vive", "OCULUS": "Oculus Rift",
    "OSX": "macOS", "MACOS": "macOS", "OS X": "macOS", "PSN": "PlayStation Network",
    "BADA": "Bada", "MOBI": "Mobile phone",
    # Arcade / misc
    "ARC": "Arcade", "ARCADE": "Arcade", "GCN": "GameCube", "XB": "Xbox",
    "NEO": "Neo Geo AES", "NEOCD": "Neo Geo CD", "PC98": "PC-9800 series",
    "PCFX": "PC-FX", "RZ": "R-Zone", "STEAM": "Steam", "ATRST": "Atari ST",
    "XBX/S": "Xbox Series X/S",
}

# Any of these normalized column headers hold platform data (either a single
# "Platform(s)" cell, or one bucket of the newer four-way release-category
# split). Matched after normalize_header() lowercases + strips [refs].
def is_platform_column(normalized_header):
    return normalized_header in ("platform", "platform(s)") or normalized_header.endswith("releases")


_SPLIT_RE = re.compile(r"[,;]|(?:\s/\s)|(?:\band\b)")
_WHOLE_CELL_PLACEHOLDER_RE = re.compile(
    r"^\s*[-—–]?\s*(n\s*/?\s*a|tba|tbd|—|–|-|none|unknown)\s*$", re.IGNORECASE
)
_PLACEHOLDER_RE = re.compile(r"^(n/?a|tba|tbd|—|–|-|none|unknown)$", re.IGNORECASE)


def split_platform_cell(text):
    """One release-category or Platform(s) cell -> list of raw tokens
    (still codes/short names at this point, not yet resolved to full names).

    Checks whole-cell placeholders like "N/A" or "-- N/a" before splitting.
    A bare "/" (no surrounding spaces) is deliberately NOT a delimiter --
    it's part of compound codes like "XSX/S" -- but " / " (spaced) is, since
    that's how genuinely distinct platforms get joined in some cells (e.g.
    "WIN / DOS"). Splitting on an unspaced "/" would also shred a stray
    "N/a" into bogus single-letter tokens that survive the per-token
    placeholder check below, since that check requires the whole token to
    look like "n/a", not just a piece of one."""
    if not text or _WHOLE_CELL_PLACEHOLDER_RE.match(text):
        return []
    parts = _SPLIT_RE.split(text)
    out = []
    for p in parts:
        p = p.strip(" \t—-")
        if not p or _PLACEHOLDER_RE.match(p):
            continue
        out.append(p)
    return out


def _clean_fallback_name(name):
    name = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", name)
    return re.sub(r"\s+", " ", name).strip()


_REGION_SUFFIX_RE = re.compile(r"^([A-Z0-9/]+)\s*\([^)]+\)$")


def resolve_platform(token, legend, unknown_log=None):
    """A raw token from a platform cell -> canonical display name.

    Checks the curated map first (stable across years), then the page's own
    Legend table (varies per year), then falls back to the raw token itself
    cleaned up -- logging it so the curated map can be extended later.

    Some cells qualify the code with a region, e.g. "PS2 (JP)" / "WIN (EU)"
    -- for a console/platform filter the region doesn't matter, so that
    gets tried too (as its own lookup, not folded into the base code's
    result) once the literal code comes up empty.
    """
    key = token.strip().upper()
    if key in PLATFORM_NAMES:
        return PLATFORM_NAMES[key]
    if key in legend:
        resolved = _clean_fallback_name(legend[key])
        if unknown_log is not None:
            unknown_log.add(f"{key} -> {resolved}")
        return resolved
    region_match = _REGION_SUFFIX_RE.match(key)
    if region_match:
        base = region_match.group(1)
        if base in PLATFORM_NAMES:
            return PLATFORM_NAMES[base]
        if base in legend:
            resolved = _clean_fallback_name(legend[base])
            if unknown_log is not None:
                unknown_log.add(f"{key} -> {resolved} (via base code {base})")
            return resolved
    if unknown_log is not None:
        unknown_log.add(f"{key} -> ? (no legend entry)")
    return token.strip()


def slugify(name):
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug or "unknown"
