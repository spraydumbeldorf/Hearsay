# PyInstaller spec - build with build.ps1
# -*- mode: python ; coding: utf-8 -*-
import glob
import os

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs, collect_submodules

ROOT = os.path.abspath(SPECPATH)
VENV = os.path.join(ROOT, ".venv")

# ctranslate2.dll depends on the Microsoft Visual C++ runtime, which many PCs don't have installed.
# Ship the DLLs from the `msvc-runtime` package both at the bundle root and next to ctranslate2.dll.
msvc = [p for p in glob.glob(os.path.join(VENV, "*.dll"))
        if os.path.basename(p).lower().startswith(("msvcp140", "vcruntime140", "vcomp140", "concrt140"))]
msvc += glob.glob(os.path.join(VENV, "Scripts", "vcruntime140*.dll"))
binaries = collect_dynamic_libs("ctranslate2")
for dll in msvc:
    binaries += [(dll, "."), (dll, "ctranslate2")]

datas = (
    collect_data_files("faster_whisper")      # silero VAD model (assets/*.onnx)
    + collect_data_files("customtkinter")     # themes
    + [(os.path.join(ROOT, "assets"), "assets")]
)

hiddenimports = collect_submodules("yt_dlp") + ["ytx.ui", "ytx.cli"]

a = Analysis(
    [os.path.join(ROOT, "run.py")],
    pathex=[os.path.join(ROOT, "src")],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=["hf_xet", "torch", "tensorflow", "matplotlib", "pandas", "scipy", "IPython", "pytest"],
    noarchive=False,
)
pyz = PYZ(a.pure)
# No PyInstaller Splash: it unpacks its own copy of Tcl/Tk, which collides with the app's copy and
# pops up "File already exists but should not: ...\_tk_data\tk.tcl" warnings on every launch.
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="YouTube Transcript Extractor",
    icon=os.path.join(ROOT, "assets", "icon.ico"),
    version=os.path.join(ROOT, "tools", "version_info.txt"),
    console=False,
    upx=False,
    runtime_tmpdir=None,
)
