"""Organise timed words into sections/paragraphs and render Markdown, plain text and SRT."""
from __future__ import annotations

import datetime as _dt
import re
from pathlib import Path

from .models import Paragraph, Section, Transcript, Word, fmt_time

_SENT_END = re.compile(r"[.?!][\"')\]]*$")
PARA_MIN = 30.0     # start a new paragraph at the first sentence end after this many seconds
PARA_MAX = 75.0     # ...or force one here if the source has no punctuation
AUTO_PART = 300.0   # videos without chapters get a section every ~5 minutes


def _ends_sentence(w: Word) -> bool:
    return bool(_SENT_END.search(w.text))


def _snap(words: list[Word], t: float, window: float = 8.0) -> int:
    """Index of the sentence start closest to time t (chapter times rarely land on a sentence)."""
    first = next((i for i, w in enumerate(words) if w.start >= t), len(words))
    best, best_d = first, None
    for i in range(len(words)):
        d = abs(words[i].start - t)
        if d > window:
            if words[i].start > t:
                break
            continue
        if i == 0 or _ends_sentence(words[i - 1]):
            if best_d is None or d < best_d:
                best, best_d = i, d
    return best


def build_sections(words: list[Word], chapters: list[tuple[float, str]], duration: float) -> list[Section]:
    if not words:
        return []
    bounds: list[tuple[int, str | None, float | None]] = []
    if chapters:
        for start, title in sorted(chapters):
            bounds.append((0 if start <= 0 else _snap(words, start), title, start))
    elif (duration or words[-1].start) > 2 * AUTO_PART:
        n, t = 1, 0.0
        while t < words[-1].start:
            bounds.append((0 if t == 0 else _snap(words, t, 20.0), f"Part {n}", None))
            n, t = n + 1, t + AUTO_PART
    else:
        bounds.append((0, None, None))
    # make boundaries strictly increasing
    clean: list[tuple[int, str | None, float | None]] = []
    for b in bounds:
        if clean and b[0] <= clean[-1][0]:
            # two chapters snapped to the same sentence: keep both titles on one section
            if b[1] and clean[-1][1]:
                clean[-1] = (clean[-1][0], f"{clean[-1][1]} / {b[1]}", clean[-1][2])
            continue
        clean.append(b)
    if clean[0][0] != 0:
        clean.insert(0, (0, None, None))

    sections: list[Section] = []
    for k, (i0, title, listed) in enumerate(clean):
        i1 = clean[k + 1][0] if k + 1 < len(clean) else len(words)
        chunk = words[i0:i1]
        if not chunk:
            continue
        sec = Section(title=title, start=chunk[0].start, listed=listed)
        para: list[Word] = []
        for j, w in enumerate(chunk):
            para.append(w)
            span = w.start - para[0].start
            last = j == len(chunk) - 1
            if last or (span >= PARA_MIN and _ends_sentence(w)) or span >= PARA_MAX:
                sec.paragraphs.append(Paragraph(para[0].start, para))
                para = []
        sections.append(sec)
    return sections


# ------------------------------------------------------------------------------------ rendering
def _meta_lines(tr: Transcript) -> list[str]:
    m = tr.meta
    bits = []
    if m.get("channel"):
        handle = f" ({m['channel_handle']})" if m.get("channel_handle") else ""
        bits.append(f"Channel: {m['channel']}{handle}")
    if m.get("upload_date"):
        bits.append(f"Uploaded: {m['upload_date']}")
    if m.get("duration"):
        bits.append(f"Length: {fmt_time(m['duration'])}")
    lines = [" · ".join(bits)] if bits else []
    if m.get("url"):
        lines.append(f"URL: {m['url']}")
    elif m.get("file"):
        lines.append(f"File: {m['file']}")
    lines.append(f"Transcript source: {tr.source_label} · Words: {tr.word_count:,} · "
                 f"Generated: {_dt.date.today().isoformat()}")
    return lines


def _numbered(tr: Transcript) -> list[tuple[str | None, Section]]:
    out, n = [], 0
    for s in tr.sections:
        if s.title:
            n += 1
            out.append((f"{n}. {s.title}" if not s.title.startswith("Part ") else s.title, s))
        else:
            out.append((None, s))
    return out


