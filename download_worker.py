r"""
Unified Download Worker
=======================
1 file, 2 mode:

  1. MANUAL — user input username/URL di Wails (IG/TikTok/Facebook)
  2. GROUP  — dari grup idol yang sudah ada

Usage:
    python download_worker.py manual '<json_config>'
    python download_worker.py group  '<json_config>'
"""
import os
import sys
import time
import json
import signal
import sqlite3
from pathlib import Path

ROOT = Path(__file__).parent.resolve()
sys.path.insert(0, str(ROOT))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


DB_CANDIDATES = [
    ROOT.parent / "website-wails" / "build" / "bin" / "media_library.db",
    ROOT / "website-wails" / "build" / "bin" / "media_library.db",
    ROOT / "build" / "bin" / "media_library.db",
    ROOT / "media_library.db",
    Path(os.getcwd()) / "media_library.db",
]


def find_db():
    for p in DB_CANDIDATES:
        if p.exists():
            return str(p)
    return None


def _safe_decode(b):
    if isinstance(b, str):
        return b
    try:
        return b.decode("utf-8", errors="replace")
    except Exception:
        return str(b)


# ══════════════════════════════════════════════════════════
# WORKER
# ══════════════════════════════════════════════════════════
class DownloadWorker:
    def __init__(self, db_path, mode, config):
        self.db_path = db_path
        self.mode = mode
        self.config = config
        self.stop = False
        self.run_id = None

    def conn(self):
        c = sqlite3.connect(self.db_path, timeout=30, isolation_level=None)
        c.text_factory = _safe_decode
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("PRAGMA busy_timeout=10000")
        return c

    # ══════════════════════════════════════════════════════
    # COOKIE HEALTH CHECK
    # ══════════════════════════════════════════════════════
    def check_cookies(self, platform):
        """Return (ok: bool, msg: str)."""
        if platform == "instagram":
            return self._check_ig_cookies()
        elif platform == "tiktok":
            return self._check_tt_cookies()
        elif platform == "facebook":
            return self._check_fb_cookies()
        return False, f"Platform belum didukung: {platform}"

    def _check_ig_cookies(self):
        """Cek IG session dengan Selenium — LEBIH KETAT."""
        print("🍪 Cek cookies Instagram...", flush=True)
        try:
            from instagram.config import InstagramConfig
            from instagram.extractor import InstagramExtractor

            cfg = InstagramConfig()
            if not cfg.is_valid():
                return False, "Sessionid kosong — isi cookies di Settings Wails"

            driver = InstagramExtractor.create_driver(headless=True)
            try:
                InstagramExtractor.setup_with_cookies(driver, cfg)

                # STEP 1: /direct/inbox/ — WAJIB login
                driver.get("https://www.instagram.com/direct/inbox/")
                time.sleep(4)

                url = (driver.current_url or "").lower()

                if "accounts/login" in url or "/login" in url:
                    return False, "Session expired — perlu login ulang di browser"
                if "challenge" in url:
                    return False, "Akun kena challenge — selesaikan verifikasi di browser"

                if "/direct/" in url or "/direct/inbox" in url:
                    body = (driver.page_source or "").lower()
                    if "messages" in body or "inbox" in body or "chat" in body:
                        return True, "Cookies Instagram valid ✅ (via DM)"

                # STEP 2: Fallback API
                driver.get("https://www.instagram.com/")
                time.sleep(2)
                api_url = "https://www.instagram.com/api/v1/users/web_profile_info/?username=instagram"
                driver.get(api_url)
                time.sleep(3)

                api_url_current = (driver.current_url or "").lower()
                api_body = (driver.page_source or "")

                if "accounts/login" in api_url_current:
                    return False, "Session expired (API redirect to login)"
                if '"data"' in api_body and '"user"' in api_body:
                    return True, "Cookies Instagram valid ✅ (via API)"

                # STEP 3: Login wall check
                driver.get("https://www.instagram.com/")
                time.sleep(2)
                body = (driver.page_source or "").lower()

                markers = [
                    "log in to instagram",
                    "sign up to see photos",
                    "sign up to like",
                    "log in with facebook",
                    "forgot password?",
                ]
                for marker in markers:
                    if marker in body:
                        return False, "Session expired (login wall)"

                if cfg.username:
                    if cfg.username.lower() in body:
                        return True, f"Cookies valid (user: {cfg.username}) ✅"

                return False, "Tidak bisa verifikasi session — update cookies"
            finally:
                try:
                    driver.quit()
                except Exception:
                    pass
        except Exception as e:
            return False, f"Error cek cookies: {str(e)[:150]}"

    def _check_tt_cookies(self):
        """Cek TikTok cookies via HTTP."""
        print("🍪 Cek cookies TikTok...", flush=True)
        try:
            import requests
            from tiktok.config import TikTokConfig
            from shared.paths import TIKTOK_COOKIES

            cfg = TikTokConfig()

            cookie_str = ""
            if os.path.exists(TIKTOK_COOKIES):
                try:
                    with open(TIKTOK_COOKIES, "r", encoding="utf-8") as f:
                        for line in f:
                            if line.startswith("#") or not line.strip():
                                continue
                            parts = line.strip().split("\t")
                            if len(parts) >= 7:
                                cookie_str += f"{parts[5]}={parts[6]}; "
                except Exception:
                    pass

            if not cookie_str:
                ok, msg = cfg.generate_netscape()
                if not ok:
                    return False, f"Gagal generate cookies: {msg}"
                if os.path.exists(TIKTOK_COOKIES):
                    with open(TIKTOK_COOKIES, "r", encoding="utf-8") as f:
                        for line in f:
                            if line.startswith("#") or not line.strip():
                                continue
                            parts = line.strip().split("\t")
                            if len(parts) >= 7:
                                cookie_str += f"{parts[5]}={parts[6]}; "

            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                              "AppleWebKit/537.36 (KHTML, like Gecko) "
                              "Chrome/131.0.0.0 Safari/537.36",
                "Accept": "application/json, text/plain, */*",
                "Accept-Language": "en-US,en;q=0.9",
                "Cookie": cookie_str.strip() if cookie_str else "",
            }

            r = requests.get(
                "https://www.tiktok.com/api/user/detail/?uniqueId=tiktok&aid=1988",
                headers=headers,
                timeout=10,
            )

            if r.status_code == 200:
                try:
                    data = r.json()
                    if data.get("userInfo") or data.get("statusCode") == 0:
                        return True, "Cookies TikTok valid ✅"
                except Exception:
                    pass

            if r.status_code in (401, 403):
                return False, "Cookies TikTok expired atau invalid"

            return True, f"Cookies ada (status HTTP {r.status_code})"
        except Exception as e:
            return False, f"Error cek TikTok cookies: {str(e)[:150]}"

    def _check_fb_cookies(self):
        """Cek Facebook cookies — generate netscape + validate."""
        print("🍪 Cek cookies Facebook...", flush=True)
        try:
            from facebook.config import FacebookConfig

            cfg = FacebookConfig()
            if not cfg.is_valid():
                return False, "Cookies Facebook kosong — butuh c_user + xs"

            ok, msg = cfg.generate_netscape()
            if not ok:
                return False, f"Gagal generate cookies: {msg}"

            print(f"   {msg}", flush=True)
            return True, "Cookies Facebook siap ✅"
        except Exception as e:
            return False, f"Error cek Facebook cookies: {str(e)[:150]}"

    # ══════════════════════════════════════════════════════
    # MODE 1: MANUAL
    # ══════════════════════════════════════════════════════
    def run_manual(self):
        platform = self.config.get("platform", "instagram").lower()
        usernames = self.config.get("usernames", [])
        quality = self.config.get("quality", "hd")
        delay = float(self.config.get("delay", 2.0))
        use_archive = bool(self.config.get("use_archive", True))
        max_workers = int(self.config.get("max_workers", 1))

        if platform == "facebook":
            items = [u.strip() for u in usernames if u and u.strip().startswith("http")]
            items = list(dict.fromkeys(items))
        else:
            items = [u.strip().lstrip("@") for u in usernames if u and u.strip()]

        print("=" * 60, flush=True)
        print(f"📥 Manual Download Worker", flush=True)
        print(f"🎯 Platform: {platform.upper()}", flush=True)
        print(f"👤 Total item: {len(items)}", flush=True)
        print(f"⚙️  Quality: {quality} | Delay: {delay}s", flush=True)
        print("=" * 60, flush=True)
        print("", flush=True)

        if not items:
            print("❌ Tidak ada item yang valid", flush=True)
            return

        cookie_ok, cookie_msg = self.check_cookies(platform)
        if not cookie_ok:
            print("", flush=True)
            print("=" * 60, flush=True)
            print(f"❌ {cookie_msg}", flush=True)
            print("=" * 60, flush=True)
            print("", flush=True)
            print("💡 Solusi:", flush=True)
            if platform == "instagram":
                print("   1. Buka instagram.com di browser (login)", flush=True)
                print("   2. Selesaikan challenge/verifikasi kalau ada", flush=True)
                print("   3. Copy sessionid dari cookies (F12 → Application → Cookies)", flush=True)
                print("   4. Update di Settings Wails → Instagram", flush=True)
            elif platform == "tiktok":
                print("   1. Login TikTok di browser", flush=True)
                print("   2. Copy cookies (F12 → Application → Cookies)", flush=True)
                print("   3. Update di Settings Wails → TikTok", flush=True)
            elif platform == "facebook":
                print("   1. Login Facebook di browser", flush=True)
                print("   2. Copy c_user, xs dari cookies (F12 → Application → Cookies)", flush=True)
                print("   3. Update di Settings Wails → Facebook", flush=True)
            print("", flush=True)
            return
        print(f"   {cookie_msg}", flush=True)
        print("", flush=True)

        success = 0
        failed = 0
        errors = []

        for idx, item in enumerate(items, 1):
            if self.stop:
                print("", flush=True)
                print("⏸️  Stop requested oleh user", flush=True)
                break

            print("", flush=True)
            print("─" * 60, flush=True)
            if platform == "facebook":
                print(f"▶️  [{idx}/{len(items)}] {item}", flush=True)
            else:
                print(f"▶️  [{idx}/{len(items)}] @{item}", flush=True)
            print("─" * 60, flush=True)

            try:
                if platform == "instagram":
                    self._download_ig_user(item, delay, max_workers)
                elif platform == "tiktok":
                    self._download_tt_user(item, quality, use_archive)
                elif platform == "facebook":
                    self._download_fb_page(item, quality)
                else:
                    print(f"   ⚠️  Platform belum didukung: {platform}", flush=True)
                    continue

                success += 1
                print(f"   ✅ Selesai", flush=True)

            except Exception as e:
                failed += 1
                err = str(e)[:200]
                errors.append(f"{item}: {err}")
                print(f"   ❌ ERROR: {err}", flush=True)

            if idx < len(items) and not self.stop:
                print(f"   ⏸️  Menunggu {delay:.0f}s sebelum item berikutnya...",
                      flush=True)
                time.sleep(delay)

        print("", flush=True)
        print("=" * 60, flush=True)
        print("✅ SELESAI", flush=True)
        print(f"   Berhasil: {success}/{len(items)}", flush=True)
        print(f"   Gagal:    {failed}/{len(items)}", flush=True)
        if errors:
            print(f"   Error ({len(errors)}):", flush=True)
            for e in errors[:10]:
                print(f"     • {e}", flush=True)
            if len(errors) > 10:
                print(f"     ... (+{len(errors)-10} lagi)", flush=True)
        print("=" * 60, flush=True)

    # ─── INSTAGRAM ───
    def _download_ig_user(self, username, delay=2.0, max_workers=1):
        from instagram.extractor import InstagramExtractor
        from instagram.downloader import InstagramDownloader
        from instagram.config import InstagramConfig

        print(f"   📷 Instagram: @{username}", flush=True)

        cached = InstagramExtractor.load_cached_shortcodes(username)
        print(f"      📚 Cache: {len(cached)} shortcode lama", flush=True)

        cfg = InstagramConfig()
        driver = InstagramExtractor.create_driver(headless=True)
        try:
            InstagramExtractor.setup_with_cookies(driver, cfg)
            extractor = InstagramExtractor(
                driver,
                on_log=lambda m: print(f"      {m}", flush=True),
                on_progress=lambda c, t, m: None,
            )
            result = extractor.extract_user(username, cached_codes=cached)
        finally:
            try:
                driver.quit()
            except Exception:
                pass

        if not result.get("success"):
            raise Exception(result.get("error", "extract failed"))

        shortcodes = result.get("links", [])
        cached_set = set(cached)
        new_codes = [sc for sc in shortcodes if sc not in cached_set]

        print(f"      Total post: {len(shortcodes)} | Baru: {len(new_codes)}",
              flush=True)

        if not new_codes:
            print(f"      ⏭️  Tidak ada post baru", flush=True)
            return

        InstagramExtractor.save_results(username, shortcodes, result.get("stats"))

        InstagramDownloader.download_user(
            shortcodes, username, cfg,
            max_workers=max_workers,
            download_delay=delay,
        )

    # ─── TIKTOK ───
    def _download_tt_user(self, username, quality="hd", use_archive=True):
        from tiktok.downloader import (
            TikTokDownloader,
            _resolve_effective_url,
        )

        print(f"   🎵 TikTok: @{username}", flush=True)

        url = TikTokDownloader.normalize_url("@" + username)

        # ⚡ Resolve sec_uid cache untuk archive counter yang konsisten
        effective_url, uname = _resolve_effective_url(url)

        exists_before, count_before, _ = TikTokDownloader.get_archive_info(effective_url)
        if effective_url != url:
            print(f"      🎯 Pakai sec_uid cache (archive: {count_before})", flush=True)
        else:
            print(f"      📚 Archive: {count_before} video", flush=True)

        ok = TikTokDownloader.download(
            url,
            quality=quality,
            use_archive=use_archive,
            on_log=lambda m: print(f"      {m}", flush=True),
        )

        exists_after, count_after, _ = TikTokDownloader.get_archive_info(effective_url)
        new_found = max(0, count_after - count_before)
        print(f"      ✅ Baru: {new_found} video", flush=True)

    # ─── FACEBOOK ───
    def _download_fb_page(self, page_url, quality="hd"):
        """
        Download semua reel dari Facebook Page.
        1. Enumerate dengan Selenium
        2. Download dengan yt-dlp
        """
        from facebook.enumerator import FacebookEnumerator
        from facebook.downloader import FacebookDownloader
        from facebook.config import FacebookConfig

        print(f"   📘 Facebook Page: {page_url}", flush=True)

        cfg = FacebookConfig()
        if not cfg.is_valid():
            raise Exception("Cookies Facebook kosong")

        # ═══ 1. ENUMERATE ═══
        print(f"      🔍 Enumerate video dari Page...", flush=True)

        driver = FacebookEnumerator.create_driver(headless=True)
        try:
            FacebookEnumerator.setup_with_cookies(driver, cfg)
            enumerator = FacebookEnumerator(
                driver,
                stop_event=self.stop,
                on_log=lambda m: print(f"      {m}", flush=True),
                on_progress=lambda c, t, m: None,
            )
            video_urls = enumerator.enumerate_page(
                page_url,
                max_scrolls=2000,
                scroll_delay=2.0,
            )
        finally:
            try:
                driver.quit()
            except Exception:
                pass

        if not video_urls:
            print(f"      ⚠️  Tidak ada video ditemukan", flush=True)
            return

        print(f"      ✅ {len(video_urls)} reel ditemukan", flush=True)

        # ═══ 2. DOWNLOAD ═══
        FacebookDownloader.download_multiple(
            video_urls,
            quality=quality,
            delay=3.0,
            stop_event=self.stop,
            on_log=lambda m: print(f"      {m}", flush=True),
            on_progress=lambda p, m: None,
        )

    # ══════════════════════════════════════════════════════
    # MODE 2: GROUP
    # ══════════════════════════════════════════════════════
    def run_group(self):
        group_id = int(self.config.get("group_id", 0))
        platforms = self.config.get("platforms", [])
        delay = float(self.config.get("delay", 1.0))

        print("=" * 60, flush=True)
        print(f"👥 Group Download Worker", flush=True)
        print(f"📁 Group ID: {group_id}", flush=True)
        print(f"🎯 Platform: {', '.join(platforms)}", flush=True)
        print("=" * 60, flush=True)
        print("", flush=True)

        # COOKIE HEALTH CHECK per platform
        for plat in platforms:
            ok, msg = self.check_cookies(plat)
            if not ok:
                print("", flush=True)
                print("=" * 60, flush=True)
                print(f"❌ {plat.upper()}: {msg}", flush=True)
                print("=" * 60, flush=True)
                print("   Group download dibatalkan.", flush=True)
                return
            print(f"   {plat.upper()}: {msg}", flush=True)
        print("", flush=True)

        accounts = self._get_group_accounts(group_id, platforms)
        total = len(accounts)

        if total == 0:
            print("⚠️  Tidak ada akun aktif untuk di-proses", flush=True)
            return

        self.run_id = self._create_run(group_id, total)

        checked = 0
        new_found = 0
        new_downloaded = 0
        errors = []

        for idx, (acc_id, platform, username, member_name) in enumerate(accounts, 1):
            if self.stop:
                print("", flush=True)
                print("⏸️  Stop requested", flush=True)
                break

            print("", flush=True)
            print(f"▶️  [{idx}/{total}] {member_name} — @{username}", flush=True)
            print("─" * 55, flush=True)

            try:
                if platform == "instagram":
                    _, nf, nd = self._process_group_ig(username)
                elif platform == "tiktok":
                    _, nf, nd = self._process_group_tt(username)
                else:
                    print(f"   ⚠️  Platform belum didukung: {platform}", flush=True)
                    continue

                checked += 1
                new_found += nf
                new_downloaded += nd
                self._mark_checked(acc_id, had_new=(nd > 0))
                self._update_run(checked, new_found, new_downloaded)

                if nd > 0:
                    print(f"   ✅ Selesai — {nd} post baru diunduh", flush=True)
                else:
                    print(f"   ⏭️  Tidak ada post baru", flush=True)

            except Exception as e:
                err = str(e)[:200]
                errors.append(f"{member_name}/{platform}/@{username}: {err}")
                print(f"   ❌ ERROR: {err}", flush=True)

            if idx < total and not self.stop:
                time.sleep(delay)

        final_status = "done" if not self.stop else "cancelled"
        self._finalize_run(final_status, checked, new_found, new_downloaded, errors)

        print("", flush=True)
        print("=" * 60, flush=True)
        print("✅ SELESAI", flush=True)
        print(f"   Akun dicek:    {checked}/{total}", flush=True)
        print(f"   Post baru:     {new_found}", flush=True)
        print(f"   Post diunduh:  {new_downloaded}", flush=True)
        if errors:
            print(f"   Error:         {len(errors)}", flush=True)
        print("=" * 60, flush=True)

    def _process_group_ig(self, username):
        from instagram.extractor import InstagramExtractor
        from instagram.downloader import InstagramDownloader
        from instagram.config import InstagramConfig

        cached = InstagramExtractor.load_cached_shortcodes(username)
        print(f"      📚 Cache: {len(cached)} shortcode lama", flush=True)

        cfg = InstagramConfig()
        driver = InstagramExtractor.create_driver(headless=True)
        try:
            InstagramExtractor.setup_with_cookies(driver, cfg)
            extractor = InstagramExtractor(
                driver,
                on_log=lambda m: print(f"      {m}", flush=True),
                on_progress=lambda c, t, m: None,
            )
            result = extractor.extract_user(username, cached_codes=cached)
        finally:
            try:
                driver.quit()
            except Exception:
                pass

        if not result.get("success"):
            raise Exception(result.get("error", "extract failed"))

        shortcodes = result.get("links", [])
        cached_set = set(cached)
        new_codes = [sc for sc in shortcodes if sc not in cached_set]
        print(f"      Total post: {len(shortcodes)} | Baru: {len(new_codes)}",
              flush=True)

        if not new_codes:
            return True, 0, 0

        InstagramExtractor.save_results(username, shortcodes, result.get("stats"))
        InstagramDownloader.download_user(
            shortcodes, username, cfg,
            max_workers=1,
            download_delay=0.5,
        )
        return True, len(new_codes), len(new_codes)

    def _process_group_tt(self, username):
        from tiktok.downloader import (
            TikTokDownloader,
            _resolve_effective_url,
        )

        url = TikTokDownloader.normalize_url("@" + username)

        # ⚡ Resolve sec_uid cache
        effective_url, uname = _resolve_effective_url(url)

        exists_before, count_before, _ = TikTokDownloader.get_archive_info(effective_url)
        if effective_url != url:
            print(f"      🎯 Pakai sec_uid cache (archive: {count_before})", flush=True)
        else:
            print(f"      📚 Archive: {count_before} video", flush=True)

        ok = TikTokDownloader.download(
            url, quality="hd", use_archive=True,
            on_log=lambda m: print(f"      {m}", flush=True),
        )

        exists_after, count_after, _ = TikTokDownloader.get_archive_info(effective_url)
        new_found = max(0, count_after - count_before)
        print(f"      Baru: {new_found} video", flush=True)
        return bool(ok), new_found, new_found

    def _get_group_accounts(self, group_id, platforms):
        ids = [group_id]
        with self.conn() as c:
            stack = [group_id]
            while stack:
                cur = stack.pop()
                for (child_id,) in c.execute(
                    "SELECT id FROM idol_groups WHERE parent_id = ?", (cur,)
                ).fetchall():
                    ids.append(child_id)
                    stack.append(child_id)

            if not platforms:
                return []

            ph1 = ",".join("?" * len(ids))
            ph2 = ",".join("?" * len(platforms))
            return c.execute(f"""
                SELECT a.id, a.platform, a.username, g.name
                FROM idol_accounts a
                JOIN idol_groups g ON a.group_id = g.id
                WHERE a.group_id IN ({ph1})
                  AND a.enabled = 1
                  AND a.platform IN ({ph2})
                ORDER BY g.sort_order, g.name, a.platform
            """, ids + platforms).fetchall()

    def _create_run(self, group_id, total):
        with self.conn() as c:
            cur = c.execute("""
                INSERT INTO idol_group_runs
                (group_id, status, total_accounts, started_at)
                VALUES (?, 'running', ?, datetime('now'))
            """, (group_id, total))
            return cur.lastrowid

    def _update_run(self, checked, new_found, new_downloaded):
        if not self.run_id:
            return
        with self.conn() as c:
            c.execute("""
                UPDATE idol_group_runs
                SET checked_accounts = ?,
                    new_posts_found = ?,
                    new_posts_downloaded = ?
                WHERE id = ?
            """, (checked, new_found, new_downloaded, self.run_id))

    def _finalize_run(self, status, checked, new_found, new_downloaded, errors):
        if not self.run_id:
            return
        with self.conn() as c:
            c.execute("""
                UPDATE idol_group_runs
                SET status = ?,
                    checked_accounts = ?,
                    new_posts_found = ?,
                    new_posts_downloaded = ?,
                    error = ?,
                    finished_at = datetime('now')
                WHERE id = ?
            """, (status, checked, new_found, new_downloaded,
                  "\n".join(errors[:20]) if errors else "",
                  self.run_id))

    def _mark_checked(self, acc_id, had_new=False):
        with self.conn() as c:
            if had_new:
                c.execute("""
                    UPDATE idol_accounts
                    SET last_check_at = datetime('now'),
                        last_download_at = datetime('now')
                    WHERE id = ?
                """, (acc_id,))
            else:
                c.execute("""
                    UPDATE idol_accounts SET last_check_at = datetime('now')
                    WHERE id = ?
                """, (acc_id,))


