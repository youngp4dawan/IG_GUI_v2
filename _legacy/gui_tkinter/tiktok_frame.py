"""TikTok tab (dengan multi-user support — gaya simpel)."""
import os
import re
import queue
import threading
import time
import customtkinter as ctk
from tkinter import messagebox
from shared.paths import DOWNLOAD_TIKTOK, ensure_all
from tiktok.config import TikTokConfig
from tiktok.downloader import TikTokDownloader, YTDLP_AVAILABLE


class TikTokFrame(ctk.CTkFrame):
    _PLACEHOLDER = "example_username"

    def __init__(self, master, app):
        super().__init__(master, fg_color="transparent")
        self.app = app
        self.thread = None
        self.stop_event = threading.Event()
        self.events = queue.Queue()
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(3, weight=1)
        self._build_input()
        self._build_options()
        self._build_controls()
        self._build_progress()
        self._poll()

    # ══════════════════════════════════════════════════════
    # INPUT (multi-user — gaya simpel)
    # ══════════════════════════════════════════════════════
    def _build_input(self):
        f = ctk.CTkFrame(self)
        f.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        f.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            f, text="📋  Usernames (satu per baris, tanpa @)",
            font=ctk.CTkFont(size=13, weight="bold")
        ).grid(row=0, column=0, padx=15, pady=(12, 6), sticky="w")

        self.input = ctk.CTkTextbox(
            f, height=140, font=ctk.CTkFont(size=12),
            wrap="none", activate_scrollbars=True,
        )
        self.input.grid(row=1, column=0, padx=15, pady=(0, 12), sticky="ew")

        # placeholder ala example_username
        self._set_placeholder()
        self.input.bind("<FocusIn>", self._on_focus_in)
        self.input.bind("<FocusOut>", self._on_focus_out)
        self.input.bind("<Control-Return>", lambda e: (self._start(), "break"))

    # ── placeholder helpers ──
    def _set_placeholder(self):
        self._placeholder_active = True
        self.input.delete("1.0", "end")
        self.input.insert("1.0", self._PLACEHOLDER)
        self.input.configure(text_color="gray")

    def _on_focus_in(self, _e=None):
        if getattr(self, "_placeholder_active", False):
            self.input.delete("1.0", "end")
            self.input.configure(text_color=("black", "white"))
            self._placeholder_active = False

    def _on_focus_out(self, _e=None):
        content = self.input.get("1.0", "end").strip()
        if not content:
            self._set_placeholder()

    def _get_input_text(self):
        if getattr(self, "_placeholder_active", False):
            return ""
        raw = self.input.get("1.0", "end").strip()
        if not raw:
            return ""
        # tiap token → pastikan ada @ kalau bukan URL
        parts = re.split(r"[\n,;|\s]+", raw)
        fixed = []
        for p in parts:
            p = p.strip()
            if not p:
                continue
            if p.startswith(("http://", "https://", "@")):
                fixed.append(p)
            else:
                fixed.append("@" + p)
        return " ".join(fixed)

    # ══════════════════════════════════════════════════════
    # OPTIONS
    # ══════════════════════════════════════════════════════
    def _build_options(self):
        f = ctk.CTkFrame(self)
        f.grid(row=1, column=0, sticky="ew", pady=(0, 10))
        ctk.CTkLabel(f, text="Options", font=ctk.CTkFont(size=13, weight="bold")).grid(
            row=0, column=0, padx=15, pady=(12, 8), sticky="w")
        o = ctk.CTkFrame(f, fg_color="transparent")
        o.grid(row=1, column=0, padx=15, pady=(0, 15), sticky="ew")
        ctk.CTkLabel(o, text="Quality:").pack(side="left", padx=(0, 8))
        self.q = ctk.StringVar(value="hd")
        ctk.CTkRadioButton(o, text="HD (1080p, no watermark)",
                            variable=self.q, value="hd").pack(side="left", padx=8)
        ctk.CTkRadioButton(o, text="SD (720p)",
                            variable=self.q, value="sd").pack(side="left", padx=8)

    # ══════════════════════════════════════════════════════
    # CONTROLS
    # ══════════════════════════════════════════════════════
    def _build_controls(self):
        f = ctk.CTkFrame(self, fg_color="transparent")
        f.grid(row=2, column=0, sticky="ew", pady=(0, 10))
        self.btn_start = ctk.CTkButton(f, text="DOWNLOAD", width=160, height=42,
                                        font=ctk.CTkFont(size=14, weight="bold"),
                                        fg_color="#E91E63", hover_color="#AD1457",
                                        command=self._start)
        self.btn_start.pack(side="left", padx=(0, 10))
        self.btn_stop = ctk.CTkButton(f, text="STOP", width=140, height=42,
                                       font=ctk.CTkFont(size=14, weight="bold"),
                                       fg_color="#C62828", hover_color="#B71C1C",
                                       state="disabled", command=self._stop)
        self.btn_stop.pack(side="left", padx=(0, 10))
        ctk.CTkButton(f, text="Open Downloads", width=160, height=42,
                      fg_color="#37474F", hover_color="#263238",
                      command=self._open_folder).pack(side="left", padx=(0, 10))
        ctk.CTkButton(f, text="Clear Log", width=120, height=42,
                      fg_color="#455A64", hover_color="#37474F",
                      command=self._clear).pack(side="left")

    # ══════════════════════════════════════════════════════
    # PROGRESS + LOG
    # ══════════════════════════════════════════════════════
    def _build_progress(self):
        f = ctk.CTkFrame(self)
        f.grid(row=3, column=0, sticky="nsew")
        f.grid_columnconfigure(0, weight=1)
        f.grid_rowconfigure(2, weight=1)
        p = ctk.CTkFrame(f, fg_color="transparent")
        p.grid(row=0, column=0, sticky="ew", padx=15, pady=(12, 6))
        p.grid_columnconfigure(0, weight=1)
        self.bar = ctk.CTkProgressBar(p, height=18)
        self.bar.grid(row=0, column=0, sticky="ew")
        self.bar.set(0)
        self.label = ctk.CTkLabel(p, text="Idle", anchor="w", font=ctk.CTkFont(size=12))
        self.label.grid(row=1, column=0, sticky="w", pady=(4, 0))
        ctk.CTkLabel(f, text="Log", font=ctk.CTkFont(size=13, weight="bold")).grid(
            row=1, column=0, padx=15, pady=(6, 4), sticky="w")
        self.log = ctk.CTkTextbox(f, font=ctk.CTkFont(family="Consolas", size=11))
        self.log.grid(row=2, column=0, padx=15, pady=(0, 15), sticky="nsew")
        self.log.configure(state="disabled")

    # ══════════════════════════════════════════════════════
    # ACTIONS
    # ══════════════════════════════════════════════════════
    def _open_folder(self):
        ensure_all()
        try:
            os.startfile(DOWNLOAD_TIKTOK)
        except Exception:
            pass

    def _clear(self):
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.configure(state="disabled")

    def _start(self):
        if not YTDLP_AVAILABLE:
            messagebox.showerror("Missing yt-dlp",
                "yt-dlp belum diinstall.\npip install yt-dlp curl_cffi")
            return

        raw = self._get_input_text()
        if not raw:
            messagebox.showerror("Error", "Masukkan minimal 1 username atau URL")
            return

        urls = TikTokDownloader.parse_multiple(raw)
        if not urls:
            messagebox.showerror("Error", "Tidak ada username/URL valid terdeteksi")
            return

        cfg = TikTokConfig()
        if not cfg.is_valid():
            messagebox.showerror("Cookies Error",
                "Cookies TikTok belum diisi!\nBuka Settings -> TikTok")
            self.app.tabview.set("Settings")
            return

        # lock UI
        self.btn_start.configure(state="disabled", text="Running...")
        self.btn_stop.configure(state="normal", text="STOP")
        self.stop_event.clear()
        self.bar.set(0)
        self.label.configure(text=f"0 / {len(urls)} target")

        self._log("=" * 55)
        self._log(f"🎯 Multi-user mode: {len(urls)} target")
        for i, u in enumerate(urls, 1):
            self._log(f"   {i}. {u}")
        self._log("=" * 55)

        self.thread = threading.Thread(
            target=self._worker, args=(raw,), daemon=True
        )
        self.thread.start()

    def _stop(self):
        if self.thread and self.thread.is_alive():
            self.stop_event.set()
            self._log("⏸️  Stop requested...")

    def _worker(self, raw_text):
        try:
            quality = self.q.get()
            self._emit("status", f"Downloading TikTok ({quality})...")
            ok = TikTokDownloader.download_multiple(
                raw_text,
                quality=quality,
                stop_event=self.stop_event,
                on_log=lambda m: self._emit("log", m),
                on_progress=lambda p, m: self._emit("progress", p, m),
            )
            self._emit("done", ok, "Selesai!" if ok else "Gagal")
        except Exception as e:
            self._emit("done", False, str(e)[:150])

    # ══════════════════════════════════════════════════════
    # EVENT PUMP
    # ══════════════════════════════════════════════════════
    def _emit(self, t, *a):
        self.events.put((t, a))

    def _poll(self):
        try:
            while True:
                t, a = self.events.get_nowait()
                if t == "log":
                    self._log(a[0])
                elif t == "progress":
                    p, m = a
                    self.bar.set(max(0.0, min(p, 1.0)))
                    self.label.configure(text=m)
                elif t == "status":
                    self.app.set_status(a[0])
                elif t == "done":
                    ok, m = a
                    self.btn_start.configure(state="normal", text="DOWNLOAD")
                    self.btn_stop.configure(state="disabled", text="STOP")
                    self.label.configure(text=m)
                    self.app.set_status(("OK: " if ok else "FAIL: ") + m)
                    self._log("=" * 55)
                    self._log(m)
                    self._log("=" * 55)
        except queue.Empty:
            pass
        self.after(100, self._poll)

    def _log(self, m):
        ts = time.strftime("%H:%M:%S")
        self.log.configure(state="normal")
        self.log.insert("end", f"[{ts}] {m}\n")
        self.log.see("end")
        self.log.configure(state="disabled")