"""Parse the {{Infobox video game}} template out of an article's wikitext.

scrape_categories.py gets only article titles from a category page, so the
developer, publisher, genre, platforms and release date for those games come
from each article's infobox. Infobox values are free-form wikitext -- piped
links, <br> lists, {{ubl}} / {{plainlist}} / {{collapsible list}} templates,
{{vgrelease|EU|date|NA|date}} regional values, bold per-platform release dates,
citations -- so this module reduces them to plain names and dates without
needing a full wikitext parser.
"""
import html
import re

from titles import FOOTNOTE_RE

# titles.FOOTNOTE_RE, but never the lone letter of a link such as [[R]]
_FOOTNOTE_RE = re.compile(r"(?<!\[)" + FOOTNOTE_RE.pattern)

# {{Infobox video game}} and its redirects (older articles still use "Infobox CVG" / "Infobox VG").
_BLOCK_START_RE = re.compile(
    r"\{\{\s*Infobox[ _-]*(?:video[ _-]*games?|VG|CVG|computer[ _]+(?:and[ _]+video[ _]+)?games?|videogame)\b",
    re.IGNORECASE,
)
_REDIRECT_RE = re.compile(r"^\s*#REDIRECT\s*:?\s*\[\[([^\[\]|#]+)", re.IGNORECASE)
_BOLD_RE = re.compile(r"'{3,5}.+?'{3,5}")
_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
_REF_SELF_CLOSING_RE = re.compile(r"<ref\b[^>]*/>", re.IGNORECASE)
_REF_RE = re.compile(r"<ref\b[^>]*>.*?</ref>", re.IGNORECASE | re.DOTALL)
_INNERMOST_TEMPLATE_RE = re.compile(r"\{\{([^{}]*)\}\}")
_WIKILINK_RE = re.compile(r"\[\[([^\[\]|]+?)(?:#[^\[\]|]*)?(?:\|([^\[\]]*))?\]\]")
_EXTERNAL_LINK_RE = re.compile(r"\[(?:https?:)?//\S+(?:\s+([^\]]+))?\]")

# Templates whose arguments are the content (list items, nowrap text, ...).
_LIST_TEMPLATES = {"ubl", "ublist", "unbulleted list", "hlist", "bulleted list", "collapsible list", "collapsible", "cslist"}
_BULLET_TEMPLATES = {"plainlist", "plain list", "flatlist", "flat list"}
_PASSTHROUGH_TEMPLATES = {"small", "nobold", "noitalic", "nowrap", "abbr", "lang", "smaller", "larger", "nobr", "wbr"}
# Regional release/credit templates: alternating region code, value, region code, value...
_REGIONAL_TEMPLATES = {"vgrelease", "video game release", "vgr", "video game release2"}


def find_infobox(wikitext):
    """The text of the {{Infobox video game ...}} template (balanced braces), or None."""
    match = _BLOCK_START_RE.search(wikitext or "")
    if not match:
        return None
    depth, i, text = 0, match.start(), wikitext
    while i < len(text):
        if text.startswith("{{", i):
            depth += 1
            i += 2
        elif text.startswith("}}", i):
            depth -= 1
            i += 2
            if depth == 0:
                return text[match.start():i]
        else:
            i += 1
    return None


def redirect_target(wikitext):
    """The article a #REDIRECT page points at, else None."""
    match = _REDIRECT_RE.match(wikitext or "")
    return match.group(1).strip() if match else None


def _split_top_level(text, sep="|"):
    """Split on `sep` only outside {{ }} and [[ ]]."""
    parts, depth_t, depth_l, current, i = [], 0, 0, [], 0
    while i < len(text):
        two = text[i:i + 2]
        if two == "{{":
            depth_t += 1
            current.append(two)
            i += 2
        elif two == "}}":
            depth_t -= 1
            current.append(two)
            i += 2
        elif two == "[[":
            depth_l += 1
            current.append(two)
            i += 2
        elif two == "]]":
            depth_l -= 1
            current.append(two)
            i += 2
        elif text[i] == sep and depth_t == 0 and depth_l == 0:
            parts.append("".join(current))
            current = []
            i += 1
        else:
            current.append(text[i])
            i += 1
    parts.append("".join(current))
    return parts


def parse_params(infobox):
    """{param name (lowercase): raw wikitext value} of an infobox template."""
    body = _COMMENT_RE.sub("", infobox)[2:-2]
    params = {}
    for part in _split_top_level(body)[1:]:  # [0] is the template name
        if "=" not in part:
            continue
        key, value = part.split("=", 1)
        params[key.strip().lower()] = value.strip()
    return params


# Articles spell some fields differently ("platform", "release"); first non-empty spelling wins.
_FIELD_ALIASES = {
    "developer": ("developer", "developers"),
    "publisher": ("publisher", "publishers"),
    "genre": ("genre", "genres"),
    "platforms": ("platforms", "platform"),
    "released": ("released", "release"),
}


