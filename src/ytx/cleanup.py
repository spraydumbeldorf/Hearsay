"""Generic transcript clean-up. Every edit is recorded as a Change so nothing is altered silently.

Rules come from what went wrong in YouTube auto-captions and Whisper output in practice:
* repeated numbers ("0.40 40", "26.0 0", "2.2 two times") - the recogniser renders the number twice
* names mis-heard as near-misses ("Olama" for Ollama, "Quen" for Qwen, "gguf" for GGUF)
* Whisper splitting numbers/compounds into tokens ("0 .40", "64 ,000", "multi -agent")
* sentences that start lower-case after a full stop
"""
from __future__ import annotations

import difflib
import re
from collections import Counter

from .models import Change, Word

_SPLIT = re.compile(r"^([\"'(\[]*)(.*?)([\"')\].,!?;:]*)$", re.S)
_NUMWORDS = {w: i for i, w in enumerate(
    "zero one two three four five six seven eight nine ten eleven twelve".split())}

# Very common words that must never be "corrected" into a name.
_STOP = set("""
a about after again all also am an and any are as at back be because been before being best both
but by can could day did do does doing done down each even every few first for from get go going good
got great had has have having he her here him his how i if in into is it its just know last like
look made make many may me more most much my need new no not now of off on once one only or other
our out over own people really right said same see she should show so some still such take than
that the their them then there these they thing things think this those through time to too two up
us use used very want was way we well were what when where which while who why will with work
would year you your yours mean meant model models video videos test tests number numbers
""".split())


def _parts(tok: str) -> tuple[str, str, str]:
    m = _SPLIT.match(tok)
    return (m.group(1), m.group(2), m.group(3)) if m else ("", tok, "")


# ---------------------------------------------------------------- repeated numbers
def _is_repeat(prev_core: str, cur_core: str) -> bool:
    if not re.fullmatch(r"\d[\d,]*\.\d+", prev_core):
        return False
    frac = prev_core.rsplit(".", 1)[1]
    if cur_core.isdigit():
        return cur_core == frac
    n = _NUMWORDS.get(cur_core.lower())
    return n is not None and frac.isdigit() and int(frac) == n


def fix_repeated_numbers(words: list[Word], changes: list[Change]) -> list[Word]:
    out: list[Word] = []
    for w in words:
        if out:
            prev = out[-1]
            _, pc, ptrail = _parts(prev.text)
            _, cc, ctrail = _parts(w.text)
            if not ptrail and _is_repeat(pc, cc):
                before = f"{prev.text} {w.text}"
                prev.text = prev.text + ctrail
                changes.append(Change(prev.start, before, prev.text, "number repeated by the recogniser"))
                continue
            if ptrail == "," and _is_repeat(pc, cc):
                before = f"{prev.text} {w.text}"
                changes.append(Change(prev.start, before, prev.text, "number repeated by the recogniser"))
                continue
        out.append(w)
    return out


# ---------------------------------------------------------------- whisper token joins
def join_split_tokens(words: list[Word], changes: list[Change]) -> list[Word]:
    out: list[Word] = []
    for w in words:
        if out and re.match(r"^[.,\-][\w]", w.text) and re.search(r"\w$", out[-1].text):
            prev = out[-1]
            before = f"{prev.text} {w.text}"
            prev.text = prev.text + w.text
            if prev.prob is not None and w.prob is not None:
                prev.prob = min(prev.prob, w.prob)
            changes.append(Change(prev.start, before, prev.text, "rejoined split number/word"))
            continue
        if not w.text:
            continue
        out.append(w)
    return out


# ---------------------------------------------------------------- names from metadata
_TOK = re.compile(r"[A-Za-z][A-Za-z0-9]*(?:[.\-+][A-Za-z0-9]+)*")


def _name_shaped(tok: str) -> bool:
    """MLX, GGUF, Qwen3.8, LMStudio - shapes ordinary words don't have."""
    return bool(re.search(r"[a-z][A-Z]|[A-Z]{2,}|\d", tok))


