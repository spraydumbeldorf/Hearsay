"""Plain data types passed between pipeline stages and the UI."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Word:
    start: float          # seconds
    text: str
    prob: Optional[float] = None  # Whisper confidence (None for captions)


@dataclass
class Change:
    start: float
    before: str
    after: str
    reason: str


@dataclass
class Paragraph:
    start: float
    words: list[Word]

    @property
    def text(self) -> str:
        return " ".join(w.text for w in self.words)


@dataclass
class Section:
    title: Optional[str]
    start: float
    listed: Optional[float]  # chapter time from the description, if any
    paragraphs: list[Paragraph] = field(default_factory=list)


@dataclass
class Transcript:
    meta: dict
    source_label: str
    words: list[Word]
    sections: list[Section]
    changes: list[Change]
    notes: list[str]

    @property
    def word_count(self) -> int:
        return len(self.words)

    @property
    def is_youtube(self) -> bool:
        return bool(self.meta.get("video_id"))

    def link_at(self, seconds: float) -> Optional[str]:
        vid = self.meta.get("video_id")
        if not vid:
            return None
        return f"https://youtu.be/{vid}?t={int(seconds)}"


def fmt_time(seconds: float) -> str:
    s = int(seconds or 0)
    h, m, sec = s // 3600, s % 3600 // 60, s % 60
    return f"{h}:{m:02d}:{sec:02d}" if h else f"{m}:{sec:02d}"
