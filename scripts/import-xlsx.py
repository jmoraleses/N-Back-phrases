#!/usr/bin/env python3
"""Convert the supplied English phrase workbook into the web app catalog."""

from pathlib import Path
import json
import re

import openpyxl


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "English_B2.xlsx"
OUTPUT = ROOT / "data" / "phrases.json"

def clean(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()


def main():
    workbook = openpyxl.load_workbook(SOURCE, read_only=True, data_only=True, keep_vba=True)
    sheet = workbook["Curso_B2"]
    rows = sheet.iter_rows(min_row=2, values_only=True)

    catalog = []
    for row_number, row in enumerate(rows, 2):
        if len(row) < 6:
            continue
        source_id = clean(row[0])
        record = {
            "id": f"phrase-{source_id}",
            "sourceId": source_id,
            "level": clean(row[1]),
            "theme": clean(row[2]),
            "frequency": clean(row[3]),
            "en": clean(row[4]),
            "es": clean(row[5]),
        }
        if record["en"] and record["es"]:
            catalog.append(
                {
                    "id": record["id"],
                    "sourceId": source_id,
                    "en": record["en"],
                    "es": record["es"],
                    "audioEnglish": f"audio_english/{int(source_id):04d}.mp3",
                    "audioSpanish": f"audio_spanish/{int(source_id):04d}.mp3",
                    "levels": [record["level"]],
                    "themes": [record["theme"]],
                    "frequencies": [record["frequency"]],
                }
            )

    OUTPUT.write_text(json.dumps(catalog, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Imported {len(catalog)} rows from {SOURCE.name} -> {OUTPUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
