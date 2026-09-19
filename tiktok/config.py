"""TikTok config."""
import time
from shared.config import BaseConfig
from shared.paths import TIKTOK_CONFIG, TIKTOK_COOKIES

IMPORTANT_COOKIES = [
    "sessionid", "sessionid_ss", "ttwid", "msToken",
    "sid_tt", "passport_csrf_token", "csrf_token",
]


class TikTokConfig(BaseConfig):
    def __init__(self, filepath=TIKTOK_CONFIG):
        super().__init__(filepath, defaults={
            "username": "", "sessionid": "", "sessionid_ss": "",
            "ttwid": "", "msToken": "", "sid_tt": "", "passport_csrf_token": "",
        })

    @property
    def username(self): return self.get("username")

    @property
    def sessionid(self): return self.get("sessionid")

    @property
    def ttwid(self): return self.get("ttwid")

    def is_valid(self):
        return bool(self.sessionid or self.ttwid)

    def get_all_cookies(self):
        return {k: self.get(k) for k in IMPORTANT_COOKIES if self.get(k)}

    def generate_netscape(self):
        cookies = self.get_all_cookies()
        if not cookies:
            return False, "No cookies"
        expires = int(time.time()) + 365 * 24 * 3600
        try:
            with open(TIKTOK_COOKIES, "w", encoding="utf-8") as f:
                f.write("# Netscape HTTP Cookie File\n")
                f.write(f"# Generated: {time.strftime('%Y-%m-%d %H:%M:%S')}\n\n")
                for name, val in cookies.items():
                    val = str(val).replace("\t", "").replace("\n", "").replace("\r", "")
                    f.write(f".tiktok.com\tTRUE\t/\tTRUE\t{expires}\t{name}\t{val}\n")
            return True, f"{len(cookies)} cookies"
        except Exception as e:
            return False, str(e)
