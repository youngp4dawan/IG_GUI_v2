import json
import time

# Path cookies kamu
JSON_PATH = r"C:\Users\User\karil\IG_GUI_v2\config\tiktok.json"
OUTPUT = r"C:\Users\User\karil\IG_GUI_v2\config\tiktok_cookies.txt"

# Field yang BUKAN cookie (metadata config)
NON_COOKIE_FIELDS = {"username"}

with open(JSON_PATH, "r", encoding="utf-8") as f:
    data = json.load(f)

expiry = int(time.time()) + 365 * 24 * 3600  # 1 tahun dari sekarang

with open(OUTPUT, "w", encoding="utf-8") as f:
    f.write("# Netscape HTTP Cookie File\n")
    f.write("# Generated from tiktok.json\n\n")
    for key, value in data.items():
        if key in NON_COOKIE_FIELDS:
            continue
        if not value:
            continue
        # domain, flag, path, secure, expiry, name, value
        f.write(f".tiktok.com\tTRUE\t/\tTRUE\t{expiry}\t{key}\t{value}\n")

print(f"✅ Saved {len(data)} cookies to {OUTPUT}")