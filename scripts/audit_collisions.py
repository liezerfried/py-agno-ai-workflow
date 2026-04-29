"""
Collision audit: runs normalize_title() over every canonical O*NET title in
valid_categories.csv and reports cases where two distinct titles normalize to
the same string — meaning the pre_processor would make them indistinguishable
before rapidfuzz runs.
"""

import csv
from collections import defaultdict
from pathlib import Path

from agents.pre_processor import normalize_title

CSV_PATH = Path(__file__).parent.parent / "data" / "valid_categories.csv"


def main() -> None:
    with CSV_PATH.open(newline="", encoding="utf-8") as f:
        titles = [row["category"] for row in csv.DictReader(f)]

    print(f"Total canonical titles: {len(titles)}\n")

    bucket: defaultdict[str, list[str]] = defaultdict(list)
    for title in titles:
        bucket[normalize_title(title)].append(title)

    collisions = {k: v for k, v in bucket.items() if len(v) > 1}

    if not collisions:
        print("NO COLLISIONS — pre_processor is safe for all canonical titles.")
        return

    print(f"COLLISIONS FOUND: {len(collisions)} normalized strings map to multiple titles\n")
    print(f"{'Normalized string':<50}  {'Original titles'}")
    print("-" * 90)
    for normalized, originals in sorted(collisions.items()):
        print(f"{normalized:<50}  {originals}")

    print(f"\nTotal titles affected: {sum(len(v) for v in collisions.values())}")


if __name__ == "__main__":
    main()