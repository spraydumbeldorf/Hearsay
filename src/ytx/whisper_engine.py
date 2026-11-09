"""Whisper speech-to-text (faster-whisper / CTranslate2, CPU int8)."""
from __future__ import annotations

import fnmatch
import os
import threading
import time
from pathlib import Path
from typing import Callable, Optional

import numpy as np

from .env import models_dir
from .models import Word

MODELS = {
    "large-v3-turbo": {"label": "Balanced — Large v3 Turbo", "repo": "mobiuslabsgmbh/faster-whisper-large-v3-turbo",
                       "size": "1.6 GB", "speed": "about 3–5 min per 10 min of video"},
    "large-v3": {"label": "Most accurate — Large v3", "repo": "Systran/faster-whisper-large-v3",
                 "size": "3.1 GB", "speed": "about 12–15 min per 10 min of video"},
    "small": {"label": "Fastest — Small", "repo": "Systran/faster-whisper-small",
              "size": "0.5 GB", "speed": "about 1–2 min per 10 min of video"},
}
DEFAULT_MODEL = "large-v3-turbo"
_FILES = ["config.json", "preprocessor_config.json", "model.bin", "tokenizer.json", "vocabulary.*"]
_loaded: dict[str, object] = {}
_lock = threading.Lock()


class Cancelled(Exception):
    pass


def _repo_cache_dir(repo: str) -> Path:
    return models_dir() / ("models--" + repo.replace("/", "--"))


def local_model_path(name: str) -> Optional[str]:
    from huggingface_hub import snapshot_download

    repo = MODELS[name]["repo"]
    try:
        p = snapshot_download(repo, cache_dir=str(models_dir()), allow_patterns=_FILES, local_files_only=True)
    except Exception:
        return None
    return p if (Path(p) / "model.bin").exists() else None


def _dir_size(p: Path) -> int:
    total = 0
    for f in p.rglob("*"):
        try:
            if f.is_file() and not f.is_symlink():
                total += f.stat().st_size
        except OSError:
            pass
    return total


def ensure_model(name: str, progress: Callable[[Optional[float], str], None], cancel: threading.Event) -> str:
    path = local_model_path(name)
    if path:
        return path
    from huggingface_hub import HfApi, snapshot_download

    repo = MODELS[name]["repo"]
    total = 0
    try:
        info = HfApi().model_info(repo, files_metadata=True)
        total = sum((s.size or 0) for s in info.siblings
                    if any(fnmatch.fnmatch(s.rfilename, pat) for pat in _FILES))
    except Exception:
        pass
    result: dict = {}

    def work():
        try:
            result["path"] = snapshot_download(repo, cache_dir=str(models_dir()), allow_patterns=_FILES)
        except Exception as e:  # noqa: BLE001
            result["error"] = e

    cache = _repo_cache_dir(repo)
    start_size = _dir_size(cache) if cache.exists() else 0
    th = threading.Thread(target=work, daemon=True)
    th.start()
    while th.is_alive():
        if cancel.is_set():
            raise Cancelled
        got = (_dir_size(cache) if cache.exists() else 0) - start_size
        if total:
            progress(min(0.99, got / total), f"{got / 1e9:.2f} of {total / 1e9:.2f} GB (one-time download)")
        else:
            progress(None, f"{got / 1e9:.2f} GB downloaded (one-time download)")
        th.join(0.5)
    if "error" in result:
        raise RuntimeError(f"Could not download the AI model: {result['error']}")
    return result["path"]


def get_model(name: str, progress: Callable[[Optional[float], str], None], cancel: threading.Event):
    with _lock:
        if name in _loaded:
            return _loaded[name]
    path = ensure_model(name, progress, cancel)
    progress(None, "Loading the AI model into memory…")
    from faster_whisper import WhisperModel

    model = WhisperModel(path, device="cpu", compute_type="int8", cpu_threads=os.cpu_count() or 4)
    with _lock:
        _loaded[name] = model
    return model


def transcribe(model, audio: np.ndarray, language: Optional[str], hotwords: Optional[str],
               progress: Callable[[float, str], None], cancel: threading.Event,
               offset: float = 0.0) -> tuple[list[Word], str]:
    from .audio import SAMPLE_RATE
    from .models import fmt_time

    duration = len(audio) / SAMPLE_RATE
    segments, info = model.transcribe(
        audio, language=language, beam_size=5, word_timestamps=True,
        vad_filter=True, hotwords=hotwords or None,
        # Feeding previous text back in is the main cause of runaway repetition loops.
        condition_on_previous_text=False,
    )
    words: list[Word] = []
    t0 = time.time()
    for seg in segments:
        if cancel.is_set():
            raise Cancelled
        for w in seg.words or []:
            words.append(Word(offset + w.start, w.word.strip(), w.probability))
        frac = min(1.0, seg.end / max(duration, 1e-6))
        elapsed = time.time() - t0
        detail = f"{fmt_time(seg.end)} of {fmt_time(duration)}"
        if frac > 0.03 and elapsed > 10:
            left = elapsed / frac * (1 - frac)
            detail += f" · about {max(1, round(left / 60))} min left"
        progress(frac, detail)
    return words, info.language
