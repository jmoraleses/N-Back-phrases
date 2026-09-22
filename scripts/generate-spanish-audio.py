#!/usr/bin/env python3
"""Create one local Spanish MP3 for every row in the English B2 catalog."""

import asyncio
import hashlib
import json
from pathlib import Path
import shutil

import edge_tts


ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "data" / "phrases.json"
CACHE = ROOT / ".tts-cache"
OUTPUT = ROOT / "audio_spanish"
VOICE = "es-ES-ElviraNeural"


def cache_path(text):
    digest = hashlib.sha256(f"es\0{text}".encode("utf-8")).hexdigest()[:24]
    return CACHE / f"{digest}.mp3"


async def create_cached_audio(text):
    target = cache_path(text)
    if target.exists() and target.stat().st_size > 0:
        return target
    target.parent.mkdir(exist_ok=True)
    await edge_tts.Communicate(text, VOICE).save(str(target))
    return target


async def main():
    rows = json.loads(CATALOG.read_text(encoding="utf-8"))
    OUTPUT.mkdir(exist_ok=True)
    unique_texts = {}
    for row in rows:
        unique_texts.setdefault(row["es"].strip().casefold(), row["es"])

    cached = {}
    for index, text in enumerate(unique_texts.values(), 1):
        cached[text.strip().casefold()] = await create_cached_audio(text)
        print(f"Audio español {index}/{len(unique_texts)} listo", flush=True)

    for row in rows:
        source = cached[row["es"].strip().casefold()]
        target = ROOT / row["audioSpanish"]
        if not target.exists() or target.stat().st_size == 0:
            shutil.copyfile(source, target)
    print(f"Generados {len(rows)} archivos en {OUTPUT.relative_to(ROOT)}/")


if __name__ == "__main__":
    asyncio.run(main())
