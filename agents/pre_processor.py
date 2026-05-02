"""
Cleans raw job titles before they reach rapidfuzz or the LLM (normalization Types 2–4).
Called inside mapping_pipeline.score() for every category — zero API calls, zero latency.
The order of regex operations matters: changing it can leave orphaned tokens in the output.
"""
import re
import unicodedata

# All regex patterns are compiled once when this module is first imported.
# Compiling once is faster than calling re.compile() inside a function that runs
# for every row in a potentially large Excel file.
# Order matters in normalize_title: noise is stripped before seniority
# so seniority words inside noise fragments don't leave orphaned tokens.

# Must run before NFKD — en/em-dash have no ASCII decomposition and would be silently dropped.
# Replaces en-dash (–) and em-dash (—) with a plain ASCII " - " so _NOISE_SEPARATOR can catch them.
_PRE_ASCII_DASH = re.compile(r"[–—]")

# Expands ampersand to "and" so "Sales & Marketing" matches "Sales and Marketing".
# The \s* on each side absorbs surrounding spaces to prevent double-spaces.
# Handles normalization Type 2 (punctuation).
_AMPERSAND = re.compile(r"\s*&\s*")

# Strips short credential abbreviations after a comma (e.g. "Accountant, CPA" → "Accountant").
# Limited to 2–3 chars so O*NET's specialization format ("Bus Drivers, School") is NOT affected.
# Handles normalization Type 4 (noise/context).
_CREDENTIAL = re.compile(r",\s*[a-z]{2,3}\s*$")

# Drops everything after " - ", " | ", or " / " (e.g. "Dev - Remoto (Contract)" → "Dev").
# These suffixes describe work arrangement or location, not the job role itself.
# Handles normalization Type 4 (noise/context).
_NOISE_SEPARATOR = re.compile(r"\s+[-|/]\s+.*$")

# Drops parenthetical context appended after the role (e.g. "Developer (Full Stack)" → "Developer").
# Handles normalization Type 4 (noise/context).
_NOISE_PARENS = re.compile(r"\s*\(.*$")

# Strips seniority/level words so "Senior Frontend Dev" and "Frontend Dev" produce the same base token.
# \b (word boundary) prevents partial matches inside longer words like "leadership" or "principal".
# Handles normalization Type 3 (seniority stripping).
_SENIORITY = re.compile(
    r"\b(senior|sr\.?|junior|jr\.?|lead|staff|principal|mid|"
    r"entry[\s-]level|entry|associate|head\s+of|head)\b",
    re.IGNORECASE,
)

# Catches dangling prepositions left at the start after seniority removal
# (e.g. "Head of Engineering" → seniority strips "Head" → "of Engineering" → "Engineering").
_LEADING_FILLER = re.compile(r"^\s*(of|the|a|and)\s+")

# Strips trailing prepositions left at the end after noise removal
# (e.g. "Engineering of" → "Engineering").
_TRAILING_FILLER = re.compile(r"\s+(of|the|a|and)\s*$")

# Strips numeric and Roman-numeral level markers (e.g. "Engineer 3" → "Engineer", "Developer II" → "Developer").
# Roman numerals II–VIII only — single "I" is excluded because it is too ambiguous as a standalone token.
# Handles normalization Type 3 (seniority stripping).
_LEVEL_SUFFIX = re.compile(r"\s+([2-9]|ii|iii|iv|v|vi|vii|viii)\s*$")

# Removes any remaining leading punctuation or whitespace before the first real word.
# Catches edge cases like ", Frontend Developer" left after credential stripping.
_LEADING_PUNCT = re.compile(r"^[\s.,;:]+")

# Final cleanup: normalize all hyphens and underscores to spaces, then collapse runs of spaces.
_DELIMITERS = re.compile(r"[-_]")
_WHITESPACE = re.compile(r"\s+")


def normalize_title(raw: str) -> str:
    """
    Apply a deterministic sequence of text-cleaning rules to a raw job title.

    Handles normalization Types 2–4 without any API calls:
      - Type 2 (casing/punctuation): lowercasing, dash/ampersand normalization.
      - Type 3 (seniority stripping): removes "Senior", "Junior", Roman numerals, etc.
      - Type 4 (noise/context): removes separators, parentheticals, credential suffixes.

    The output is fed directly to rapidfuzz.process.extract() in mapping_pipeline.score().
    A cleaner input string means higher similarity scores and fewer unnecessary LLM calls.

    Args:
        raw: The original free-text job title exactly as read from the Excel file.

    Returns:
        A lowercase, accent-free, noise-stripped version of the title suitable for
        fuzzy matching against the O*NET canonical title list.
    """
    title = raw.strip()

    # Step 1 — Pre-NFKD: normalize special characters that ASCII encoding would drop or mishandle.
    title = _PRE_ASCII_DASH.sub(" - ", title)   # en/em-dash → ASCII hyphen (must run before NFKD)
    title = _AMPERSAND.sub(" and ", title)       # & → "and" (Type 2: punctuation normalization)

    # Step 2 — Strip accents: NFKD decomposes "é" into "e" + a combining accent byte;
    # encode("ascii", "ignore") drops the accent byte, leaving just "e".
    # Also converts non-breaking space ( ) to a regular space via compatibility decomposition.
    title = unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode()

    title = title.lower()   # Type 2: casing normalization — "FULL-STACK" and "full-stack" become identical

    # Step 3 — Remove noise and seniority markers (Types 3 and 4).
    title = _CREDENTIAL.sub("", title)          # "Accountant, CPA" → "Accountant" (Type 4)
    title = _NOISE_SEPARATOR.sub("", title)     # "Dev - Remoto" → "Dev" (Type 4)
    title = _NOISE_PARENS.sub("", title)        # "Developer (Full Stack)" → "Developer" (Type 4)
    title = _SENIORITY.sub("", title)           # "Senior Frontend Dev" → " Frontend Dev" (Type 3)
    title = _LEADING_FILLER.sub("", title)      # "of Engineering" → "Engineering" (orphan cleanup)
    title = _TRAILING_FILLER.sub("", title)     # "Engineering of" → "Engineering" (orphan cleanup)
    title = _LEVEL_SUFFIX.sub("", title)        # "Engineer II" → "Engineer" (Type 3)
    title = _LEADING_PUNCT.sub("", title)       # Remove any remaining leading punctuation

    # Step 4 — Final normalization: unify delimiters and collapse whitespace.
    title = _DELIMITERS.sub(" ", title)         # Hyphens and underscores → spaces
    title = _WHITESPACE.sub(" ", title).strip() # Collapse multiple spaces into one
    return title
