"""
YouTube Upload Tab — Dashboard Style
=====================================
Layout:
  ┌─────────────────────────────────────────────────┐
  │ Top: Source toolbar                             │
  ├────────────────────────┬────────────────────────┤
  │ Video Grid (left)      │ Preview Panel (right)  │
  │ 3 columns              │ 400x300 thumbnail      │
  │ Checkbox overlay       │ Info lengkap           │
  ├────────────────────────┴────────────────────────┤
  │ Bottom: Upload settings + Progress + Log        │
  └─────────────────────────────────────────────────┘

Fitur:
- Force re-upload checkbox (ignore upload history)
- Persistent Chrome debug session (tidak tutup antar upload)
- Grid view + preview panel
- Drag & drop support
"""
import os
import queue
import socket
import threading
import time
import subprocess
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

import customtkinter as ctk
from tkinter import messagebox

try:
    from PIL import Image
    from customtkinter import CTkImage
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

try:
    from tkinterdnd2 import DND_FILES
    DND_AVAILABLE = True
except ImportError:
    DND_AVAILABLE = False

from shared.paths import DOWNLOAD_INSTAGRAM, DOWNLOAD_TIKTOK, ensure_all
from shared.thumbnails import extract_thumbnail
from youtube.config import YouTubeConfig
from youtube.uploader import YouTubeUploader
from youtube.profile_import import (
    list_chrome_profiles, get_chrome_user_data_path,
    save_profile_to_config, get_saved_profile, validate_profile,
    is_chrome_running, kill_chrome,
)


VIDEO_EXTS = (".mp4", ".mov", ".webm", ".mkv", ".avi", ".flv", ".wmv")
GRID_COLS = 3
THUMB_SIZE = 150
PREVIEW_SIZE = (400, 300)


def _human_size(n):
    for unit in ["B", "KB", "MB", "GB"]:
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def _clean_name(filename):
    import re
    stem = Path(filename).stem
    cleaned = re.sub(r'^\d{15,}_', '', stem).strip()
    return cleaned if cleaned else stem


def _get_chrome_exe():
    for c in [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        os.path.expanduser(r"~\AppData\Local\Google\Chrome\Application\chrome.exe"),
    ]:
        if os.path.exists(c):
            return c
    return None


def scan_users(platform):
    base = DOWNLOAD_INSTAGRAM if platform == "instagram" else DOWNLOAD_TIKTOK
    if not os.path.exists(base):
        return []
    return sorted([d for d in os.listdir(base)
                   if os.path.isdir(os.path.join(base, d))])


def scan_videos(platform, username):
    base = DOWNLOAD_INSTAGRAM if platform == "instagram" else DOWNLOAD_TIKTOK
    user_folder = os.path.join(base, username)
    if not os.path.exists(user_folder):
        return []
    videos = []
    for root, dirs, files in os.walk(user_folder):
        for f in files:
            if f.lower().endswith(VIDEO_EXTS):
                path = os.path.join(root, f)
                try:
                    size = os.path.getsize(path)
                except Exception:
                    size = 0
                videos.append({
                    "path": path, "name": f,
                    "size": size, "size_str": _human_size(size),
                })
    return sorted(videos, key=lambda v: v["name"])


