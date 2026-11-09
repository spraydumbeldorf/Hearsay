"""YouTube access via yt-dlp: metadata, caption tracks (json3), audio-only download."""
from __future__ import annotations

import json
import re
import threading
from pathlib import Path
from typing import Callable, Optional

URL_RE = re.compile(r"^https?://", re.I)


def is_url(s: str) -> bool:
    return bool(URL_RE.match(s.strip()))


class _Logger:
    def __init__(self, log: Callable[[str], None]):
        self.log = log

    def debug(self, msg):  # yt-dlp routes [download] lines through debug
        pass

    def info(self, msg):
        pass

    def warning(self, msg):
        # harmless for audio-only use: impersonation, DASH m4a container, JS runtime notices
        if not any(s in msg for s in ("impersonat", "DASH m4a", "JavaScript runtime")):
            self.log(f"yt-dlp: {msg}")

    def error(self, msg):
        self.log(f"yt-dlp error: {msg}")


def _base_opts(log):
    return {
        "quiet": True,
        "no_warnings": False,
        "noplaylist": True,
        "logger": _Logger(log),
        "noprogress": True,
    }


def fetch_info(url: str, log: Callable[[str], None]) -> dict:
    import yt_dlp

    opts = _base_opts(log) | {"skip_download": True}
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)
        return ydl.sanitize_info(info)


def meta_from_info(info: dict) -> dict:
    upload = info.get("upload_date") or ""
    return {
        "title": info.get("title") or "Untitled video",
        "channel": info.get("channel") or info.get("uploader") or "",
        "channel_handle": info.get("uploader_id") or "",
        "upload_date": f"{upload[:4]}-{upload[4:6]}-{upload[6:]}" if len(upload) == 8 else "",
        "duration": info.get("duration") or 0,
        "url": info.get("webpage_url") or info.get("original_url") or "",
        "video_id": info.get("id") if "youtube" in (info.get("extractor") or "").lower() else None,
        "views": info.get("view_count"),
        "likes": info.get("like_count"),
        "description": info.get("description") or "",
        "tags": info.get("tags") or [],
        "chapters": [(float(c.get("start_time") or 0), c.get("title") or "") for c in (info.get("chapters") or [])],
        "language": (info.get("language") or "").split("-")[0] or None,
    }


def pick_caption_track(info: dict, lang_pref: Optional[str]) -> Optional[dict]:
    """Prefer creator-uploaded captions, then the auto captions in the video's original language.

    Returns {"kind": "manual"|"auto", "lang": str, "url": str} or None.
    Auto-caption keys like 'en-orig' mark the original (non-translated) language; other auto keys are
    machine translations, which we only use if the user explicitly asked for that language.
    """
    manual = {k: v for k, v in (info.get("subtitles") or {}).items() if k != "live_chat"}
    auto = info.get("automatic_captions") or {}
    video_lang = (info.get("language") or "").split("-")[0] or None
    orig_auto = next((k for k in auto if k.endswith("-orig")), None)
    orig_lang = orig_auto[:-5] if orig_auto else video_lang

    def json3_url(tracks):
        for t in tracks or []:
            if t.get("ext") == "json3" and t.get("url"):
                return t["url"]
        return None

    def find(tracks: dict, lang: Optional[str]):
        if not lang:
            return None
        for key in [lang] + sorted(k for k in tracks if k.split("-")[0] == lang):
            if key in tracks and (u := json3_url(tracks[key])):
                return key, u
        return None

    for lang in [lang_pref, video_lang, orig_lang, "en"]:
        if (hit := find(manual, lang)):
            return {"kind": "manual", "lang": hit[0], "url": hit[1]}
    want = lang_pref or orig_lang or "en"
    if orig_auto and want == orig_lang and (u := json3_url(auto[orig_auto])):
        return {"kind": "auto", "lang": orig_lang, "url": u}
    if want in auto and (u := json3_url(auto[want])):
        translated = bool(orig_lang and want != orig_lang)
        return {"kind": "auto-translated" if translated else "auto", "lang": want, "url": u}
    if manual:  # any manual track beats nothing
        key = next(iter(manual))
        if (u := json3_url(manual[key])):
            return {"kind": "manual", "lang": key, "url": u}
    return None


def download_json(url: str, log: Callable[[str], None]) -> dict:
    import yt_dlp

    with yt_dlp.YoutubeDL(_base_opts(log)) as ydl:
        return json.loads(ydl.urlopen(url).read().decode("utf-8"))


def download_audio(url: str, dest: Path, progress: Callable[[float, str], None],
                   cancel: threading.Event, log: Callable[[str], None]) -> Path:
    import yt_dlp
    from yt_dlp.utils import DownloadCancelled

    def hook(d):
        if cancel.is_set():
            raise DownloadCancelled("cancelled")
        if d.get("status") == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate")
            done = d.get("downloaded_bytes") or 0
            if total:
                progress(done / total, f"{done / 1e6:.1f} of {total / 1e6:.1f} MB")

    opts = _base_opts(log) | {
        # audio-only m4a needs no ffmpeg; fall back to anything with sound
        "format": "bestaudio[ext=m4a]/bestaudio/best",
        "outtmpl": str(dest / "%(id)s.%(ext)s"),
        "progress_hooks": [hook],
        "postprocessors": [],
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=True)
        path = Path(ydl.prepare_filename(info))
    if not path.exists():
        found = sorted(dest.glob(f"{info.get('id')}.*"))
        if not found:
            raise FileNotFoundError("Audio download finished but the file was not found")
        path = found[0]
    return path
