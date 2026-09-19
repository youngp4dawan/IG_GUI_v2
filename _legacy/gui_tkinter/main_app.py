"""Main window — Dashboard style dengan sidebar."""
import customtkinter as ctk

try:
    from tkinterdnd2 import TkinterDnD, DND_FILES
    DND_AVAILABLE = True
except ImportError:
    DND_AVAILABLE = False

from gui.sidebar import Sidebar


if DND_AVAILABLE:
    class MainApp(ctk.CTk, TkinterDnD.DnDWrapper):
        def __init__(self):
            super().__init__()
            self.TkdndVersion = TkinterDnD._require(self)
            self._build_ui()
else:
    class MainApp(ctk.CTk):
        def __init__(self):
            super().__init__()
            self._build_ui()


def _build_ui(self):
    self.title("Social Media Downloader v2.0")
    self.geometry("1280x820")
    self.minsize(1100, 720)

    # Grid: sidebar (fixed) + content (expand)
    self.grid_columnconfigure(1, weight=1)
    self.grid_rowconfigure(0, weight=1)

    # ─── Sidebar ─────────────────────────────────────
    menu_items = [
        {"id": "instagram", "icon": "📷", "label": "Instagram"},
        {"id": "tiktok",    "icon": "🎵", "label": "TikTok"},
        {"id": "youtube",   "icon": "📤", "label": "Upload YouTube"},
        {"id": "x",         "icon": "🐦", "label": "X (Twitter)"},
        {"id": "settings",  "icon": "⚙️", "label": "Settings"},
    ]

    self.sidebar = Sidebar(self, menu_items, on_select=self._switch_view)
    self.sidebar.grid(row=0, column=0, sticky="ns")

    # ─── Content area ────────────────────────────────
    self.content = ctk.CTkFrame(self, fg_color="transparent", corner_radius=0)
    self.content.grid(row=0, column=1, sticky="nsew")
    self.content.grid_columnconfigure(0, weight=1)
    self.content.grid_rowconfigure(0, weight=1)

    # Placeholder — frames akan di-instantiate lazily
    self.frames = {}
    self.current_frame = None

    # Default: instagram
    self.after(50, lambda: self._switch_view("instagram"))


def _switch_view(self, view_id):
    """Switch content area sesuai menu yang diklik."""
    # Hide current
    if self.current_frame:
        self.current_frame.grid_forget()

    # Lazy create
    if view_id not in self.frames:
        frame = self._create_frame(view_id)
        if not frame:
            return
        self.frames[view_id] = frame
        frame.grid(row=0, column=0, sticky="nsew", padx=15, pady=15)

    self.current_frame = self.frames[view_id]
    self.current_frame.grid()


def _create_frame(self, view_id):
    """Factory — bikin frame sesuai view_id."""
    try:
        if view_id == "instagram":
            from gui.instagram_frame import InstagramFrame
            return InstagramFrame(self.content, app=self)

        elif view_id == "tiktok":
            from gui.tiktok_frame import TikTokFrame
            return TikTokFrame(self.content, app=self)

        elif view_id == "youtube":
            from gui.youtube_frame import YouTubeFrame
            return YouTubeFrame(self.content, app=self)

        elif view_id == "x":
            f = ctk.CTkFrame(self.content, fg_color="transparent")
            ctk.CTkLabel(
                f,
                text="🐦  X (Twitter)\n\nComing soon...",
                font=ctk.CTkFont(size=24),
                text_color="gray",
            ).pack(expand=True)
            return f

        elif view_id == "settings":
            from gui.settings_frame import SettingsFrame
            return SettingsFrame(self.content, app=self)

    except Exception as e:
        import traceback
        traceback.print_exc()
        # Fallback error frame
        f = ctk.CTkFrame(self.content, fg_color="transparent")
        ctk.CTkLabel(
            f, text=f"⚠️ Error loading {view_id}:\n{e}",
            font=ctk.CTkFont(size=14), text_color="#F44336",
        ).pack(expand=True)
        return f

    return None


def set_status(self, text):
    """No-op — status dihapus, atau bisa tampil di footer sidebar."""
    pass


# Attach methods
MainApp._build_ui = _build_ui
MainApp._switch_view = _switch_view
MainApp._create_frame = _create_frame
MainApp.set_status = set_status