def field(params, name):
    """The raw value of an infobox field under whichever spelling the article uses, or None."""
    for key in _FIELD_ALIASES[name]:
        if params.get(key):
            return params[key]
    return None


def remove_refs(text):
    text = _COMMENT_RE.sub("", text)
    text = _REF_SELF_CLOSING_RE.sub("", text)
    return _REF_RE.sub("", text)


def _template_args(inner):
    """(lowercase name, positional args, named args) of one innermost template body."""
    parts = _split_top_level(inner)
    name = parts[0].strip().lower()
    positional, named = [], {}
    for part in parts[1:]:
        key, eq, value = part.partition("=")
        if eq and re.fullmatch(r"\s*[A-Za-z_ ]+\s*", key):
            named[key.strip().lower()] = value.strip()
        else:
            positional.append(part.strip())
    return name, positional, named


def _expand_one(match):
    name, positional, named = _template_args(match.group(1))
    # List-like templates are blocks: surround them with line breaks so text
    # written right before or after one ("Namco{{vgrelease|EU|[[Sega]]}}")
    # doesn't fuse with the first or last item.
    if name in _REGIONAL_TEMPLATES:
        # alternating region code / value; keep the values
        return "\n" + "\n".join(v for i, v in enumerate(positional) if i % 2 == 1 and v) + "\n"
    if name in _BULLET_TEMPLATES:
        items = []
        for arg in positional:
            items += [i.strip() for i in re.split(r"(?:^|\n|\s)\*\s*", arg) if i.strip()]
        return "\n" + "\n".join(items) + "\n"
    if name in _LIST_TEMPLATES:
        items = list(positional)
        if name in ("collapsible list", "collapsible") and named.get("title"):
            items.insert(0, named["title"])
        return "\n" + "\n".join(i for i in items if i) + "\n"
    if name in _PASSTHROUGH_TEMPLATES:
        return positional[0] if positional else ""
    if name in ("start date", "start date and age", "release date", "film date"):
        nums = [p for p in positional if re.fullmatch(r"\d+", p)]
        if nums and len(nums[0]) == 4:
            return "-".join([nums[0]] + [n.zfill(2) for n in nums[1:3]])
    return ""  # citations, notes (efn), anything unknown: drop


def expand_templates(text):
    """Replace templates (innermost first) with their plain content."""
    for _ in range(12):
        new = _INNERMOST_TEMPLATE_RE.sub(_expand_one, text)
        if new == text:
            break
        text = new
    return text


def _strip_markup(text):
    text = _WIKILINK_RE.sub(lambda m: (m.group(2) or m.group(1)).strip(), text)
    text = _EXTERNAL_LINK_RE.sub(lambda m: m.group(1) or "", text)
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    text = text.replace("'''", "").replace("''", "")
    return html.unescape(text).replace("\xa0", " ")


def links_and_text(value):
    """([(link target, label)], plain text) of a value, refs/templates removed.
    List items stay newline-separated."""
    # footnote markers can sit inside a link label: [[Quintet|Shade[a]]]
    text = _FOOTNOTE_RE.sub("", expand_templates(remove_refs(value or "")))
    links = [(m.group(1).strip(), (m.group(2) or "").strip()) for m in _WIKILINK_RE.finditer(text)]
    return links, _strip_markup(text)


_REGION_LABEL_RE = re.compile(r"^\s*(?:WW|JP|NA|EU|AU|AUS|UK|AS|KOR|KR|CN|ROW|PAL)\s*:\s*")


def names(value, limit=4, drop_bold=False):
    """Company/genre-style value -> list of distinct plain names.

    drop_bold: bold text in a developer/publisher list is a platform label
    (Arcade, "PlayStation, Saturn"), not a company -- remove it."""
    if drop_bold:
        stripped = _BOLD_RE.sub("", value or "")
        if re.search(r"[A-Za-z0-9]", _strip_markup(expand_templates(remove_refs(stripped)))):
            value = stripped
    _, text = links_and_text(value)
    out = []
    for line in text.split("\n"):
        line = _REGION_LABEL_RE.sub("", line)
        line = re.sub(r"\s*\([^()]*\)", "", line)  # "(NES/Game Boy)", "(Switch)" notes
        line = re.sub(r"[ \t]+", " ", line).strip(" ,;*|-–")
        if line and line.lower() not in ("tba", "tbd", "n/a", "none", "unknown") and line not in out:
            out.append(line)
        if len(out) >= limit:
            break
    return out


def platform_groups(value):
    """Platform-field value -> groups of alternative spellings, one group per
    item: a link contributes [target, label] (either may be what a platform
    name map knows), each plain-text item contributes [text]. Parenthetical
    notes drop out of the plain text, but links inside them are still seen."""
    links, text = links_and_text(value)
    groups = [[t for t in (target, label) if t] for target, label in links]
    for token in re.split(r"[\n,;/•·&]| and ", re.sub(r"\([^()]*\)", " ", text)):
        token = token.strip(" *-–|")
        if token:
            groups.append([token])
    return groups


