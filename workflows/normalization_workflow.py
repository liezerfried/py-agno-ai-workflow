import csv
from pathlib import Path

_VALID_CATEGORIES_PATH = Path(__file__).parent.parent / "data" / "valid_categories.csv"


def load_valid_categories() -> list[str]:
    with open(_VALID_CATEGORIES_PATH, newline="", encoding="utf-8") as f:
        return [row["category"] for row in csv.DictReader(f)]