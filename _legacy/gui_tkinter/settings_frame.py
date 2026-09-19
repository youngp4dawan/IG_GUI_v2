"""Settings tab — Instagram + TikTok cookies saja (YouTube pakai Chrome profile)."""
import customtkinter as ctk
from tkinter import messagebox

from instagram.config import InstagramConfig
from tiktok.config import TikTokConfig


class SettingsFrame(ctk.CTkScrollableFrame):
    def __init__(self, master, app):
        super().__init__(master, fg_color="transparent")
        self.app = app
        self.grid_columnconfigure(0, weight=1)
        self._build()
        self._load()

    def _build(self):
        # INSTAGRAM
        ctk.CTkLabel(self, text="📷 Instagram Cookies",
                     font=ctk.CTkFont(size=18, weight="bold")).grid(
            row=0, column=0, padx=20, pady=(20, 5), sticky="w")
        ctk.CTkLabel(self, text="F12 → Application → Cookies → instagram.com",
                     text_color="gray").grid(
            row=1, column=0, padx=20, pady=(0, 15), sticky="w")

        form = ctk.CTkFrame(self)
        form.grid(row=2, column=0, padx=20, pady=0, sticky="ew")
        form.grid_columnconfigure(1, weight=1)
        self.ig = {}
        for i, (label, key, hint) in enumerate([
            ("Username", "username", "Akun IG"),
            ("sessionid", "sessionid", "Cookie sessionid"),
            ("csrftoken", "csrftoken", "Cookie csrftoken"),
            ("ds_user_id", "ds_user_id", "Cookie ds_user_id"),
        ]):
            ctk.CTkLabel(form, text=label + ":", anchor="w",
                         font=ctk.CTkFont(size=13, weight="bold")).grid(
                row=i*2, column=0, padx=15, pady=(12 if i==0 else 8, 2), sticky="w")
            ctk.CTkLabel(form, text=hint, text_color="gray", anchor="w",
                         font=ctk.CTkFont(size=11)).grid(
                row=i*2, column=1, padx=(0,15), pady=(12 if i==0 else 8, 2), sticky="w")
            e = ctk.CTkEntry(form, height=36)
            e.grid(row=i*2+1, column=0, columnspan=2, padx=15, pady=(0,4), sticky="ew")
            self.ig[key] = e

        bf = ctk.CTkFrame(self, fg_color="transparent")
        bf.grid(row=3, column=0, padx=20, pady=(15,10), sticky="ew")
        ctk.CTkButton(bf, text="💾 Save Instagram", width=160, height=38,
                      fg_color="#2E7D32", hover_color="#1B5E20",
                      command=self._save_ig).pack(side="left", padx=(0,10))
        ctk.CTkButton(bf, text="🔄 Reload", width=120, height=38,
                      fg_color="#37474F", hover_color="#263238",
                      command=self._load).pack(side="left")

        ctk.CTkFrame(self, height=2, fg_color="gray30").grid(
            row=4, column=0, padx=20, pady=15, sticky="ew")

        # TIKTOK
        ctk.CTkLabel(self, text="🎵 TikTok Cookies",
                     font=ctk.CTkFont(size=18, weight="bold")).grid(
            row=5, column=0, padx=20, pady=(10,5), sticky="w")
        ctk.CTkLabel(self, text="Minimal: sessionid + ttwid",
                     text_color="gray").grid(
            row=6, column=0, padx=20, pady=(0,15), sticky="w")

        form2 = ctk.CTkFrame(self)
        form2.grid(row=7, column=0, padx=20, pady=0, sticky="ew")
        form2.grid_columnconfigure(1, weight=1)
        self.tt = {}
        for i, (label, key, hint) in enumerate([
            ("Username", "username", "Akun TikTok"),
            ("sessionid", "sessionid", "WAJIB"),
            ("ttwid", "ttwid", "WAJIB"),
            ("msToken", "msToken", "Anti-bot"),
            ("sessionid_ss", "sessionid_ss", "Secure session"),
            ("sid_tt", "sid_tt", "Session ID"),
        ]):
            ctk.CTkLabel(form2, text=label + ":", anchor="w",
                         font=ctk.CTkFont(size=13, weight="bold")).grid(
                row=i*2, column=0, padx=15, pady=(12 if i==0 else 8, 2), sticky="w")
            ctk.CTkLabel(form2, text=hint, text_color="gray", anchor="w",
                         font=ctk.CTkFont(size=11)).grid(
                row=i*2, column=1, padx=(0,15), pady=(12 if i==0 else 8, 2), sticky="w")
            e = ctk.CTkEntry(form2, height=36)
            e.grid(row=i*2+1, column=0, columnspan=2, padx=15, pady=(0,4), sticky="ew")
            self.tt[key] = e

        bf2 = ctk.CTkFrame(self, fg_color="transparent")
        bf2.grid(row=8, column=0, padx=20, pady=(15,10), sticky="ew")
        ctk.CTkButton(bf2, text="💾 Save TikTok", width=160, height=38,
                      fg_color="#E91E63", hover_color="#AD1457",
                      command=self._save_tt).pack(side="left", padx=(0,10))
        ctk.CTkButton(bf2, text="🔄 Reload", width=120, height=38,
                      fg_color="#37474F", hover_color="#263238",
                      command=self._load).pack(side="left", padx=(0,10))
        ctk.CTkButton(bf2, text="🧪 Test Cookies", width=140, height=38,
                      fg_color="#1565C0", hover_color="#0D47A1",
                      command=self._test_tt).pack(side="left")

        ctk.CTkFrame(self, height=2, fg_color="gray30").grid(
            row=9, column=0, padx=20, pady=15, sticky="ew")

        # Info YouTube
        yt_info = ctk.CTkFrame(self)
        yt_info.grid(row=10, column=0, padx=20, pady=(10, 20), sticky="ew")

        ctk.CTkLabel(yt_info,
                     text="📤 YouTube — pakai Chrome Profile (bukan cookies)",
                     font=ctk.CTkFont(size=14, weight="bold")).pack(
            padx=15, pady=(15, 8), anchor="w")

        ctk.CTkLabel(yt_info,
                     text=("Login YouTube di Chrome biasa → tutup Chrome →\n"
                           "buka tab Upload YouTube → klik Import Chrome Profile.\n\n"
                           "Metode ini paling aman untuk Google (tidak kena verify)."),
                     anchor="w", justify="left", text_color="#B0BEC5",
                     font=ctk.CTkFont(size=12)).pack(padx=15, pady=(0, 15), anchor="w")

    def _load(self):
        ig = InstagramConfig()
        for k in self.ig:
            self.ig[k].delete(0, "end")
            self.ig[k].insert(0, ig.get(k))

        tt = TikTokConfig()
        for k in self.tt:
            self.tt[k].delete(0, "end")
            self.tt[k].insert(0, tt.get(k))

        self.app.set_status("⚙️ Settings loaded")

    def _save_ig(self):
        data = {k: self.ig[k].get().strip() for k in self.ig}
        if not data["sessionid"]:
            messagebox.showerror("Error", "sessionid IG wajib diisi")
            return
        if InstagramConfig().set(**data):
            messagebox.showinfo("Success", "✅ Instagram config disimpan")

    def _save_tt(self):
        data = {k: self.tt[k].get().strip() for k in self.tt}
        if not (data["sessionid"] or data["ttwid"]):
            messagebox.showerror("Error", "Minimal isi sessionid atau ttwid")
            return
        if TikTokConfig().set(**data):
            messagebox.showinfo("Success", "✅ TikTok config disimpan")

    def _test_tt(self):
        cfg = TikTokConfig()
        if not cfg.is_valid():
            messagebox.showerror("Error", "Cookies TikTok belum diisi")
            return
        cookies = cfg.get_all_cookies()
        messagebox.showinfo("TikTok Cookies",
            f"✅ {len(cookies)} cookies terdeteksi:\n\n" + ", ".join(cookies.keys()))