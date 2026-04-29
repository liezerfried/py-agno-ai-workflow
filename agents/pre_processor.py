import re
import unicodedata

# Compiled once at import time for efficiency.
# Order matters in normalize_title: noise is stripped before seniority
# so seniority words inside noise fragments don't leave orphaned tokens.

# Must run before NFKD — en/em-dash have no ASCII decomposition and would be silently dropped.
_PRE_ASCII_DASH = re.compile(r"[–—]")
# Expands ampersand to "and" so "Sales & Marketing" matches "Sales and Marketing".
_AMPERSAND = re.compile(r"\s*&\s*")

# Strips short credential abbreviations after a comma (e.g. "Accountant, CPA" → "Accountant").
# Limited to 2–3 chars so O*NET's specialization format ("Bus Drivers, School") is not affected.
_CREDENTIAL = re.compile(r",\s*[a-z]{2,3}\s*$")

# Drops everything after " - ", " | ", or " / " (e.g. "Dev - Remoto" → "Dev")
_NOISE_SEPARATOR = re.compile(r"\s+[-|/]\s+.*$")

# Drops parenthetical context (e.g. "Developer (Full Stack)" → "Developer")
_NOISE_PARENS = re.compile(r"\s*\(.*$")

# Strips seniority/level words so "Senior Frontend Dev" and "Frontend Dev" map to the same token.
# \b prevents partial matches inside words like "leadership".
_SENIORITY = re.compile(
    r"\b(senior|sr\.?|junior|jr\.?|lead|staff|principal|mid|"
    r"entry[\s-]level|entry|associate|head\s+of|head)\b",
    re.IGNORECASE,
)

# Catches dangling particles left behind after seniority removal
# (e.g. "Head of Engineering" → "of Engineering" → "Engineering")
_LEADING_FILLER = re.compile(r"^\s*(of|the|a|and)\s+")
# Strips trailing particles left after noise removal (e.g. "Engineering of" → "Engineering")
_TRAILING_FILLER = re.compile(r"\s+(of|the|a|and)\s*$")

# Strips numeric and Roman-numeral level markers (e.g. "Engineer 3", "Developer II").
# Roman: II–VIII only — single "I" excluded, too ambiguous as a standalone token.
_LEVEL_SUFFIX = re.compile(r"\s+([2-9]|ii|iii|iv|v|vi|vii|viii)\s*$")

# Removes any remaining leading punctuation or whitespace before the first real word
_LEADING_PUNCT = re.compile(r"^[\s.,;:]+")

# Post-processing: unify delimiters and collapse gaps
_DELIMITERS = re.compile(r"[-_]")
_WHITESPACE = re.compile(r"\s+")


def normalize_title(raw: str) -> str:
    title = raw.strip()

    # Pre-NFKD: normalize characters that ASCII encode would silently drop or mishandle.
    title = _PRE_ASCII_DASH.sub(" - ", title)
    title = _AMPERSAND.sub(" and ", title)

    # NFKD decomposes accented chars; ASCII encode then drops the diacritic bytes.
    # Also maps non-breaking space (\u00a0) to regular ASCII space via compatibility decomposition.
    title = unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode()

    title = title.lower()

    title = _CREDENTIAL.sub("", title)
    title = _NOISE_SEPARATOR.sub("", title)
    title = _NOISE_PARENS.sub("", title)
    title = _SENIORITY.sub("", title)
    title = _LEADING_FILLER.sub("", title)
    title = _TRAILING_FILLER.sub("", title)
    title = _LEVEL_SUFFIX.sub("", title)
    title = _LEADING_PUNCT.sub("", title)

    title = _DELIMITERS.sub(" ", title)
    title = _WHITESPACE.sub(" ", title).strip()
    return title