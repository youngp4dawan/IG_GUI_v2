"""Facebook config — cookies management."""
import os
from shared.config import BaseConfig
from shared.paths import FACEBOOK_CONFIG, FACEBOOK_COOKIES


class FacebookConfig(BaseConfig):
    """
    Config untuk Facebook.
    Cookies format: Netscape HTTP Cookie File.
    """

    def __init__(self, filepath=FACEBOOK_CONFIG):
        super().__init__(filepath, defaults={
            "c_user": "",
            "xs": "",
            "datr": "",
            "sb": "",
            "fr": "",
        })

    @property
    def c_user(self):
        return self.get("c_user")

    @property
    def xs(self):
        return self.get("xs")

    @property
    def datr(self):
        return self.get("datr")

    @property
    def sb(self):
        return self.get("sb")

    @property
    def fr(self):
        return self.get("fr")

    def is_valid(self):
        # Minimal butuh c_user + xs
        return bool(self.c_user and self.xs)

    def generate_netscape(self):
        """
        Generate Netscape cookie file untuk yt-dlp.
        Return (ok: bool, msg: str).
        """
        if not self.is_valid():
            return False, "Cookies Facebook tidak lengkap (butuh c_user + xs)"

        lines = ["# Netscape HTTP Cookie File", "# Facebook cookies", ""]

        cookies_to_write = [
            (".facebook.com", "c_user", self.c_user),
            (".facebook.com", "xs", self.xs),
            (".facebook.com", "datr", self.datr),
            (".facebook.com", "sb", self.sb),
            (".facebook.com", "fr", self.fr),
            (".www.facebook.com", "c_user", self.c_user),
            (".www.facebook.com", "xs", self.xs),
        ]

        for domain, name, value in cookies_to_write:
            if not value:
                continue
            # Format: domain  TRUE  /  TRUE  expiry  name  value
            lines.append(f"{domain}\tTRUE\t/\tTRUE\t0\t{name}\t{value}")

        try:
            os.makedirs(os.path.dirname(FACEBOOK_COOKIES), exist_ok=True)
            with open(FACEBOOK_COOKIES, "w", encoding="utf-8") as f:
                f.write("\n".join(lines) + "\n")
            return True, f"Cookies written: {len(lines) - 3} entries"
        except Exception as e:
            return False, f"Gagal tulis cookies: {str(e)[:100]}"

    def get_cookies_list(self):
        """Return list cookies untuk Selenium."""
        c = []
        if self.c_user:
            c.append({"name": "c_user", "value": self.c_user, "domain": ".facebook.com"})
        if self.xs:
            c.append({"name": "xs", "value": self.xs, "domain": ".facebook.com"})
        if self.datr:
            c.append({"name": "datr", "value": self.datr, "domain": ".facebook.com"})
        if self.sb:
            c.append({"name": "sb", "value": self.sb, "domain": ".facebook.com"})
        if self.fr:
            c.append({"name": "fr", "value": self.fr, "domain": ".facebook.com"})
        return c