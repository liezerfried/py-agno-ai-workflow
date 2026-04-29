import re
import unicodedata

# Compiled once at import time for efficiency.
# Order matters in normalize_title: separators/parens are stripped before seniority
# so seniority words inside noise fragments don't leave orphaned tokens.

# Drops everything after " - ", " | ", or " / " (e.g. "Dev - Remoto" → "Dev")
_NOISE_SEPARATOR = re.compile(r"\s+[-|/]\s+.*$")

# Drops parenthetical context (e.g. "Developer (Full Stack)" → "Developer")
_NOISE_PARENS = re.compile(r"\s*\(.*$")

# Strips seniority/level words so "Senior Frontend Dev" and "Frontend Dev" map to the same token.
# Word-boundary anchors (\b) prevent partial matches inside words like "leadership".
_SENIORITY = re.compile(
    r"\b(senior|sr\.?|junior|jr\.?|lead|staff|principal|mid|"
    r"entry[\s-]level|entry|associate|head\s+of|head)\b",
    re.IGNORECASE,
)

# Catches dangling articles left behind after seniority removal (e.g. "Head of Engineering" → "of Engineering" → "Engineering")
_LEADING_FILLER = re.compile(r"^\s*(of|the|a|and)\s+")

# Removes any remaining leading punctuation or whitespace before the first real word
_LEADING_PUNCT = re.compile(r"^[\s.,;:]+")


def normalize_title(raw: str) -> str:
    # NFKD decomposes accented chars; encoding to ASCII then drops the diacritic bytes.
    # This handles "Désarrolleur" → "Desarrolleur" without a translation table.
    title = unicodedata.normalize("NFKD", raw.strip()).encode("ascii", "ignore").decode()

    # Lowercase before regex passes so all patterns can be case-insensitive without re.I overhead.
    title = title.lower()

    title = _NOISE_SEPARATOR.sub("", title)
    title = _NOISE_PARENS.sub("", title)
    title = _SENIORITY.sub("", title)
    title = _LEADING_FILLER.sub("", title)
    title = _LEADING_PUNCT.sub("", title)

    # Unify token delimiters: "full-stack" and "full_stack" both become "full stack"
    title = re.sub(r"[-_]", " ", title)

    # Collapse any multi-space gaps left by substitutions above
    title = re.sub(r"\s+", " ", title).strip()
    return title