def build_vocabulary(meta: dict) -> dict[str, str]:
    """lower-case -> preferred spelling for names found in the video's metadata.

    A plain capitalised word only counts as a name if the description capitalises it mid-sentence
    and never writes it in lower case (so "Ollama" qualifies, "Setting" from a chapter title doesn't).
    Titles, chapter titles and tags are title-case or all-lower-case, so they only contribute
    name-shaped tokens.
    """
    desc = re.sub(r"https?://\S+|\S+\.(?:com|org|net|io|ai|dev)\S*|#\w+|@\w+", " ", meta.get("description") or "")
    headings =[meta.get("title") or ""] + [t for _, t in meta.get("chapters") or []] + list(meta.get("tags") or [])
    mid_cap: Counter[str] = Counter()
    lower_seen: set[str] = set()

    def tokens(line: str):
        # identifiers like OLLAMA_NUM_PARALLEL are code, not names; skip them whole
        for m in re.finditer(r"[A-Za-z][A-Za-z0-9_]*(?:[.\-+][A-Za-z0-9_]+)*", line):
            if "_" not in m.group(0):
                yield m

    def add(tok: str):
        mid_cap[tok] += 1
        # "Qwen3.8-27B" also teaches the bare name "Qwen"
        head = re.match(r"[A-Za-z]{3,}", tok)
        if head and head.group(0) != tok:
            mid_cap[head.group(0)] += 1

    for line in desc.splitlines():
        letters = re.sub(r"[^A-Za-z]", "", line)
        if len(letters) >= 4 and letters.isupper():
            continue  # ALL-CAPS heading such as "CHAPTERS"
        for m in tokens(line):
            tok = m.group(0)
            if tok.islower():
                lower_seen.add(tok)
                continue
            pre = line[:m.start()].rstrip()
            at_start = not pre or pre[-1] in ".!?:;-#\"'(—–•*>|"
            if _name_shaped(tok) or not at_start:
                add(tok)
    for text in headings:
        for m in tokens(text):
            if _name_shaped(m.group(0)):
                add(m.group(0))
    # names typed by the user count as names whatever their shape (weighted to win casing ties)
    for term in meta.get("extra_terms") or []:
        for m in tokens(term):
            for _ in range(100):
                add(m.group(0))
            lower_seen.discard(m.group(0).lower())
    by_lower: dict[str, list[tuple[str, int]]] = {}
    for tok, n in mid_cap.items():
        by_lower.setdefault(tok.lower(), []).append((tok, n))
    vocab: dict[str, str] = {}
    for lo, forms in by_lower.items():
        if len(lo) < 3 or lo in _STOP:
            continue
        # prefer normal casing over ALL CAPS, then the most frequent form
        forms.sort(key=lambda f: (f[0].isupper() and len(f[0]) > 4, -f[1]))
        tok = forms[0][0]
        if not _name_shaped(tok) and lo in lower_seen and forms[0][1] < 100:
            continue
        if tok.isupper() and len(tok) > 6:
            continue  # long all-caps words are emphasis, not names
        vocab[lo] = tok
    return vocab


def fix_names(words: list[Word], meta: dict, changes: list[Change]) -> list[Word]:
    vocab = build_vocabulary(meta)
    if not vocab:
        return words
    present = {(_parts(w.text)[1]).lower() for w in words}
    # Only terms the recogniser never got right are targets for fuzzy matching; terms that
    # already appear correctly (e.g. "Studio") would otherwise swallow real words ("studios").
    targets = {lo: sp for lo, sp in vocab.items() if lo not in present and len(lo) >= 4}
    mixed_case = {lo: sp for lo, sp in vocab.items() if sp != sp.lower() and sp != sp.capitalize()}
    cache: dict[tuple[str, bool], str | None] = {}

    def best(core_lo: str, name_like: bool) -> str | None:
        """Closest metadata name. Loose matches (>=0.75) only for tokens the recogniser itself
        marked as a name (capitalised mid-sentence, or containing digits) - real words like
        "come"/"something" must never become "Code"/"Setting"."""
        key = (core_lo, name_like)
        if key in cache:
            return cache[key]
        hit = None
        if core_lo not in vocab and core_lo not in _STOP and len(core_lo) >= 4:
            need = 0.75 if name_like else 0.88
            scored = []
            for lo, sp in targets.items():
                if lo[0] != core_lo[0] or abs(len(lo) - len(core_lo)) > 2:
                    continue
                if core_lo.rstrip("s") == lo.rstrip("s"):  # plural/singular of a real word
                    continue
                r = difflib.SequenceMatcher(None, core_lo, lo).ratio()
                if r >= need:
                    scored.append((r, sp))
            if scored:
                scored.sort(reverse=True)
                if len(scored) == 1 or scored[0][0] - scored[1][0] >= 0.05:
                    hit = scored[0][1]
        cache[key] = hit
        return hit

    prev_text = ""
    for w in words:
        lead, core, trail = _parts(w.text)
        at_sentence_start = not prev_text or bool(re.search(r"[.?!][\"')\]]*$", prev_text))
        prev_text = w.text
        if not core:
            continue
        poss = ""
        if core.endswith("'s") or core.endswith("’s"):
            core, poss = core[:-2], core[-2:]
        lo = core.lower()
        name_like = bool(re.search(r"\d", core)) or (core[:1].isupper() and not at_sentence_start)
        new = None
        if lo in mixed_case and core != mixed_case[lo]:
            new, why = mixed_case[lo], "spelling from video title/description"
        elif (cand := best(lo, name_like)) is not None:
            new, why = cand, f"name from video title/description (heard “{core}”)"
        if new:
            before = w.text
            w.text = f"{lead}{new}{poss}{trail}"
            changes.append(Change(w.start, before, w.text, why))
    return words


