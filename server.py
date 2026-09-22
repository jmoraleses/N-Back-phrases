#!/usr/bin/env python3
"""Serve the game with pre-generated audio; use local models only for subtitle processing."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
from pathlib import Path
import shutil
import subprocess
import tempfile
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse
import numpy as np
import wave


ROOT = Path(__file__).resolve().parent
CACHE = ROOT / ".tts-cache"
CACHE.mkdir(exist_ok=True)
SUBTITLES_DIR = ROOT / "subtitles"
DATA_DIR = ROOT / "data"
PHRASES_JSON = DATA_DIR / "phrases.json"
TRANSLATION_CACHE = DATA_DIR / "translations.json"
MODELS_DIR = ROOT / "models"
PORT = int(os.environ.get("PHRASE_GAME_PORT", "8000"))

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


def send_json(handler: SimpleHTTPRequestHandler, status: int, payload: dict) -> None:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def send_sse_event(handler: SimpleHTTPRequestHandler, event: str, data: dict) -> None:
    """Send a Server-Sent Event."""
    try:
        message = f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
        handler.wfile.write(message.encode("utf-8"))
        handler.wfile.flush()
    except (BrokenPipeError, ConnectionResetError) as e:
        # Client disconnected, log and continue
        print(f"Client disconnected during SSE: {e}")
        raise


MMS_VOICE_ID = "mms"


def cache_name(text: str, language: str, voice: str = MMS_VOICE_ID) -> str:
    digest = hashlib.sha256(f"{language}\0{voice}\0{text}".encode("utf-8")).hexdigest()[:24]
    return f"{digest}.wav"


def get_system_voices(language: str) -> list[dict[str, str]]:
    """Return installed macOS voices matching the requested language."""
    locale_prefix = "en_" if language == "en" else "es_"
    try:
        result = subprocess.run(
            ["say", "-v", "?"],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return []

    voices = []
    for line in result.stdout.splitlines():
        match = re.match(r"^(.+?)\s{2,}([a-z]{2}_[A-Z]{2})\s+#", line.strip())
        if match and match.group(2).startswith(locale_prefix):
            name = match.group(1).strip()
            voices.append({"id": name, "name": f"{name} · {match.group(2)}", "engine": "macOS say"})
    return voices


def get_voice_options(language: str) -> list[dict[str, str]]:
    """Return neural and installed system voices for a language."""
    options = []
    if TORCH_AVAILABLE and TRANSFORMERS_AVAILABLE:
        options.append({
            "id": MMS_VOICE_ID,
            "name": "MMS-TTS · voz neural",
            "engine": "mms-tts",
        })
    options.extend(get_system_voices(language))
    return options


def validate_voice(language: str, voice: str | None) -> str:
    options = get_voice_options(language)
    available = {item["id"] for item in options}
    voice_id = (voice or (MMS_VOICE_ID if MMS_VOICE_ID in available else (options[0]["id"] if options else ""))).strip()
    if voice_id not in available:
        raise ValueError(f"Voz no disponible para {language}: {voice_id}")
    return voice_id


def _release_torch_cache():
    """Force release PyTorch cached memory (CUDA and MPS)."""
    if TORCH_AVAILABLE and torch is not None:
        try:
            import gc
            gc.collect()
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
            mps_backend = getattr(torch.backends, 'mps', None)
            if mps_backend and mps_backend.is_available():
                torch.mps.empty_cache()
        except Exception:
            pass


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
    
    def clear(self):
        """Release all loaded models from memory."""
        with self._lock:
            for language, (tokenizer, model, device) in self._models.items():
                del model
                del tokenizer
            self._models.clear()
            _release_torch_cache()
            print("Modelos MMS-TTS liberados de memoria.")
    
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
        
        del waveform
        del encoded
        _release_torch_cache()
        
        return "mms-tts"


# Global TTS instance
_tts_instance = None

def get_tts():
    global _tts_instance
    if _tts_instance is None:
        _tts_instance = LocalTTS()
    return _tts_instance


async def generate_edge_tts(text: str, language: str, output: Path) -> None:
    """Generate TTS audio using MMS-TTS in a thread to avoid blocking the event loop."""
    tts = get_tts()
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, tts.generate_audio, text, language, output)


def generate_say(text: str, voice: str, output: Path) -> None:
    with tempfile.NamedTemporaryFile(suffix=".aiff", dir=CACHE, delete=False) as temporary:
        source = Path(temporary.name)
    try:
        subprocess.run(
            ["say", "-v", voice, "-r", "175", "-o", str(source), text],
            check=True,
            capture_output=True,
            text=True,
            timeout=45,
        )
        subprocess.run(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(source), str(output)],
            check=True,
            capture_output=True,
            text=True,
            timeout=45,
        )
    finally:
        source.unlink(missing_ok=True)


def generate_audio(text: str, language: str, voice: str, output: Path) -> str:
    if voice == MMS_VOICE_ID:
        if not TORCH_AVAILABLE or not TRANSFORMERS_AVAILABLE:
            raise RuntimeError("MMS-TTS no está disponible en este entorno.")
        asyncio.run(generate_edge_tts(text, language, output))
        return "mms-tts"
    generate_say(text, voice, output)
    return "macOS say"


def clean_audio_directories() -> None:
    """Remove all previous audio files and cache."""
    if CACHE.exists():
        shutil.rmtree(CACHE)
    CACHE.mkdir(parents=True, exist_ok=True)
    # Remove all subtitle audio folders
    audio_root = ROOT / "audio"
    if audio_root.exists():
        shutil.rmtree(audio_root)


def clean_session_audio(subtitle_name: str | None = None) -> None:
    """Remove audio files for a specific subtitle session or all audio."""
    audio_root = ROOT / "audio"
    if not audio_root.exists():
        return

    if subtitle_name:
        # Remove only specific subtitle folder
        subtitle_folder = audio_root / subtitle_name
        if subtitle_folder.exists():
            shutil.rmtree(subtitle_folder)
    else:
        # Remove all audio
        shutil.rmtree(audio_root)


def get_subtitle_files() -> list[str]:
    """Get list of available subtitle files (without .srt extension)."""
    srt_files = list(SUBTITLES_DIR.glob("*.srt"))
    return [f.stem for f in srt_files]


def parse_srt_files(subtitle_filter: str | None = None) -> list[dict]:
    """Parse all SRT files in subtitles directory and extract English text with source info.
    If subtitle_filter is provided, only parse that subtitle file.
    """
    if not PYsrt_AVAILABLE:
        raise RuntimeError("pysrt no está instalado. Ejecuta: pip install pysrt")

    all_phrases = []
    srt_files = list(SUBTITLES_DIR.glob("*.srt"))

    if not srt_files:
        raise FileNotFoundError(f"No se encontraron archivos .srt en {SUBTITLES_DIR}")

    if subtitle_filter:
        srt_files = [f for f in srt_files if f.stem == subtitle_filter]
        if not srt_files:
            raise FileNotFoundError(f"No se encontró el archivo de subtítulos: {subtitle_filter}")

    for srt_file in srt_files:
        subtitle_name = srt_file.stem  # filename without .srt
        subs = pysrt.open(str(srt_file), encoding="utf-8")
        for sub in subs:
            text = sub.text.strip()
            text = text.replace("\n", " ")
            text = " ".join(text.split())
            if text and len(text) > 1:
                all_phrases.append({
                    "text": text,
                    "subtitle_name": subtitle_name,
                    "source_file": srt_file.name
                })

    return all_phrases


def load_translation_cache() -> dict:
    """Load translation cache from file."""
    if TRANSLATION_CACHE.exists():
        try:
            with open(TRANSLATION_CACHE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def save_translation_cache(cache: dict) -> None:
    """Save translation cache to file."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(TRANSLATION_CACHE, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)


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
                    truncation=True,
                    max_length=200,
                )
                encoded = {key: value.to(self._device) for key, value in encoded.items()}
                
                with torch.no_grad():
                    generated = self._model.generate(
                        **encoded,
                        forced_bos_token_id=self._tokenizer.convert_tokens_to_ids(target_lang),
                        max_length=200,
                        num_beams=1,
                    )
                
                result = self._tokenizer.batch_decode(generated, skip_special_tokens=True)[0].strip()
                translated.append(result)
                
                del encoded
                del generated
                
                if (i + 1) % 5 == 0:
                    _release_torch_cache()
                    
            except Exception as e:
                print(f"Error traduciendo: {text[:50]}... - {e}")
                translated.append(text)
        
        return translated
    
    def clear(self):
        """Release the NLLB model and tokenizer from memory."""
        with self._lock:
            del self._model
            del self._tokenizer
            del self._device
            self._model = None
            self._tokenizer = None
            self._device = None
            _release_torch_cache()
            print("Modelo NLLB liberado de memoria.")


