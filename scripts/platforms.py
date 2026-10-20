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


# --- Names as they appear in article infoboxes (link targets such as "Xbox
# (console)", piped labels such as "PS4" / "Mac OS X", plain text). Keys are
# lowercase; values are the canonical buckets used everywhere else.
_WIKI_ALIASES = {
    "Windows": ["microsoft windows", "windows", "pc", "pc (microsoft windows)", "windows 95", "windows 98", "windows 3.1",
                "windows 3.x", "windows xp", "windows vista", "windows 7", "windows 8", "windows 10", "windows 11",
                "personal computer", "ibm pc", "pc game", "win", "windows 9x", "windows nt", "windows 2000"],
    "MS-DOS": ["ms-dos", "dos", "ms dos", "pc dos", "ibm pc compatible", "ibm pc compatibles", "ibm pc-compatible", "pc-compatible"],
    "macOS": ["macos", "mac os x", "os x", "mac os", "classic mac os", "macintosh", "mac", "mac (computer)", "apple macintosh",
              "mac os 9", "macos sierra", "mac os classic"],
    "Linux": ["linux", "steamos", "linux distributions"],
    "Android": ["android", "android os", "android tv", "android (os)"],
    "iOS": ["ios", "iphone", "ipad", "ios (apple)", "iphone os", "apple ios", "ipod touch", "ipados", "iphone os"],
    "tvOS": ["tvos", "apple tv"], "watchOS": ["watchos", "apple watch"],
    # Windows Mobile / Pocket PC (2000) is a different, much older platform than Windows Phone (2010).
    "Windows Phone": ["windows phone"], "Windows Mobile": ["windows mobile", "pocket pc", "windows ce", "windows pocket pc"],
    "BlackBerry OS": ["blackberry", "blackberry os", "blackberry 10"],
    "Mobile phone": ["mobile phone", "mobile phones", "mobile game", "feature phone", "j2me", "java me", "brew", "symbian", "palm os", "mobile"],
    "Browser": ["web browser", "browser", "adobe flash", "flash", "html5", "adobe shockwave", "shockwave", "java applet"],
    "PlayStation": ["playstation", "playstation (console)", "ps1", "psx", "playstation 1", "sony playstation", "ps one", "psone"],
    "PlayStation 2": ["playstation 2", "ps2"], "PlayStation 3": ["playstation 3", "ps3"],
    "PlayStation 4": ["playstation 4", "ps4"], "PlayStation 5": ["playstation 5", "ps5"],
    "PlayStation Portable": ["playstation portable", "psp"], "PlayStation Vita": ["playstation vita", "ps vita", "vita", "psvita", "psv"],
    "PlayStation Network": ["playstation network", "psn"],
    "PlayStation VR": ["playstation vr", "psvr"], "PlayStation VR2": ["playstation vr2", "psvr2"],
    "Xbox": ["xbox", "xbox (console)", "original xbox", "xbox live"],
    "Xbox 360": ["xbox 360", "x360", "xbox live arcade", "xbla"], "Xbox One": ["xbox one", "xbone", "xb1", "xbox one x", "xbox one s"],
    "Xbox Series X/S": ["xbox series x/s", "xbox series x and series s", "xbox series x", "xbox series s", "xbox series x|s", "xbox series"],
    "Nintendo Switch": ["nintendo switch", "switch", "nintendo switch (console)", "switch lite", "nintendo switch online"],
    "Nintendo Switch 2": ["nintendo switch 2", "switch 2"],
    "Wii": ["wii", "wiiware", "wii (console)", "virtual console (wii)"], "Wii U": ["wii u", "wiiu", "wii u (console)"],
    "GameCube": ["gamecube", "nintendo gamecube", "gc", "gcn"], "Nintendo 64": ["nintendo 64", "n64"],
    "Super Nintendo Entertainment System": ["super nintendo entertainment system", "super nes", "snes", "super famicom", "sfc", "super nintendo"],
    "Nintendo Entertainment System": ["nintendo entertainment system", "nes", "famicom", "family computer", "famicom disk system"],
    "Game Boy": ["game boy", "gb", "super game boy"], "Game Boy Color": ["game boy color", "gbc"],
    "Game Boy Advance": ["game boy advance", "gba"], "Nintendo DS": ["nintendo ds", "ds", "nintendo dsi", "dsiware", "dsi"],
    "Nintendo 3DS": ["nintendo 3ds", "3ds", "new nintendo 3ds", "nintendo 2ds"], "Virtual Boy": ["virtual boy"],
    "Genesis / Mega Drive": ["sega genesis", "sega mega drive", "mega drive", "genesis", "sega mega drive/genesis", "genesis/mega drive",
                             "mega drive/genesis", "sega genesis/mega drive", "sega genesis (console)"],
    "Sega Master System": ["sega master system", "master system", "sega mark iii", "sega master system/mark iii"],
    "Game Gear": ["sega game gear", "game gear"], "Sega CD": ["sega cd", "mega-cd", "mega cd", "sega mega-cd"],
    "Sega 32X": ["sega 32x", "32x"], "Sega Saturn": ["sega saturn", "saturn"], "Dreamcast": ["dreamcast", "sega dreamcast", "dc"],
    "Arcade": ["arcade", "arcade video game", "arcade game", "arcade cabinet", "arcade games", "coin-op", "arcade system board"],
    "3DO Interactive Multiplayer": ["3do", "3do interactive multiplayer", "panasonic 3do"],
    "Atari Jaguar": ["atari jaguar", "jaguar"], "Atari Lynx": ["atari lynx", "lynx"], "Atari 2600": ["atari 2600", "atari vcs 2600"],
    "Atari 5200": ["atari 5200"], "Atari 7800": ["atari 7800"], "Atari ST": ["atari st", "atari ste", "atari falcon"],
    "Atari 8-bit": ["atari 8-bit", "atari 8-bit family", "atari 800", "atari 400", "atari xl"], "Atari VCS": ["atari vcs"],
    "Amiga": ["amiga", "commodore amiga", "amiga 500", "amiga 1200"], "Amiga CD32": ["amiga cd32", "cd32"],
    "Commodore 64": ["commodore 64", "c64"], "ZX Spectrum": ["zx spectrum", "sinclair zx spectrum"],
    "Amstrad CPC": ["amstrad cpc"], "MSX": ["msx", "msx2"], "Apple II": ["apple ii", "apple iie", "apple ii series"],
    "BBC Micro": ["bbc micro", "bbc microcomputer"], "Neo Geo AES": ["neo geo", "neo geo aes", "neo-geo", "neo geo mvs"],
    "Neo Geo CD": ["neo geo cd"], "Neo Geo Pocket": ["neo geo pocket"], "Neo Geo Pocket Color": ["neo geo pocket color"],
    "PC Engine": ["pc engine", "turbografx-16", "turbografx", "pc engine/turbografx-16", "turbografx-16/pc engine", "supergrafx", "pc engine supergrafx"],
    "PC Engine CD": ["pc engine cd-rom²", "pc engine super cd-rom²", "pc engine cd-rom2", "turbografx-cd", "turbografx-cd/pc engine cd-rom²", "pc engine cd"],
    "PC-FX": ["pc-fx"], "PC-9800 series": ["pc-9800 series", "pc-98", "nec pc-9801", "pc-9801", "nec pc-9800 series"],
    "FM Towns": ["fm towns", "fm towns marty"], "Sharp X68000": ["sharp x68000", "x68000"],
    "WonderSwan": ["wonderswan", "bandai wonderswan"], "WonderSwan Color": ["wonderswan color"], "N-Gage": ["n-gage", "nokia n-gage"],
    "Ouya": ["ouya"], "Stadia": ["stadia", "google stadia"], "Amazon Luna": ["amazon luna", "luna"],
    "Oculus Rift": ["oculus rift", "oculus rift s"], "Meta Quest": ["meta quest", "oculus quest", "meta quest 2", "meta quest 3", "quest 2", "oculus quest 2"],
    "SteamVR": ["steamvr", "htc vive", "valve index"], "Nvidia Shield": ["nvidia shield", "shield", "shield tv"],
    "Amazon Fire TV": ["amazon fire tv", "fire tv"], "Fire OS": ["fire os"], "PICO 4": ["pico 4"], "GameStick": ["gamestick"],
    "Gizmondo": ["gizmondo"], "R-Zone": ["r-zone"], "Zeebo": ["zeebo"], "CD-i": ["cd-i", "philips cd-i"],
}
# The long tail: computers, handhelds and variants that a few dozen games each
# list, curated from logs/unknown_infobox_platforms.json. Entries here add to
# the canonical buckets above or start small ones of their own.
_WIKI_EXTRA_ALIASES = {
    "Windows": ["windows 3.0", "windows 3.1x", "windows 3", "windows 3.11", "windows for workgroups", "windows me", "windows server",
                "windows 2.0", "windows 2.1", "microsoft windows 3.1", "windows pc", "microsoft windows 95", "microsoft windows 98",
                "windows 8.1", "windows 10 pc", "vista", "xp home", "xp pro", "nt4", "windows 2k", "windows store", "microsoft store",
                "windows xp/vista"],
    "MS-DOS": ["microsoft dos", "dos 5", "ms-dos 6"],
    "macOS": ["mac os 7", "mac os 8", "system 7", "system 6", "mac os 7.5"],
    "Mobile phone": ["i-mode", "ezweb", "ez-web", "mobile devices", "i-appli", "ezplus", "mobile (java)", "mobile (brew)", "wap", "j-phone",
                     "docomo", "vodafone live!", "foma", "foma 903i", "freedom of mobile multimedia access", "softbank 3g", "softbank mobile",
                     "yahoo mobile", "yahoo! mobile", "symbian^3", "symbian^1", "symbian os", "s60", "series 60", "meego", "nokia n9", "palm",
                     "palm (pda)", "webos"],
    "Amiga": ["amigaos", "amiga os", "amiga 4000", "amiga 600", "amiga 2000", "amiga 3000", "amiga 500+", "amiga aga", "amiga ocs",
              "amiga ecs", "amiga original chipset", "amiga enhanced chip set", "advanced graphics architecture", "ecs", "ocs", "aga",
              "amigaos 4", "amiga os 4", "amigaos 4.1"],
    "Atari ST": ["atari falcon030", "falcon", "falcon030", "atari st/ste"],
    "PC Engine": ["pc-engine", "turbografx 16", "pc engine hucard", "hucard"],
    "PC Engine CD": ["turboduo", "pc engine duo", "turbografx cd", "pc engine cd-rom", "pc engine arcade cd-rom²", "pc engine arcade cd-rom2",
                     "pc engine super cd-rom²", "pc engine super cd-rom2", "pce cd", "super cd-rom²", "super cd-rom2", "pc engine cd-rom²"],
    "Nintendo Entertainment System": ["nintendo family computer", "datach", "datach joint rom system", "nes/famicom"],
    "PC-9800 series": ["pc-9821", "nec pc-98", "nec pc-9800", "pc-9800", "nec pc-9821", "nec pc-9801"],
    "PC-8800 series": ["pc-88", "pc-8801", "pc-8800", "nec pc-8801", "nec pc-88", "pc-8801 mkii", "pc-8801 msx2"],
    "Arcade": ["playchoice-10", "playchoice 10", "cp system", "cp system ii", "cps-1", "cps-2", "cps changer", "exa-arcadia", "taito x-55",
               "sega system 32", "namco system 22", "namco system 12", "sega model 2", "sega model 3"],
    "ZX Spectrum": ["zx spectrum 48k", "zx spectrum 128", "spectrum", "sinclair spectrum", "zx spectrum 128k"],
    "MSX": ["msx turbo r", "msx2+", "msx1"],
    "Sharp X1": ["sharp x1", "x1", "x1 turbo", "sharp x1 turbo"],
    "Acorn Archimedes": ["archimedes", "risc os", "acorn 32-bit", "acorn archimedes"],
    "Acorn Electron": ["acorn electron"],
    "Amstrad GX4000": ["gx4000", "amstrad gx4000"],
    "Amstrad CPC": ["cpc", "amstrad cpc plus", "cpc plus", "amstrad cpc 464", "amstrad cpc 6128"],
    "Amstrad PCW": ["amstrad pcw", "pcw"],
    "Amiga CDTV": ["cdtv", "commodore cdtv"],
    "Commodore 128": ["commodore 128", "c128"],
    "Commodore 16 / Plus/4": ["commodore 16", "commodore plus/4", "plus/4", "commodore 16/plus/4", "c16", "plus 4", "commodore plus 4"],
    "VIC-20": ["vic-20", "commodore vic-20"],
    "SAM Coupé": ["sam coupé", "sam coupe"],
    "Dragon 32/64": ["dragon 32/64", "dragon 32", "dragon 64", "dragon 32 and 64"],
    "Oric": ["oric", "oric computers", "oric-1", "oric atmos"],
    "Sinclair ZX80/ZX81": ["zx81", "zx80", "sinclair zx81", "sinclair zx80"],
    "TRS-80": ["trs-80", "tandy trs-80", "trs-80 color computer", "trs-80 coco", "tandy color computer"],
    "Tandy Video Information System": ["tandy video information system", "tandy memorex vis", "memorex vis"],
    "Evercade": ["evercade", "evercade vs"],
    "GP32": ["gp32"],
    "Apple Pippin": ["apple pippin", "pippin", "bandai pippin", "apple bandai pippin"],
    "Sega Pico": ["sega pico"],
    "Atari Jaguar CD": ["jaguar cd", "atari jaguar cd"],
    "Satellaview": ["satellaview", "bs-x", "st.giga"],
    "Nintendo 64DD": ["64dd", "nintendo 64dd"],
    "Browser": ["web", "browser game", "browser games", "web browsers", "world wide web", "internet", "adobe flash player", "webgl",
                "google chrome", "online"],
    "Facebook": ["facebook", "facebook platform", "google+"],
    "OnLive": ["onlive", "onlive game system"],
    "Nuon": ["nuon", "nuon (dvd technology)"],
    "GP2X": ["gp2x", "gp2x wiz", "gp2x caanoo"],
    "HarmonyOS": ["harmonyos"],
    "Game.com": ["game.com", "tiger game.com"],
    "Windows Phone": ["windows phone 7", "windows phone 8", "windows phone 8.1", "windows 10 mobile"],
    "PlayStation 2": ["sony playstation 2"], "Wii": ["nintendo wii"], "Neo Geo Pocket Color": ["neo-geo pocket color"],
    "Xbox Series X/S": ["xbox series xs", "xbox series x and s", "xbox series x|s", "xbox series x and series s"],
    "Xbox 360": ["xbox live indie games"],
    "Meta Quest": ["meta quest pro", "meta quest 3s", "meta quest 3", "oculus quest 2"],
    "Gear VR": ["samsung gear vr", "gear vr"],
    "N-Gage": ["n-gage 2.0"],
    "Fire OS": ["kindle fire", "fire tablet"],
    "Android": ["google play"],
    "BlackBerry OS": ["blackberry playbook", "blackberry 10 os"],
}
for _canonical, _aliases in _WIKI_EXTRA_ALIASES.items():
    _WIKI_ALIASES.setdefault(_canonical, []).extend(_aliases)