# ══════════════════════════════════════════════════════════
# ENTRY
# ══════════════════════════════════════════════════════════
def main():
    if len(sys.argv) < 3:
        print("Usage: python download_worker.py <mode> '<json_config>'", flush=True)
        print("  mode: manual | group", flush=True)
        sys.exit(1)

    mode = sys.argv[1].lower()
    if mode not in ("manual", "group"):
        print(f"❌ Mode tidak valid: {mode}", flush=True)
        sys.exit(1)

    try:
        config = json.loads(sys.argv[2])
    except Exception as e:
        print(f"❌ Config JSON tidak valid: {e}", flush=True)
        sys.exit(1)

    db = find_db()
    if not db:
        print("❌ media_library.db tidak ditemukan di:", flush=True)
        for p in DB_CANDIDATES:
            print(f"   - {p}", flush=True)
        sys.exit(1)

    print(f"🔧 DB: {db}", flush=True)
    print("", flush=True)

    worker = DownloadWorker(db, mode, config)

    def handler(sig, frame):
        print("", flush=True)
        print("⏸️  Stop signal received", flush=True)
        worker.stop = True

    signal.signal(signal.SIGINT, handler)
    signal.signal(signal.SIGTERM, handler)

    try:
        if mode == "manual":
            worker.run_manual()
        elif mode == "group":
            worker.run_group()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()