# Global translator instance
_translator_instance = None

def get_translator():
    global _translator_instance
    if _translator_instance is None:
        _translator_instance = LocalTranslator()
    return _translator_instance


def cleanup_models():
    """Release all ML models from memory before the game starts."""
    global _tts_instance, _translator_instance
    tts = _tts_instance
    if tts is not None:
        tts.clear()
    _tts_instance = None

    translator = _translator_instance
    if translator is not None:
        translator.clear()
    _translator_instance = None

    print("Todos los modelos liberados de memoria.")


async def translate_to_spanish(texts: list[str], subtitle_name: str, progress_callback=None) -> list[str]:
    """Translate English texts to Spanish using NLLB-200 with caching."""
    if not TRANSFORMERS_AVAILABLE:
        raise RuntimeError("transformers no está instalado. Ejecuta: pip install transformers")

    loop = asyncio.get_running_loop()
    translator = get_translator()

    async def _translate():
        cache = load_translation_cache()
        subtitle_cache = cache.get(subtitle_name, {})

        texts_to_translate = []
        translate_indices = []
        translated = []
        for i, text in enumerate(texts):
            if text in subtitle_cache:
                translated.append(subtitle_cache[text])
            else:
                translated.append(None)
                texts_to_translate.append(text)
                translate_indices.append(i)

        if texts_to_translate:
            if progress_callback:
                await progress_callback({"stage": "translating", "progress": 10, "message": f"Traduciendo {len(texts_to_translate)} frases nuevas al español..."})

            result = await loop.run_in_executor(
                None, translator.translate_to_spanish, texts_to_translate
            )

            for j, result_text in enumerate(result):
                subtitle_cache[texts_to_translate[j]] = result_text
                translated[translate_indices[j]] = result_text

                if progress_callback and j % 5 == 0:
                    progress = 10 + int((j / len(texts_to_translate)) * 20)
                    await progress_callback({
                        "stage": "translating",
                        "progress": progress,
                        "message": f"Traduciendo {j + 1} de {len(texts_to_translate)}...",
                        "current": j + 1,
                        "total": len(texts_to_translate),
                    })

            cache[subtitle_name] = subtitle_cache
            save_translation_cache(cache)

        return translated

    return await _translate()