_WIKI_NAME_LOOKUP = {}
for _canonical, _aliases in _WIKI_ALIASES.items():
    _WIKI_NAME_LOOKUP[_canonical.lower()] = _canonical
    for _alias in _aliases:
        _WIKI_NAME_LOOKUP[_alias] = _canonical
for _name in set(PLATFORM_NAMES.values()):
    _WIKI_NAME_LOOKUP.setdefault(_name.lower(), _name)
for _key, _name in IGDB_PLATFORM_NAMES.items():
    _WIKI_NAME_LOOKUP.setdefault(_key.lower(), _name)
# Platform codes ("PS2", "GBA") are safe to look up as plain tokens only when
# long enough -- and not an ordinary word ("AND" is Android's code).
for _code, _name in PLATFORM_NAMES.items():
    if len(_code) >= 3 and _code.lower() not in {"and", "web"}:
        _WIKI_NAME_LOOKUP.setdefault(_code.lower(), _name)

_PLATFORM_QUALIFIER_RE = re.compile(
    r"\s*\((?:console|operating system|os|computer|video game console|game console|handheld game console|home computer|"
    r"home console|platform|series|video game|brand)\)$"
)


def resolve_wiki_platform(text):
    """A platform as spelled in an infobox -> canonical bucket, or None."""
    text = text.replace("&nbsp;", " ").replace("\xa0", " ")
    key = re.sub(r"\s+", " ", _PLATFORM_QUALIFIER_RE.sub("", text.strip().lower().replace("™", "").replace("®", "")))
    return _WIKI_NAME_LOOKUP.get(key)


