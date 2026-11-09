"""Decode any audio/video file to 16 kHz mono float32 for Whisper.

faster-whisper's own decode_audio() passes `metadata_errors=` to av.open(), which newer PyAV
releases reject, so we decode with PyAV directly.
"""
from __future__ import annotations

import threading
from pathlib import Path
from typing import Callable, Optional

import numpy as np

SAMPLE_RATE = 16000


class NoAudioError(Exception):
    pass


def load_audio(path: str | Path,
               progress: Optional[Callable[[float], None]] = None,
               cancel: Optional[threading.Event] = None,
               clip: Optional[tuple[float, float]] = None) -> np.ndarray:
    import av

    chunks: list[np.ndarray] = []
    with av.open(str(path)) as container:
        if not container.streams.audio:
            raise NoAudioError(f"No audio track found in {Path(path).name}")
        stream = container.streams.audio[0]
        total = None
        if container.duration:
            total = container.duration / 1_000_000
        elif stream.duration and stream.time_base:
            total = float(stream.duration * stream.time_base)
        if clip and clip[0] > 0:
            container.seek(int(clip[0] * 1_000_000), any_frame=False, backward=True)
        resampler = av.audio.resampler.AudioResampler(format="s16", layout="mono", rate=SAMPLE_RATE)
        last_report = -1.0
        for frame in container.decode(stream):
            if cancel is not None and cancel.is_set():
                raise InterruptedError
            t = float(frame.time or 0)
            if clip and t >= clip[1]:
                break
            for f in resampler.resample(frame):
                chunks.append(f.to_ndarray().reshape(-1))
            if progress and total and t - last_report >= 5:
                last_report = t
                span = (clip[1] - clip[0]) if clip else total
                progress(min(1.0, (t - (clip[0] if clip else 0)) / max(span, 1e-6)))
        for f in resampler.resample(None):
            chunks.append(f.to_ndarray().reshape(-1))
    if not chunks:
        raise NoAudioError(f"Could not decode any audio from {Path(path).name}")
    pcm = np.concatenate(chunks)
    return pcm.astype(np.float32) / 32768.0
