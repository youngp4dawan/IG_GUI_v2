"""Sidebar navigation component."""
import customtkinter as ctk


class Sidebar(ctk.CTkFrame):
    """
    Sidebar dengan menu items.
    items = [{"id": "...", "icon": "📷", "label": "Instagram"}, ...]
    on_select = callback(id) dipanggil saat item diklik.
    """
    def __init__(self, master, items, on_select, width=200):
        super().__init__(master, width=width, corner_radius=0, fg_color="#0f1620")
        self.pack_propagate(False)
        self.items = items
        self.on_select = on_select
        self.buttons = {}
        self.active_id = None

        # Logo/Header
        header = ctk.CTkFrame(self, height=70, corner_radius=0, fg_color="#0a0f16")
        header.pack(fill="x")
        header.pack_propagate(False)

        ctk.CTkLabel(
            header, text="🎬  Downloader",
            font=ctk.CTkFont(size=16, weight="bold"),
            anchor="w",
        ).pack(padx=20, pady=(20, 4), anchor="w")

        ctk.CTkLabel(
            header, text="v2.0",
            font=ctk.CTkFont(size=10),
            text_color="gray",
            anchor="w",
        ).pack(padx=20, anchor="w")

        # Menu items
        menu_frame = ctk.CTkFrame(self, fg_color="transparent")
        menu_frame.pack(fill="both", expand=True, pady=(20, 0))

        for item in items:
            btn = ctk.CTkButton(
                menu_frame,
                text=f"   {item['icon']}   {item['label']}",
                anchor="w",
                height=44,
                corner_radius=8,
                fg_color="transparent",
                text_color="#B0BEC5",
                hover_color="#1e3a5f",
                font=ctk.CTkFont(size=13),
                command=lambda i=item["id"]: self._on_click(i),
            )
            btn.pack(fill="x", padx=12, pady=2)
            self.buttons[item["id"]] = btn

        # Footer
        ctk.CTkLabel(
            self,
            text="© 2025 Social Downloader",
            font=ctk.CTkFont(size=10),
            text_color="#546e7a",
        ).pack(side="bottom", pady=15)

    def _on_click(self, item_id):
        self.set_active(item_id)
        if self.on_select:
            self.on_select(item_id)

    def set_active(self, item_id):
        """Highlight item yang aktif."""
        self.active_id = item_id
        for iid, btn in self.buttons.items():
            if iid == item_id:
                btn.configure(fg_color="#1976D2", text_color="white")
            else:
                btn.configure(fg_color="transparent", text_color="#B0BEC5")