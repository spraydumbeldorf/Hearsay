<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="assets/logo/hearsay-logo-dark.png">
    <img src="assets/logo/hearsay-logo-light.png" alt="Hearsay: Every word, on the record." width="460">
  </picture>
</p>

# Hearsay

**Every word, on the record.** A Windows desktop app that turns a YouTube link or a local video/audio file into a clean, organised
transcript, split into the video's chapters with timestamped paragraphs. It saves Markdown, plain-text
and subtitle (.srt) files automatically.

**Program:** `dist\Hearsay.exe` (a single file; copy it anywhere and double-click).

## Using it

1. **Source:** paste a YouTube link, or switch to *Video / audio file* and browse to a file
   (mp4, mkv, mov, webm, mp3, m4a, wav, flac, …).
2. **Method**
   - **Captions:** downloads YouTube's own captions and takes seconds. Automatic captions can drop or mis-hear
     words.
   - **Whisper AI:** downloads only the audio and transcribes it on this PC with OpenAI's Whisper model
     (run locally, so nothing is uploaded). Much more accurate. Local files always use this.
3. **AI model** (Whisper only):

   | Model | Download (once) | Speed on a typical laptop CPU |
   |---|---|---|
   | Balanced: Large v3 Turbo *(default)* | 1.6 GB | ~3–5 min per 10 min of video |
   | Most accurate: Large v3 | 3.1 GB | ~12–15 min per 10 min of video |
   | Fastest: Small | 0.5 GB | ~1–2 min per 10 min of video |

4. **Fix names** (on by default) learns product and people names from the video's title, tags and description,
   and uses them to correct mis-heard spellings ("Olama" → "Ollama"). For files, or when a video's description
   doesn't mention a name, type names into **Extra names** (e.g. `Ollama, Qwen, Claude Code`).
5. Press **Generate transcript**.

Results appear in three tabs:

- **Transcript:** chapters and timestamped paragraphs. Click a timestamp to open the video at that moment.
  Words Whisper was unsure about are underlined.
- **Changes:** every automatic correction (before → after, with the reason). Nothing is altered silently.
- **Details:** channel, date, link, the video's chapter list and its description.

Files are saved to `Documents\Transcripts\<title> [video id].md / .txt / .srt`. Use **Save as…** to save a
copy anywhere else, or **Copy text** to put it on the clipboard.

## What it fixes automatically

| Problem (seen in real captions/Whisper output) | Fix |
|---|---|
| Numbers said twice: "0.40 40", "26.0 0", "2.2 two times" | the duplicate is dropped |
| Names mis-heard: "Olama", "Quen", "gguf" | corrected from the video's own metadata or your extra names |
| Whisper splitting tokens: "64 ,000", "multi -agent" | rejoined |
| Whisper repetition glitch: "the price of the price of the price of" | collapsed to one copy |
| Missing full stop before a capitalised sentence start | added |
| Sentences starting lower-case | capitalised |

Every change is listed in the Changes tab and at the end of the Markdown file.

## Good to know

- Model files are stored in `%LOCALAPPDATA%\Hearsay\models`. Delete that folder to free
  the space; models are downloaded again when next needed.
- Chapter times come from the video description, and creators sometimes get them wrong. Each section starts at
  the nearest sentence, and if that's more than 15 seconds from the listed time, both times are shown.
- Errors are logged to `%LOCALAPPDATA%\Hearsay\error.log`.
- YouTube changes often. If links stop working, rebuild with a newer `yt-dlp` (edit `requirements.txt`).
- Private, members-only and age-restricted videos can't be read.

## Command-line mode

```
Hearsay.exe --cli <link-or-file> [--method captions|whisper]
    [--model large-v3-turbo|large-v3|small] [--language en] [--terms "Ollama, Qwen"]
    [--out DIR] [--clip 8:10-8:40]
```

Progress is written to `ytx-cli.log` in the output folder.

## Building from source

```
powershell -ExecutionPolicy Bypass -File build.ps1
```

This creates `.venv`, installs `requirements.txt`, generates the icon (`tools\make_assets.py`) and runs
PyInstaller (`ytx.spec`). The logo and icon are drawn by `tools\make_assets.py` (`assets\logo\` has the SVG and PNG versions). Run from source with `.venv\Scripts\python.exe run.py`.

Project layout:

```
run.py               entry point (UI, or --cli)
src/ytx/ui.py        CustomTkinter interface
src/ytx/pipeline.py  source → words → cleanup → sections
src/ytx/youtube.py   yt-dlp: metadata, json3 captions, audio-only download
src/ytx/whisper_engine.py  faster-whisper (CPU, int8), model download with progress
src/ytx/audio.py     PyAV decoding to 16 kHz mono
src/ytx/captions.py  json3 → timed words
src/ytx/cleanup.py   automatic corrections (all logged)
src/ytx/document.py  chapters/paragraphs, Markdown/TXT/SRT output
```

### Packaging notes (lessons learned)

- `ctranslate2.dll` needs the Visual C++ runtime, which isn't installed on every PC. The `msvc-runtime` DLLs are
  bundled and registered with `os.add_dll_directory` before import (`env.prepare_runtime`).
- faster-whisper's `decode_audio()` passes an argument newer PyAV rejects, so audio is decoded directly with PyAV.
- Captions are read in **json3**, not VTT. Auto-caption VTT repeats every line across rolling cues.
- PyInstaller's splash screen is **not** used. It unpacks a second copy of Tcl/Tk and triggers
  "File already exists but should not: …\_tk_data\tk.tcl" warnings.
- `tk.Text` isn't scaled by CustomTkinter, so its fonts are set in scaled pixels. The window size is fitted to the
  monitor's work area, which matters at 150–200 % display scaling.
