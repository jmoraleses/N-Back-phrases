#!/usr/bin/env python3
"""Validate the active catalog and, when applicable, its workbook source."""

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
    catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
    assert catalog, "Catálogo vacío"
    assert len({row["id"] for row in catalog}) == len(catalog), "IDs duplicados"
    assert len({row["sourceId"] for row in catalog}) == len(catalog), "sourceId duplicados"

    for row in catalog:
        assert row.get("en"), f"Frase inglesa vacía: {row.get('id')}"
        assert row.get("es"), f"Frase española vacía: {row.get('id')}"
        assert (ROOT / row["audioEnglish"]).is_file(), row["audioEnglish"]
        assert (ROOT / row["audioSpanish"]).is_file(), row["audioSpanish"]

    # Subtitle processing creates a valid catalog with its own source IDs. In
    # that mode there is no workbook row-to-row mapping to compare.
    if any(row.get("subtitleName") for row in catalog):
        print(f"OK: {len(catalog)} frases de subtítulos coinciden con sus dos audios.")
        return

    workbook = openpyxl.load_workbook(WORKBOOK, read_only=True, data_only=True, keep_vba=True)
    sheet = workbook["Curso_B2"]
    source_rows = []
    for row in sheet.iter_rows(min_row=2, values_only=True):
        if len(row) >= 6 and clean(row[0]) and clean(row[4]) and clean(row[5]):
            source_rows.append((clean(row[0]), clean(row[4]), clean(row[5])))

    assert len(source_rows) == 5000, f"Excel: {len(source_rows)} filas válidas"
    assert len(catalog) == len(source_rows), f"Catálogo: {len(catalog)} filas"

    for source, row in zip(source_rows, catalog):
        source_id, english, spanish = source
        assert row["sourceId"] == source_id
        assert row["en"] == english
        assert row["es"] == spanish
    print(f"OK: {len(catalog)} filas del Excel coinciden con sus dos audios por ID.")


if __name__ == "__main__":
    main()
