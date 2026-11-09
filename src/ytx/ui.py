"""Desktop UI (CustomTkinter)."""
from __future__ import annotations

import argparse
import os
import queue
import subprocess
import sys
import threading
import time
import traceback
import webbrowser
import tkinter as tk
import tkinter.font as tkfont
from pathlib import Path
from tkinter import filedialog

import customtkinter as ctk

from . import APP_NAME, APP_VERSION
from .env import default_output_dir, prepare_runtime, resource_path
from .models import Transcript, fmt_time

# ----------------------------------------------------------------------------- palette
ACCENT = ("#5B5BD6", "#6C6CF0")
ACCENT_HOVER = ("#4949C2", "#5A5AE0")
ACCENT_TEXT = ("#5B5BD6", "#9C9CFA")   # accent used as text on the card background
ACCENT_SOFT = ("#EDEDFC", "#25253F")
BG = ("#F4F5F8", "#0F1014")
SIDEBAR = ("#FFFFFF", "#17181D")
CARD = ("#FFFFFF", "#17181D")
BORDER = ("#E3E5EC", "#272832")
MUTED = ("#6A6E7F", "#9497AA")
TEXT = ("#15161C", "#E9EAF0")
FIELD = ("#F4F5F8", "#1F2027")
DANGER = ("#D6455D", "#F07088")
SUCCESS = ("#1E9E6A", "#43C68E")
SEG_TRACK = ("#E8EAF0", "#22232B")
SEG_PILL = ("#FFFFFF", "#353645")
SEG_HOVER = ("#DCDFE7", "#2C2D38")


def seg_style(**extra):
    """Windows-11-style segmented control: soft track, raised pill for the selected option."""
    return dict(fg_color=SEG_TRACK, unselected_color=SEG_TRACK, unselected_hover_color=SEG_HOVER,
                selected_color=SEG_PILL, selected_hover_color=SEG_PILL, text_color=TEXT,
                text_color_disabled=MUTED, corner_radius=10) | extra

METHOD_INFO = {
    "Captions": "Uses YouTube’s own captions. Takes seconds, but automatic captions can drop or mis-hear words.",
    "Whisper AI": "Listens to the audio with an AI model on this PC. Much more accurate, and takes a few minutes. "
                  "Nothing is uploaded.",
}


def _pick(fams: set[str], *names: str) -> str:
    return next((n for n in names if n in fams), "TkDefaultFont")


