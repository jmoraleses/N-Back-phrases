#!/usr/bin/env python3
"""Process SRT subtitles: parse, translate to Spanish, generate TTS audio, and create phrases.json."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import shutil
from pathlib import Path
from typing import Any
import numpy as np
import wave

try:
    import torch
    from transformers import AutoModelForTextToWaveform, AutoTokenizer, AutoModelForSeq2SeqLM
    TORCH_AVAILABLE = True
except ImportError:
    torch = None
    AutoModelForTextToWaveform = None
    AutoTokenizer = None
    AutoModelForSeq2SeqLM = None
    TORCH_AVAILABLE = False

TRANSFORMERS_AVAILABLE = TORCH_AVAILABLE

try:
    import pysrt
    PYsrt_AVAILABLE = True
except ImportError:
    pysrt = None
    PYsrt_AVAILABLE = False


ROOT = Path(__file__).resolve().parent
SUBTITLES_DIR = ROOT / "subtitles"
DATA_DIR = ROOT / "data"
AUDIO_EN_DIR = ROOT / "audio_english"
AUDIO_ES_DIR = ROOT / "audio_spanish"
TTS_CACHE = ROOT / ".tts-cache"
PHRASES_JSON = DATA_DIR / "phrases.json"
MODELS_DIR = ROOT / "models"

# NLLB language codes
NLLB_LANGUAGE_CODES = {
    "en": "eng_Latn",
    "es": "spa_Latn",
}

# MMS-TTS language codes
MMS_TTS_LANGUAGE_CODES = {
    "en": "eng",
    "es": "spa",
}

DEFAULT_NLLB_MODEL = "facebook/nllb-200-distilled-600M"


def clean_directories() -> None:
    """Remove all previous audio files and cache."""
    for directory in [AUDIO_EN_DIR, AUDIO_ES_DIR, TTS_CACHE]:
        if directory.exists():
            shutil.rmtree(directory)
        directory.mkdir(parents=True, exist_ok=True)
    print("Limpiados directorios de audio y caché anteriores.")


def parse_srt_files() -> list[str]:
    """Parse all SRT files in subtitles directory and extract English text."""
    if not PYsrt_AVAILABLE:
        raise RuntimeError("pysrt no está instalado. Ejecuta: pip install pysrt")

    phrases = []
    srt_files = list(SUBTITLES_DIR.glob("*.srt"))

    if not srt_files:
        raise FileNotFoundError(f"No se encontraron archivos .srt en {SUBTITLES_DIR}")

    for srt_file in srt_files:
        print(f"Procesando: {srt_file.name}")
        subs = pysrt.open(str(srt_file), encoding="utf-8")
        for sub in subs:
            text = sub.text.strip()
            text = text.replace("\n", " ")
            text = " ".join(text.split())
            if text and len(text) > 1:
                phrases.append(text)

    print(f"Extraídas {len(phrases)} frases de {len(srt_files)} archivo(s) SRT.")
    return phrases


class LocalTranslator:
    """Local translator using NLLB-200 model."""
    
    def __init__(self):
        self._model = None
        self._tokenizer = None
        self._device = None
        self._lock = __import__('threading').Lock()
    
    def _load_model(self):
        """Load NLLB model and tokenizer."""
        if self._model is not None:
            return
        
        with self._lock:
            if self._model is not None:
                return
            
            if not TRANSFORMERS_AVAILABLE:
                raise RuntimeError("transformers no está instalado. Ejecuta: pip install transformers")
            
            print(f"Cargando modelo NLLB: {DEFAULT_NLLB_MODEL}")
            MODELS_DIR.mkdir(parents=True, exist_ok=True)
            
            self._tokenizer = AutoTokenizer.from_pretrained(
                DEFAULT_NLLB_MODEL,
                cache_dir=str(MODELS_DIR),
                local_files_only=False
            )
            self._model = AutoModelForSeq2SeqLM.from_pretrained(
                DEFAULT_NLLB_MODEL,
                cache_dir=str(MODELS_DIR),
                local_files_only=False
            )
            
            # Set device
            if TORCH_AVAILABLE:
                mps_backend = getattr(torch.backends, 'mps', None)
                device_name = "mps" if mps_backend and mps_backend.is_available() else "cpu"
                self._device = torch.device(device_name)
                self._model.to(self._device)
                if self._device.type == "mps":
                    self._model.half()
            else:
                self._device = __import__('torch').device('cpu')
            
            self._model.eval()
            print("Modelo NLLB cargado correctamente.")
    
    def translate_to_spanish(self, texts: list[str]) -> list[str]:
        """Translate English texts to Spanish using NLLB-200."""
        self._load_model()
        
        translated = []
        source_lang = NLLB_LANGUAGE_CODES["en"]
        target_lang = NLLB_LANGUAGE_CODES["es"]
        
        for i, text in enumerate(texts):
            try:
                self._tokenizer.src_lang = source_lang
                encoded = self._tokenizer(
                    [text],
                    return_tensors="pt",
                    padding=True,
                    truncation=True
                )
                encoded = {key: value.to(self._device) for key, value in encoded.items()}
                
                with torch.no_grad():
                    generated = self._model.generate(
                        **encoded,
                        forced_bos_token_id=self._tokenizer.convert_tokens_to_ids(target_lang),
                        max_new_tokens=160,
                        num_beams=1
                    )
                
                result = self._tokenizer.batch_decode(generated, skip_special_tokens=True)[0].strip()
                translated.append(result)
                
                if (i + 1) % 50 == 0:
                    print(f"  Traducidas {i + 1}/{len(texts)} frases...")
                    
            except Exception as e:
                print(f"Error traduciendo: {text[:50]}... - {e}")
                translated.append(text)
        
        print(f"Traducción completada: {len(translated)} frases.")
        return translated


def translate_to_spanish(texts: list[str]) -> list[str]:
    """Translate English texts to Spanish using NLLB-200."""
    if not TRANSFORMERS_AVAILABLE:
        raise RuntimeError("transformers no está instalado. Ejecuta: pip install transformers")
    
    translator = LocalTranslator()
    return translator.translate_to_spanish(texts)


def generate_cache_name(text: str, language: str) -> str:
    """Generate cache filename from text and language."""
    digest = hashlib.sha256(f"{language}\0{text}".encode("utf-8")).hexdigest()[:24]
    return f"{digest}.wav"


class LocalTTS:
    """Local TTS using MMS-TTS model."""
    
    def __init__(self):
        self._models = {}
        self._lock = __import__('threading').Lock()
    
    def _load_model(self, language: str):
        """Load MMS-TTS model for specific language."""
        if language in self._models:
            return self._models[language]
        
        with self._lock:
            if language in self._models:
                return self._models[language]
            
            if not TORCH_AVAILABLE or not TRANSFORMERS_AVAILABLE:
                raise RuntimeError("torch y transformers no están instalados")
            
            model_code = MMS_TTS_LANGUAGE_CODES.get(language)
            if not model_code:
                raise RuntimeError(f"MMS-TTS no tiene modelo para {language}")
            
            model_ref = f"facebook/mms-tts-{model_code}"
            print(f"Cargando modelo MMS-TTS: {model_ref}")
            MODELS_DIR.mkdir(parents=True, exist_ok=True)
            
            tokenizer = AutoTokenizer.from_pretrained(
                model_ref,
                cache_dir=str(MODELS_DIR),
                local_files_only=False
            )
            model = AutoModelForTextToWaveform.from_pretrained(
                model_ref,
                cache_dir=str(MODELS_DIR),
                local_files_only=False
            )
            
            # Set device
            mps_backend = getattr(torch.backends, 'mps', None)
            device_name = "mps" if mps_backend and mps_backend.is_available() else "cpu"
            device = torch.device(device_name)
            model.to(device)
            model.eval()
            
            self._models[language] = (tokenizer, model, device)
            print(f"Modelo MMS-TTS cargado para {language}.")
            return self._models[language]
    
    def generate_audio(self, text: str, language: str, output: Path) -> str:
        """Generate TTS audio using MMS-TTS."""
        tokenizer, model, device = self._load_model(language)
        
        encoded = tokenizer(
            text, return_tensors="pt", padding=True, truncation=True
        )
        encoded = {key: value.to(device) for key, value in encoded.items()}
        
        with torch.no_grad():
            waveform = model(**encoded).waveform
        
        values = waveform.squeeze().detach().float().cpu().numpy().astype(np.float32)
        sample_rate = int(getattr(model.config, "sampling_rate", 16_000))
        
        # Save as WAV file
        pcm = np.clip(values, -1.0, 1.0)
        pcm = (pcm * 32767.0).astype(np.int16)
        
        with wave.open(str(output), 'wb') as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(sample_rate)
            wav_file.writeframes(pcm.tobytes())
        
        return "mms-tts"


def generate_tts_audio(text: str, language: str, output: Path) -> str:
    """Generate TTS audio using MMS-TTS."""
    if not TORCH_AVAILABLE or not TRANSFORMERS_AVAILABLE:
        raise RuntimeError("torch y transformers no están instalados. Ejecuta: pip install torch transformers")
    
    tts = LocalTTS()
    return tts.generate_audio(text, language, output)


async def process_phrases(english_texts: list[str], spanish_texts: list[str]) -> list[dict[str, Any]]:
    """Generate audio for all phrases and create phrases.json structure."""
    phrases_data = []
    total = len(english_texts)

    for i, (en_text, es_text) in enumerate(zip(english_texts, spanish_texts)):
        phrase_id = f"phrase-{i + 1}"
        source_id = str(i + 1)

        en_cache_name = generate_cache_name(en_text, "en")
        es_cache_name = generate_cache_name(es_text, "es")

        en_cache_path = TTS_CACHE / en_cache_name
        es_cache_path = TTS_CACHE / es_cache_name

        en_audio_path = AUDIO_EN_DIR / f"{i + 1:04d}.wav"
        es_audio_path = AUDIO_ES_DIR / f"{i + 1:04d}.wav"

        if not en_cache_path.exists() or en_cache_path.stat().st_size == 0:
            await generate_tts_audio(en_text, "en", en_cache_path)
        shutil.copy2(en_cache_path, en_audio_path)

        if not es_cache_path.exists() or es_cache_path.stat().st_size == 0:
            await generate_tts_audio(es_text, "es", es_cache_path)
        shutil.copy2(es_cache_path, es_audio_path)

        phrase_data = {
            "id": phrase_id,
            "sourceId": source_id,
            "en": en_text,
            "es": es_text,
            "audioEnglish": f"audio_english/{i + 1:04d}.wav",
            "audioSpanish": f"audio_spanish/{i + 1:04d}.wav",
            "levels": ["B2"],
            "themes": ["Subtitles"],
            "frequencies": ["Media"],
        }
        phrases_data.append(phrase_data)

        if (i + 1) % 20 == 0:
            print(f"  Generados audios {i + 1}/{total}...")

    print(f"Generación de audio completada: {total} frases.")
    return phrases_data


def save_phrases_json(phrases_data: list[dict[str, Any]]) -> None:
    """Save phrases data to JSON file."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(PHRASES_JSON, "w", encoding="utf-8") as f:
        json.dump(phrases_data, f, ensure_ascii=False, indent=2)
    print(f"Guardado {PHRASES_JSON} con {len(phrases_data)} frases.")