def generate_cache_name(text: str, language: str, voice: str = MMS_VOICE_ID) -> str:
    """Generate a cache filename that is unique to text, language, and voice."""
    return cache_name(text, language, voice)


async def process_subtitles(
    subtitle_filter: str | None = None,
    max_phrases: int | None = None,
    voice_en: str | None = None,
    voice_es: str | None = None,
    progress_callback=None,
) -> dict:
    """Process subtitles: parse, translate, generate audio, create phrases.json.
    Creates a subfolder per subtitle file with English and Spanish audio subfolders.
    Always randomly selects phrases from the subtitle file and overwrites existing audio.
    """

    voice_en = validate_voice("en", voice_en)
    voice_es = validate_voice("es", voice_es)

    # Clean previous audio to allow fresh generation
    clean_audio_directories()

    if progress_callback:
        await progress_callback({"stage": "parsing", "progress": 0, "message": "Extrayendo frases de subtítulos..."})

    phrases_data = parse_srt_files(subtitle_filter)  # Returns list of dicts with text, subtitle_name, source_file

    if not phrases_data:
        raise ValueError("No se encontraron frases válidas en los subtítulos.")

    # Group by subtitle_name
    from collections import defaultdict
    import random
    grouped = defaultdict(list)
    for phrase in phrases_data:
        grouped[phrase["subtitle_name"]].append(phrase)

    # Always randomly select phrases
    if max_phrases and max_phrases < len(phrases_data):
        # Select specific number of random phrases
        phrases_data = random.sample(phrases_data, max_phrases)
    else:
        # Shuffle all phrases for random selection
        random.shuffle(phrases_data)

    # Regroup after random selection/shuffling
    grouped = defaultdict(list)
    for phrase in phrases_data:
        grouped[phrase["subtitle_name"]].append(phrase)

    if progress_callback:
        await progress_callback({"stage": "translating", "progress": 10, "message": f"Traduciendo {len(phrases_data)} frases al español..."})

    # Extract all texts for translation
    english_texts = [p["text"] for p in phrases_data]

    # Get subtitle_name for translation cache (use first subtitle since we filter by one)
    subtitle_names = list(grouped.keys())
    subtitle_name = subtitle_names[0] if subtitle_names else "unknown"
    spanish_texts = await translate_to_spanish(english_texts, subtitle_name, progress_callback)

    # Add Spanish translations back to phrases_data
    for i, phrase in enumerate(phrases_data):
        phrase["es"] = spanish_texts[i]

    if progress_callback:
        await progress_callback({"stage": "audio", "progress": 30, "message": "Generando audios por subtítulo..."})

    # Process each subtitle group - create subfolder structure
    audio_root = ROOT / "audio"
    phrases_data_final = []
    total = len(phrases_data)
    global_idx = 0

    for subtitle_idx, (subtitle_name, phrases) in enumerate(grouped.items()):
        # Create folder structure: audio/{subtitle_name}/{en,es}/
        sub_en_dir = audio_root / subtitle_name / "en"
        sub_es_dir = audio_root / subtitle_name / "es"
        sub_en_dir.mkdir(parents=True, exist_ok=True)
        sub_es_dir.mkdir(parents=True, exist_ok=True)

        for phrase_idx, phrase in enumerate(phrases):
            en_text = phrase["text"]
            es_text = phrase["es"]

            en_cache_name = generate_cache_name(en_text, "en", voice_en)
            es_cache_name = generate_cache_name(es_text, "es", voice_es)

            en_cache_path = CACHE / en_cache_name
            es_cache_path = CACHE / es_cache_name

            en_audio_path = sub_en_dir / f"{phrase_idx + 1:04d}.wav"
            es_audio_path = sub_es_dir / f"{phrase_idx + 1:04d}.wav"

            # Only generate if not already cached
            if not en_cache_path.exists() or en_cache_path.stat().st_size == 0:
                await asyncio.get_running_loop().run_in_executor(
                    None, generate_audio, en_text, "en", voice_en, en_cache_path
                )
            # Copy to subtitle folder
            if not en_audio_path.exists():
                shutil.copy2(en_cache_path, en_audio_path)

            if not es_cache_path.exists() or es_cache_path.stat().st_size == 0:
                await asyncio.get_running_loop().run_in_executor(
                    None, generate_audio, es_text, "es", voice_es, es_cache_path
                )
            # Copy to subtitle folder
            if not es_audio_path.exists():
                shutil.copy2(es_cache_path, es_audio_path)

            phrase_data = {
                "id": f"phrase-{global_idx + 1}",
                "sourceId": str(global_idx + 1),
                "en": en_text,
                "es": es_text,
                "audioEnglish": f"audio/{subtitle_name}/en/{phrase_idx + 1:04d}.wav",
                "audioSpanish": f"audio/{subtitle_name}/es/{phrase_idx + 1:04d}.wav",
                "subtitleName": subtitle_name,
                "levels": ["B2"],
                "themes": ["Subtitles"],
                "frequencies": ["Media"],
            }
            phrases_data_final.append(phrase_data)

            if progress_callback and global_idx % 5 == 0:
                progress = 30 + int((global_idx / total) * 60)
                await progress_callback({
                    "stage": "audio",
                    "progress": progress,
                    "message": f"Generando audio {global_idx + 1} de {total} ({subtitle_name})...",
                    "current": global_idx + 1,
                    "total": total,
                    "subtitle": subtitle_name
                })

            global_idx += 1

    if progress_callback:
        await progress_callback({"stage": "saving", "progress": 95, "message": "Guardando catálogo de frases..."})

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(PHRASES_JSON, "w", encoding="utf-8") as f:
        json.dump(phrases_data_final, f, ensure_ascii=False, indent=2)

    # Save current subtitle name for cleanup
    session_subtitle = DATA_DIR / "current_subtitle.txt"
    with open(session_subtitle, "w", encoding="utf-8") as f:
        f.write(subtitle_name)

    if progress_callback:
        await progress_callback({"stage": "complete", "progress": 100, "message": f"Completado: {len(phrases_data_final)} frases procesadas."})

    return {
        "success": True,
        "phrasesCount": len(phrases_data_final),
        "subtitleCount": len(grouped),
        "subtitleName": subtitle_name,
        "message": f"Procesadas {len(phrases_data_final)} frases de {len(grouped)} archivo(s) de subtítulos."
    }