class App(ctk.CTk):
    def __init__(self, args: argparse.Namespace):
        super().__init__()
        self.args = args
        self.q: queue.Queue = queue.Queue()
        self.cancel = threading.Event()
        self.worker: threading.Thread | None = None
        self.transcript: Transcript | None = None
        self.saved: dict[str, Path] | None = None
        self.file_path: Path | None = None
        self.ts_links: dict[str, float] = {}
        self.match_idx = 0
        self._mode_seen = None
        self.job_started = 0.0

        from .whisper_engine import DEFAULT_MODEL, MODELS
        self.models = MODELS
        self.model_by_label = {v["label"]: k for k, v in MODELS.items()}
        self.model_ready: dict[str, bool] = {}
        self.default_model = DEFAULT_MODEL

        fams = set(tkfont.families(self))
        self.ff = _pick(fams, "Segoe UI Variable Text", "Segoe UI")
        self.ff_display = _pick(fams, "Segoe UI Variable Display", "Segoe UI")
        self.ff_mono = _pick(fams, "Cascadia Mono", "Consolas")

        self.title(APP_NAME)
        # Fit the screen: at 150-200 % display scaling a fixed 1220x800 window can be taller than the display.
        ax, ay, aw, ah = _work_area(self)
        w, h = int(min(1220, aw - 40)), int(min(820, ah - 70))  # leave room for the title bar
        self.geometry(f"{w}x{h}+{int(ax + max(0, (aw - w) / 2))}+{int(ay + max(0, (ah - h - 32) / 2))}")
        self.minsize(min(980, w), min(620, h))
        self.configure(fg_color=BG)
        ico = resource_path("assets", "icon.ico")
        if ico.exists():
            try:
                self.iconbitmap(str(ico))
            except tk.TclError:
                pass
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self._build_sidebar()
        self._build_main()
        self._show_welcome()
        self.after(80, self._poll)
        threading.Thread(target=self._check_models, daemon=True).start()

    # ------------------------------------------------------------------ fonts
    def f(self, size=13, weight="normal", display=False):
        return ctk.CTkFont(family=self.ff_display if display else self.ff, size=size, weight=weight)

    # ------------------------------------------------------------------ sidebar
    def _section_label(self, parent, text):
        return ctk.CTkLabel(parent, text=text.upper(), text_color=MUTED, font=self.f(11, "bold"), anchor="w")

    def _build_sidebar(self):
        sb = ctk.CTkFrame(self, width=360, corner_radius=0, fg_color=SIDEBAR, border_width=0)
        sb.grid(row=0, column=0, sticky="nsew")
        sb.grid_propagate(False)
        sb.grid_columnconfigure(0, weight=1)
        self.sidebar = sb
        px = 26

        brand = ctk.CTkFrame(sb, fg_color="transparent")
        brand.grid(row=0, column=0, sticky="ew", padx=px, pady=(20, 12))
        logo = None
        png = resource_path("assets", "icon.png")
        if png.exists():
            try:
                from PIL import Image
                img = ctk.CTkImage(Image.open(png), size=(44, 44))
                logo = ctk.CTkLabel(brand, text="", image=img, width=44, height=44)
            except Exception:
                logo = None
        if logo is None:
            logo = ctk.CTkLabel(brand, text="≡", width=42, height=42, corner_radius=12, fg_color=ACCENT,
                                text_color="#FFFFFF", font=ctk.CTkFont(family=self.ff_display, size=24, weight="bold"))
        logo.grid(row=0, column=0, rowspan=2, padx=(0, 12))
        ctk.CTkLabel(brand, text="Transcript Extractor", font=self.f(19, "bold", True), text_color=TEXT,
                     anchor="w").grid(row=0, column=1, sticky="w")
        ctk.CTkLabel(brand, text="YouTube & video files → clean transcripts", font=self.f(12),
                     text_color=MUTED, anchor="w").grid(row=1, column=1, sticky="w")

        r = 1
        self._section_label(sb, "1  Source").grid(row=r, column=0, sticky="ew", padx=px, pady=(4, 8)); r += 1
        self.seg_source = ctk.CTkSegmentedButton(
            sb, values=["YouTube link", "Video / audio file"], command=self._on_source, height=36,
            font=self.f(13), **seg_style())
        self.seg_source.set("YouTube link")
        self.seg_source.grid(row=r, column=0, sticky="ew", padx=px); r += 1

        self.src_holder = ctk.CTkFrame(sb, fg_color="transparent", height=44)
        self.src_holder.grid(row=r, column=0, sticky="ew", padx=px, pady=(10, 0)); r += 1
        self.src_holder.grid_columnconfigure(0, weight=1)
        self.url_row = ctk.CTkFrame(self.src_holder, fg_color="transparent")
        self.url_row.grid_columnconfigure(0, weight=1)
        self.url_entry = ctk.CTkEntry(self.url_row, placeholder_text="Paste a YouTube link…", height=40,
                                      font=self.f(13), fg_color=FIELD, border_color=BORDER, corner_radius=10)
        self.url_entry.grid(row=0, column=0, sticky="ew")
        self.url_entry.bind("<Return>", lambda e: self._start())
        ctk.CTkButton(self.url_row, text="Paste", width=66, height=40, corner_radius=10, font=self.f(13),
                      fg_color=FIELD, hover_color=BORDER, text_color=TEXT, border_width=1, border_color=BORDER,
                      command=self._paste).grid(row=0, column=1, padx=(8, 0))
        self.file_row = ctk.CTkFrame(self.src_holder, fg_color="transparent")
        self.file_row.grid_columnconfigure(0, weight=1)
        self.file_label = ctk.CTkLabel(self.file_row, text="No file chosen", anchor="w", height=40, corner_radius=10,
                                       fg_color=FIELD, text_color=MUTED, font=self.f(13))
        self.file_label.grid(row=0, column=0, sticky="ew")
        ctk.CTkButton(self.file_row, text="Browse…", width=86, height=40, corner_radius=10, font=self.f(13),
                      fg_color=ACCENT, hover_color=ACCENT_HOVER, command=self._browse).grid(row=0, column=1, padx=(8, 0))
        self.url_row.grid(row=0, column=0, sticky="ew")

        self._section_label(sb, "2  Method").grid(row=r, column=0, sticky="ew", padx=px, pady=(18, 8)); r += 1
        self.seg_method = ctk.CTkSegmentedButton(
            sb, values=list(METHOD_INFO), command=self._on_method, height=36, font=self.f(13), **seg_style())
        self.seg_method.set("Captions")
        self.seg_method.grid(row=r, column=0, sticky="ew", padx=px); r += 1
        self.method_desc = ctk.CTkLabel(sb, text=METHOD_INFO["Captions"], wraplength=300, justify="left",
                                        anchor="w", text_color=MUTED, font=self.f(12))
        self.method_desc.grid(row=r, column=0, sticky="ew", padx=px, pady=(8, 0)); r += 1

        # model picker: only shown for Whisper AI
        self.model_box = ctk.CTkFrame(sb, fg_color="transparent")
        self.r_model = r; r += 1
        self.model_box.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(self.model_box, text="AI model", font=self.f(12, "bold"), text_color=TEXT, anchor="w").grid(
            row=0, column=0, sticky="w")
        self.model_status = ctk.CTkLabel(self.model_box, text="", font=self.f(11), text_color=MUTED, anchor="e")
        self.model_status.grid(row=0, column=1, sticky="e")
        self.model_menu = ctk.CTkOptionMenu(
            self.model_box, values=[v["label"] for v in self.models.values()], height=36, corner_radius=10,
            font=self.f(13), dropdown_font=self.f(13), fg_color=FIELD, button_color=FIELD,
            button_hover_color=BORDER, text_color=TEXT, command=lambda _: self._update_model_status())
        self.model_menu.set(self.models[self.default_model]["label"])
        self.model_menu.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(4, 0))

        lang_box = ctk.CTkFrame(sb, fg_color="transparent")
        lang_box.grid(row=r, column=0, sticky="ew", padx=px, pady=(10, 0)); r += 1
        lang_box.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(lang_box, text="Language", font=self.f(12, "bold"), text_color=TEXT,
                     anchor="w").grid(row=0, column=0, sticky="w", padx=(0, 12))
        from .pipeline import LANGUAGES
        self.languages = LANGUAGES
        self.lang_menu = ctk.CTkOptionMenu(
            lang_box, values=list(LANGUAGES), height=34, corner_radius=10, font=self.f(13),
            dropdown_font=self.f(13), fg_color=FIELD, button_color=FIELD, button_hover_color=BORDER, text_color=TEXT)
        self.lang_menu.set("Auto-detect")
        self.lang_menu.grid(row=0, column=1, sticky="ew")

        self.sw_names = ctk.CTkSwitch(sb, text="Fix names using the video’s title & description",
                                      font=self.f(12), text_color=TEXT, progress_color=ACCENT,
                                      fg_color=BORDER, button_color=("#4A4D5C", "#FFFFFF"),
                                      button_hover_color=("#2F313C", "#E9EAF0"), command=self._on_names_switch)
        self.sw_names.select()
        self.sw_names.grid(row=r, column=0, sticky="w", padx=px, pady=(14, 0)); r += 1
        self.terms = ctk.CTkEntry(sb, placeholder_text="Extra names to spell right, e.g. Ollama, Qwen",
                                  height=34, corner_radius=10, font=self.f(12), fg_color=FIELD, border_color=BORDER)
        self.terms.grid(row=r, column=0, sticky="ew", padx=px, pady=(8, 0)); r += 1

        self.btn_go = ctk.CTkButton(sb, text="Generate transcript", height=46, corner_radius=12,
                                    font=self.f(15, "bold"), fg_color=ACCENT, hover_color=ACCENT_HOVER,
                                    text_color="#FFFFFF", text_color_disabled="#D8D8F5", command=self._start)
        self.btn_go.grid(row=r, column=0, sticky="ew", padx=px, pady=(16, 0)); r += 1

        self.prog = ctk.CTkFrame(sb, fg_color=FIELD, corner_radius=12)
        self.prog.grid_columnconfigure(0, weight=1)
        self.prog_stage = ctk.CTkLabel(self.prog, text="", font=self.f(13, "bold"), text_color=TEXT, anchor="w")
        self.prog_stage.grid(row=0, column=0, sticky="ew", padx=(14, 4), pady=(10, 4))
        self.btn_cancel = ctk.CTkButton(self.prog, text="Cancel", width=64, height=26, corner_radius=8,
                                        font=self.f(12), fg_color="transparent", hover_color=BORDER,
                                        text_color=DANGER, command=self._cancel)
        self.prog_bar = ctk.CTkProgressBar(self.prog, height=8, corner_radius=4, progress_color=ACCENT)
        self.prog_bar.grid(row=1, column=0, columnspan=2, sticky="ew", padx=14)
        self.prog_bar.set(0)
        self.prog_detail = ctk.CTkLabel(self.prog, text="", font=self.f(11), text_color=MUTED, anchor="w",
                                        justify="left", wraplength=280)
        self.prog_detail.grid(row=2, column=0, columnspan=2, sticky="ew", padx=14, pady=(4, 10))
        self.r_prog = r
        r += 1

        sb.grid_rowconfigure(r, weight=1); r += 1
        foot = ctk.CTkFrame(sb, fg_color="transparent")
        foot.grid(row=r, column=0, sticky="ew", padx=px, pady=(12, 16))
        foot.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(foot, text="Theme", font=self.f(12), text_color=MUTED).grid(row=0, column=0, padx=(0, 8))
        self.theme_menu = ctk.CTkSegmentedButton(foot, values=["System", "Light", "Dark"], height=28,
                                                 font=self.f(11), command=self._on_theme, **seg_style())
        self.theme_menu.set("System")
        self.theme_menu.grid(row=0, column=1, sticky="w")
        ctk.CTkLabel(foot, text=f"v{APP_VERSION}", font=self.f(11), text_color=MUTED).grid(row=0, column=2)
        self._on_method("Captions")

    # ------------------------------------------------------------------ main area
    def _build_main(self):
        main = ctk.CTkFrame(self, fg_color="transparent")
        main.grid(row=0, column=1, sticky="nsew", padx=(22, 22), pady=(20, 20))
        main.grid_columnconfigure(0, weight=1)
        main.grid_rowconfigure(2, weight=1)

        head = ctk.CTkFrame(main, fg_color="transparent")
        head.grid(row=0, column=0, sticky="ew", padx=6)
        head.grid_columnconfigure(0, weight=1)
        self.h_title = ctk.CTkLabel(head, text="Your transcript will appear here", font=self.f(22, "bold", True),
                                    text_color=TEXT, anchor="w", justify="left")
        self.h_title.grid(row=0, column=0, sticky="ew")
        self.h_meta = ctk.CTkLabel(head, text="Paste a link or choose a file, then press Generate.",
                                   font=self.f(13), text_color=MUTED, anchor="w", justify="left")
        self.h_meta.grid(row=1, column=0, sticky="ew", pady=(2, 0))
        head.bind("<Configure>", lambda e: (self.h_title.configure(wraplength=max(300, e.width - 10)),
                                            self.h_meta.configure(wraplength=max(300, e.width - 10))))

        bar = ctk.CTkFrame(main, fg_color="transparent")
        bar.grid(row=1, column=0, sticky="ew", pady=(14, 10), padx=6)
        bar.grid_columnconfigure(2, weight=1)
        self.find = ctk.CTkEntry(bar, placeholder_text="\U0001F50D  Find in transcript", width=250, height=34,
                                 corner_radius=10, font=self.f(13), fg_color=CARD, border_color=BORDER)
        self.find.grid(row=0, column=0)
        self.find.bind("<KeyRelease>", self._on_find)
        self.find.bind("<Return>", lambda e: self._next_match())
        self.find_count = ctk.CTkLabel(bar, text="", font=self.f(12), text_color=MUTED)
        self.find_count.grid(row=0, column=1, padx=10)
        btn = dict(height=34, corner_radius=10, font=self.f(13), fg_color=CARD, hover_color=FIELD,
                   text_color=TEXT, border_width=1, border_color=BORDER)
        self.b_copy = ctk.CTkButton(bar, text="Copy text", width=96, command=self._copy, **btn)
        self.b_save = ctk.CTkButton(bar, text="Save as…", width=92, command=self._save_as, **btn)
        self.b_open = ctk.CTkButton(bar, text="Open folder", width=106, command=self._open_folder, **btn)
        self.b_copy.grid(row=0, column=3, padx=(0, 8))
        self.b_save.grid(row=0, column=4, padx=(0, 8))
        self.b_open.grid(row=0, column=5)
        for b in (self.b_copy, self.b_save, self.b_open):
            b.configure(state="disabled")

        self.tabs = ctk.CTkTabview(main, fg_color=CARD, corner_radius=14, border_width=1, border_color=BORDER,
                                   segmented_button_fg_color=SEG_TRACK,
                                   segmented_button_unselected_color=SEG_TRACK,
                                   segmented_button_unselected_hover_color=SEG_HOVER,
                                   segmented_button_selected_color=SEG_PILL,
                                   segmented_button_selected_hover_color=SEG_PILL,
                                   text_color=TEXT, anchor="nw")
        self.tabs.grid(row=2, column=0, sticky="nsew")
        self.texts: dict[str, tk.Text] = {}
        for name in ("Transcript", "Changes", "Details"):
            tab = self.tabs.add(name)
            tab.grid_columnconfigure(0, weight=1)
            tab.grid_rowconfigure(0, weight=1)
            t = tk.Text(tab, wrap="word", borderwidth=0, highlightthickness=0, padx=26, pady=18,
                        cursor="arrow", undo=False, spacing1=0, spacing2=3)
            t.grid(row=0, column=0, sticky="nsew")
            sc = ctk.CTkScrollbar(tab, command=t.yview)
            sc.grid(row=0, column=1, sticky="ns")
            t.configure(yscrollcommand=sc.set)
            self.texts[name] = t
            t.bind("<Key>", self._readonly_keys)
        self.tabs._segmented_button.configure(font=self.f(13))
        self._apply_text_theme()

    @staticmethod
    def _readonly_keys(e):
        if (e.state & 0x4) and e.keysym.lower() in ("c", "a"):
            if e.keysym.lower() == "a":
                e.widget.tag_add("sel", "1.0", "end")
                return "break"
            return None
        if e.keysym in ("Up", "Down", "Left", "Right", "Prior", "Next", "Home", "End"):
            return None
        return "break"

    # ------------------------------------------------------------------ theme for tk.Text
    def _c(self, pair):
        return pair[1] if ctk.get_appearance_mode() == "Dark" else pair[0]

    def _apply_text_theme(self):
        mode = ctk.get_appearance_mode()
        self._mode_seen = mode
        dark = mode == "Dark"
        # tk.Text isn't scaled by CustomTkinter, so size its fonts in scaled pixels to match the widgets.
        sc = ctk.ScalingTracker.get_widget_scaling(self)

        def F(fam, px, *style):
            return (fam, -int(round(px * sc)), *style)

        def P(px):
            return int(round(px * sc))

        for t in self.texts.values():
            t.configure(bg=self._c(CARD), fg=self._c(TEXT), insertbackground=self._c(TEXT),
                        selectbackground=self._c(ACCENT_SOFT), selectforeground=self._c(TEXT),
                        font=F(self.ff, 15), padx=P(26), pady=P(16), spacing2=P(3))
            t.tag_configure("h1", font=F(self.ff_display, 24, "bold"), spacing3=P(4))
            t.tag_configure("meta", foreground=self._c(MUTED), font=F(self.ff, 13), spacing3=P(2))
            t.tag_configure("note", foreground=self._c(MUTED), font=F(self.ff, 13), lmargin1=0, lmargin2=P(22),
                            spacing1=P(2))
            t.tag_configure("h2", font=F(self.ff_display, 19, "bold"), spacing1=P(26), spacing3=P(2),
                            foreground=self._c(TEXT))
            t.tag_configure("sub", foreground=self._c(MUTED), font=F(self.ff, 12), spacing3=P(10))
            t.tag_configure("ts", foreground=self._c(ACCENT_TEXT), font=F(self.ff_mono, 13, "bold"))
            t.tag_configure("body", font=F(self.ff, 15), spacing3=P(14), lmargin1=0, lmargin2=0)
            t.tag_configure("low", underline=True, foreground="#B7791F" if not dark else "#F2C14E")
            t.tag_configure("hl", background="#FFE58A" if not dark else "#6B5A10",
                            foreground="#000000" if not dark else "#FFFFFF")
            t.tag_configure("hlcur", background="#FFB020" if not dark else "#C08A00")
            t.tag_configure("welcome_big", font=F(self.ff_display, 21, "bold"), spacing1=P(20), spacing3=P(6),
                            foreground=self._c(TEXT))
            t.tag_configure("welcome", foreground=self._c(MUTED), font=F(self.ff, 15), spacing3=P(8))
            t.tag_configure("step", font=F(self.ff, 15), spacing3=P(10), lmargin1=P(4), lmargin2=P(34),
                            foreground=self._c(TEXT))
            t.tag_configure("code", font=F(self.ff_mono, 13), foreground=self._c(MUTED))
            t.tag_configure("chg_reason", foreground=self._c(MUTED), font=F(self.ff, 12))
            t.tag_configure("chg_before", foreground=self._c(DANGER), overstrike=True)
            t.tag_configure("chg_after", foreground=self._c(SUCCESS))
            t.tag_raise("hl")
            t.tag_raise("hlcur")
            t.tag_raise("sel")

    def _on_theme(self, v):
        ctk.set_appearance_mode(v.lower())
        self.after(50, self._apply_text_theme)

    # ------------------------------------------------------------------ inputs
    def _on_source(self, v):
        if v == "YouTube link":
            self.file_row.grid_forget()
            self.url_row.grid(row=0, column=0, sticky="ew")
            self.seg_method.configure(state="normal")
        else:
            self.url_row.grid_forget()
            self.file_row.grid(row=0, column=0, sticky="ew")
            self.seg_method.set("Whisper AI")
            self._on_method("Whisper AI")
            self.seg_method.configure(state="disabled")

    def _on_method(self, v):
        txt = METHOD_INFO[v]
        if self.seg_source.get() != "YouTube link":
            txt = "Files are transcribed with the Whisper AI model on this PC. Nothing is uploaded."
        self.method_desc.configure(text=txt)
        if v == "Whisper AI":
            self.model_box.grid(row=self.r_model, column=0, sticky="ew", padx=26, pady=(12, 0))
        else:
            self.model_box.grid_forget()
        self._update_model_status()

    def _on_names_switch(self):
        self.terms.configure(state="normal" if self.sw_names.get() else "disabled")

    def _paste(self):
        try:
            txt = self.clipboard_get().strip()
        except tk.TclError:
            return
        self.url_entry.delete(0, "end")
        self.url_entry.insert(0, txt)

    def _browse(self):
        p = filedialog.askopenfilename(
            title="Choose a video or audio file",
            filetypes=[("Video and audio", "*.mp4 *.mkv *.mov *.avi *.webm *.wmv *.flv *.m4v *.mp3 *.m4a *.wav "
                                           "*.flac *.ogg *.opus *.aac *.wma"), ("All files", "*.*")])
        if p:
            self._set_file(Path(p))

    def _set_file(self, p: Path):
        self.file_path = p
        name = p.name if len(p.name) <= 34 else p.name[:22] + "…" + p.name[-10:]
        self.file_label.configure(text=f"  {name}", text_color=TEXT)

    def _check_models(self):
        from .whisper_engine import local_model_path
        for k in self.models:
            try:
                self.model_ready[k] = bool(local_model_path(k))
            except Exception:
                self.model_ready[k] = False
        self.q.put(("models",))

    def _update_model_status(self):
        key = self.model_by_label.get(self.model_menu.get(), self.default_model)
        m = self.models[key]
        if key not in self.model_ready:
            s, col = "Checking…", MUTED
        elif self.model_ready[key]:
            s, col = "✓ Installed", SUCCESS
        else:
            s, col = f"{m['size']} one-time download", MUTED
        self.model_status.configure(text=s, text_color=col)
        self.model_menu_tip = m["speed"]

    # ------------------------------------------------------------------ job control
    def _start(self):
        if self.worker and self.worker.is_alive():
            return
        from .pipeline import Options
        if self.seg_source.get() == "YouTube link":
            src = self.url_entry.get().strip()
            if not src.lower().startswith(("http://", "https://")):
                self._flash_error("Paste a full YouTube link (starting with https://).")
                return
        else:
            if not self.file_path or not self.file_path.exists():
                self._flash_error("Choose a video or audio file first.")
                return
            src = str(self.file_path)
        method = "whisper" if self.seg_method.get() == "Whisper AI" else "captions"
        opts = Options(
            source=src, method=method,
            model=self.model_by_label.get(self.model_menu.get(), self.default_model),
            language=self.languages.get(self.lang_menu.get()),
            fix_names=bool(self.sw_names.get()),
            extra_terms=self.terms.get().strip() if self.sw_names.get() else "",
        )
        self.cancel.clear()
        self._set_running(True)
        self._progress("Starting", None, "")
        self.job_started = time.time()
        self.worker = threading.Thread(target=self._work, args=(opts,), daemon=True)
        self.worker.start()

    def _work(self, opts):
        from . import document
        from .pipeline import Cancelled, run
        try:
            tr = run(opts, lambda s, f, d: self.q.put(("progress", s, f, d)), self.cancel,
                     lambda m: self.q.put(("log", m)))
            paths = document.save_all(tr, default_output_dir())
            self.q.put(("done", tr, paths))
        except Cancelled:
            self.q.put(("cancelled",))
        except Exception as e:  # noqa: BLE001
            self.q.put(("error", _friendly(e), traceback.format_exc()))

    def _cancel(self):
        self.cancel.set()
        self.btn_cancel.configure(text="Cancelling…", state="disabled")

    def _set_running(self, running: bool):
        state = "disabled" if running else "normal"
        for w in (self.btn_go, self.url_entry, self.seg_source, self.sw_names, self.lang_menu, self.terms):
            w.configure(state=state)
        if not running and not self.sw_names.get():
            self.terms.configure(state="disabled")
        if self.seg_source.get() == "YouTube link":
            self.seg_method.configure(state=state)
        self.model_menu.configure(state=state)
        if running:
            self.btn_go.configure(text="Working…")
            self.btn_cancel.configure(text="Cancel", state="normal")
            self.btn_cancel.grid(row=0, column=1, padx=(0, 8), pady=(8, 2))
            self.prog.grid(row=self.r_prog, column=0, sticky="ew", padx=26, pady=(12, 0))
        else:
            self.btn_go.configure(text="Generate transcript")
            self.btn_cancel.grid_forget()

    def _progress(self, stage, frac, detail):
        self.prog_stage.configure(text=stage, text_color=TEXT)
        if frac is None:
            if self.prog_bar.cget("mode") != "indeterminate":
                self.prog_bar.configure(mode="indeterminate")
                self.prog_bar.start()
        else:
            if self.prog_bar.cget("mode") != "determinate":
                self.prog_bar.stop()
                self.prog_bar.configure(mode="determinate")
            self.prog_bar.set(max(0.0, min(1.0, frac)))
        self.prog_detail.configure(text=detail)

    def _finish_progress(self, stage, detail, color=TEXT, frac=1.0):
        self.prog_bar.stop()
        self.prog_bar.configure(mode="determinate")
        self.prog_bar.set(frac)
        self.prog_stage.configure(text=stage, text_color=color)
        self.prog_detail.configure(text=detail)

    def _flash_error(self, msg):
        self.prog.grid(row=self.r_prog, column=0, sticky="ew", padx=26, pady=(12, 0))
        self._finish_progress("Can’t start yet", msg, DANGER, 0)

    def _poll(self):
        try:
            while True:
                ev = self.q.get_nowait()
                kind = ev[0]
                if kind == "progress":
                    self._progress(*ev[1:])
                elif kind == "models":
                    self._update_model_status()
                elif kind == "done":
                    self._on_done(ev[1], ev[2])
                elif kind == "cancelled":
                    self._set_running(False)
                    self._finish_progress("Cancelled", "Nothing was saved.", MUTED, 0)
                elif kind == "error":
                    self._set_running(False)
                    self._finish_progress("Something went wrong", ev[1], DANGER, 0)
                    self._log_error(ev[2])
                    if self.args.exit_after:
                        self.after(500, self.destroy)
        except queue.Empty:
            pass
        if ctk.get_appearance_mode() != self._mode_seen:
            self._apply_text_theme()
        self.after(80, self._poll)

    def _log_error(self, tb: str):
        try:
            from .env import data_dir
            with open(data_dir() / "error.log", "a", encoding="utf-8") as fh:
                fh.write(time.strftime("%Y-%m-%d %H:%M:%S ") + tb + "\n")
        except Exception:
            pass

    def _on_done(self, tr: Transcript, paths: dict[str, Path]):
        self.transcript, self.saved = tr, paths
        self._set_running(False)
        took = time.time() - self.job_started
        self._finish_progress("✓ Transcript ready", f"{tr.word_count:,} words in {_dur(took)}. "
                              f"Saved as .md, .txt and .srt in Documents\\Transcripts.", SUCCESS)
        for b in (self.b_copy, self.b_save, self.b_open):
            b.configure(state="normal")
        self._render(tr)
        if self.find.get():
            self.find.delete(0, "end")
            self.focus_set()  # lets CTkEntry redraw its placeholder
        self.find_count.configure(text="")
        if self.model_ready is not None:
            threading.Thread(target=self._check_models, daemon=True).start()
        if self.args.screenshot:
            self.after(int(self.args.delay * 1000), self._screenshot)

    # ------------------------------------------------------------------ rendering
    def _clear(self, t: tk.Text):
        t.configure(state="normal")
        t.delete("1.0", "end")

    def _show_welcome(self):
        t = self.texts["Transcript"]
        self._clear(t)
        t.insert("end", "Turn any video into a clean, organised transcript\n", "welcome_big")
        t.insert("end", "Everything runs on this PC.\n\n", "welcome")
        steps = [
            ("1", "Paste a YouTube link, or switch to Video / audio file and choose one."),
            ("2", "Pick a method: Captions is instant; Whisper AI listens to the audio and is far more accurate."),
            ("3", "Press Generate. The transcript is split into chapters and timed paragraphs, and saved "
                  "automatically as Markdown, plain text and subtitles (.srt)."),
        ]
        for n, s in steps:
            t.insert("end", f"{n}   ", ("step", "ts"))
            t.insert("end", s + "\n", "step")
        t.insert("end", "\nTips\n", "h2")
        tips = [
            "Click any timestamp to open the video at that moment.",
            "Words the AI wasn’t sure about are underlined.",
            "The Changes tab lists every automatic correction, so you can check it.",
        ]
        for s in tips:
            t.insert("end", "•  " + s + "\n", "step")
        t.configure(state="disabled")
        for name, msg in (("Changes", "Automatic corrections will be listed here."),
                          ("Details", "Video details will appear here.")):
            x = self.texts[name]
            self._clear(x)
            x.insert("end", msg, "welcome")
            x.configure(state="disabled")

    def _render(self, tr: Transcript):
        m = tr.meta
        self.h_title.configure(text=m.get("title") or "Transcript")
        bits = [b for b in (m.get("channel"), fmt_time(m["duration"]) if m.get("duration") else None,
                            m.get("upload_date"), tr.source_label, f"{tr.word_count:,} words") if b]
        self.h_meta.configure(text="  ·  ".join(bits))

        t = self.texts["Transcript"]
        self._clear(t)
        self.ts_links.clear()
        for tag in [x for x in t.tag_names() if x.startswith("tsl")]:
            t.tag_delete(tag)
        for n in tr.notes:
            t.insert("end", "ⓘ  " + n + "\n", "note")
        if tr.notes:
            t.insert("end", "\n", "note")
        num = 0
        for si, s in enumerate(tr.sections):
            if s.title:
                if not s.title.startswith("Part "):
                    num += 1
                    head = f"{num}.  {s.title}"
                else:
                    head = s.title
                t.insert("end", head + "\n", "h2")
                sub = f"Starts at {fmt_time(s.start)}"
                if s.listed is not None and abs(s.listed - s.start) > 15:
                    sub += f"  ·  chapter list says {fmt_time(s.listed)}"
                t.insert("end", sub + "\n", "sub")
            for pi, p in enumerate(s.paragraphs):
                tag = f"tsl{si}_{pi}"
                self.ts_links[tag] = p.start
                t.insert("end", fmt_time(p.start), ("ts", tag))
                t.insert("end", "   ", "body")
                for wi, w in enumerate(p.words):
                    tags = ("body", "low") if (w.prob is not None and w.prob < 0.4) else ("body",)
                    t.insert("end", w.text, tags)
                    if wi < len(p.words) - 1:
                        t.insert("end", " ", "body")
                t.insert("end", "\n", "body")
                if tr.is_youtube:
                    t.tag_bind(tag, "<Enter>", lambda e, w=t: w.configure(cursor="hand2"))
                    t.tag_bind(tag, "<Leave>", lambda e, w=t: w.configure(cursor="arrow"))
                    t.tag_bind(tag, "<Button-1>", lambda e, s=p.start: webbrowser.open(tr.link_at(s)))
        t.configure(state="disabled")
        t.yview_moveto(0)

        c = self.texts["Changes"]
        self._clear(c)
        if tr.changes:
            c.insert("end", f"{len(tr.changes)} automatic correction(s)\n", "h2")
            c.insert("end", "Nothing is dropped silently: each edit to the raw text is shown here.\n\n", "sub")
            for ch in tr.changes:
                c.insert("end", f"{fmt_time(ch.start):>7}   ", "ts")
                c.insert("end", ch.before, "chg_before")
                c.insert("end", "  →  ", "body")
                c.insert("end", ch.after or "(removed)", "chg_after")
                c.insert("end", f"    {ch.reason}\n", "chg_reason")
        else:
            c.insert("end", "No corrections were needed.", "welcome")
        c.configure(state="disabled")

        d = self.texts["Details"]
        self._clear(d)
        d.insert("end", (m.get("title") or "") + "\n", "h1")
        rows = [("Channel", m.get("channel")), ("Uploaded", m.get("upload_date")),
                ("Length", fmt_time(m["duration"]) if m.get("duration") else None),
                ("Views", f"{m['views']:,}" if m.get("views") else None), ("Link", m.get("url")),
                ("File", m.get("file")), ("Transcript source", tr.source_label),
                ("Saved to", str(self.saved["md"].parent) if self.saved else None)]
        for k, v in rows:
            if v:
                d.insert("end", f"{k}:  ", ("body", "sub"))
                d.insert("end", f"{v}\n", "meta")
        if m.get("chapters"):
            d.insert("end", "\nChapters listed in the description\n", "h2")
            for st, title in m["chapters"]:
                d.insert("end", f"{fmt_time(st):>7}   ", "ts")
                d.insert("end", title + "\n", "body")
        if m.get("description"):
            d.insert("end", "\nDescription\n", "h2")
            d.insert("end", m["description"] + "\n", "meta")
        d.configure(state="disabled")
        self.tabs.set("Transcript")

    # ------------------------------------------------------------------ find
    def _on_find(self, e=None):
        if e is not None and e.keysym == "Return":
            return
        t = self.texts["Transcript"]
        t.tag_remove("hl", "1.0", "end")
        t.tag_remove("hlcur", "1.0", "end")
        q = self.find.get().strip()
        self.matches = []
        if len(q) < 2:
            self.find_count.configure(text="")
            return
        idx = "1.0"
        while True:
            idx = t.search(q, idx, nocase=True, stopindex="end")
            if not idx:
                break
            end = f"{idx}+{len(q)}c"
            t.tag_add("hl", idx, end)
            self.matches.append((idx, end))
            idx = end
        self.match_idx = -1
        self.find_count.configure(text=f"{len(self.matches)} found" if self.matches else "No matches")
        self._next_match()

    def _next_match(self):
        if not getattr(self, "matches", None):
            return
        t = self.texts["Transcript"]
        t.tag_remove("hlcur", "1.0", "end")
        self.match_idx = (self.match_idx + 1) % len(self.matches)
        a, b = self.matches[self.match_idx]
        t.tag_add("hlcur", a, b)
        t.see(a)
        self.find_count.configure(text=f"{self.match_idx + 1} of {len(self.matches)}")

    # ------------------------------------------------------------------ actions
    def _copy(self):
        if not self.transcript:
            return
        from .document import render_text
        self.clipboard_clear()
        self.clipboard_append(render_text(self.transcript))
        self.b_copy.configure(text="✓ Copied")
        self.after(1500, lambda: self.b_copy.configure(text="Copy text"))

    def _save_as(self):
        if not self.transcript:
            return
        from .document import render_markdown, render_srt, render_text, safe_filename
        p = filedialog.asksaveasfilename(
            title="Save transcript", defaultextension=".md",
            initialfile=safe_filename(self.transcript.meta.get("title") or "transcript"),
            filetypes=[("Markdown", "*.md"), ("Plain text", "*.txt"), ("Subtitles (SRT)", "*.srt")])
        if not p:
            return
        ext = Path(p).suffix.lower()
        render = {".txt": render_text, ".srt": render_srt}.get(ext, render_markdown)
        Path(p).write_text(render(self.transcript), encoding="utf-8")
        self.prog_detail.configure(text=f"Saved {Path(p).name}")

    def _open_folder(self):
        target = self.saved["md"] if self.saved else default_output_dir()
        try:
            if self.saved and target.exists():
                subprocess.Popen(["explorer", "/select,", str(target)])
            else:
                default_output_dir().mkdir(parents=True, exist_ok=True)
                os.startfile(default_output_dir())  # noqa: S606
        except Exception:
            pass

    # ------------------------------------------------------------------ testing hooks
    def _screenshot(self):
        try:
            from PIL import ImageGrab
            self.attributes("-topmost", True)
            self.update()
            x, y = self.winfo_rootx(), self.winfo_rooty()
            w, h = self.winfo_width(), self.winfo_height()
            ImageGrab.grab(bbox=(x, y, x + w, y + h), all_screens=True).save(self.args.screenshot)
            self.attributes("-topmost", False)
        except Exception:
            self._log_error(traceback.format_exc())
        if self.args.exit_after:
            self.after(300, self.destroy)


