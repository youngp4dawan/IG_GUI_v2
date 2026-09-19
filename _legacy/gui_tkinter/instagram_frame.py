"""Instagram tab — UI utama (dengan cache shortcode support)."""
import os
import queue
import threading
import time

import customtkinter as ctk
from tkinter import messagebox

from instagram.config import InstagramConfig
from instagram.extractor import InstagramExtractor
from instagram.downloader import InstagramDownloader
from shared.paths import DOWNLOAD_INSTAGRAM, DATA_INSTAGRAM_LINKS
from shared.utils import ensure_dirs
from shared.config import load_json
from instagram.constants import DOWNLOAD_DELAY, DEFAULT_WORKERS


class InstagramFrame(ctk.CTkFrame):
    def __init__(self, master, app):
        super().__init__(master, fg_color="transparent")
        self.app = app
        self.worker_thread = None
        self.stop_event = threading.Event()
        self.event_queue = queue.Queue()

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(3, weight=1)

        self._build_input_section()
        self._build_options_section()
        self._build_controls()
        self._build_progress_and_log()

        self._poll_events()

    # ─── UI BUILD ─────────────────────────────────────────
    def _build_input_section(self):
        frame = ctk.CTkFrame(self)
        frame.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        frame.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            frame, text="📝 Usernames (satu per baris, tanpa @)",
            font=ctk.CTkFont(size=13, weight="bold"),
        ).grid(row=0, column=0, padx=15, pady=(12, 5), sticky="w")

        self.usernames_text = ctk.CTkTextbox(frame, height=100)
        self.usernames_text.grid(row=1, column=0, padx=15, pady=(0, 12), sticky="ew")
        self.usernames_text.insert("1.0", "example_username")

        # ─── Mode ─────────────────────────────────────────
        mode_frame = ctk.CTkFrame(frame, fg_color="transparent")
        mode_frame.grid(row=2, column=0, padx=15, pady=(0, 12), sticky="ew")

        ctk.CTkLabel(
            mode_frame, text="Mode:",
            font=ctk.CTkFont(size=13, weight="bold"),
        ).pack(side="left", padx=(0, 12))

        self.mode_var = ctk.StringVar(value="both")

        ctk.CTkRadioButton(
            mode_frame, text="Download",
            variable=self.mode_var, value="both",
        ).pack(side="left", padx=8)

        # ─── Fitur tambahan (di-comment, siap diaktifkan nanti) ───
        # ctk.CTkRadioButton(
        #     mode_frame, text="Extract only",
        #     variable=self.mode_var, value="extract",
        # ).pack(side="left", padx=8)
        #
        # ctk.CTkRadioButton(
        #     mode_frame, text="Download from existing",
        #     variable=self.mode_var, value="download",
        # ).pack(side="left", padx=8)

    def _build_options_section(self):
        frame = ctk.CTkFrame(self)
        frame.grid(row=1, column=0, sticky="ew", pady=(0, 10))
        frame.grid_columnconfigure((0, 1), weight=1)

        ctk.CTkLabel(
            frame, text="⚙️ Options",
            font=ctk.CTkFont(size=13, weight="bold"),
        ).grid(row=0, column=0, padx=15, pady=(12, 8), sticky="w")

        # Checkboxes
        self.opt_skip_reels = ctk.BooleanVar(value=True)
        ctk.CTkCheckBox(
            frame, text="Skip reels if main complete",
            variable=self.opt_skip_reels,
        ).grid(row=1, column=0, padx=15, pady=4, sticky="w")

        self.opt_hd = ctk.BooleanVar(value=True)
        ctk.CTkCheckBox(
            frame, text="HD video (via yt-dlp)",
            variable=self.opt_hd,
        ).grid(row=2, column=0, padx=15, pady=4, sticky="w")

        self.opt_headless = ctk.BooleanVar(value=True)
        ctk.CTkCheckBox(
            frame, text="Headless browser (invisible)",
            variable=self.opt_headless,
        ).grid(row=3, column=0, padx=15, pady=(4, 15), sticky="w")

        # ── Cache checkbox (BARU) ──
        self.opt_use_cache = ctk.BooleanVar(value=True)
        ctk.CTkCheckBox(
            frame, text="Gunakan cache shortcode (skip scan jika lengkap)",
            variable=self.opt_use_cache,
        ).grid(row=4, column=0, padx=15, pady=(0, 15), sticky="w")

        # Delay + Workers
        delay_frame = ctk.CTkFrame(frame, fg_color="transparent")
        delay_frame.grid(row=1, column=1, padx=15, pady=4, sticky="w")
        ctk.CTkLabel(delay_frame, text="Download delay (s):").pack(side="left")
        self.opt_delay = ctk.CTkEntry(delay_frame, width=60)
        self.opt_delay.insert(0, str(DOWNLOAD_DELAY))
        self.opt_delay.pack(side="left", padx=(8, 0))

        workers_frame = ctk.CTkFrame(frame, fg_color="transparent")
        workers_frame.grid(row=2, column=1, padx=15, pady=4, sticky="w")
        ctk.CTkLabel(workers_frame, text="Parallel workers:").pack(side="left")
        self.opt_workers = ctk.CTkEntry(workers_frame, width=60)
        self.opt_workers.insert(0, str(DEFAULT_WORKERS))
        self.opt_workers.pack(side="left", padx=(8, 0))

    def _build_controls(self):
        frame = ctk.CTkFrame(self, fg_color="transparent")
        frame.grid(row=2, column=0, sticky="ew", pady=(0, 10))

        self.btn_start = ctk.CTkButton(
            frame, text="▶  START", width=140, height=42,
            font=ctk.CTkFont(size=14, weight="bold"),
            fg_color="#2E7D32", hover_color="#1B5E20",
            command=self._on_start,
        )
        self.btn_start.pack(side="left", padx=(0, 10))

        self.btn_stop = ctk.CTkButton(
            frame, text="⏸  STOP", width=140, height=42,
            font=ctk.CTkFont(size=14, weight="bold"),
            fg_color="#C62828", hover_color="#B71C1C",
            state="disabled",
            command=self._on_stop,
        )
        self.btn_stop.pack(side="left", padx=(0, 10))

        self.btn_open_folder = ctk.CTkButton(
            frame, text="📁 Open Downloads", width=160, height=42,
            fg_color="#37474F", hover_color="#263238",
            command=self._open_download_folder,
        )
        self.btn_open_folder.pack(side="left", padx=(0, 10))

        self.btn_clear_log = ctk.CTkButton(
            frame, text="🗑  Clear Log", width=120, height=42,
            fg_color="#455A64", hover_color="#37474F",
            command=self._clear_log,
        )
        self.btn_clear_log.pack(side="left")

    def _build_progress_and_log(self):
        frame = ctk.CTkFrame(self)
        frame.grid(row=3, column=0, sticky="nsew")
        frame.grid_columnconfigure(0, weight=1)
        frame.grid_rowconfigure(2, weight=1)

        prog_frame = ctk.CTkFrame(frame, fg_color="transparent")
        prog_frame.grid(row=0, column=0, sticky="ew", padx=15, pady=(12, 6))
        prog_frame.grid_columnconfigure(0, weight=1)

        self.progress_bar = ctk.CTkProgressBar(prog_frame, height=18)
        self.progress_bar.grid(row=0, column=0, sticky="ew")
        self.progress_bar.set(0)

        self.progress_label = ctk.CTkLabel(
            prog_frame, text="Idle", anchor="w", font=ctk.CTkFont(size=12),
        )
        self.progress_label.grid(row=1, column=0, sticky="w", pady=(4, 0))

        ctk.CTkLabel(
            frame, text="📋 Log",
            font=ctk.CTkFont(size=13, weight="bold"),
        ).grid(row=1, column=0, padx=15, pady=(6, 4), sticky="w")

        self.log_text = ctk.CTkTextbox(
            frame, font=ctk.CTkFont(family="Consolas", size=11),
        )
        self.log_text.grid(row=2, column=0, padx=15, pady=(0, 15), sticky="nsew")
        self.log_text.configure(state="disabled")

    # ─── ACTIONS ──────────────────────────────────────────
    def _open_download_folder(self):
        ensure_dirs(DOWNLOAD_INSTAGRAM)
        try:
            os.startfile(DOWNLOAD_INSTAGRAM)
        except Exception:
            pass

    def _clear_log(self):
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.configure(state="disabled")

    def _on_start(self):
        config = InstagramConfig()
        if not config.is_valid():
            messagebox.showerror(
                "Config Error",
                "Cookies belum diisi!\n\nBuka tab ⚙️ Settings → isi sessionid, csrftoken, ds_user_id",
            )
            self.app.tabview.set("⚙️ Settings")
            return

        raw = self.usernames_text.get("1.0", "end").strip()
        usernames = [u.strip().lstrip("@") for u in raw.splitlines() if u.strip()]
        usernames = [u for u in usernames if u != "example_username"]

        if not usernames:
            messagebox.showerror("Input Error", "Masukkan minimal 1 username")
            return

        mode = self.mode_var.get()

        msg = f"Jalankan untuk {len(usernames)} username dengan mode: {mode}?"
        if not messagebox.askyesno("Confirm", msg):
            return

        self._disable_controls()
        self.stop_event.clear()
        self.progress_bar.set(0)
        self._append_log("=" * 60)
        self._append_log(f"🚀 Start: {len(usernames)} user, mode={mode}")
        self._append_log("=" * 60)

        self.worker_thread = threading.Thread(
            target=self._worker,
            args=(usernames, mode, config),
            daemon=True,
        )
        self.worker_thread.start()

    def _on_stop(self):
        if self.worker_thread and self.worker_thread.is_alive():
            self.stop_event.set()
            self._append_log("⏸️ Stop requested...")
            self.btn_stop.configure(state="disabled", text="⏸ Stopping...")

    def _disable_controls(self):
        self.btn_start.configure(state="disabled", text="⏳ Running...")
        self.btn_stop.configure(state="normal", text="⏸  STOP")

    def _enable_controls(self):
        self.btn_start.configure(state="normal", text="▶  START")
        self.btn_stop.configure(state="disabled", text="⏸  STOP")

    # ─── WORKER ───────────────────────────────────────────
    def _worker(self, usernames, mode, config):
        try:
            driver = None
            extractor = None
            use_cache = bool(self.opt_use_cache.get())

            # Baca delay & workers dari GUI
            try:
                delay = float(self.opt_delay.get())
            except (ValueError, AttributeError):
                delay = DOWNLOAD_DELAY

            try:
                workers = int(self.opt_workers.get())
                workers = max(1, min(workers, 8))   # clamp 1..8
            except (ValueError, AttributeError):
                workers = DEFAULT_WORKERS

            if mode in ("both", "extract"):
                self._emit("log", "🌐 Membuka browser...")
                self._emit("status", "🌐 Membuka browser...")
                driver = InstagramExtractor.create_driver(headless=self.opt_headless.get())
                InstagramExtractor.setup_with_cookies(driver, config)
                self._emit("log", "✅ Browser siap")
                extractor = InstagramExtractor(
                    driver,
                    stop_event=self.stop_event,
                    on_log=lambda m: self._emit("log", m),
                    on_progress=lambda c, t, m: self._emit("progress", c, t, m),
                )

            total_users = len(usernames)

            for i, username in enumerate(usernames, 1):
                if self.stop_event.is_set():
                    break

                self._emit("log", f"\n{'='*60}")
                self._emit("log", f"👤 [{i}/{total_users}] @{username}")
                self._emit("log", "=" * 60)

                # ── Extract phase ──
                if mode in ("both", "extract"):
                    # 1. Load cache
                    cached = []
                    if use_cache:
                        cached = InstagramExtractor.load_cached_shortcodes(username)
                        if cached:
                            self._emit("log", f"📚 Cache: {len(cached)} shortcode lama")
                        else:
                            self._emit("log", "📚 Cache: kosong (scan dari nol)")
                    else:
                        self._emit("log", "📚 Cache dimatikan — scan dari nol")

                    self._emit("status", f"📥 Extracting @{username}...")
                    result = extractor.extract_user(username, cached_codes=cached)

                    if result["success"]:
                        InstagramExtractor.save_results(
                            username, result["links"], result.get("stats"),
                        )
                        new_found = result.get("stats", {}).get("new_found", 0)
                        self._emit(
                            "log",
                            f"💾 Shortcode tersimpan: {result['count']} post "
                            f"(+{new_found} baru)"
                        )
                    else:
                        self._emit("log", f"❌ Extract gagal: {result.get('error')}")
                        continue

                # ── Download phase ──
                if mode in ("both", "download"):
                    json_file = os.path.join(
                        DATA_INSTAGRAM_LINKS, f"@{username}",
                        f"{username}_post_links.json"
                    )
                    data = load_json(json_file)
                    shortcodes = (data or {}).get("shortcodes", [])

                    if not shortcodes:
                        self._emit("log", f"⚠️  @{username}: tidak ada shortcode. Extract dulu.")
                        continue

                    self._emit("status", f"📥 Downloading @{username}...")
                    self._emit("log", f"⚡ Workers: {workers}, delay: {delay}s")

                    InstagramDownloader.download_user(
                        shortcodes, username, config,
                        stop_event=self.stop_event,
                        on_log=lambda m: self._emit("log", m),
                        on_progress=lambda c, t, m: self._emit("progress", c, t, m),
                        max_workers=workers,
                        download_delay=delay,
                    )

            if driver:
                try:
                    driver.quit()
                except Exception:
                    pass

            self._emit(
                "done",
                True,
                "Semua selesai!" if not self.stop_event.is_set() else "Dihentikan",
            )

        except Exception as e:
            self._emit("done", False, f"Error: {str(e)[:200]}")
            import traceback
            self._emit("log", traceback.format_exc())

    # ─── EVENT QUEUE ──────────────────────────────────────
    def _emit(self, event_type, *args):
        self.event_queue.put((event_type, args))

    def _poll_events(self):
        try:
            while True:
                ev, args = self.event_queue.get_nowait()
                if ev == "log":
                    self._append_log(args[0])
                elif ev == "progress":
                    cur, tot, msg = args
                    if tot > 0:
                        self.progress_bar.set(min(cur / tot, 1.0))
                    self.progress_label.configure(text=f"{msg} — {cur}/{tot}")
                elif ev == "status":
                    self.app.set_status(f"⏳ {args[0]}")
                elif ev == "done":
                    success, msg = args
                    self._enable_controls()
                    self.progress_label.configure(text=msg)
                    self.app.set_status(f"{'✅' if success else '❌'} {msg}")
                    self._append_log(f"\n{'='*60}")
                    self._append_log(f"{'🎉' if success else '❌'} {msg}")
                    self._append_log("=" * 60)
        except queue.Empty:
            pass

        self.after(100, self._poll_events)

    def _append_log(self, message):
        ts = time.strftime("%H:%M:%S")
        line = f"[{ts}] {message}\n"
        self.log_text.configure(state="normal")
        self.log_text.insert("end", line)
        self.log_text.see("end")
        self.log_text.configure(state="disabled")