_MONTH = r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|June?|July?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)"
_DATE_RE = re.compile(
    rf"(?P<m1>{_MONTH})\.?\s+(?P<d1>\d{{1,2}})(?:st|nd|rd|th)?,?\s+(?P<y1>(?:19|20)\d\d)"      # March 4, 2014
    rf"|(?P<d2>\d{{1,2}})(?:st|nd|rd|th)?\s+(?P<m2>{_MONTH})\.?,?\s+(?P<y2>(?:19|20)\d\d)"      # 4 March 2014
    rf"|(?P<m3>{_MONTH})\.?,?\s+(?P<y3>(?:19|20)\d\d)"                                          # March 2014
    r"|(?P<y4>(?:19|20)\d\d)-(?P<n4>\d\d)-(?P<d4>\d\d)"                                         # 2014-03-04
    r"|(?<![\w.,/-])(?P<y5>(?:19|20)\d\d)(?![\w-])",                                            # 2014
    re.IGNORECASE,
)
_MONTH_NAMES = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"]


def _month_number(text):
    return next(i for i, name in enumerate(_MONTH_NAMES, 1) if name.lower().startswith(text[:3].lower()))


def _date_from_match(m):
    """(year, month or None, day or None)"""
    if m.group("y1"):
        return int(m.group("y1")), _month_number(m.group("m1")), int(m.group("d1"))
    if m.group("y2"):
        return int(m.group("y2")), _month_number(m.group("m2")), int(m.group("d2"))
    if m.group("y3"):
        return int(m.group("y3")), _month_number(m.group("m3")), None
    if m.group("y4"):
        return int(m.group("y4")), int(m.group("n4")), int(m.group("d4"))
    return int(m.group("y5")), None, None


def format_date(date):
    year, month, day = date
    if month and day:
        return f"{_MONTH_NAMES[month - 1]} {day}, {year}"
    if month:
        return f"{_MONTH_NAMES[month - 1]} {year}"
    return str(year)


# A bold date followed by the platforms it applies to: '''1990:''' MS-DOS<br>'''March 1992:''' NES
_DATED_LABEL_RE = re.compile(r"\x01(?P<date>[^\x01\x02]+?)\s*:?\s*\x02[ \t]*:?[ \t]*(?P<platforms>[^\x01\x02\n]*)")


def release_info(value, target_year=None):
    """Read a `released` value.

    Returns (display date, {platform label: earliest release year}, [years of
    dates with no platform label]). Bold text ('''Windows''', '''PS4''') is how
    infoboxes label per-platform release dates; a run of labels takes the next
    date it meets. Some articles turn that around and bold the date instead
    ('''1990:''' Amiga, ST), in which case the platforms follow it. The display
    date is the earliest date in `target_year` (full date, else month + year);
    None when only a bare year is known."""
    raw = re.sub(r"'''(.+?)'''", lambda m: "\x01" + m.group(1) + "\x02", remove_refs(value or ""))
    text = _strip_markup(expand_templates(raw))
    pending, per_platform, unlabelled, dates = [], {}, [], []

    def dated_group(m):
        """'''1990:''' MS-DOS, Amiga  -- the bold part is the date, the platforms follow it."""
        date_match = _DATE_RE.fullmatch(m.group("date").strip(" :"))
        platforms = m.group("platforms").strip()
        if not date_match or not platforms:
            return m.group(0)  # a platform label ('''Windows'''), handled below
        date = _date_from_match(date_match)
        dates.append(date)
        for part in re.split(r"[,/&]| and ", platforms):
            part = part.strip(" :")
            if part and date[0] < per_platform.get(part, 9999):
                per_platform[part] = date[0]
        return "\n"

    text = _DATED_LABEL_RE.sub(dated_group, text)
    label_or_date = re.compile(r"\x01(?P<label>.+?)\x02|(?P<date>" + _DATE_RE.pattern + ")", re.IGNORECASE)
    for m in label_or_date.finditer(text):
        if m.group("label") is not None:
            pending.append(m.group("label"))
            continue
        date = _date_from_match(_DATE_RE.fullmatch(m.group("date")))
        dates.append(date)
        if pending:
            for label in pending:
                for part in re.split(r"[,/&]| and ", label):
                    part = part.strip(" :")
                    if part and date[0] < per_platform.get(part, 9999):
                        per_platform[part] = date[0]
            pending = []
        else:
            unlabelled.append(date[0])
    candidates = [d for d in dates if (target_year is None or d[0] == target_year) and d[1]]
    display = format_date(min(candidates, key=lambda d: (d[1], d[2] or 99))) if candidates else None
    return display, per_platform, unlabelled