def _work_area(win) -> tuple[float, float, float, float]:
    """Usable desktop area (excluding the taskbar) in CustomTkinter's logical units."""
    sc = ctk.ScalingTracker.get_window_scaling(win)
    if os.name == "nt":
        try:
            import ctypes
            from ctypes import wintypes
            r = wintypes.RECT()
            if ctypes.windll.user32.SystemParametersInfoW(0x30, 0, ctypes.byref(r), 0):  # SPI_GETWORKAREA
                return r.left / sc, r.top / sc, (r.right - r.left) / sc, (r.bottom - r.top) / sc
        except Exception:
            pass
    return 0, 0, win.winfo_screenwidth(), win.winfo_screenheight() - 48


def _dur(s: float) -> str:
    s = int(s)
    return f"{s} s" if s < 60 else f"{s // 60} min {s % 60:02d} s"


def _friendly(e: Exception) -> str:
    msg = str(e).strip()
    low = msg.lower()
    if "private video" in low:
        return "This video is private, so it can’t be read."
    if "sign in to confirm your age" in low or "age-restricted" in low:
        return "This video is age-restricted and needs a signed-in account; it can’t be read."
    if "video unavailable" in low or "this video is not available" in low:
        return "YouTube says this video is unavailable."
    if "unsupported url" in low or "is not a valid url" in low:
        return "That doesn’t look like a video link."
    if "getaddrinfo" in low or "urlopen error" in low or "connection" in low and "error" in low:
        return "Couldn’t reach the internet. Check your connection and try again."
    if "no speech" in low:
        return "No speech was found in this video."
    if "no audio track" in low:
        return msg
    msg = msg.replace("ERROR: ", "")
    return msg if len(msg) < 300 else msg[:300] + "…"


