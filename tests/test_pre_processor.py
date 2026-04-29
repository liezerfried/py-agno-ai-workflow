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
])
def test_normalize_title(raw: str, expected: str) -> None:
    assert normalize_title(raw) == expected