# ---------------------------------------------------------------- sentence case
def capitalize_sentences(words: list[Word], changes: list[Change]) -> list[Word]:
    prev_end = True
    for w in words:
        lead, core, trail = _parts(w.text)
        if prev_end and core[:1].islower() and core[:1].isalpha():
            before = w.text
            w.text = lead + core[0].upper() + core[1:] + trail
            changes.append(Change(w.start, before, w.text, "sentence start"))
        prev_end = bool(re.search(r"[.?!][\"')\]]*$", w.text))
    return words


def collapse_loops(words: list[Word], changes: list[Change], min_repeats: int = 3) -> list[Word]:
    """Whisper sometimes gets stuck repeating a phrase ("the price of the price of the price of").
    Keep one copy of any 1-8 word phrase repeated `min_repeats`+ times back to back."""
    norm = [re.sub(r"[^\w']", "", w.text.lower()) for w in words]
    out: list[Word] = []
    i = 0
    while i < len(words):
        cut = None
        for n in range(1, 9):
            if i + n * min_repeats > len(words):
                break
            unit = norm[i:i + n]
            if not all(unit):
                continue
            reps = 1
            while norm[i + reps * n:i + (reps + 1) * n] == unit:
                reps += 1
            # single words repeat in real speech ("no, no, no"), so demand more for n == 1
            if reps >= (min_repeats if n > 1 else 5):
                cut = (n, reps)
                break
        if cut:
            n, reps = cut
            removed = words[i + n:i + n * reps]
            changes.append(Change(words[i].start,
                                  " ".join(w.text for w in words[i:i + n * reps]),
                                  " ".join(w.text for w in words[i:i + n]),
                                  f"AI repetition glitch: phrase repeated {reps}×"))
            out.extend(words[i:i + n])
            i += n * reps
            del removed
            continue
        out.append(words[i])
        i += 1
    return out


_STARTERS = set("""But And The So Now This That It It's We If When Then Or Because They You He She There
What Which Why How Also Instead However Meanwhile Finally First Second Next Here Let's Our My Your""".split())


def restore_full_stops(words: list[Word], changes: list[Change]) -> list[Word]:
    """Whisper sometimes capitalises a new sentence but forgets the full stop before it
    ("set it manually But most people"). Add the stop when a common sentence-starter is capitalised
    right after an unpunctuated lower-case word."""
    for prev, w in zip(words, words[1:]):
        _, core, _ = _parts(w.text)
        if core in _STARTERS and re.search(r"[a-z0-9]$", prev.text):
            before = f"{prev.text} {w.text}"
            prev.text += "."
            changes.append(Change(prev.start, before, f"{prev.text} {w.text}", "added missing full stop"))
    return words


def clean(words: list[Word], meta: dict, fix_names_enabled: bool = True,
          from_whisper: bool = False) -> tuple[list[Word], list[Change]]:
    changes: list[Change] = []
    words = [Word(w.start, w.text.strip(), w.prob) for w in words if w.text.strip()]
    words = join_split_tokens(words, changes)
    if from_whisper:
        words = collapse_loops(words, changes)
        words = restore_full_stops(words, changes)
    words = fix_repeated_numbers(words, changes)
    if fix_names_enabled:
        words = fix_names(words, meta, changes)
    words = capitalize_sentences(words, changes)
    changes.sort(key=lambda c: c.start)
    return words, changes


def hotwords_for(meta: dict, limit: int = 40) -> str | None:
    """Spelling hints for Whisper: names from the metadata only.

    The title isn't included: titles are usually Title Case, and Whisper copies that style
    ("Running PS in Terminal").
    """
    vocab = build_vocabulary(meta)
    user = [t for t in meta.get("extra_terms") or []]  # full phrases like "Claude Code" first
    terms = [t for t in dict.fromkeys(vocab.values()) if _name_shaped(t) or t[:1].isupper()]
    terms = list(dict.fromkeys(user + terms))[:limit]
    # a punctuated hint keeps Whisper's output punctuated
    return (", ".join(terms) + ".") if terms else None