class GameHandler(SimpleHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path == "/.well-known/appspecific/com.chrome.devtools.json":
            self.send_response(204)
            self.end_headers()
            return
        if parsed.path == "/api/tts/health":
            send_json(
                self,
                200,
                {
                    "available": True,
                    "engine": "cache",
                    "voiceName": "Cache de audio",
                },
            )
            return
        if parsed.path == "/api/subtitles/list":
            send_json(self, 200, {"subtitles": get_subtitle_files()})
            return
        if parsed.path == "/api/subtitles/process":
            self.handle_subtitles_sse(parsed.query)
            return
        if parsed.path == "/api/voices":
            language = parse_qs(parsed.query).get("language", ["es"])[0]
            if language not in {"en", "es"}:
                send_json(self, 400, {"error": "Idioma no válido."})
                return
            send_json(self, 200, {"voices": get_voice_options(language)})
            return
        if parsed.path == "/api/cleanup":
            self.handle_cleanup()
            return
        if parsed.path.startswith("/tts-cache/"):
            filename = Path(parsed.path.removeprefix("/tts-cache/")).name
            if filename != parsed.path.removeprefix("/tts-cache/") or not filename.endswith(".wav"):
                self.send_error(404)
                return
            self.path = f"/.tts-cache/{filename}"
        super().do_GET()

    def handle_subtitles_sse(self, query: str) -> None:
        """Handle Server-Sent Events for subtitle processing progress."""
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()

        # Parse query parameters
        from urllib.parse import parse_qs
        params = parse_qs(query)
        subtitle_filter = params.get("subtitle", [None])[0]
        max_phrases = int(params.get("max_phrases", [0])[0]) if params.get("max_phrases", ["0"])[0] else None
        voice_en = params.get("voice_en", [None])[0]
        voice_es = params.get("voice_es", [None])[0]

        import asyncio
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        async def progress_callback(data):
            try:
                send_sse_event(self, "progress", data)
            except (BrokenPipeError, ConnectionResetError):
                # Client disconnected, silence the error
                pass

        try:
            result = loop.run_until_complete(process_subtitles(
                subtitle_filter,
                max_phrases,
                voice_en=voice_en,
                voice_es=voice_es,
                progress_callback=progress_callback,
            ))
            try:
                send_sse_event(self, "complete", result)
            except (BrokenPipeError, ConnectionResetError):
                pass
        except Exception as error:
            try:
                send_sse_event(self, "error", {"error": str(error)})
            except (BrokenPipeError, ConnectionResetError):
                pass
        finally:
            cleanup_models()
            loop.close()

    def handle_cleanup(self) -> None:
        """Handle cleanup request to remove subtitle files manually."""
        try:
            # Read current subtitle name
            session_subtitle = DATA_DIR / "current_subtitle.txt"
            subtitle_name = None
            if session_subtitle.exists():
                with open(session_subtitle, "r", encoding="utf-8") as f:
                    subtitle_name = f.read().strip()

            # Clean specific subtitle audio files
            if subtitle_name:
                clean_session_audio(subtitle_name)
            else:
                # Clean all audio if no specific subtitle
                clean_audio_directories()

            # Clean phrases.json
            if PHRASES_JSON.exists():
                PHRASES_JSON.unlink()

            # Clean current subtitle file
            if session_subtitle.exists():
                session_subtitle.unlink()

            send_json(self, 200, {"success": True, "message": "Archivos de subtítulo eliminados correctamente."})
        except Exception as error:
            send_json(self, 500, {"error": str(error)})

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path == "/api/subtitles/process":
            try:
                content_length = int(self.headers.get("Content-Length", "0"))
                payload = json.loads(self.rfile.read(content_length)) if content_length else {}
                subtitle_filter = payload.get("subtitle")
                max_phrases = payload.get("max_phrases")
                result = asyncio.run(process_subtitles(
                    subtitle_filter,
                    max_phrases,
                    voice_en=payload.get("voice_en"),
                    voice_es=payload.get("voice_es"),
                ))
                send_json(self, 200, result)
            except Exception as error:  # noqa: BLE001
                send_json(self, 500, {"error": str(error)})
            finally:
                cleanup_models()
            return
        if parsed.path == "/api/cleanup":
            # handle_cleanup() owns the response, including its error response.
            self.handle_cleanup()
            return
        if parsed.path == "/api/models/cleanup":
            try:
                cleanup_models()
                send_json(self, 200, {"success": True, "message": "Modelos liberados."})
            except Exception as error:  # noqa: BLE001
                send_json(self, 500, {"error": str(error)})
            return
        if parsed.path == "/api/tts/test":
            try:
                content_length = int(self.headers.get("Content-Length", "0"))
                payload = json.loads(self.rfile.read(content_length)) if content_length else {}
                text = str(payload.get("text", "")).strip()
                language = str(payload.get("language", "")).strip().lower()
                if not text:
                    raise ValueError("El texto de prueba está vacío.")
                if language not in {"en", "es"}:
                    raise ValueError("Idioma no válido.")
                voice = validate_voice(language, str(payload.get("voice", "")))
                filename = cache_name(text, language, voice)
                audio_path = CACHE / filename
                if not audio_path.exists() or audio_path.stat().st_size == 0:
                    generate_audio(text, language, voice, audio_path)
                send_json(self, 200, {"url": f"/tts-cache/{filename}", "cached": False})
            except Exception as error:  # noqa: BLE001
                send_json(self, 500, {"error": str(error)})
            finally:
                cleanup_models()
            return
        if parsed.path == "/api/tts":
            try:
                content_length = int(self.headers.get("Content-Length", "0"))
                payload = json.loads(self.rfile.read(content_length))
                text = str(payload.get("text", "")).strip()
                language = str(payload.get("language", "es")).strip().lower()
                filename = cache_name(text, language)
                cached = CACHE / filename
                if cached.exists() and cached.stat().st_size > 0:
                    send_json(self, 200, {"url": f"/tts-cache/{filename}", "engine": "cache", "cached": True})
                else:
                    send_json(self, 404, {"error": "Audio no disponible. Procesa los subtítulos antes de jugar."})
            except Exception as error:  # noqa: BLE001
                send_json(self, 500, {"error": str(error)})
            return
        self.send_error(404)
        return


if __name__ == "__main__":
    os.chdir(ROOT)
    server = ThreadingHTTPServer(("127.0.0.1", PORT), GameHandler)
    print(f"English Phrase N-Back: http://localhost:{PORT}")
    print(f"TTS engine: {'mms-tts' if TORCH_AVAILABLE and TRANSFORMERS_AVAILABLE else 'macOS say'}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nServidor detenido.")
    finally:
        server.server_close()
