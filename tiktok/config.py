"""TikTok config."""
import time
from shared.config import BaseConfig
from shared.paths import TIKTOK_CONFIG, TIKTOK_COOKIES

# Field yang BUKAN cookie (metadata config) — di-skip saat generate netscape
NON_COOKIE_FIELDS = {"username"}

# Cookies yang dianggap minimal untuk validasi
CRITICAL_COOKIES = [
    "sessionid", "sessionid_ss", "ttwid", "msToken", "sid_tt",
]

# Cookies yang direkomendasikan (untuk warning kalau hilang)
RECOMMENDED_COOKIES = [
    "s_v_web_id", "tt_csrf_token", "odin_tt", "_abck",
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
        """
        [PATCH] Ambil SEMUA field dari JSON (kecuali metadata),
        bukan cuma whitelist. TikTok modern butuh cookies tambahan
        seperti s_v_web_id, tt_csrf_token, odin_tt, _abck.
        """
        # _data adalah dict internal BaseConfig — sesuaikan kalau beda
        raw = getattr(self, "_data", None) or getattr(self, "data", None)
        if raw is None:
            # Fallback: coba beberapa nama atribut umum
            for attr in ("_raw", "_json", "_config", "_cache"):
                raw = getattr(self, attr, None)
                if raw is not None:
                    break

        if raw is None:
            # Fallback terakhir: pakai whitelist lama
            return {k: self.get(k) for k in CRITICAL_COOKIES if self.get(k)}

        cookies = {}
        for key, value in raw.items():
            if key in NON_COOKIE_FIELDS:
                continue
            if value is None:
                continue
            value = str(value).strip()
            if not value:
                continue
            cookies[key] = value
        return cookies

    def generate_netscape(self):
        cookies = self.get_all_cookies()
        if not cookies:
            return False, "No cookies"

        # Validasi minimal
        missing_critical = [k for k in CRITICAL_COOKIES if k not in cookies]
        if missing_critical:
            return False, f"Missing critical: {', '.join(missing_critical)}"

        # Warning (tidak block) kalau recommended hilang
        missing_recommended = [k for k in RECOMMENDED_COOKIES if k not in cookies]

        expires = int(time.time()) + 365 * 24 * 3600
        try:
            with open(TIKTOK_COOKIES, "w", encoding="utf-8") as f:
                f.write("# Netscape HTTP Cookie File\n")
                f.write(f"# Generated: {time.strftime('%Y-%m-%d %H:%M:%S')}\n\n")
                for name, val in cookies.items():
                    val = str(val).replace("\t", "").replace("\n", "").replace("\r", "")
                    f.write(f".tiktok.com\tTRUE\t/\tTRUE\t{expires}\t{name}\t{val}\n")

            msg = f"{len(cookies)} cookies"
            if missing_recommended:
                msg += f" (⚠️  missing: {', '.join(missing_recommended)})"
            return True, msg
        except Exception as e:
            return False, str(e)