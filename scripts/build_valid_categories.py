import csv
import openpyxl
from pathlib import Path

SOURCE = Path("data/raw/related_ocuppations.xlsx")
OUTPUT = Path("data/valid_categories.csv")


def build():
    wb = openpyxl.load_workbook(SOURCE)
    ws = wb.active

    titles = set()
    for i, row in enumerate(ws.iter_rows(values_only=True)):
        if i == 0:
            continue
        if row[1]:
            titles.add(row[1])

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)

    with open(OUTPUT, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["category"])
        for title in sorted(titles):
            writer.writerow([title])

    print(f"Generadas {len(titles)} categorías en {OUTPUT}")


if __name__ == "__main__":
    build()
