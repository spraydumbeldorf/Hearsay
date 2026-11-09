"""Headless mode (used for testing and scripting).

python run.py --cli SOURCE [--method captions|whisper] [--model large-v3-turbo] [--out DIR] [--clip 0:00-1:30]
"""
from __future__ import annotations

import argparse
import sys
import threading
import time
import traceback
from pathlib import Path


def _secs(s: str) -> float:
    parts = [float(p) for p in s.split(":")]
    v = 0.0
    for p in parts:
        v = v * 60 + p
    return v


def main(argv: list[str]) -> int:
    from .env import default_output_dir, prepare_runtime

    prepare_runtime()
    from . import document, pipeline

    ap = argparse.ArgumentParser(prog="ytx --cli")
    ap.add_argument("source")
    ap.add_argument("--method", default="captions", choices=["captions", "whisper"])
    ap.add_argument("--model", default="large-v3-turbo")
    ap.add_argument("--language", default=None)
    ap.add_argument("--no-name-fixes", action="store_true")
    ap.add_argument("--out", default=str(default_output_dir()))
    ap.add_argument("--clip", default=None, help="start-end, e.g. 8:10-8:40")
    ap.add_argument("--terms", default="", help="extra names, comma separated")
    a = ap.parse_args(argv)

    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    logf = open(out / "ytx-cli.log", "a", encoding="utf-8")

    def emit(msg: str):
        line = f"{time.strftime('%H:%M:%S')} {msg}"
        logf.write(line + "\n")
        logf.flush()
        if sys.stdout:
            try:
                print(line, flush=True)
            except Exception:
                pass

    last = {"k": None}

    def progress(stage, frac, detail):
        key = (stage, None if frac is None else int(frac * 10))
        if key != last["k"]:
            last["k"] = key
            pct = "" if frac is None else f" {frac * 100:5.1f}%"
            emit(f"[{stage}]{pct} {detail}")

    clip = None
    if a.clip:
        s, e = a.clip.split("-")
        clip = (_secs(s), _secs(e))
    opts = pipeline.Options(a.source, a.method, a.model, a.language, not a.no_name_fixes, clip, a.terms)
    t0 = time.time()
    try:
        tr = pipeline.run(opts, progress, threading.Event(), emit)
        paths = document.save_all(tr, out)
        emit(f"DONE in {time.time() - t0:.0f}s: {tr.word_count} words, {len(tr.sections)} sections, "
             f"{len(tr.changes)} changes, source={tr.source_label}")
        for k, p in paths.items():
            emit(f"  {k}: {p}")
        return 0
    except Exception as e:  # noqa: BLE001
        emit(f"FAILED: {e}\n{traceback.format_exc()}")
        return 1
    finally:
        logf.close()