class YouTubeFrame(ctk.CTkFrame):
    def __init__(self, master, app):
        super().__init__(master, fg_color="transparent")
        self.app = app
        self.thread = None
        self.stop_event = threading.Event()
        self.events = queue.Queue()

        # State
        self.current_platform = "instagram"
        self.current_user = None
        self.all_videos = []
        self.selected_video = None
        self.selected_index = None
        self.video_checkboxes = {}
        self.video_widgets = {}
        self.dropped_mode = False
        self.chrome_profiles = []

        # ⚡ Force re-upload flag
        self._force_reupload_var = ctk.BooleanVar(value=False)

        # Thumbnails
        self._thumb_executor = ThreadPoolExecutor(max_workers=4)
        self._thumb_refs = []
        self._load_gen = 0

        # Layout
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        self._build_top_toolbar()
        self._build_main_content()
        self._build_bottom_panel()

        self._poll()
        self._load_users()
        self._load_chrome_profiles()
        self._update_profile_status()

    # ══════════════════════════════════════════════════════
    # TOP TOOLBAR
    # ══════════════════════════════════════════════════════
    def _build_top_toolbar(self):
        f = ctk.CTkFrame(self, fg_color="#1a2332", corner_radius=10)
        f.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        f.grid_columnconfigure(5, weight=1)

        ctk.CTkLabel(f, text="Platform:",
                     font=ctk.CTkFont(size=12, weight="bold")).grid(
            row=0, column=0, padx=(15, 8), pady=12, sticky="w")

        self.platform_var = ctk.StringVar(value="instagram")
        pf = ctk.CTkFrame(f, fg_color="transparent")
        pf.grid(row=0, column=1, pady=12, sticky="w")
        ctk.CTkRadioButton(pf, text="Instagram", width=100,
                           variable=self.platform_var, value="instagram",
                           command=self._on_platform_change).pack(side="left", padx=(0, 8))
        ctk.CTkRadioButton(pf, text="TikTok", width=80,
                           variable=self.platform_var, value="tiktok",
                           command=self._on_platform_change).pack(side="left")

        ctk.CTkLabel(f, text="User:",
                     font=ctk.CTkFont(size=12, weight="bold")).grid(
            row=0, column=2, padx=(15, 8), pady=12, sticky="w")

        self.user_var = ctk.StringVar(value="(belum ada user)")
        self.user_menu = ctk.CTkOptionMenu(
            f, variable=self.user_var, values=["(belum ada user)"],
            command=self._on_user_change, width=200,
        )
        self.user_menu.grid(row=0, column=3, padx=(0, 8), pady=12, sticky="w")

        ctk.CTkButton(f, text="🔄 Refresh", width=100, height=30,
                       fg_color="#37474F", hover_color="#263238",
                       command=self._load_users).grid(
            row=0, column=4, padx=(0, 8), pady=12)

        self.profile_indicator = ctk.CTkLabel(
            f, text="⏳",
            font=ctk.CTkFont(size=11),
            text_color="gray",
        )
        self.profile_indicator.grid(row=0, column=5, padx=(0, 15), pady=12, sticky="e")

        self.profile_indicator.bind("<Button-1>", lambda e: self._show_profile_dialog())

    # ══════════════════════════════════════════════════════
    # MAIN CONTENT
    # ══════════════════════════════════════════════════════
    def _build_main_content(self):
        f = ctk.CTkFrame(self, fg_color="transparent")
        f.grid(row=1, column=0, sticky="nsew")
        f.grid_columnconfigure(0, weight=3)
        f.grid_columnconfigure(1, weight=2)
        f.grid_rowconfigure(0, weight=1)

        # ─── LEFT: Video Grid ──────────────────────────
        left = ctk.CTkFrame(f, fg_color="#1a2332", corner_radius=10)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        left.grid_columnconfigure(0, weight=1)
        left.grid_rowconfigure(1, weight=1)

        h = ctk.CTkFrame(left, fg_color="transparent")
        h.grid(row=0, column=0, sticky="ew", padx=12, pady=(12, 6))
        h.grid_columnconfigure(0, weight=1)

        self.count_label = ctk.CTkLabel(
            h, text="📋 0 video",
            font=ctk.CTkFont(size=13, weight="bold"), anchor="w",
        )
        self.count_label.grid(row=0, column=0, sticky="w")

        btn_frame = ctk.CTkFrame(h, fg_color="transparent")
        btn_frame.grid(row=0, column=1, sticky="e")

        ctk.CTkButton(btn_frame, text="✅ All", width=65, height=26,
                       fg_color="#2E7D32", hover_color="#1B5E20",
                       font=ctk.CTkFont(size=11),
                       command=self._select_all).pack(side="left", padx=2)
        ctk.CTkButton(btn_frame, text="❌ None", width=70, height=26,
                       fg_color="#455A64", hover_color="#37474F",
                       font=ctk.CTkFont(size=11),
                       command=self._deselect_all).pack(side="left", padx=2)

        self.video_scroll = ctk.CTkScrollableFrame(left, fg_color="#0f1620")
        self.video_scroll.grid(row=1, column=0, sticky="nsew", padx=12, pady=(0, 12))

        for c in range(GRID_COLS):
            self.video_scroll.grid_columnconfigure(c, weight=1)

        if DND_AVAILABLE:
            try:
                self.video_scroll.drop_target_register(DND_FILES)
                self.video_scroll.dnd_bind('<<Drop>>', self._on_file_drop)
            except Exception:
                pass

        # ─── RIGHT: Preview Panel ──────────────────────
        right = ctk.CTkFrame(f, fg_color="#1a2332", corner_radius=10)
        right.grid(row=0, column=1, sticky="nsew")
        right.grid_columnconfigure(0, weight=1)
        right.grid_rowconfigure(1, weight=1)

        ctk.CTkLabel(right, text="📺  Preview",
                     font=ctk.CTkFont(size=13, weight="bold"),
                     anchor="w").grid(row=0, column=0, sticky="ew", padx=12, pady=(12, 6))

        preview_content = ctk.CTkFrame(right, fg_color="#0f1620", corner_radius=8)
        preview_content.grid(row=1, column=0, sticky="nsew", padx=12, pady=(0, 12))
        preview_content.grid_columnconfigure(0, weight=1)
        preview_content.grid_rowconfigure(0, weight=1)

        self.preview_img_label = ctk.CTkLabel(
            preview_content,
            text="\n\n🖼️\n\nKlik video di sebelah kiri",
            fg_color="#0a0f16",
            corner_radius=8,
            font=ctk.CTkFont(size=14),
            text_color="gray",
        )
        self.preview_img_label.grid(row=0, column=0, sticky="nsew", padx=10, pady=10)

        info = ctk.CTkFrame(preview_content, fg_color="transparent")
        info.grid(row=1, column=0, sticky="ew", padx=10, pady=(0, 10))

        self.preview_title = ctk.CTkLabel(
            info, text="",
            font=ctk.CTkFont(size=12, weight="bold"),
            wraplength=350, justify="left", anchor="w",
        )
        self.preview_title.pack(fill="x", pady=(4, 2))

        self.preview_meta = ctk.CTkLabel(
            info, text="",
            font=ctk.CTkFont(size=11),
            text_color="#B0BEC5",
            justify="left", anchor="w",
        )
        self.preview_meta.pack(fill="x", pady=(0, 8))

        btns = ctk.CTkFrame(info, fg_color="transparent")
        btns.pack(fill="x")

        self.btn_open_video = ctk.CTkButton(
            btns, text="▶️ Buka Video", height=32,
            fg_color="#1976D2", hover_color="#0D47A1",
            font=ctk.CTkFont(size=11),
            state="disabled",
            command=self._open_selected_video,
        )
        self.btn_open_video.pack(side="left", fill="x", expand=True, padx=(0, 4))

        self.btn_open_folder = ctk.CTkButton(
            btns, text="📂 Folder", width=90, height=32,
            fg_color="#455A64", hover_color="#37474F",
            font=ctk.CTkFont(size=11),
            state="disabled",
            command=self._open_selected_folder,
        )
        self.btn_open_folder.pack(side="left")

        self.include_var = ctk.BooleanVar(value=True)
        self.include_cb = ctk.CTkCheckBox(
            info, text="Include di upload",
            variable=self.include_var,
            font=ctk.CTkFont(size=11),
            state="disabled",
            command=self._on_include_toggle,
        )
        self.include_cb.pack(fill="x", pady=(8, 0))

    # ══════════════════════════════════════════════════════
    # BOTTOM PANEL: Upload settings + progress + log
    # ══════════════════════════════════════════════════════
    def _build_bottom_panel(self):
        f = ctk.CTkFrame(self, fg_color="#1a2332", corner_radius=10)
        f.grid(row=2, column=0, sticky="ew", pady=(10, 0))
        f.grid_columnconfigure(0, weight=1)

        # ⚡ Upload settings row
        s = ctk.CTkFrame(f, fg_color="transparent")
        s.grid(row=0, column=0, sticky="ew", padx=15, pady=(12, 6))

        ctk.CTkLabel(s, text="Privacy:",
                     font=ctk.CTkFont(size=12)).pack(side="left", padx=(0, 5))
        self.privacy_var = ctk.StringVar(value="unlisted")
        ctk.CTkOptionMenu(s, variable=self.privacy_var,
                          values=["public", "unlisted", "private"],
                          width=110).pack(side="left", padx=(0, 15))

        ctk.CTkLabel(s, text="Prefix:",
                     font=ctk.CTkFont(size=12)).pack(side="left", padx=(0, 5))
        self.prefix_entry = ctk.CTkEntry(s, width=180, placeholder_text="(opsional)")
        self.prefix_entry.pack(side="left", padx=(0, 15))

        # ⚡ FORCE RE-UPLOAD CHECKBOX
        self.force_reupload_cb = ctk.CTkCheckBox(
            s, text="⚡ Force re-upload",
            variable=self._force_reupload_var,
            font=ctk.CTkFont(size=11),
            text_color="#FF9800",
            hover_color="#F57C00",
        )
        self.force_reupload_cb.pack(side="left", padx=(0, 15))

        self.btn_start = ctk.CTkButton(
            s, text="🚀  MULAI UPLOAD", width=180, height=40,
            font=ctk.CTkFont(size=14, weight="bold"),
            fg_color="#D32F2F", hover_color="#B71C1C",
            command=self._on_start,
        )
        self.btn_start.pack(side="left", padx=(0, 8))

        self.btn_stop = ctk.CTkButton(
            s, text="⏸", width=50, height=40,
            font=ctk.CTkFont(size=14, weight="bold"),
            fg_color="#616161", hover_color="#424242",
            state="disabled", command=self._on_stop,
        )
        self.btn_stop.pack(side="left")

        # Progress row
        p = ctk.CTkFrame(f, fg_color="transparent")
        p.grid(row=1, column=0, sticky="ew", padx=15, pady=(0, 6))
        p.grid_columnconfigure(0, weight=1)

        self.bar = ctk.CTkProgressBar(p, height=12)
        self.bar.grid(row=0, column=0, sticky="ew")
        self.bar.set(0)

        self.label = ctk.CTkLabel(p, text="Ready", anchor="w",
                                   font=ctk.CTkFont(size=11), text_color="#B0BEC5")
        self.label.grid(row=1, column=0, sticky="w", pady=(2, 0))

        # Log row
        log_frame = ctk.CTkFrame(f, fg_color="transparent")
        log_frame.grid(row=2, column=0, sticky="ew", padx=15, pady=(0, 12))
        log_frame.grid_columnconfigure(0, weight=1)

        log_header = ctk.CTkFrame(log_frame, fg_color="transparent")
        log_header.grid(row=0, column=0, sticky="ew")

        ctk.CTkLabel(log_header, text="📋 Log",
                     font=ctk.CTkFont(size=11, weight="bold"),
                     text_color="#90A4AE").pack(side="left")

        self.log_expand_btn = ctk.CTkButton(
            log_header, text="▼ Expand", width=90, height=22,
            fg_color="#37474F", hover_color="#263238",
            font=ctk.CTkFont(size=10),
            command=self._toggle_log,
        )
        self.log_expand_btn.pack(side="right")

        self.log = ctk.CTkTextbox(
            log_frame, height=70,
            font=ctk.CTkFont(family="Consolas", size=10),
            fg_color="#0f1620",
        )
        self.log.grid(row=1, column=0, sticky="ew", pady=(4, 0))
        self.log.configure(state="disabled")

        self._log_expanded = False

    def _toggle_log(self):
        self._log_expanded = not self._log_expanded
        if self._log_expanded:
            self.log.configure(height=300)
            self.log_expand_btn.configure(text="▲ Collapse")
        else:
            self.log.configure(height=70)
            self.log_expand_btn.configure(text="▼ Expand")

    # ══════════════════════════════════════════════════════
    # DRAG & DROP
    # ══════════════════════════════════════════════════════
    def _on_file_drop(self, event):
        try:
            files = self.tk.splitlist(event.data)
        except Exception as e:
            self._log(f"⚠️ Gagal parse drop: {e}")
            return

        video_files = []
        for f in files:
            f = f.strip()
            if not f:
                continue
            if os.path.isdir(f):
                for root, _, fs in os.walk(f):
                    for fn in fs:
                        if fn.lower().endswith(VIDEO_EXTS):
                            video_files.append(os.path.join(root, fn))
            elif f.lower().endswith(VIDEO_EXTS):
                video_files.append(f)

        if not video_files:
            self._log("⚠️ Tidak ada file video di drop")
            return

        videos = []
        for f in video_files:
            try:
                size = os.path.getsize(f)
            except Exception:
                size = 0
            videos.append({
                "path": f, "name": os.path.basename(f),
                "size": size, "size_str": _human_size(size),
            })

        self.dropped_mode = True
        self._log(f"📥 Drop: {len(videos)} video")
        self._render_videos(videos, source="drag & drop")

    # ══════════════════════════════════════════════════════
    # RENDER GRID
    # ══════════════════════════════════════════════════════
    def _render_videos(self, videos, source=""):
        self._clear_grid()
        gen = self._load_gen
        self.all_videos = list(videos)

        if not videos:
            lbl = ctk.CTkLabel(
                self.video_scroll,
                text="📭  Belum ada video\n\nPilih user di atas atau drag & drop",
                text_color="gray", font=ctk.CTkFont(size=13),
                justify="center",
            )
            lbl.grid(row=0, column=0, columnspan=GRID_COLS, pady=60)
            self.count_label.configure(text="📋 0 video")
            return

        for i, v in enumerate(videos):
            if gen != self._load_gen:
                return
            row = i // GRID_COLS
            col = i % GRID_COLS
            try:
                self._create_video_card(v, row, col, gen)
            except Exception as e:
                self._log(f"⚠️ Error render video {i}: {e}")

        label = f"📋 {len(videos)} video"
        if source:
            label += f"  ({source})"
        self.count_label.configure(text=label)

    def _create_video_card(self, video, row, col, gen):
        card = ctk.CTkFrame(self.video_scroll, fg_color="#1e2a3a", corner_radius=8,
                             border_width=2, border_color="#1e2a3a")
        card.grid(row=row, column=col, padx=4, pady=4, sticky="nsew")

        path = video["path"]
        var = ctk.BooleanVar(value=True)
        self.video_checkboxes[path] = var
        self.video_widgets[path] = card

        thumb_frame = ctk.CTkFrame(card, fg_color="transparent")
        thumb_frame.pack(fill="x", padx=6, pady=(6, 4))

        thumb_label = ctk.CTkLabel(
            thumb_frame, text="⏳", width=THUMB_SIZE, height=THUMB_SIZE,
            fg_color="#0f1620", corner_radius=6,
            font=ctk.CTkFont(size=18),
        )
        thumb_label.pack()

        thumb_label.bind("<Button-1>", lambda e, i=video: self._select_video(video))
        thumb_frame.bind("<Button-1>", lambda e, i=video: self._select_video(video))

        info = ctk.CTkFrame(card, fg_color="transparent")
        info.pack(fill="x", padx=6, pady=(0, 6))

        clean = _clean_name(video["name"])
        display = clean if len(clean) <= 25 else clean[:25] + "..."

        cb = ctk.CTkCheckBox(
            info, text=display,
            variable=var,
            font=ctk.CTkFont(size=10),
            command=lambda p=path: self._on_checkbox_change(p),
        )
        cb.pack(anchor="w")

        ctk.CTkLabel(
            info, text=video["size_str"],
            font=ctk.CTkFont(size=9),
            text_color="#90A4AE",
            anchor="w",
        ).pack(anchor="w")

        self._load_thumb_async(path, thumb_label, gen)

    def _clear_grid(self):
        self._load_gen += 1
        try:
            children = list(self.video_scroll.winfo_children())
        except Exception:
            children = []
        for w in children:
            try:
                w.destroy()
            except Exception:
                pass
        self.video_checkboxes.clear()
        self.video_widgets.clear()
        self.all_videos = []
        self._thumb_refs.clear()

    # ══════════════════════════════════════════════════════
    # THUMBNAIL
    # ══════════════════════════════════════════════════════
    def _load_thumb_async(self, video_path, label, gen):
        def worker():
            try:
                tp = extract_thumbnail(video_path)
                if tp:
                    self.after(0, lambda: self._apply_thumb(label, tp, gen))
            except Exception:
                pass
        self._thumb_executor.submit(worker)

    def _apply_thumb(self, label, thumb_path, gen):
        if gen != self._load_gen:
            return
        try:
            if not label.winfo_exists():
                return
        except Exception:
            return

        if not PIL_AVAILABLE:
            try:
                label.configure(text="🖼")
            except Exception:
                pass
            return

        try:
            img = Image.open(thumb_path)
            ctk_img = CTkImage(light_image=img, dark_image=img,
                                size=(THUMB_SIZE, THUMB_SIZE))
            if label.winfo_exists():
                label.configure(image=ctk_img, text="")
                self._thumb_refs.append(ctk_img)
        except Exception:
            pass

    # ══════════════════════════════════════════════════════
    # SELECT VIDEO → PREVIEW
    # ══════════════════════════════════════════════════════
    def _select_video(self, video):
        self.selected_video = video

        for p, card in self.video_widgets.items():
            try:
                if p == video["path"]:
                    card.configure(border_color="#1976D2")
                else:
                    card.configure(border_color="#1e2a3a")
            except Exception:
                pass

        clean = _clean_name(video["name"])
        self.preview_title.configure(text=clean)

        meta_lines = [f"💾 {video['size_str']}"]
        info = self._get_video_info(video["path"])
        if info:
            if info.get("duration"):
                meta_lines.append(f"⏱️ {info['duration']}")
            if info.get("resolution"):
                meta_lines.append(f"🎬 {info['resolution']}")
        self.preview_meta.configure(text="  |  ".join(meta_lines))

        self._load_preview_image(video["path"])

        self.btn_open_video.configure(state="normal")
        self.btn_open_folder.configure(state="normal")
        self.include_cb.configure(state="normal")
        self.include_var.set(self.video_checkboxes.get(video["path"], ctk.BooleanVar(value=True)).get())

    def _load_preview_image(self, video_path):
        try:
            tp = extract_thumbnail(video_path)
            if not tp or not PIL_AVAILABLE:
                self.preview_img_label.configure(
                    image="", text="\n\n🎬\n\n(Preview tidak tersedia)\n",
                )
                return

            img = Image.open(tp)
            ctk_img = CTkImage(light_image=img, dark_image=img,
                                size=PREVIEW_SIZE)
            self.preview_img_label.configure(image=ctk_img, text="")
            self._thumb_refs.append(ctk_img)
        except Exception as e:
            self.preview_img_label.configure(text=f"\n\n⚠️\n\n{e}\n")

    def _get_video_info(self, path):
        try:
            cmd = [
                "ffprobe", "-v", "error",
                "-select_streams", "v:0",
                "-show_entries", "stream=width,height,duration",
                "-of", "csv=p=0",
                path,
            ]
            import subprocess
            creationflags = 0x08000000 if os.name == "nt" else 0
            r = subprocess.run(cmd, capture_output=True, text=True,
                                timeout=10, creationflags=creationflags)
            if r.returncode == 0 and r.stdout.strip():
                parts = r.stdout.strip().split(",")
                info = {}
                if len(parts) >= 2:
                    w, h = parts[0], parts[1]
                    info["resolution"] = f"{w}×{h}"
                if len(parts) >= 3:
                    try:
                        sec = int(float(parts[2]))
                        m, s = divmod(sec, 60)
                        info["duration"] = f"{m:02d}:{s:02d}"
                    except Exception:
                        pass
                return info
        except Exception:
            pass
        return {}

    def _open_selected_video(self):
        if self.selected_video:
            try:
                os.startfile(self.selected_video["path"])
            except Exception as e:
                self._log(f"⚠️ {e}")

    def _open_selected_folder(self):
        if self.selected_video:
            try:
                os.startfile(os.path.dirname(self.selected_video["path"]))
            except Exception as e:
                self._log(f"⚠️ {e}")

    def _on_include_toggle(self):
        if not self.selected_video:
            return
        path = self.selected_video["path"]
        if path in self.video_checkboxes:
            self.video_checkboxes[path].set(self.include_var.get())

    def _on_checkbox_change(self, path):
        if self.selected_video and self.selected_video["path"] == path:
            self.include_var.set(self.video_checkboxes[path].get())

    # ══════════════════════════════════════════════════════
    # SELECT ALL / NONE
    # ══════════════════════════════════════════════════════
    def _select_all(self):
        for v in self.video_checkboxes.values():
            v.set(True)
        if self.selected_video:
            self.include_var.set(True)

    def _deselect_all(self):
        for v in self.video_checkboxes.values():
            v.set(False)
        if self.selected_video:
            self.include_var.set(False)

    def _get_selected_videos(self):
        return [v for v in self.all_videos
                if self.video_checkboxes.get(v["path"])
                and self.video_checkboxes[v["path"]].get()]

    # ══════════════════════════════════════════════════════
    # LOAD USERS
    # ══════════════════════════════════════════════════════
    def _on_platform_change(self):
        self.current_platform = self.platform_var.get()
        if not self.dropped_mode:
            self._load_users()

    def _load_users(self):
        ensure_all()
        users = scan_users(self.current_platform)
        if not users:
            self.user_menu.configure(values=["(belum ada user)"])
            self.user_var.set("(belum ada user)")
            self.current_user = None
            self._clear_grid()
            self.count_label.configure(text="📋 0 video")
            return
        self.user_menu.configure(values=users)
        self.user_var.set(users[0])
        self.current_user = users[0]
        self._load_videos()

    def _on_user_change(self, choice):
        if choice and choice != "(belum ada user)":
            self.current_user = choice
            self.dropped_mode = False
            self._load_videos()

    def _load_videos(self):
        if not self.current_user:
            return
        videos = scan_videos(self.current_platform, self.current_user)
        self._log(f"📥 {len(videos)} video dari @{self.current_user}")
        self._render_videos(videos, source=f"@{self.current_user}")

    # ══════════════════════════════════════════════════════
    # PROFILE HELPERS
    # ══════════════════════════════════════════════════════
    def _load_chrome_profiles(self):
        self.chrome_profiles = list_chrome_profiles()
        self._update_profile_status()

    def _update_profile_status(self):
        saved = get_saved_profile()
        if not saved.get("user_data_path"):
            self.profile_indicator.configure(text="❌ Profile: None", text_color="#F44336")
            return
        ok, msg = validate_profile()
        if ok:
            self.profile_indicator.configure(
                text=f"✅ Profile: {saved['profile_folder']}",
                text_color="#4CAF50",
            )
        else:
            self.profile_indicator.configure(text="❌ Profile error", text_color="#F44336")

    def _show_profile_dialog(self):
        win = ctk.CTkToplevel(self)
        win.title("Profile Setup")
        win.geometry("600x500")
        win.transient(self)
        win.grab_set()

        ctk.CTkLabel(win, text="🔐 YouTube Profile Setup",
                     font=ctk.CTkFont(size=16, weight="bold")).pack(pady=(20, 10))

        ctk.CTkLabel(win,
                     text="Pilih Chrome profile → Set → Buka Chrome Login → Login → Tutup → Test",
                     text_color="gray", wraplength=500).pack(pady=(0, 15))

        ctk.CTkLabel(win, text="Chrome Profile:").pack(anchor="w", padx=20, pady=(10, 4))

        profile_var = ctk.StringVar(value="(belum ada)")
        values = ["(belum ada)"]
        for p in self.chrome_profiles:
            label = p["folder"]
            if p["name"] and p["name"] != p["folder"]:
                label += f" — {p['name']}"
            values.append(label)
        profile_menu = ctk.CTkOptionMenu(win, variable=profile_var, values=values, width=450)
        profile_menu.pack(padx=20, pady=(0, 15))

        status_lbl = ctk.CTkLabel(win, text="", font=ctk.CTkFont(size=11))
        status_lbl.pack(pady=(0, 10))

        log_box = ctk.CTkTextbox(win, height=150, font=ctk.CTkFont(family="Consolas", size=10))
        log_box.pack(fill="both", expand=True, padx=20, pady=(0, 10))
        log_box.configure(state="disabled")

        def _log_dialog(msg):
            ts = time.strftime("%H:%M:%S")
            log_box.configure(state="normal")
            log_box.insert("end", f"[{ts}] {msg}\n")
            log_box.see("end")
            log_box.configure(state="disabled")

        def _get_selected():
            label = profile_var.get()
            for p in self.chrome_profiles:
                check = p["folder"]
                if p["name"] and p["name"] != p["folder"]:
                    check += f" — {p['name']}"
                if check == label:
                    return p
            return None

        def _on_set():
            sel = _get_selected()
            if not sel:
                status_lbl.configure(text="⚠️ Pilih profile dulu", text_color="#FF9800")
                return
            ud = get_chrome_user_data_path()
            if not ud:
                status_lbl.configure(text="❌ Chrome path tidak ditemukan", text_color="#F44336")
                return
            if save_profile_to_config(str(ud), sel["folder"]):
                _log_dialog(f"✅ Profile diset: {sel['folder']}")
                status_lbl.configure(text="✅ Profile saved", text_color="#4CAF50")
                self._update_profile_status()

        def _on_open_login():
            sel = _get_selected()
            if not sel:
                status_lbl.configure(text="⚠️ Pilih profile dulu", text_color="#FF9800")
                return
            chrome = _get_chrome_exe()
            if not chrome:
                status_lbl.configure(text="❌ Chrome tidak ditemukan", text_color="#F44336")
                return
            try:
                import subprocess
                if is_chrome_running():
                    kill_chrome()
                    time.sleep(2)
                subprocess.Popen([chrome,
                                  f"--profile-directory={sel['folder']}",
                                  "https://studio.youtube.com"])
                _log_dialog(f"🌐 Chrome dibuka: {sel['folder']}")
                _log_dialog("Login YouTube → Tutup Chrome → Klik Test")
            except Exception as e:
                _log_dialog(f"❌ {e}")

        def _on_test():
            sel = _get_selected()
            if not sel:
                status_lbl.configure(text="⚠️ Pilih profile dulu", text_color="#FF9800")
                return
            status_lbl.configure(text="🔍 Testing...", text_color="gray")

            def worker():
                try:
                    up = YouTubeUploader(
                        on_log=lambda m: self.after(0, lambda: _log_dialog(m)),
                        stop_event=threading.Event(),
                    )
                    ok = up.check_login()
                    self.after(0, lambda: status_lbl.configure(
                        text="✅ Login valid!" if ok else "❌ Login gagal",
                        text_color="#4CAF50" if ok else "#F44336",
                    ))
                    self.after(0, self._update_profile_status)
                except Exception as e:
                    self.after(0, lambda: status_lbl.configure(
                        text=f"❌ {e}", text_color="#F44336"))

            threading.Thread(target=worker, daemon=True).start()

        bf = ctk.CTkFrame(win, fg_color="transparent")
        bf.pack(fill="x", padx=20, pady=(0, 20))

        ctk.CTkButton(bf, text="💾 Set", width=120, height=36,
                       fg_color="#1976D2", command=_on_set).pack(side="left", padx=2)
        ctk.CTkButton(bf, text="🌐 Buka Login", width=140, height=36,
                       fg_color="#7B1FA2", command=_on_open_login).pack(side="left", padx=2)
        ctk.CTkButton(bf, text="🔍 Test", width=100, height=36,
                       fg_color="#2E7D32", command=_on_test).pack(side="left", padx=2)
        ctk.CTkButton(bf, text="❌ Close", width=100, height=36,
                       fg_color="#455A64", command=win.destroy).pack(side="right", padx=2)

        self._update_profile_status()

    # ══════════════════════════════════════════════════════
    # UPLOAD
    # ══════════════════════════════════════════════════════
    def _on_start(self):
        if self.thread and self.thread.is_alive():
            messagebox.showwarning("Warning", "Upload sedang berjalan")
            return

        saved = get_saved_profile()
        if not saved.get("user_data_path"):
            messagebox.showerror("Profile Error",
                "Profile belum diset!\n\nKlik indikator profile di kanan atas")
            return

        ok, msg = validate_profile()
        if not ok:
            messagebox.showerror("Profile Error", msg)
            return

        # ⚡ NO kill Chrome — uploader akan auto-handle Chrome debug

        selected = self._get_selected_videos()
        if not selected:
            messagebox.showerror("Error", "Pilih minimal 1 video")
            return

        cfg = YouTubeConfig()
        privacy = self.privacy_var.get()
        prefix = self.prefix_entry.get().strip()
        source_user = self.current_user if not self.dropped_mode else "manual_drop"
        force_reupload = self._force_reupload_var.get()

        confirm_msg = (
            f"Upload {len(selected)} video?\n\n"
            f"Privacy: {privacy}\n"
            f"Prefix: {prefix or '(none)'}\n"
            f"Source: {source_user}\n"
        )
        if force_reupload:
            confirm_msg += "\n⚡ FORCE RE-UPLOAD aktif (ignore history)"

        if not messagebox.askyesno("Konfirmasi", confirm_msg):
            return

        videos_to_upload = []
        for i, v in enumerate(selected, 1):
            fname = _clean_name(v["name"])
            title = f"{prefix} {fname}".strip() if prefix else fname
            if len(title) > 100:
                title = title[:100]

            desc = cfg.description_template
            desc = desc.replace("{username}", source_user or "")
            desc = desc.replace("{source}", self.current_platform)
            desc = desc.replace("{filename}", fname)
            desc = desc.replace("{index}", str(i))

            videos_to_upload.append({
                "path": v["path"], "title": title,
                "description": desc, "tags": cfg.tags,
                "privacy": privacy,
            })

        self._set_running(True, f"Upload {len(videos_to_upload)} video")
        self._log("=" * 55)
        self._log(f"▶ Upload {len(videos_to_upload)} video")
        if force_reupload:
            self._log(f"⚡ Force re-upload: ON")
        self._log("=" * 55)

        def worker():
            try:
                uploader = YouTubeUploader(
                    config=cfg, stop_event=self.stop_event,
                    on_log=lambda m: self._emit("log", m),
                    on_progress=lambda c, t, m: self._emit("progress", c, t, m),
                )
                # ⚡ Pass force_reupload
                uploader.upload_batch(
                    videos_to_upload,
                    source_platform=self.current_platform,
                    source_username=source_user,
                    force_reupload=force_reupload,
                )
                self._emit("done", True, "✅ Upload selesai")
            except Exception as e:
                self._emit("done", False, f"❌ {str(e)[:150]}")

        self.stop_event.clear()
        self.thread = threading.Thread(target=worker, daemon=True)
        self.thread.start()

    def _on_stop(self):
        if self.thread and self.thread.is_alive():
            self.stop_event.set()
            self._log("⏸ Stop requested...")

    def _set_running(self, running, label=""):
        if running:
            self.btn_start.configure(state="disabled", text="⏳ Running...")
            self.btn_stop.configure(state="normal")
        else:
            self.btn_start.configure(state="normal", text="🚀  MULAI UPLOAD")
            self.btn_stop.configure(state="disabled")
            self._update_profile_status()

    # ══════════════════════════════════════════════════════
    # EVENT QUEUE
    # ══════════════════════════════════════════════════════
    def _emit(self, t, *a):
        self.events.put((t, a))

    def _poll(self):
        try:
            while True:
                ev, args = self.events.get_nowait()
                if ev == "log":
                    self._log(args[0])
                elif ev == "progress":
                    cur, tot, msg = args
                    self.bar.set(min(cur / max(tot, 1), 1.0))
                    self.label.configure(text=f"{msg} ({cur}/{tot})")
                elif ev == "done":
                    ok, msg = args
                    self._set_running(False)
                    self.label.configure(text=msg)
                    self._log("")
                    self._log("=" * 55)
                    self._log(msg)
                    self._log("=" * 55)
        except queue.Empty:
            pass
        self.after(100, self._poll)

    def _log(self, message):
        ts = time.strftime("%H:%M:%S")
        self.log.configure(state="normal")
        self.log.insert("end", f"[{ts}] {message}\n")
        self.log.see("end")
        self.log.configure(state="disabled")