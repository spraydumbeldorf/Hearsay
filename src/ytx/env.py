"""Paths and runtime setup shared by the UI and the CLI."""
from __future__ import annotations

import os
import sys
from pathlib import Path

from . import APP_NAME, LEGACY_APP_NAMES


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def resource_path(*parts: str) -> Path:
    """Files shipped with the app (icons etc.): inside the bundle when frozen, repo root otherwise."""
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2]))
    return base.joinpath(*parts)


def data_dir() -> Path:
    root = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    base = root / APP_NAME
    if not base.exists():
        # The app was renamed: move the old folder (with its multi-GB models) instead of re-downloading.
        for old in LEGACY_APP_NAMES:
            if (root / old).is_dir():
                try:
                    (root / old).rename(base)
                except OSError:
                    pass
                break
    base.mkdir(parents=True, exist_ok=True)
    return base


def models_dir() -> Path:
    d = data_dir() / "models"
    d.mkdir(parents=True, exist_ok=True)
    return d


def temp_dir() -> Path:
    d = data_dir() / "tmp"
    d.mkdir(parents=True, exist_ok=True)
    return d


def documents_dir() -> Path:
    """The real Documents folder (follows OneDrive/known-folder redirection)."""
    if os.name == "nt":
        try:
            import ctypes
            from ctypes import wintypes

            buf = ctypes.create_unicode_buffer(wintypes.MAX_PATH)
            # CSIDL_PERSONAL = 5 (My Documents)
            if ctypes.windll.shell32.SHGetFolderPathW(None, 5, None, 0, buf) == 0 and buf.value:
                return Path(buf.value)
        except Exception:
            pass
    return Path.home() / "Documents"


def default_output_dir() -> Path:
    return documents_dir() / "Transcripts"


def prepare_runtime() -> None:
    """Must run before faster_whisper / ctranslate2 are imported.

    Lessons from the manual run:
    * ctranslate2.dll needs the Microsoft Visual C++ runtime, which isn't installed system-wide
      on every PC. We ship the DLLs (pip package `msvc-runtime`) and register their folder.
    * Plain HTTP downloads give predictable progress for the model download (no Xet chunk cache).
    """
    os.environ.setdefault("HF_HUB_DISABLE_XET", "1")
    os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
    os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
    os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
    os.environ.setdefault("HF_HUB_VERBOSITY", "error")
    if os.name != "nt":
        return
    candidates = [Path(sys.prefix), Path(sys.prefix) / "Scripts", Path(sys.base_prefix)]
    if is_frozen():
        meipass = Path(getattr(sys, "_MEIPASS"))
        candidates = [meipass, meipass / "ctranslate2"] + candidates
    for c in candidates:
        if c.is_dir() and (any(c.glob("msvcp140*.dll")) or (c / "vcruntime140.dll").exists()):
            try:
                os.add_dll_directory(str(c))
            except OSError:
                pass