async def main() -> None:
    """Main processing pipeline."""
    print("=" * 60)
    print("PROCESADOR DE SUBTÍTULOS - English Phrase N-Back")
    print("=" * 60)

    if not PYsrt_AVAILABLE:
        print("ERROR: pysrt no instalado. Ejecuta: pip install pysrt")
        return
    if not TRANSFORMERS_AVAILABLE:
        print("ERROR: transformers no instalado. Ejecuta: pip install transformers")
        return
    if not TORCH_AVAILABLE:
        print("ERROR: torch no instalado. Ejecuta: pip install torch")
        return

    clean_directories()

    print("\n1. Extrayendo frases de subtítulos...")
    english_texts = parse_srt_files()

    print("\n2. Traduciendo al español...")
    spanish_texts = translate_to_spanish(english_texts)

    print("\n3. Generando audios (inglés y español)...")
    phrases_data = await process_phrases(english_texts, spanish_texts)

    print("\n4. Guardando phrases.json...")
    save_phrases_json(phrases_data)

    print("\n" + "=" * 60)
    print("¡PROCESO COMPLETADO!")
    print(f"Frases procesadas: {len(phrases_data)}")
    print(f"Audio inglés: {AUDIO_EN_DIR}")
    print(f"Audio español: {AUDIO_ES_DIR}")
    print(f"Catálogo: {PHRASES_JSON}")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())