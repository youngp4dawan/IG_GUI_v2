"""Entry point — dengan Drag & Drop support."""
import customtkinter as ctk

from shared.paths import ensure_all
from shared.logger import setup_logging
from gui.main_app import MainApp


def main():
    ensure_all()
    setup_logging()
    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("blue")
    MainApp().mainloop()


if __name__ == "__main__":
    main()