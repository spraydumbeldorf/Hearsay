"""End-to-end job: source -> words -> cleaned -> organised Transcript."""
from __future__ import annotations

import shutil
import threading
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from . import audio as audio_mod
from . import cleanup, document, youtube
from .env import temp_dir
from .models import Transcript, fmt_time

# progress(stage, fraction or None, detail)
ProgressFn = Callable[[str, Optional[float], str], None]

LANGUAGES = {
    "Auto-detect": None, "English": "en", "Spanish": "es", "French": "fr", "German": "de",
    "Portuguese": "pt", "Italian": "it", "Dutch": "nl", "Polish": "pl", "Turkish": "tr",
    "Russian": "ru", "Ukrainian": "uk", "Arabic": "ar", "Hebrew": "he", "Hindi": "hi",
    "Japanese": "ja", "Korean": "ko", "Chinese": "zh", "Indonesian": "id", "Vietnamese": "vi",
}


class Cancelled(Exception):
    pass


@dataclass
class Options:
    source: str                       # YouTube/other URL or local file path
    method: str = "captions"          # "captions" | "whisper"
    model: str = "large-v3-turbo"
    language: Optional[str] = None    # ISO code or None = auto
    fix_names: bool = True            # metadata-based name fixes + Whisper spelling hints
    clip: Optional[tuple[float, float]] = None  # testing: only transcribe this window (seconds)
    extra_terms: str = ""             # user-supplied names, comma separated


def run(opts: Options, progress: ProgressFn, cancel: threading.Event,
        log: Callable[[str], None] = lambda m: None) -> Transcript:
    from . import whisper_engine as we

    def check():
        if cancel.is_set():
            raise Cancelled

    src = opts.source.strip().strip('"')
    notes: list[str] = []
    words = None
    source_label = ""
    audio_path: Optional[Path] = None
    work = temp_dir() / uuid.uuid4().hex[:8]
    method = opts.method

    try:
        if youtube.is_url(src):
            progress("Reading video details", None, "Contacting YouTube…")
            info = youtube.fetch_info(src, log)
            meta = youtube.meta_from_info(info)
            check()
            if method == "captions":
                track = youtube.pick_caption_track(info, opts.language)
                if track is None:
                    notes.append("This video has no captions, so the transcript was made with Whisper AI from the audio.")
                    method = "whisper"
                else:
                    progress("Downloading captions", None, f"{track['kind']} captions · {track['lang']}")
                    from .captions import parse_json3

                    words = parse_json3(youtube.download_json(track["url"], log))
                    if opts.clip:
                        words = [w for w in words if opts.clip[0] <= w.start < opts.clip[1]]
                    if not words:
                        notes.append("The caption track was empty, so Whisper AI was used instead.")
                        method = "whisper"
                    else:
                        source_label = {
                            "manual": f"Captions uploaded by the creator ({track['lang']})",
                            "auto": f"YouTube automatic captions ({track['lang']})",
                            "auto-translated": f"YouTube auto-translated captions ({track['lang']})",
                        }[track["kind"]]
                        if track["kind"] != "manual":
                            notes.append("Made from YouTube's automatic captions, which can drop or mis-hear words. "
                                         "For best accuracy, choose Whisper AI.")
            if method == "whisper":
                work.mkdir(parents=True, exist_ok=True)
                progress("Downloading audio", 0.0, "")
                audio_path = youtube.download_audio(
                    src, work, lambda f, d: progress("Downloading audio", f, d), cancel, log)
        else:
            path = Path(src)
            if not path.is_file():
                raise FileNotFoundError(f"File not found: {src}")
            method = "whisper"
            audio_path = path
            meta = {"title": path.stem, "file": str(path), "duration": 0, "description": "",
                    "tags": [], "chapters": [], "language": None, "video_id": None}
        check()
        meta["extra_terms"] = [t.strip() for t in opts.extra_terms.replace(";", ",").split(",") if t.strip()]

        if method == "whisper":
            assert audio_path is not None
            model = we.get_model(opts.model, lambda f, d: progress("Preparing AI model", f, d), cancel)
            check()
            progress("Reading audio", 0.0, audio_path.name)
            try:
                pcm = audio_mod.load_audio(audio_path, lambda f: progress("Reading audio", f, audio_path.name),
                                           cancel, opts.clip)
            except InterruptedError:
                raise Cancelled
            if not meta.get("duration"):
                meta["duration"] = len(pcm) / audio_mod.SAMPLE_RATE
            check()
            hot = cleanup.hotwords_for(meta) if opts.fix_names else None
            lang = opts.language or meta.get("language")
            progress("Transcribing with Whisper AI", 0.0, "Starting…")
            try:
                words, detected = we.transcribe(
                    model, pcm, lang, hot, lambda f, d: progress("Transcribing with Whisper AI", f, d), cancel,
                    offset=opts.clip[0] if opts.clip else 0.0)
            except we.Cancelled:
                raise Cancelled
            label = we.MODELS[opts.model]["label"].split("—")[-1].strip()
            source_label = f"Whisper AI, {label} ({detected})"
            low = sum(1 for w in words if w.prob is not None and w.prob < 0.4)
            if low:
                notes.append(f"{low} word(s) were transcribed with low confidence; they are underlined in the app.")
        check()

        progress("Cleaning up", None, "")
        words, changes = cleanup.clean(words or [], meta, opts.fix_names, from_whisper=(method == "whisper"))
        if not words:
            raise RuntimeError("No speech was found.")
        if meta.get("chapters"):
            notes.append("Chapter titles and times come from the video description. Each section starts at the "
                         "nearest sentence to the listed time.")
        if changes:
            notes.append(f"{len(changes)} automatic correction(s) were made; each one is listed in the Changes tab "
                         "and at the end of the saved file.")
        if opts.clip:
            notes.append(f"Test clip only: {fmt_time(opts.clip[0])}–{fmt_time(opts.clip[1])}.")
        chapters = meta.get("chapters") or []
        if opts.clip and chapters:
            before = [c for c in chapters if c[0] <= opts.clip[0]]
            chapters = before[-1:] + [c for c in chapters if opts.clip[0] < c[0] < opts.clip[1]]
        sections = document.build_sections(words, chapters, meta.get("duration") or 0)
        return Transcript(meta=meta, source_label=source_label, words=words, sections=sections,
                          changes=changes, notes=notes)
    finally:
        shutil.rmtree(work, ignore_errors=True)
