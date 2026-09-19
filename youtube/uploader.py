"""
YouTube Uploader — Connect Mode dengan Auto-Launch
====================================================
Auto-launch Chrome debug + persistent session.
Tidak kill Chrome user — hanya chromedriver.
Force re-upload option untuk abaikan history.
"""
import os
import re
import time
import socket
import threading
import subprocess
from pathlib import Path

from shared.paths import YOUTUBE_UPLOAD_HISTORY
from shared.config import load_json, save_json
from shared.utils import current_time
from youtube.config import YouTubeConfig


DEBUG_PORT = 9222
DEBUG_HOST = "127.0.0.1"


# ══════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════
def _human_size(n):
    for unit in ["B", "KB", "MB", "GB"]:
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def _clean_title_from_filename(filename_stem):
    """Hapus prefix angka TikTok ID."""
    cleaned = re.sub(r'^\d{15,}_', '', filename_stem)
    cleaned = cleaned.strip()
    return cleaned if cleaned else filename_stem


def _check_debug_port(host=DEBUG_HOST, port=DEBUG_PORT, timeout=2):
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        result = sock.connect_ex((host, port))
        sock.close()
        return result == 0
    except Exception:
        return False


def check_chrome_debug():
    """Return (success, info) untuk GUI."""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(2)
        result = sock.connect_ex((DEBUG_HOST, DEBUG_PORT))
        sock.close()
        if result == 0:
            return True, f"Chrome debug aktif di port {DEBUG_PORT}"
        return False, "Chrome debug tidak aktif"
    except Exception as e:
        return False, f"Error: {str(e)[:100]}"


def _get_chrome_exe():
    candidates = [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        os.path.expanduser(r"~\AppData\Local\Google\Chrome\Application\chrome.exe"),
    ]
    for c in candidates:
        if os.path.exists(c):
            return c
    return None


def _kill_chromedriver_only():
    """Kill HANYA chromedriver — jangan ganggu Chrome user."""
    for proc in ["chromedriver.exe", "chromedriver"]:
        try:
            subprocess.run(["taskkill", "/F", "/IM", proc, "/T"],
                            capture_output=True, timeout=10)
        except Exception:
            pass


def _kill_chrome_debug_only():
    """Kill HANYA Chrome yang pakai ChromeDebugProfile."""
    debug_profile = os.path.join(os.path.expanduser("~"), "ChromeDebugProfile")

    try:
        result = subprocess.run(
            ["wmic", "process", "where",
             f"name='chrome.exe' and CommandLine like '%ChromeDebugProfile%'",
             "get", "ProcessId"],
            capture_output=True, text=True, timeout=10,
        )
        for line in result.stdout.splitlines():
            line = line.strip()
            if line.isdigit():
                try:
                    subprocess.run(["taskkill", "/F", "/PID", line],
                                    capture_output=True, timeout=5)
                except Exception:
                    pass
    except Exception:
        pass


