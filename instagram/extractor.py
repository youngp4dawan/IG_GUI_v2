"""
Instagram Extractor — extract shortcode via Selenium.
Download logic ada di instagram/downloader.py (dipisah).
"""
import os
import re
import shutil
import subprocess
import threading
import time

from shared.paths import DATA_INSTAGRAM_LINKS
from shared.utils import ensure_dirs, current_time, USER_AGENT
from shared.config import save_json
from shared.logger import log
from instagram.constants import (
    BLOCK_RESOURCES, DISABLE_ANIMATIONS,
    SCROLL_DELAY_MIN, SCROLL_DELAY_MAX,
    SCROLL_STALL_LIMIT, SCROLL_STALL_LIMIT_SMALL, SMALL_USER_THRESHOLD,
    SCROLL_STALL_TIMEOUT, SCROLL_POLL_INTERVAL,
    PAGE_LOAD_TIMEOUT, INITIAL_WAIT,
    MAX_SCROLLS_PROFILE, MAX_SCROLLS_REELS, SKIP_REELS_RATIO,
    SHORTCODE_PATTERN,
)


# ============================================================
# SELENIUM EXTRACTOR
# ============================================================
_DRIVER_PATH = None
_DRIVER_LOCK = threading.Lock()


def _get_driver_path():
    global _DRIVER_PATH
    with _DRIVER_LOCK:
        if _DRIVER_PATH is None:
            from webdriver_manager.chrome import ChromeDriverManager
            _DRIVER_PATH = ChromeDriverManager().install()
        return _DRIVER_PATH


