import pytest

from agents.pre_processor import normalize_title


@pytest.mark.parametrize("raw, expected", [
    # Type 2 — casing/punctuation
    ("FULL-STACK DEVELOPER", "full stack developer"),
    ("HUMAN_RESOURCES", "human resources"),
    # Type 3 — seniority stripping
    ("Senior Frontend Developer", "frontend developer"),
    ("Jr. Software Engineer", "software engineer"),
    ("Lead Data Scientist", "data scientist"),
    ("Principal Product Manager", "product manager"),
    ("Staff Engineer", "engineer"),
    # Type 4 — noise/context
    ("Dev - Remoto (Contract)", "dev"),
    ("Developer | Full Stack", "developer"),
    ("Engineer / Backend", "engineer"),
    ("Software Developer (Contractor)", "software developer"),
    # Combined
    ("Senior Backend Dev - Remote", "backend dev"),
    ("JUNIOR DATA SCIENTIST (Full Time)", "data scientist"),
    # Type 1 input — normalize_title doesn't fix typos, just cleans; rapidfuzz handles typos
    ("Fronted Developer", "fronted developer"),
    # Accented characters (NFKD strip)
    ("Desarrolladora Backend", "desarrolladora backend"),
    # Already clean
    ("Software Engineer", "software engineer"),
    # Cycle 1 — em-dash / en-dash separator
    ("Dev — Remote", "dev"),
    ("Dev – Remoto", "dev"),
    # Cycle 2 — non-breaking space (NFKD maps   → ASCII space, already handled)
    ("Software Engineer", "software engineer"),
    # Cycle 3 — ampersand expansion
    ("Sales & Marketing Manager", "sales and marketing manager"),
    ("Research & Development", "research and development"),
    # Cycle 4 — comma + credential stripping
    ("Accountant, CPA", "accountant"),
    ("Nurse, RN", "nurse"),
    # Cycle 5 — trailing filler words
    ("Engineering of", "engineering"),
    ("Developer and", "developer"),
    ("Head of Engineering", "engineering"),
    # Cycle 6 — numeric level suffix
    ("Developer 2", "developer"),
    ("Engineer 3", "engineer"),
    # Cycle 7 — Roman numeral level suffix (II+ only; I alone is ambiguous)
    ("Developer II", "developer"),
    ("Engineer III", "engineer"),
    ("Analyst IV", "analyst"),
    ("Developer I", "developer i"),
    # Cycle 8 — edge cases
    ("", ""),
    ("   ", ""),
    ("x", "x"),
])
def test_normalize_title(raw: str, expected: str) -> None:
    assert normalize_title(raw) == expected