def render_markdown(tr: Transcript) -> str:
    L = [f"# {tr.meta.get('title', 'Transcript')}", ""]
    for line in _meta_lines(tr):
        k, _, v = line.partition(": ")
        L.append(line.replace(f"{k}: ", f"**{k}:** ", 1).replace(" · ", " · ") + "  ")
    L.append("")
    if tr.notes:
        for n in tr.notes:
            L.append(f"> {n}  ")
        L.append("")
    numbered = _numbered(tr)
    if sum(1 for t, _ in numbered if t) > 1:
        L += ["## Contents", ""]
        for title, s in numbered:
            if title:
                anchor = re.sub(r"[^\w\- ]", "", title.lower()).strip().replace(" ", "-")
                L.append(f"- [{title}](#{anchor}) — {fmt_time(s.start)}")
        L.append("")
    L += ["---", ""]
    for title, s in numbered:
        if title:
            L += [f"## {title}", ""]
            sub = f"*Starts at {fmt_time(s.start)}"
            if s.listed is not None and abs(s.listed - s.start) > 15:
                sub += f" (chapter list says {fmt_time(s.listed)})"
            L += [sub + "*", ""]
        for p in s.paragraphs:
            link = tr.link_at(p.start)
            ts = f"[`{fmt_time(p.start)}`]({link})" if link else f"`{fmt_time(p.start)}`"
            L += [f"{ts} {p.text}", ""]
    if tr.changes:
        L += ["---", "", f"## Changes made to the raw text ({len(tr.changes)})", "",
              "| Time | Before | After | Why |", "|---|---|---|---|"]
        for c in tr.changes:
            esc = lambda s: s.replace("|", "\\|")
            L.append(f"| {fmt_time(c.start)} | {esc(c.before)} | {esc(c.after)} | {c.reason} |")
        L.append("")
    return "\n".join(L) + "\n"


def render_text(tr: Transcript) -> str:
    L = [tr.meta.get("title", "Transcript"), "=" * min(80, len(tr.meta.get("title", "Transcript"))), ""]
    L += _meta_lines(tr) + [""]
    for n in tr.notes:
        L.append(f"Note: {n}")
    if tr.notes:
        L.append("")
    for title, s in _numbered(tr):
        if title:
            L += ["", f"{title}  [{fmt_time(s.start)}]", "-" * min(80, len(title) + 10), ""]
        for p in s.paragraphs:
            L += [f"[{fmt_time(p.start)}] {p.text}", ""]
    return "\n".join(L).rstrip() + "\n"


def render_srt(tr: Transcript) -> str:
    def ts(t: float) -> str:
        ms = int(round(t * 1000))
        h, ms = divmod(ms, 3_600_000)
        m, ms = divmod(ms, 60_000)
        s, ms = divmod(ms, 1000)
        return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

    cues: list[list[Word]] = []
    cur: list[Word] = []
    for w in tr.words:
        cur.append(w)
        span = w.start - cur[0].start
        chars = sum(len(x.text) + 1 for x in cur)
        if (_ends_sentence(w) and span >= 1.5) or span >= 6.0 or chars >= 80:
            cues.append(cur)
            cur = []
    if cur:
        cues.append(cur)
    out = []
    for i, cue in enumerate(cues, 1):
        start = cue[0].start
        end = cues[i][0].start if i < len(cues) else cue[-1].start + 2.0
        end = min(end, start + 7.0)
        text = " ".join(w.text for w in cue)
        if len(text) > 42:  # two balanced lines
            mid = len(text) // 2
            cut = text.rfind(" ", 0, mid + 10)
            if cut > 0:
                text = text[:cut] + "\n" + text[cut + 1:]
        out.append(f"{i}\n{ts(start)} --> {ts(end)}\n{text}\n")
    return "\n".join(out)


def safe_filename(name: str, limit: int = 120) -> str:
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", name).strip().rstrip(".")
    return (name[:limit].rstrip() or "transcript")


def save_all(tr: Transcript, out_dir: Path) -> dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = safe_filename(tr.meta.get("title") or "transcript")
    if tr.meta.get("video_id"):
        stem += f" [{tr.meta['video_id']}]"
    paths = {
        "md": out_dir / f"{stem}.md",
        "txt": out_dir / f"{stem}.txt",
        "srt": out_dir / f"{stem}.srt",
    }
    paths["md"].write_text(render_markdown(tr), encoding="utf-8")
    paths["txt"].write_text(render_text(tr), encoding="utf-8")
    paths["srt"].write_text(render_srt(tr), encoding="utf-8")
    return paths