class InstagramExtractor:
    JS_QUERY = """
        return Array.from(document.querySelectorAll(
            'a[href*="/p/"], a[href*="/reel/"]'
        )).map(a => a.getAttribute('href'));
    """
    JS_COUNT_LINKS = """
        return document.querySelectorAll('a[href*="/p/"], a[href*="/reel/"]').length;
    """
    JS_FEED_ENDED = """
        const text = document.body.innerText || '';
        return text.includes("You've seen all") || text.includes("No more posts") || text.includes("end of feed");
    """
    JS_SCROLL_TO_BOTTOM = """
        var links = document.querySelectorAll('a[href*="/p/"], a[href*="/reel/"]');
        if (links.length > 0) {
            links[links.length - 1].scrollIntoView({behavior: 'instant', block: 'end'});
        } else {
            window.scrollTo(0, document.body.scrollHeight);
        }
    """
    JS_DISABLE_ANIMATIONS = """
        if (document.getElementById('__ig_speedup')) return true;
        var style = document.createElement('style');
        style.id = '__ig_speedup';
        style.textContent = `*, *::before, *::after { animation-duration: 0s !important; transition-duration: 0s !important; } html { scroll-behavior: auto !important; }`;
        document.head.appendChild(style);
        return true;
    """
    JS_GET_SHARED_DATA = """
        var scripts = document.querySelectorAll('script');
        for (var i = 0; i < scripts.length; i++) {
            var txt = scripts[i].textContent || '';
            var m = txt.match(/window\\._sharedData\\s*=\\s*(\\{.+?\\});/);
            if (m) { try { return JSON.parse(m[1]); } catch(e) {} }
        }
        return null;
    """
    JS_CHECK_LOGIN_WALL = """
        var url = window.location.href;
        if (url.indexOf('/accounts/login') >= 0) return 'login';
        if (url.indexOf('/challenge') >= 0) return 'challenge';
        var text = document.body ? document.body.innerText : '';
        if (text.indexOf("Sorry, this page isn't available") >= 0) return 'notfound';
        return null;
    """
    JS_GET_HEADER_COUNT = """
        var headers = document.querySelectorAll('header, main, section');
        for (var i = 0; i < headers.length; i++) {
            var text = headers[i].innerText || '';
            var m = text.match(/([\\d][\\d,\\.]*)\\s+posts?/i);
            if (m) { var n = parseInt(m[1].replace(/[,.]/g, ''), 10); if (n > 0) return n; }
            m = text.match(/([\\d][\\d.,]*)\\s+kiriman/i);
            if (m) { var n2 = parseInt(m[1].replace(/[,.]/g, ''), 10); if (n2 > 0) return n2; }
        }
        return null;
    """

    def __init__(self, driver, stop_event=None, on_log=None, on_progress=None):
        self.driver = driver
        self.stop_event = stop_event or threading.Event()
        self.on_log = on_log or (lambda msg: None)
        self.on_progress = on_progress or (lambda cur, tot, msg: None)

    # ── DRIVER SETUP ──
    @staticmethod
    def create_driver(headless=True):
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options
        from selenium.webdriver.chrome.service import Service

        opts = Options()
        if headless:
            opts.add_argument("--headless=new")
        opts.add_argument("--no-sandbox")
        opts.add_argument("--disable-dev-shm-usage")
        opts.add_argument("--disable-blink-features=AutomationControlled")
        opts.add_argument("--window-size=1920,1080")
        opts.add_argument(f"user-agent={USER_AGENT}")
        opts.add_argument("--log-level=3")
        opts.add_argument("--disable-logging")
        opts.add_argument("--disable-gpu")
        opts.add_argument("--disable-extensions")
        opts.add_argument("--disable-background-networking")
        opts.add_argument("--no-first-run")
        opts.add_experimental_option("excludeSwitches", ["enable-logging", "enable-automation"])
        opts.add_experimental_option("useAutomationExtension", False)

        prefs = {
            "profile.managed_default_content_settings.images": 2,
            "profile.managed_default_content_settings.media_stream": 2,
        }
        opts.add_experimental_option("prefs", prefs)

        service = Service(_get_driver_path(), log_output=subprocess.DEVNULL)
        driver = webdriver.Chrome(service=service, options=opts)

        driver.execute_cdp_cmd(
            "Page.addScriptToEvaluateOnNewDocument",
            {"source": "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"},
        )

        if BLOCK_RESOURCES:
            try:
                driver.execute_cdp_cmd("Network.enable", {})
                driver.execute_cdp_cmd("Network.setBlockedURLs", {"urls": [
                    "*.jpg", "*.jpeg", "*.png", "*.gif", "*.webp", "*.svg", "*.ico",
                    "*.mp4", "*.webm", "*.mkv", "*.mov",
                    "*.mp3", "*.m4a", "*.ogg", "*.wav",
                    "*.woff", "*.woff2", "*.ttf", "*.eot", "*.otf",
                    "*google-analytics*", "*googletagmanager*", "*doubleclick*",
                ]})
            except Exception:
                pass

        return driver

    @staticmethod
    def setup_with_cookies(driver, config):
        from selenium.webdriver.support.ui import WebDriverWait
        driver.get("https://www.instagram.com")
        try:
            WebDriverWait(driver, 10).until(lambda d: d.execute_script("return document.body !== null"))
        except Exception:
            pass
        time.sleep(0.5)

        for c in config.get_cookies_list():
            try:
                driver.add_cookie(c)
            except Exception:
                pass

        driver.refresh()
        try:
            WebDriverWait(driver, 10).until(lambda d: d.execute_script("return document.body !== null"))
        except Exception:
            pass
        time.sleep(0.5)
        return driver

    # ── HELPERS ──
    def _inject_animations_off(self):
        if not DISABLE_ANIMATIONS:
            return
        try:
            self.driver.execute_script(self.JS_DISABLE_ANIMATIONS)
        except Exception:
            pass

    def _check_login_wall(self):
        try:
            return self.driver.execute_script(self.JS_CHECK_LOGIN_WALL)
        except Exception:
            return None

    def _get_shared_data(self):
        try:
            return self.driver.execute_script(self.JS_GET_SHARED_DATA)
        except Exception:
            return None

    def _get_header_count(self):
        try:
            count = self.driver.execute_script(self.JS_GET_HEADER_COUNT)
            return int(count) if count else 0
        except Exception:
            return 0

    def _extract_shortcodes_js(self):
        try:
            hrefs = self.driver.execute_script(self.JS_QUERY) or []
        except Exception:
            return set()
        return {m.group(2) for h in hrefs for m in [re.search(SHORTCODE_PATTERN, h or "")] if m}

    def _count_dom_links(self):
        try:
            return self.driver.execute_script(self.JS_COUNT_LINKS) or 0
        except Exception:
            return 0

    def _wait_for_content_ready(self, timeout=PAGE_LOAD_TIMEOUT):
        try:
            from selenium.webdriver.support.ui import WebDriverWait
            WebDriverWait(self.driver, timeout).until(
                lambda d: d.execute_script(
                    "return document.querySelectorAll('a[href*=\"/p/\"], a[href*=\"/reel/\"]').length > 0"
                )
            )
            return True
        except Exception:
            return False

    def _scroll_and_wait(self, current_count):
        try:
            self.driver.execute_script(self.JS_SCROLL_TO_BOTTOM)
        except Exception:
            return current_count

        elapsed = 0.0
        last_dom = current_count
        while elapsed < SCROLL_DELAY_MAX:
            time.sleep(SCROLL_POLL_INTERVAL)
            elapsed += SCROLL_POLL_INTERVAL
            dom_count = self._count_dom_links()
            if dom_count > last_dom:
                time.sleep(SCROLL_DELAY_MIN)
                break
            last_dom = dom_count
        return self._count_dom_links()

    # ══════════════════════════════════════════════════════
    # SCROLL EXTRACT (dengan incremental early-stop)
    # ══════════════════════════════════════════════════════
    def _scroll_extract(self, url, page_type, max_scrolls, username="", header_count=0,
                        cached_codes=None, expected_new=0):
        """
        Scroll halaman dan kumpulkan shortcode.
        - cached_codes : set shortcode yang sudah diketahui (untuk hitung 'baru')
        - expected_new : jumlah post baru yang diharapkan; kalau ketemu → stop awal
        """
        cached_codes = cached_codes or set()
        all_links = set()
        if self.stop_event.is_set():
            return all_links

        try:
            self.driver.get(url)
        except Exception as e:
            log.warning("Buka %s gagal: %s", url, e)
            return None

        time.sleep(1)
        wall = self._check_login_wall()
        if wall == "login":
            self.on_log("🔴 LOGIN WALL — session expired! Update cookies di Settings.")
            return None
        if wall == "challenge":
            self.on_log("🔴 CHALLENGE — akun perlu verifikasi di browser")
            return None
        if wall == "notfound":
            self.on_log("❌ Profile tidak ditemukan / 404")
            return None

        self._inject_animations_off()

        if not self._wait_for_content_ready(timeout=PAGE_LOAD_TIMEOUT):
            return None

        time.sleep(INITIAL_WAIT)

        all_links |= self._extract_shortcodes_js()
        initial_count = len(all_links)

        if header_count > 0 and initial_count >= header_count:
            self.on_log(f"   ⚡ Semua post sudah ter-load ({initial_count}/{header_count})")
            return all_links

        stall_limit = SCROLL_STALL_LIMIT_SMALL if (0 < header_count < SMALL_USER_THRESHOLD) else SCROLL_STALL_LIMIT

        last_count = initial_count
        last_new_time = time.time()
        stall_count = 0
        stop_reason = "max_scrolls"

        for i in range(1, max_scrolls + 1):
            if self.stop_event.is_set():
                stop_reason = "user stop"
                break

            all_links |= self._extract_shortcodes_js()
            cur = len(all_links)

            self.on_progress(cur, header_count or max_scrolls, f"{page_type} #{i}")

            # ── EARLY STOP: incremental mode ──
            if cached_codes and expected_new > 0:
                new_found = len(all_links - cached_codes)
                if new_found >= expected_new:
                    stop_reason = f"incremental selesai ({new_found}/{expected_new} baru)"
                    break

            if header_count > 0 and cur >= header_count:
                stop_reason = f"semua post didapat ({cur}/{header_count})"
                break

            feed_ended = False
            try:
                feed_ended = self.driver.execute_script(self.JS_FEED_ENDED)
            except Exception:
                pass

            if cur > last_count:
                stall_count = 0
                last_new_time = time.time()
            else:
                stall_count += 1
                elapsed = time.time() - last_new_time
                if stall_count >= stall_limit:
                    stop_reason = f"{stall_count} stall"
                    break
                if elapsed >= SCROLL_STALL_TIMEOUT:
                    stop_reason = f"no new {elapsed:.0f}s"
                    break
                if feed_ended and stall_count >= 2:
                    stop_reason = "feed ended"
                    break

            last_count = cur
            self._scroll_and_wait(cur)

            if i % 20 == 0:
                self._inject_animations_off()
            if stall_count > 0:
                time.sleep(min(stall_count * 0.4, 2.0))

        self.on_log(f"   ⏹️ Stop: {stop_reason}")
        return all_links

    # ══════════════════════════════════════════════════════
    # EXTRACT USER (dengan cache fast-path)
    # ══════════════════════════════════════════════════════
    def extract_user(self, username, cached_codes=None):
        """
        Extract shortcode. Kalau `cached_codes` diberikan dan sudah lengkap
        (>= header_count), scroll di-skip total.
        """
        cached_codes = set(cached_codes or [])
        result = {
            "username": username, "success": False, "count": 0, "links": [], "error": None,
            "stats": {
                "from_main_profile": 0, "from_reels_tab": 0, "header_count": 0,
                "from_cache": len(cached_codes), "new_found": 0,
            },
        }

        try:
            self.on_log(f"📥 @{username}: Main Profile...")

            header_count = 0
            shared_shortcodes = set()

            # ── Buka profil sekali untuk baca header ──
            try:
                self.driver.get(f"https://www.instagram.com/{username}/")
                time.sleep(2)

                wall = self._check_login_wall()
                if wall in ("login", "challenge", "notfound"):
                    result["error"] = {"login": "Login wall", "challenge": "Challenge",
                                       "notfound": "Not found"}[wall]
                    self.on_log(f"🔴 @{username}: {result['error']}")
                    return result

                self._inject_animations_off()
                header_count = self._get_header_count()

                shared = self._get_shared_data()
                if shared:
                    try:
                        pp = shared.get("entry_data", {}).get("ProfilePage", [{}])
                        if pp:
                            gql = pp[0].get("graphql", {})
                            ud = gql.get("user", {})
                            media = ud.get("edge_owner_to_timeline_media", {})
                            if not header_count:
                                header_count = media.get("count", 0)
                            for edge in media.get("edges", []):
                                sc = edge.get("node", {}).get("shortcode")
                                if sc:
                                    shared_shortcodes.add(sc)
                    except Exception:
                        pass

                if header_count:
                    label = "small" if header_count < SMALL_USER_THRESHOLD else "large"
                    self.on_log(f"   📊 Header: {header_count} post ({label})")
                else:
                    self.on_log("   📊 Header tidak terdeteksi")
            except Exception:
                pass

            result["stats"]["header_count"] = header_count

            # ══════════════════════════════════════════════════
            # FAST PATH: cache lengkap → skip scroll
            # ══════════════════════════════════════════════════
            if cached_codes and header_count > 0 and len(cached_codes) >= header_count:
                self.on_log(f"   ⚡ Cache sudah lengkap "
                            f"({len(cached_codes)}/{header_count}) — skip scroll!")
                result["success"] = True
                result["count"] = len(cached_codes)
                result["links"] = sorted(cached_codes)
                result["stats"]["from_main_profile"] = len(cached_codes)
                return result

            # ══════════════════════════════════════════════════
            # INCREMENTAL: hitung berapa post baru yang harus dicari
            # ══════════════════════════════════════════════════
            expected_new = 0
            if cached_codes and header_count > 0 and header_count > len(cached_codes):
                expected_new = header_count - len(cached_codes)
                self.on_log(f"   🔄 Incremental: cari {expected_new} post baru "
                            f"(cache {len(cached_codes)}/{header_count})")

            main = self._scroll_extract(
                f"https://www.instagram.com/{username}/",
                "Main", MAX_SCROLLS_PROFILE, username, header_count,
                cached_codes=cached_codes, expected_new=expected_new,
            )
            if main is None:
                result["error"] = "Profile error"
                return result

            main |= shared_shortcodes
            # Union dengan cache — supaya post lama yang sudah diketahui tidak hilang
            main |= cached_codes

            result["stats"]["from_main_profile"] = len(main)
            result["stats"]["new_found"] = len(main - cached_codes)

            # ── Reels: skip kalau main sudah cukup ──
            skip_reels = False
            if header_count > 0:
                ratio = len(main) / header_count
                if ratio >= SKIP_REELS_RATIO:
                    skip_reels = True
                    self.on_log(f"   ⏩ Skip reels (main {len(main)}/{header_count} = {ratio*100:.0f}%)")

            if not skip_reels:
                self.on_log(f"🎬 @{username}: Reels Tab...")
                reels = self._scroll_extract(
                    f"https://www.instagram.com/{username}/reels/",
                    "Reels", MAX_SCROLLS_REELS, username, 0,
                    cached_codes=cached_codes, expected_new=0,
                ) or set()
            else:
                reels = set()

            new_reels = reels - main
            result["stats"]["from_reels_tab"] = len(new_reels)
            all_links = main | reels | cached_codes

            result["success"] = True
            result["count"] = len(all_links)
            result["links"] = sorted(all_links)

            new_total = len(all_links - cached_codes)
            ratio = (len(all_links) / header_count * 100) if header_count else 0
            self.on_log(f"🎉 @{username}: {len(all_links)} total "
                        f"(+{new_total} baru) [{ratio:.0f}% dari header]")

        except Exception as e:
            result["error"] = str(e)[:200]
            log.exception("Extract @%s", username)

        return result

    # ── SAVE CACHE ──
    @staticmethod
    def load_cached_shortcodes(username):
        """Baca shortcode dari cache JSON. Return [] kalau tidak ada."""
        from shared.config import load_json
        path = os.path.join(DATA_INSTAGRAM_LINKS, f"@{username}",
                            f"{username}_post_links.json")
        if not os.path.exists(path):
            return []
        try:
            data = load_json(path) or {}
            return data.get("shortcodes", []) or []
        except Exception:
            return []

    @staticmethod
    def save_results(username, shortcodes, stats=None):
        stats = stats or {"from_main_profile": len(shortcodes), "from_reels_tab": 0}
        user_folder = os.path.join(DATA_INSTAGRAM_LINKS, f"@{username}")
        ensure_dirs(user_folder)

        json_data = {
            "username": username,
            "total_posts": len(shortcodes),
            "header_count": stats.get("header_count", 0),
            "extraction_date": current_time(),
            "extraction_stats": stats,
            "links": [f"https://www.instagram.com/p/{sc}/" for sc in shortcodes],
            "shortcodes": shortcodes,
        }
        save_json(os.path.join(user_folder, f"{username}_post_links.json"), json_data)
        return json_data