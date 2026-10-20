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
    "XBX/S": "Xbox Series X/S", "XB1": "Xbox One", "TVOS": "tvOS", "WATCHOS": "watchOS",
    "PICO4": "PICO 4", "SHIELD": "Nvidia Shield", "ATRVCS": "Atari VCS", "GS": "GameStick",
    "FOS": "Fire OS",
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


_REGION_LABELS = {"WW", "JP", "NA", "EU", "AS", "SA", "AU", "OC", "KR", "CN", "UK", "ROW", "INT"}


def is_known_platform(token, legend):
    key = token.strip().upper()
    if key in PLATFORM_NAMES or key in legend:
        return True
    region_match = _REGION_SUFFIX_RE.match(key)
    return bool(region_match) and (region_match.group(1) in PLATFORM_NAMES or region_match.group(1) in legend)


def expand_platform_token(token, legend):
    """One comma-separated token from a platform cell -> the platform codes it
    really holds. The newer list articles put several codes into one cell,
    mixed with region labels and footnote markers ("PS4 WW : WIN AS : NS",
    "NS2 [ G ]", "PS5. XBX/S"). Such a token is split only when every
    non-region piece is a recognized code; otherwise it's left whole so it
    still falls back to the raw name and gets logged for curation."""
    if is_known_platform(token, legend):
        return [token]
    cleaned = re.sub(r"\[[^\]]*\]", " ", token)
    pieces = [p for p in re.split(r"[\s:.,;]+", cleaned) if p and p.upper() not in _REGION_LABELS]
    if pieces and all(is_known_platform(p, legend) for p in pieces):
        return pieces
    return [token]


def slugify(name):
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug or "unknown"