def main(argv: list[str]) -> int:
    prepare_runtime()
    ap = argparse.ArgumentParser()
    ap.add_argument("--demo", help="testing: fill in this source and start immediately")
    ap.add_argument("--method", default=None, choices=["captions", "whisper"])
    ap.add_argument("--theme", default="system", choices=["system", "light", "dark"])
    ap.add_argument("--terms", default="", help="testing: pre-fill the extra names field")
    ap.add_argument("--screenshot", help="testing: save a screenshot of the window (after the demo job)")
    ap.add_argument("--delay", type=float, default=1.5)
    ap.add_argument("--exit-after", action="store_true")
    args, _ = ap.parse_known_args(argv)

    ctk.set_appearance_mode(args.theme)
    ctk.set_default_color_theme("blue")
    app = App(args)
    try:
        import pyi_splash  # type: ignore
        pyi_splash.close()
    except Exception:
        pass
    if args.theme != "system":
        app.theme_menu.set(args.theme.capitalize())
    if args.terms:
        app.terms.insert(0, args.terms)
    if args.demo:
        src = args.demo
        if src.lower().startswith(("http://", "https://")):
            app.url_entry.insert(0, src)
        else:
            app.seg_source.set("Video / audio file")
            app._on_source("Video / audio file")
            app._set_file(Path(src))
        if args.method:
            app.seg_method.set("Whisper AI" if args.method == "whisper" else "Captions")
            app._on_method(app.seg_method.get())
        app.after(600, app._start)
    elif args.screenshot:
        app.after(int(args.delay * 1000), app._screenshot)
    app.mainloop()
    return 0