# ══════════════════════════════════════════════════════════
# AUTO-LAUNCH CHROME DEBUG
# ══════════════════════════════════════════════════════════
def launch_chrome_debug(verbose_callback=None):
    """Auto-launch Chrome debug port 9222."""
    def log(msg):
        if verbose_callback:
            verbose_callback(msg)

    if _check_debug_port():
        log("✅ Chrome debug sudah jalan")
        return True, "OK"

    chrome_exe = _get_chrome_exe()
    if not chrome_exe:
        return False, "Chrome tidak ditemukan"

    debug_profile = os.path.join(os.path.expanduser("~"), "ChromeDebugProfile")
    os.makedirs(debug_profile, exist_ok=True)

    log("🔪 Membersihkan chromedriver lama...")
    _kill_chromedriver_only()
    time.sleep(1)

    # Cek lock file (Chrome mati mendadak)
    lock_file = os.path.join(debug_profile, "SingletonLock")
    if os.path.exists(lock_file):
        log("🔓 Membersihkan Chrome debug yang nyangkut...")
        _kill_chrome_debug_only()
        time.sleep(2)
        for lock in ["SingletonLock", "SingletonCookie", "SingletonSocket"]:
            lf = os.path.join(debug_profile, lock)
            if os.path.exists(lf):
                try:
                    os.remove(lf)
                except Exception:
                    pass

    log("🚀 Membuka Chrome dengan debug port 9222...")
    try:
        creationflags = 0x00000008 | 0x00000200
        subprocess.Popen(
            [
                chrome_exe,
                "--remote-debugging-port=9222",
                f"--user-data-dir={debug_profile}",
                "--no-first-run",
                "--no-default-browser-check",
                "--disable-blink-features=AutomationControlled",
                "https://studio.youtube.com",
            ],
            creationflags=creationflags,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception as e:
        return False, f"Gagal buka Chrome: {str(e)[:150]}"

    log("⏱️ Menunggu Chrome siap (max 30s)...")
    for i in range(30):
        time.sleep(1)
        if _check_debug_port():
            log("✅ Chrome debug aktif!")
            return True, "OK"

    return False, "Chrome tidak siap dalam 30 detik"


def ensure_chrome_debug(verbose_callback=None):
    """Cek + auto-launch. Return (success, was_running, message)."""
    def log(msg):
        if verbose_callback:
            verbose_callback(msg)

    if _check_debug_port():
        return True, True, "Chrome debug sudah jalan"

    log("⚠️ Chrome debug belum jalan")
    log("   Membuka Chrome otomatis...")

    ok, msg = launch_chrome_debug(verbose_callback)
    if not ok:
        return False, False, msg

    log("")
    log("💡 Kalau ini pertama kali:")
    log("   1. Login YouTube di Chrome yang terbuka")
    log("   2. JANGAN tutup Chrome")
    log("   3. Klik Test Login lagi")
    log("")

    return True, False, "Chrome debug baru dibuka"


# ══════════════════════════════════════════════════════════
# UPLOADER CLASS
# ══════════════════════════════════════════════════════════
class YouTubeUploader:

    def __init__(self, config=None, stop_event=None, on_log=None, on_progress=None):
        self.config = config or YouTubeConfig()
        self.stop_event = stop_event or threading.Event()
        self.on_log = on_log or (lambda m: None)
        self.on_progress = on_progress or (lambda c, t, m: None)
        self.driver = None

    def _create_driver(self):
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options
        from selenium.webdriver.chrome.service import Service
        from webdriver_manager.chrome import ChromeDriverManager

        if not _check_debug_port():
            raise Exception("Chrome debug TIDAK jalan di port 9222!")

        self.on_log("✅ Chrome debug terdeteksi")

        opts = Options()
        opts.add_experimental_option("debuggerAddress", f"{DEBUG_HOST}:{DEBUG_PORT}")

        self.on_log("🔌 Connect ke Chrome...")
        try:
            service = Service(ChromeDriverManager().install(), log_output=os.devnull)
            driver = webdriver.Chrome(service=service, options=opts)
            self.on_log("   ✅ Connected!")
        except Exception as e:
            raise Exception(f"Gagal connect: {str(e)[:200]}")

        try:
            driver.set_page_load_timeout(120)
            driver.set_script_timeout(120)
        except Exception:
            pass

        return driver

    def _disconnect(self):
        """⚡ Hanya lepas driver — JANGAN stop service. Chrome tetap hidup."""
        if self.driver:
            self.driver = None

    # ══════════════════════════════════════════════════════
    # LOGIN CHECK
    # ══════════════════════════════════════════════════════
    def check_login(self):
        self.on_log("=" * 55)
        self.on_log("🔍 Cek login YouTube")
        self.on_log("=" * 55)

        ok, was_running, msg = ensure_chrome_debug(verbose_callback=self.on_log)
        if not ok:
            self.on_log(f"❌ {msg}")
            return False

        if not was_running:
            self.on_log("")
            self.on_log("⏸️ Chrome baru dibuka. Login YouTube dulu,")
            self.on_log("   lalu klik Test Login lagi.")
            time.sleep(3)

        try:
            self.driver = self._create_driver()
        except Exception as e:
            self.on_log(f"❌ {str(e)[:300]}")
            return False

        try:
            try:
                current = self.driver.current_url.lower()
            except Exception:
                current = ""

            if "studio.youtube.com" not in current:
                self.on_log("   Navigate ke YouTube Studio...")
                self.driver.get("https://studio.youtube.com")
                time.sleep(6)

            url = self.driver.current_url.lower()
            body = self.driver.page_source.lower()

            if "accounts.google.com" in url or "/signin" in url:
                self.on_log("❌ Belum login YouTube!")
                self.on_log("   1. Buka Chrome yang sedang terbuka")
                self.on_log("   2. Login YouTube di sana")
                self.on_log("   3. JANGAN tutup Chrome")
                self.on_log("   4. Klik Test Login lagi")
                return False

            if "verify it's you" in body:
                self.on_log("⚠️ Google minta verifikasi — selesaikan di Chrome")
                return False

            if "studio.youtube.com" in url:
                markers = ["channel content", "your channel", "dashboard",
                           "youtube studio", "content", "videos"]
                if any(m in body for m in markers):
                    self.on_log("✅ Login valid!")
                    return True

            self.on_log("⚠️ Status tidak jelas")
            return False

        except Exception as e:
            self.on_log(f"❌ Error: {str(e)[:200]}")
            return False
        finally:
            self._disconnect()

    # ══════════════════════════════════════════════════════
    # UPLOAD BATCH
    # ══════════════════════════════════════════════════════
    def upload_batch(self, videos, source_platform="instagram", source_username="",
                     force_reupload=False):
        if not videos:
            self.on_log("Tidak ada video")
            return

        ok, was_running, msg = ensure_chrome_debug(verbose_callback=self.on_log)
        if not ok:
            self.on_log(f"❌ {msg}")
            return

        self.on_log(f"Upload {len(videos)} video")
        self.on_log(f"Privacy: {self.config.privacy}")
        if force_reupload:
            self.on_log("⚡ Force re-upload: history diabaikan")

        try:
            self.driver = self._create_driver()
        except Exception as e:
            self.on_log(f"❌ Gagal connect: {str(e)[:200]}")
            return

        try:
            self.on_log("Verifikasi login...")
            try:
                current = self.driver.current_url.lower()
            except Exception:
                current = ""

            if "studio.youtube.com" not in current:
                self.driver.get("https://studio.youtube.com")
                time.sleep(5)

            url = self.driver.current_url.lower()
            body = self.driver.page_source.lower()

            if "accounts.google.com" in url or "/signin" in url:
                self.on_log("❌ Tidak login")
                return

            if "verify it's you" in body:
                self.on_log("⚠️ Verifikasi manual...")
                for _ in range(90):
                    if self.stop_event.is_set():
                        return
                    time.sleep(2)
                    try:
                        body = self.driver.page_source.lower()
                        if "verify it's you" not in body and \
                           "studio.youtube.com" in self.driver.current_url.lower():
                            break
                    except Exception:
                        break

            self.on_log("✅ Login OK")

            history = load_json(YOUTUBE_UPLOAD_HISTORY, {"uploads": []})
            uploaded_paths = {u["path"] for u in history.get("uploads", [])} \
                             if not force_reupload else set()

            success = 0
            failed = 0
            skipped = 0

            for idx, video in enumerate(videos, 1):
                if self.stop_event.is_set():
                    self.on_log("⏸ Dihentikan")
                    break

                path = video.get("path")
                if not path or not os.path.exists(path):
                    self.on_log(f"[{idx}/{len(videos)}] File tidak ada")
                    failed += 1
                    continue

                if path in uploaded_paths:
                    self.on_log(f"[{idx}/{len(videos)}] Skip (sudah diupload): {os.path.basename(path)[:60]}")
                    skipped += 1
                    continue

                self.on_progress(idx, len(videos), f"Upload {os.path.basename(path)}")
                self.on_log(f"\n[{idx}/{len(videos)}] {os.path.basename(path)}")

                try:
                    ok = self._upload_one(
                        path,
                        title=video.get("title"),
                        description=video.get("description"),
                        tags=video.get("tags"),
                        privacy=video.get("privacy") or self.config.privacy,
                    )
                    if ok:
                        success += 1
                        history["uploads"].append({
                            "path": path,
                            "title": video.get("title"),
                            "uploaded_at": current_time(),
                            "platform": source_platform,
                            "username": source_username,
                        })
                        save_json(YOUTUBE_UPLOAD_HISTORY, history)
                        self.on_log(f"✅ OK")
                    else:
                        failed += 1
                        self.on_log(f"❌ GAGAL")
                except Exception as e:
                    failed += 1
                    self.on_log(f"❌ ERROR: {str(e)[:150]}")

                if idx < len(videos) and not self.stop_event.is_set():
                    time.sleep(3)

            self.on_log(f"\n{'=' * 55}")
            self.on_log(f"SELESAI:")
            self.on_log(f"  ✅ Berhasil: {success}")
            self.on_log(f"  ⏩ Di-skip:  {skipped}")
            self.on_log(f"  ❌ Gagal:    {failed}")
            self.on_log("=" * 55)

        except Exception as e:
            self.on_log(f"❌ Error: {str(e)[:200]}")
        finally:
            self._disconnect()

    # ══════════════════════════════════════════════════════
    # UPLOAD ONE
    # ══════════════════════════════════════════════════════
    def _upload_one(self, filepath, title=None, description=None, tags=None, privacy=None):
        from selenium.webdriver.common.by import By
        from selenium.webdriver.support.ui import WebDriverWait
        from selenium.webdriver.support import expected_conditions as EC
        from selenium.webdriver.common.keys import Keys

        if not title:
            raw_name = Path(filepath).stem
            title = _clean_title_from_filename(raw_name)
            if len(title) > 100:
                title = title[:100]
            self.on_log(f"   📝 Title: {title[:70]}")

        if not description:
            description = self.config.description_template
        if not tags:
            tags = self.config.tags
        privacy = privacy or self.config.privacy

        self.on_log("   [1/8] Buka upload page...")
        self.driver.get("https://www.youtube.com/upload")
        time.sleep(6)

        try:
            wait = WebDriverWait(self.driver, 30)
            file_input = wait.until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "input[type='file']"))
            )
        except Exception:
            self.on_log("   Cari input alt...")
            try:
                btn = self.driver.find_element(
                    By.XPATH,
                    "//button[contains(., 'Upload')] | //ytcp-button[contains(., 'Upload')]"
                )
                btn.click()
                time.sleep(2)
                file_input = self.driver.find_element(By.CSS_SELECTOR, "input[type='file']")
            except Exception as e:
                self.on_log(f"   ❌ {str(e)[:100]}")
                return False

        self.on_log(f"   Upload: {os.path.basename(filepath)} ({_human_size(os.path.getsize(filepath))})")
        file_input.send_keys(os.path.abspath(filepath))

        self.on_log("   [2/8] Tunggu editor...")
        time.sleep(8)

        self.on_log("   [3/8] Set title & description...")
        try:
            wait = WebDriverWait(self.driver, 60)
            title_box = wait.until(
                EC.presence_of_element_located(
                    (By.CSS_SELECTOR, "#textbox[contenteditable='true']")
                )
            )
            title_box.click()
            time.sleep(0.5)
            title_box.send_keys(Keys.CONTROL + "a")
            title_box.send_keys(Keys.DELETE)
            time.sleep(0.3)
            title_box.send_keys(title[:100])
            self.on_log(f"   ✅ Title diset")
        except Exception as e:
            self.on_log(f"   ⚠️ Title: {str(e)[:80]}")

        time.sleep(1)

        try:
            desc_box = self.driver.find_element(
                By.CSS_SELECTOR, "#description-textbox[contenteditable='true']"
            )
            if desc_box:
                desc_box.click()
                time.sleep(0.5)
                desc_box.send_keys(Keys.CONTROL + "a")
                desc_box.send_keys(Keys.DELETE)
                desc_box.send_keys(description[:5000])
        except Exception:
            pass

        time.sleep(1)

        self.on_log("   [4/8] Set 'Made for kids'...")
        self._close_popups()
        self._set_made_for_kids(made_for_kids=False)
        time.sleep(2)

        self.on_log("   [5/8] Next → Video elements...")
        if not self._click_next_with_retry(max_retries=5, retry_delay=3):
            self.on_log("   ⚠️ Next disabled")
            return False
        time.sleep(2)

        self.on_log("   [6/8] Next → Checks...")
        self._close_popups()
        if not self._click_next_with_retry(max_retries=5, retry_delay=3):
            self.on_log("   ⚠️ Gagal ke Checks")
            return False
        time.sleep(2)

        self.on_log("   [7/8] Tunggu Checks...")
        self._wait_for_checks_complete(max_wait_seconds=600)

        self.on_log("   [8/8] Next → Visibility...")
        self._close_popups()
        if not self._click_next_with_retry(max_retries=5, retry_delay=3):
            self.on_log("   ⚠️ Gagal ke Visibility")
            return False
        time.sleep(3)

        self.on_log("   Set privacy...")
        time.sleep(2)
        self._close_popups()

        self._set_made_for_kids(made_for_kids=False)
        time.sleep(2)
        self._close_popups()

        self.on_log(f"   → Privacy: {privacy}")
        self._set_privacy(privacy)
        time.sleep(1)

        self._close_popups()

        self.on_log("   Click Save...")
        time.sleep(2)
        self._click_publish()

        # ══════════════════════════════════════════════════
        # ⚡ FIX: Tunggu konfirmasi maks 60s + klik Close
        # (jangan tunggu processing selesai — itu urusan server YT)
        # ══════════════════════════════════════════════════
        self.on_log("   Tunggu dialog konfirmasi...")
        publish_confirmed = False

        for i in range(30):
            if self.stop_event.is_set():
                return False
            time.sleep(2)
            try:
                body = self.driver.page_source.lower()

                success_markers = [
                    "video published",
                    "video saved",
                    "video processing",
                    "your video is being processed",
                    "publishing",
                    "checks complete",
                ]
                if any(m in body for m in success_markers):
                    publish_confirmed = True
                    self.on_log(f"   ✅ Dialog terdeteksi ({i*2}s)")
                    break

                try:
                    url = self.driver.current_url.lower()
                    if "studio.youtube.com" in url and "/video/" in url:
                        publish_confirmed = True
                        self.on_log("   ✅ Redirect ke video page")
                        break
                except Exception:
                    pass

                try:
                    close_btn = self.driver.find_element(
                        By.XPATH,
                        "//ytcp-button[contains(., 'Close')] | "
                        "//tp-yt-paper-button[contains(., 'Close')] | "
                        "//button[contains(., 'Close')]"
                    )
                    if close_btn.is_displayed():
                        publish_confirmed = True
                        self.on_log("   ✅ Tombol Close terdeteksi")
                        break
                except Exception:
                    pass

            except Exception as e:
                self.on_log(f"   ⚠️  Cek error: {str(e)[:80]}")

        if not publish_confirmed:
            self.on_log("   ⚠️  Tidak yakin upload selesai (timeout 60s), tapi lanjut")

        # ⚡ Klik Close
        self.on_log("   Tutup dialog...")
        try:
            closed = False
            for _ in range(5):
                close_btns = self.driver.find_elements(
                    By.XPATH,
                    "//ytcp-button[contains(., 'Close')] | "
                    "//tp-yt-paper-button[contains(., 'Close')] | "
                    "//button[contains(., 'Close')] | "
                    "//ytcp-button[@id='close-button']"
                )
                for btn in close_btns:
                    try:
                        if btn.is_displayed() and btn.is_enabled():
                            self.driver.execute_script("arguments[0].click();", btn)
                            self.on_log("   ✅ Dialog closed")
                            closed = True
                            break
                    except Exception:
                        continue
                if closed:
                    break
                time.sleep(1)
        except Exception as e:
            self.on_log(f"   ⚠️  Close dialog: {str(e)[:80]}")

        time.sleep(2)
        self.on_log("   ✅ Selesai!")
        return True

    # ══════════════════════════════════════════════════════
    # HELPERS
    # ══════════════════════════════════════════════════════
    def _wait_for_checks_complete(self, max_wait_seconds=600):
        from selenium.webdriver.common.by import By
        start = time.time()
        last_log = 0
        last_pct = -1

        while time.time() - start < max_wait_seconds:
            if self.stop_event.is_set():
                return False
            try:
                next_btn = self.driver.find_element(By.CSS_SELECTOR, "#next-button")
                is_disabled = next_btn.get_attribute("aria-disabled") == "true"
                if not is_disabled:
                    self.on_log("   ✅ Checks selesai!")
                    return True
            except Exception:
                pass
            try:
                body = self.driver.page_source.lower()
                match = re.search(r"checking\s+(\d+)%", body)
                if match:
                    pct = int(match.group(1))
                    if pct != last_pct:
                        last_pct = pct
                        elapsed = int(time.time() - start)
                        self.on_log(f"   ⏳ Checking {pct}% ({elapsed}s)")
            except Exception:
                pass
            now = time.time()
            if now - last_log > 30:
                last_log = now
                self.on_log(f"   ⏳ Menunggu Checks... ({int(now-start)}s)")
            time.sleep(3)
        return False

    def _click_next_with_retry(self, max_retries=5, retry_delay=3):
        from selenium.webdriver.common.by import By
        for attempt in range(max_retries):
            try:
                next_btn = self.driver.find_element(By.CSS_SELECTOR, "#next-button")
                is_disabled = next_btn.get_attribute("aria-disabled") == "true"
                if not is_disabled:
                    try:
                        next_btn.click()
                    except Exception:
                        self.driver.execute_script("arguments[0].click();", next_btn)
                    return True
                if attempt == 0:
                    try:
                        body = self.driver.page_source.lower()
                        if "you need to answer this question" in body:
                            self._set_made_for_kids(made_for_kids=False)
                            time.sleep(1.5)
                    except Exception:
                        pass
                self.on_log(f"   ⏳ Next disabled... ({attempt+1}/{max_retries})")
                time.sleep(retry_delay)
            except Exception:
                time.sleep(retry_delay)
        return False

    def _close_popups(self):
        from selenium.webdriver.common.by import By
        closed = 0
        selectors = [
            "//ytcp-button[contains(., 'Close')]",
            "//button[contains(., 'Close')]",
            "//ytcp-button[contains(., 'Dismiss')]",
            "//ytcp-button[contains(., 'Got it')]",
            "//paper-button[contains(., 'Close')]",
        ]
        for sel in selectors:
            try:
                btns = self.driver.find_elements(By.XPATH, sel)
                for b in btns:
                    try:
                        if b.is_displayed() and b.is_enabled():
                            self.driver.execute_script("arguments[0].click();", b)
                            closed += 1
                            time.sleep(0.3)
                    except Exception:
                        continue
            except Exception:
                continue
        return closed

    def _set_made_for_kids(self, made_for_kids=False):
        from selenium.webdriver.common.by import By
        target = "VIDEO_MADE_FOR_KIDS_MFK" if made_for_kids else "VIDEO_MADE_FOR_KIDS_NOT_MFK"
        strategies = [
            f"//tp-yt-paper-radio-button[@name='{target}']",
            f"//tp-yt-paper-radio-button[contains(@id, '{target}')]",
            ("//tp-yt-paper-radio-button[.//*[contains(text(), \"Yes, it's made for kids\")]]"
             if made_for_kids else
             "//tp-yt-paper-radio-button[.//*[contains(text(), \"No, it's not made for kids\")]]"),
        ]
        for xpath in strategies:
            try:
                elems = self.driver.find_elements(By.XPATH, xpath)
                if not elems:
                    continue
                elem = elems[0]
                try:
                    self.driver.execute_script(
                        "arguments[0].scrollIntoView({block: 'center'});", elem)
                    time.sleep(0.6)
                except Exception:
                    pass
                try:
                    elem.click()
                except Exception:
                    self.driver.execute_script("arguments[0].click();", elem)
                time.sleep(0.5)
                self.on_log(f"   ✅ Made for kids: {'Yes' if made_for_kids else 'No'}")
                return True
            except Exception:
                continue
        return False

    def _set_privacy(self, privacy):
        from selenium.webdriver.common.by import By
        target = {"public": "PUBLIC", "unlisted": "UNLISTED", "private": "PRIVATE"}.get(
            privacy.lower(), "UNLISTED")
        try:
            xpath = f"//tp-yt-paper-radio-button[@name='{target}']"
            elems = self.driver.find_elements(By.XPATH, xpath)
            if elems:
                elem = elems[0]
                try:
                    self.driver.execute_script(
                        "arguments[0].scrollIntoView({block: 'center'});", elem)
                    time.sleep(0.5)
                except Exception:
                    pass
                try:
                    elem.click()
                except Exception:
                    self.driver.execute_script("arguments[0].click();", elem)
                time.sleep(0.5)
                self.on_log(f"   ✅ Privacy: {target}")
                return True
        except Exception:
            pass
        try:
            index_map = {"PRIVATE": 0, "UNLISTED": 1, "PUBLIC": 2}
            idx = index_map.get(target, 1)
            elem = self.driver.find_element(By.XPATH, f"(//tp-yt-paper-radio-button)[{idx+1}]")
            self.driver.execute_script("arguments[0].click();", elem)
            time.sleep(0.5)
            self.on_log(f"   ✅ Privacy: {target}")
            return True
        except Exception:
            pass
        self.on_log(f"   ⚠️ Gagal set privacy")
        return False

    def _click_publish(self):
        from selenium.webdriver.common.by import By
        try:
            btn = self.driver.find_element(By.CSS_SELECTOR, "#done-button")
            if btn.is_enabled() and btn.is_displayed():
                try:
                    btn.click()
                except Exception:
                    self.driver.execute_script("arguments[0].click();", btn)
                self.on_log("   ✅ Click Save")
                return True
        except Exception:
            pass
        try:
            btns = self.driver.find_elements(
                By.XPATH,
                "//ytcp-button[contains(., 'Save')] | "
                "//ytcp-button[contains(., 'Publish')] | "
                "//button[contains(., 'Save')] | "
                "//button[contains(., 'Publish')]"
            )
            for b in btns:
                try:
                    if b.is_enabled() and b.is_displayed():
                        try:
                            b.click()
                        except Exception:
                            self.driver.execute_script("arguments[0].click();", b)
                        self.on_log("   ✅ Click Save")
                        return True
                except Exception:
                    continue
        except Exception:
            pass
        return False