# IGDB's own platform names -> the same canonical display names PLATFORM_NAMES
# uses, so titles added from IGDB land in the same platform filter buckets as
# the Wikipedia-sourced ones (e.g. "Windows", not a separate "PC (Microsoft
# Windows)"). Matched case-insensitively; anything missing falls back to
# IGDB's raw name and gets logged for later curation, same as resolve_platform.
IGDB_PLATFORM_NAMES = {
    # Computers / mobile / browser
    "PC (Microsoft Windows)": "Windows", "Mac": "macOS", "Linux": "Linux", "DOS": "MS-DOS",
    "iOS": "iOS", "Android": "Android", "Web browser": "Browser", "Windows Phone": "Windows Phone",
    "Amiga": "Amiga", "Commodore C64/128/MAX": "Commodore 64", "Atari ST/STE": "Atari ST",
    "Atari 8-bit": "Atari 8-bit", "Apple II": "Apple II", "MSX": "MSX", "ZX Spectrum": "ZX Spectrum",
    "BBC Microcomputer System": "BBC Micro", "BlackBerry OS": "BlackBerry OS",
    # Sony
    "PlayStation 5": "PlayStation 5", "PlayStation 4": "PlayStation 4", "PlayStation 3": "PlayStation 3",
    "PlayStation 2": "PlayStation 2", "PlayStation": "PlayStation",
    "PlayStation Portable": "PlayStation Portable", "PlayStation Vita": "PlayStation Vita",
    "PlayStation VR": "PlayStation VR", "PlayStation VR2": "PlayStation VR2",
    # Microsoft
    "Xbox Series X|S": "Xbox Series X/S", "Xbox One": "Xbox One", "Xbox 360": "Xbox 360", "Xbox": "Xbox",
    # Nintendo
    "Nintendo Switch 2": "Nintendo Switch 2", "Nintendo Switch": "Nintendo Switch",
    "Wii U": "Wii U", "Wii": "Wii", "Nintendo GameCube": "GameCube", "Nintendo 64": "Nintendo 64",
    "Super Nintendo Entertainment System": "Super Nintendo Entertainment System",
    # Regional names share a bucket, as in the Wikipedia legend ("Super NES / Super Famicom").
    "Super Famicom": "Super Nintendo Entertainment System", "Nintendo Entertainment System": "Nintendo Entertainment System",
    "Family Computer": "Nintendo Entertainment System", "Nintendo 3DS": "Nintendo 3DS", "New Nintendo 3DS": "Nintendo 3DS",
    "Nintendo DS": "Nintendo DS", "Nintendo DSi": "Nintendo DS", "Game Boy Advance": "Game Boy Advance",
    "Game Boy Color": "Game Boy Color", "Game Boy": "Game Boy", "Virtual Boy": "Virtual Boy",
    # Sega / others
    "Dreamcast": "Dreamcast", "Sega Saturn": "Sega Saturn", "Sega Mega Drive/Genesis": "Genesis / Mega Drive",
    "Sega Master System/Mark III": "Sega Master System", "Sega Game Gear": "Game Gear",
    "Sega CD": "Sega CD", "Sega 32X": "Sega 32X", "Arcade": "Arcade",
    "Atari 2600": "Atari 2600", "Atari 5200": "Atari 5200", "Atari 7800": "Atari 7800",
    "Atari Jaguar": "Atari Jaguar", "Atari Lynx": "Atari Lynx",
    "3DO Interactive Multiplayer": "3DO Interactive Multiplayer", "Philips CD-i": "CD-i",
    "Neo Geo CD": "Neo Geo CD", "Neo Geo Pocket Color": "Neo Geo Pocket Color",
    "Neo Geo Pocket": "Neo Geo Pocket", "TurboGrafx-16/PC Engine": "PC Engine",
    "WonderSwan": "WonderSwan", "WonderSwan Color": "WonderSwan Color", "N-Gage": "N-Gage",
    "Ouya": "Ouya",
    # Streaming / VR
    "Google Stadia": "Stadia", "Stadia": "Stadia", "Amazon Luna": "Amazon Luna",
    "Meta Quest 2": "Meta Quest", "Meta Quest 3": "Meta Quest", "Oculus Quest": "Meta Quest",
    "Oculus Rift": "Oculus Rift", "SteamVR": "SteamVR", "Windows Mixed Reality": "Windows Mixed Reality",
    "Oculus VR": "Oculus VR", "Gear VR": "Gear VR", "Daydream": "Daydream", "visionOS": "visionOS",
    "Amazon Fire TV": "Amazon Fire TV", "Windows Mobile": "Windows Mobile",
    "Legacy Mobile Device": "Mobile phone", "OnLive Game System": "OnLive", "Zeebo": "Zeebo",
    # Japanese / European home computers and add-ons seen in older years
    "Neo Geo AES": "Neo Geo AES", "Neo Geo MVS": "Arcade", "PC-FX": "PC-FX",
    "PC-9800 Series": "PC-9800 series", "PC-8800 Series": "PC-8800 series",
    "NEC PC-6000 Series": "NEC PC-6000", "Sharp X68000": "Sharp X68000", "Sharp X1": "Sharp X1",
    "FM Towns": "FM Towns", "Amstrad CPC": "Amstrad CPC", "Acorn Archimedes": "Acorn Archimedes",
    "Apple IIGS": "Apple IIGS", "MSX2": "MSX", "Amiga CD32": "Amiga CD32", "Commodore CDTV": "Amiga CDTV",
    "Satellaview": "Satellaview", "Family Computer Disk System": "Famicom Disk System", "64DD": "Nintendo 64DD",
    "Atari Jaguar CD": "Atari Jaguar CD", "LaserActive": "LaserActive",
    "Turbografx-16/PC Engine CD": "PC Engine CD", "PC Engine SuperGrafx": "SuperGrafx",
}
_IGDB_PLATFORM_NAMES_CI = {k.lower(): v for k, v in IGDB_PLATFORM_NAMES.items()}


def resolve_igdb_platform(name, unknown_log=None):
    """An IGDB platform name -> canonical display name (raw name if uncurated)."""
    resolved = _IGDB_PLATFORM_NAMES_CI.get(name.strip().lower())
    if resolved:
        return resolved
    if unknown_log is not None:
        unknown_log.add(name.strip())
    return name.strip()
