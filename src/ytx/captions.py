"""Parse YouTube json3 caption data into timed words.

json3 is used instead of VTT because auto-caption VTT repeats each line across rolling cues and
has to be de-duplicated heuristically; json3 gives each word exactly once with its own offset.
"""
from __future__ import annotations

from .models import Word


def parse_json3(data: dict) -> list[Word]:
    words: list[Word] = []
    for ev in data.get("events", []):
        segs = ev.get("segs")
        if not segs or ev.get("aAppend"):
            continue
        t0 = ev.get("tStartMs", 0)
        dur = ev.get("dDurationMs", 0)
        if any("tOffsetMs" in s for s in segs):
            # auto captions: per-word offsets
            for s in segs:
                for w in s.get("utf8", "").split():
                    words.append(Word((t0 + s.get("tOffsetMs", 0)) / 1000, w))
        else:
            # uploaded captions: one line per event; spread words across the cue
            toks = " ".join(s.get("utf8", "") for s in segs).split()
            for i, w in enumerate(toks):
                words.append(Word((t0 + dur * i / max(len(toks), 1)) / 1000, w))
    words.sort(key=lambda w: w.start)
    return words
