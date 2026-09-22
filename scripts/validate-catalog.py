#!/usr/bin/env python3
"""Validate that every catalog row comes from the workbook and has both audios."""

import json
from pathlib import Path
import re

import openpyxl


ROOT = Path(__file__).resolve().parents[1]
WORKBOOK = ROOT / "English_B2.xlsx"
CATALOG = ROOT / "data" / "phrases.json"


def clean(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()


def main():
    workbook = openpyxl.load_workbook(WORKBOOK, read_only=True, data_only=True, keep_vba=True)
    sheet = workbook["Curso_B2"]
    source_rows = []
    for row in sheet.iter_rows(min_row=2, values_only=True):
        if len(row) >= 6 and clean(row[0]) and clean(row[4]) and clean(row[5]):
            source_rows.append((clean(row[0]), clean(row[4]), clean(row[5])))

    catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
    assert len(source_rows) == 5000, f"Excel: {len(source_rows)} filas válidas"
    assert len(catalog) == len(source_rows), f"Catálogo: {len(catalog)} filas"
    assert len({row["sourceId"] for row in catalog}) == len(catalog), "IDs duplicados"

    for source, row in zip(source_rows, catalog):
        source_id, english, spanish = source
        assert row["sourceId"] == source_id
        assert row["en"] == english
        assert row["es"] == spanish
        assert (ROOT / row["audioEnglish"]).is_file(), row["audioEnglish"]
        assert (ROOT / row["audioSpanish"]).is_file(), row["audioSpanish"]

    print(f"OK: {len(catalog)} filas del Excel coinciden con sus dos audios por ID.")


if __name__ == "__main__":
    main()
