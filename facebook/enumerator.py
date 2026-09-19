"""
Facebook Page Reels Enumerator (Fixed IIFE Bug)
================================================
Scrape semua reel dari Facebook Page.

Fix history:
- IIFE di JS swallowing return value → pakai top-level return
- Tambah Selenium fallback (find_elements)
- Multi-strategy scroll: CDP mouse wheel + JS increment
- No click() pada body
"""
import re
import time
import threading
from shared.logger import log


class FacebookEnumerator:

    # ══════════════════════════════════════════════════════
    # JS — EXTRACT REEL LINKS (TOP-LEVEL RETURN, no IIFE)
    # ══════════════════════════════════════════════════════
    JS_GET_VIDEO_LINKS = r"""
        var __result = [];
        var __seen = {};
        var __anchors = document.querySelectorAll('a[href*="/reel/"]');
        for (var __i = 0; __i < __anchors.length; __i++) {
            var __href = __anchors[__i].getAttribute('href');
            if (!__href) continue;

            var __m = __href.match(/\/reel\/(\d+)/);
            var __id = null;
            if (__m) {
                __id = __m[1];
            } else {
                var __m2 = __href.match(/\/reels\/(\d+)/);
                if (__m2) __id = __m2[1];
            }

            if (__id && !__seen[__id]) {
                __seen[__id] = true;
                __result.push('https://www.facebook.com/reel/' + __id);
            }
        }
        return __result;
    """

    JS_COUNT = r"""
        return document.querySelectorAll('a[href*="/reel/"]').length;
    """

    JS_SCROLL_TO_LAST = r"""
        var __anchors = document.querySelectorAll('a[href*="/reel/"]');
        var __bestContainer = null;
        var __maxDiff = 0;
        var __all = document.querySelectorAll('div');
        for (var __i = 0; __i < __all.length; __i++) {
            var __el = __all[__i];
            var __s = window.getComputedStyle(__el);
            if (__s.overflowY === 'auto' || __s.overflowY === 'scroll') {
                var __diff = __el.scrollHeight - __el.clientHeight;
                if (__diff > __maxDiff) {
                    __maxDiff = __diff;
                    __bestContainer = __el;
                }
            }
        }

        var __increment = 600;
        var __scrollTarget = document.scrollingElement || document.documentElement || document.body;

        if (__bestContainer && __bestContainer.scrollHeight > __bestContainer.clientHeight) {
            var __before = __bestContainer.scrollTop;
            __bestContainer.scrollTop = Math.min(
                __before + __increment,
                __bestContainer.scrollHeight
            );
            if (__bestContainer.scrollTop === __before) {
                __bestContainer.scrollTop = __bestContainer.scrollHeight;
            }
        }

        try {
            var __wBefore = window.pageYOffset || __scrollTarget.scrollTop;
            __scrollTarget.scrollTop = __wBefore + __increment;
        } catch (e) {}

        try { window.dispatchEvent(new Event('scroll')); } catch (e) {}

        return { success: true, count: __anchors.length };
    """

    def __init__(self, driver, stop_event=None, on_log=None, on_progress=None):
        self.driver = driver
        self.stop_event = stop_event or threading.Event()
        self.on_log = on_log or (lambda m: None)
        self.on_progress = on_progress or (lambda c, t, m: None)

    # ══════════════════════════════════════════════════════
    # DRIVER SETUP
    # ══════════════════════════════════════════════════════
    @staticmethod
    def create_driver(headless=True):
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options
        from selenium.webdriver.chrome.service import Service
        from webdriver_manager.chrome import ChromeDriverManager
        from shared.utils import USER_AGENT
        import subprocess

        opts = Options()
        if headless:
            opts.add_argument("--headless=new")
        opts.add_argument("--no-sandbox")
        opts.add_argument("--disable-dev-shm-usage")
        opts.add_argument("--disable-blink-features=AutomationControlled")
        opts.add_argument("--window-size=1920,1080")
        opts.add_argument(f"--user-agent={USER_AGENT}")
        opts.add_argument("--log-level=3")
        opts.add_argument("--disable-gpu")
        opts.add_argument("--no-first-run")
        opts.add_argument("--lang=en-US")
        opts.add_experimental_option("excludeSwitches", ["enable-logging", "enable-automation"])
        opts.add_experimental_option("useAutomationExtension", False)

        service = Service(ChromeDriverManager().install(), log_output=subprocess.DEVNULL)
        driver = webdriver.Chrome(service=service, options=opts)

        driver.execute_cdp_cmd(
            "Page.addScriptToEvaluateOnNewDocument",
            {"source": "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"},
        )
        return driver

    @staticmethod
    def setup_with_cookies(driver, config):
        from selenium.webdriver.support.ui import WebDriverWait
        driver.get("https://www.facebook.com/")
        try:
            WebDriverWait(driver, 10).until(
                lambda d: d.execute_script("return document.body !== null")
            )
        except Exception:
            pass
        time.sleep(1)

        for c in config.get_cookies_list():
            try:
                driver.add_cookie(c)
            except Exception:
                pass

        driver.refresh()
        try:
            WebDriverWait(driver, 10).until(
                lambda d: d.execute_script("return document.body !== null")
            )
        except Exception:
            pass
        time.sleep(1)
        return driver

    # ══════════════════════════════════════════════════════
    # HELPERS
    # ══════════════════════════════════════════════════════
    def _check_login_wall(self):
        try:
            url = self.driver.current_url.lower()
            if "login" in url or "checkpoint" in url:
                return True
        except Exception:
            pass
        return False

    def _wait_for_content(self, timeout=30):
        for i in range(timeout):
            if self.stop_event.is_set():
                return False
            try:
                count = self.driver.execute_script(self.JS_COUNT) or 0
                if count > 0:
                    return True
            except Exception:
                pass
            time.sleep(1)
        return False

    def _scroll_via_cdp(self, dy=800):
        try:
            size = self.driver.get_window_size()
            cx = size["width"] // 2
            cy = size["height"] // 2

            self.driver.execute_cdp_cmd("Input.dispatchMouseEvent", {
                "type": "mouseWheel",
                "x": cx,
                "y": cy,
                "deltaX": 0,
                "deltaY": dy,
            })
            return True
        except Exception as e:
            log.warning("CDP scroll error: %s", e)
            return False

    def _extract_via_selenium(self):
        """Fallback: extract anchors via Selenium find_elements."""
        from selenium.webdriver.common.by import By
        urls = set()
        try:
            elems = self.driver.find_elements(By.CSS_SELECTOR, 'a[href*="/reel/"]')
            for el in elems:
                href = el.get_attribute("href")
                if not href:
                    continue
                m = re.search(r"/reel/(\d+)", href)
                if m:
                    urls.add(f"https://www.facebook.com/reel/{m.group(1)}")
                    continue
                m = re.search(r"/reels/(\d+)", href)
                if m:
                    urls.add(f"https://www.facebook.com/reel/{m.group(1)}")
        except Exception as e:
            log.warning("Selenium extract error: %s", e)
        return list(urls)

    # ══════════════════════════════════════════════════════
    # MAIN ENUMERATE
    # ══════════════════════════════════════════════════════
    def enumerate_page(self, page_url, max_scrolls=500, scroll_delay=2.5):
        page_url = page_url.rstrip("/")

        if "/reels" in page_url or "/reel/" in page_url or "/videos" in page_url:
            urls_to_try = [page_url]
        else:
            urls_to_try = [
                f"{page_url}/reels",
                f"{page_url}/videos",
            ]

        all_links = set()

        for target_url in urls_to_try:
            if self.stop_event.is_set():
                break

            self.on_log(f"📘 Membuka: {target_url}")

            try:
                self.driver.get(target_url)
            except Exception as e:
                self.on_log(f"❌ Gagal buka: {str(e)[:100]}")
                continue

            time.sleep(5)

            if self._check_login_wall():
                self.on_log("🔴 LOGIN WALL — cookies expired")
                return []

            self.on_log("⏳ Menunggu konten render...")
            if not self._wait_for_content(timeout=30):
                self.on_log("⚠️  Tidak ada reel terdeteksi setelah 30 detik")
                continue

            try:
                init_count = self.driver.execute_script(self.JS_COUNT) or 0
                self.on_log(f"✅ {init_count} reel ter-render — mulai scroll")
            except Exception:
                self.on_log("✅ Konten render — mulai scroll")

            stall_count = 0
            last_count = len(all_links)
            STALL_LIMIT = 15
            last_progress_log = time.time()

            for i in range(1, max_scrolls + 1):
                if self.stop_event.is_set():
                    self.on_log("⏸️ Dihentikan")
                    break

                # ══════════════════════════════════════════════
                # EXTRACT (JS + Selenium fallback)
                # ══════════════════════════════════════════════
                links = []
                try:
                    links = self.driver.execute_script(self.JS_GET_VIDEO_LINKS) or []
                except Exception as e:
                    log.warning("JS extract error: %s", e)

                # Fallback kalau JS return empty
                if not links:
                    links = self._extract_via_selenium()
                    if links and i <= 3:
                        self.on_log(f"   🔧 Fallback Selenium: {len(links)} reel")

                all_links.update(links)

                cur = len(all_links)

                # Debug log tiap 5 scroll
                if i <= 3 or i % 10 == 0:
                    try:
                        dom_count = self.driver.execute_script(self.JS_COUNT) or 0
                        self.on_log(f"   🔍 DOM: {dom_count} anchor, extracted: {len(links)}, total: {cur}")
                    except Exception:
                        pass

                self.on_progress(cur, 0, f"Scroll #{i}")

                if cur > last_count:
                    self.on_log(f"   📊 {cur} reel (scroll #{i})")
                    last_progress_log = time.time()
                elif time.time() - last_progress_log > 12:
                    self.on_log(f"   ⏳ Stuck di {cur} reel (scroll #{i})")
                    last_progress_log = time.time()

                if cur == last_count:
                    stall_count += 1
                    if stall_count >= STALL_LIMIT:
                        self.on_log(f"⏹️ Selesai — {STALL_LIMIT} scroll tanpa reel baru")
                        break
                else:
                    stall_count = 0

                last_count = cur

                # ══════════════════════════════════════════════
                # MULTI-STRATEGY SCROLL
                # ══════════════════════════════════════════════
                self._scroll_via_cdp(dy=800)
                time.sleep(0.4)
                try:
                    self.driver.execute_script(self.JS_SCROLL_TO_LAST)
                except Exception:
                    pass
                time.sleep(0.4)
                self._scroll_via_cdp(dy=600)

                time.sleep(scroll_delay)

                if i % 10 == 0:
                    time.sleep(2)

        self.on_log(f"✅ Total: {len(all_links)} reel ditemukan")
        return sorted(all_links)