# When each canonical platform first shipped. Infoboxes list every platform a
# game ever reached, so a platform that launched after the game's year is a
# later port, not part of that year's release.
PLATFORM_LAUNCH_YEAR = {
    "PlayStation": 1994, "PlayStation 2": 2000, "PlayStation 3": 2006, "PlayStation 4": 2013, "PlayStation 5": 2020,
    "PlayStation Portable": 2004, "PlayStation Vita": 2011, "PlayStation VR": 2016, "PlayStation VR2": 2023,
    "PlayStation Network": 2006, "Xbox": 2001, "Xbox 360": 2005, "Xbox One": 2013, "Xbox Series X/S": 2020,
    "Nintendo Switch": 2017, "Nintendo Switch 2": 2025, "Wii": 2006, "Wii U": 2012, "GameCube": 2001, "Nintendo 64": 1996,
    "Super Nintendo Entertainment System": 1990, "Game Boy Color": 1998, "Game Boy Advance": 2001, "Nintendo DS": 2004,
    "Nintendo 3DS": 2011, "Virtual Boy": 1995, "Game Gear": 1990, "Sega Saturn": 1994, "Dreamcast": 1998, "Sega 32X": 1994,
    "Sega CD": 1991, "3DO Interactive Multiplayer": 1993, "Atari Jaguar": 1993, "Neo Geo CD": 1994,
    "Neo Geo Pocket Color": 1999, "WonderSwan": 1999, "WonderSwan Color": 2000, "N-Gage": 2003, "iOS": 2007, "Android": 2008,
    "Windows Phone": 2010, "tvOS": 2015, "watchOS": 2015, "Stadia": 2019, "Amazon Luna": 2020, "Oculus Rift": 2016,
    "Meta Quest": 2019, "SteamVR": 2015, "Ouya": 2013, "Nvidia Shield": 2013, "Amazon Fire TV": 2014, "Fire OS": 2011,
    "PICO 4": 2022, "Atari VCS": 2021, "PC-FX": 1994, "Linux": 1991, "Windows": 1985, "Zeebo": 2009, "GameStick": 2013,
    "CD-i": 1991, "Amiga CDTV": 1991, "Amiga CD32": 1993, "Atari Jaguar CD": 1995, "Satellaview": 1995,
    "Nintendo 64DD": 1999, "Neo Geo Pocket": 1998, "Windows Mobile": 2000, "Gear VR": 2015, "Daydream": 2016,
    "Windows Mixed Reality": 2017, "visionOS": 2024, "Evercade": 2020, "Apple Pippin": 1996, "Sega Pico": 1993,
    "GP32": 2001, "Game.com": 1997, "Facebook": 2007, "OnLive": 2010, "Nuon": 2000, "GP2X": 2005, "HarmonyOS": 2019,
}


def available_in_year(platforms, year, released_years=None):
    """Drop the platforms that provably came later than `year`.

    `released_years` ({platform: earliest release year}) is used where the
    infobox gave per-platform dates; otherwise a platform is kept only if it
    had launched by the following year (allowing for pre-launch releases)."""
    kept = []
    for platform in platforms:
        known = (released_years or {}).get(platform)
        if known is not None:
            if known <= year:
                kept.append(platform)
        else:
            launch = PLATFORM_LAUNCH_YEAR.get(platform)
            if launch is None or launch <= year + 1:
                kept.append(platform)
    return kept
