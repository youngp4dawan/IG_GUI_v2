"""Instagram downloader (instaloader + yt-dlp fallback, parallel)."""
import os
import shutil
import subprocess
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from shared.paths import DOWNLOAD_INSTAGRAM
from shared.utils import ensure_dirs, current_time, USER_AGENT
from shared.config import load_json, save_json
from instagram.config import InstagramConfig
from instagram.constants import (
    YTDLP_TIMEOUT, MAX_CONSECUTIVE_ERRORS, DOWNLOAD_DELAY, DEFAULT_WORKERS,
)

YTDLP_AVAILABLE = shutil.which("yt-dlp") is not None


class InstagramDownloader:
    """Download Instagram posts via instaloader + yt-dlp fallback (parallel)."""

    # ══════════════════════════════════════════════════════
    # ARCHIVE MANAGEMENT
    # ══════════════════════════════════════════════════════
    @staticmethod
    def _data_file(username):
        return os.path.join(DOWNLOAD_INSTAGRAM, username, f"{username}_data.json")

    @staticmethod
    def get_archive_info(username):
        path = InstagramDownloader._data_file(username)
        if not os.path.exists(path):
            return False, 0, path
        try:
            data = load_json(path) or {}
            return True, len(data.get("posts", [])), path
        except Exception:
            return False, 0, path

    @staticmethod
    def reset_archive(username):
        path = InstagramDownloader._data_file(username)
        if os.path.exists(path):
            try:
                os.remove(path)
                return True
            except Exception:
                return False
        return False

    # ══════════════════════════════════════════════════════
    # THUMBNAIL URL HELPER (level class — bukan nested!)
    # ══════════════════════════════════════════════════════
    @staticmethod
    def _get_thumb_url(post):
        """Ambil URL thumbnail dengan fallback berlapis."""
        # 1. instaloader modern (>=4.10): post.url selalu ada
        url = getattr(post, "url", None)
        if url:
            return url
        # 2. fallback: atribut lama
        node = getattr(post, "_node", None) or {}
        return node.get("thumbnail_src") or node.get("display_url")

    # ══════════════════════════════════════════════════════
    # INSTALOADER FACTORY (per-thread)
    # ══════════════════════════════════════════════════════
    @staticmethod
    def create_instaloader(config, base_folder):
        import instaloader
        loader = instaloader.Instaloader(
            download_videos=True,
            download_video_thumbnails=False,
            download_geotags=False,
            download_comments=False,
            save_metadata=False,
            compress_json=False,
            post_metadata_txt_pattern="",
            fatal_status_codes=[404],
            quiet=True,
            dirname_pattern=base_folder,
        )
        config.apply_to_instaloader(loader)
        return loader

    # ══════════════════════════════════════════════════════
    # MAIN DOWNLOAD (parallel)
    # ══════════════════════════════════════════════════════
    @staticmethod
    def download_user(shortcodes, username, config=None, stop_event=None,
                      on_log=None, on_progress=None,
                      max_workers=DEFAULT_WORKERS, download_delay=None):
        import instaloader

        stop_event = stop_event or threading.Event()
        on_log = on_log or (lambda m: None)
        on_progress = on_progress or (lambda c, t, m: None)
        config = config or InstagramConfig()
        delay = DOWNLOAD_DELAY if download_delay is None else download_delay

        if not shortcodes:
            on_log(f"⚠️  @{username}: tidak ada shortcode untuk didownload")
            return

        user_folder = os.path.join(DOWNLOAD_INSTAGRAM, username)
        ensure_dirs(user_folder)
        data_file = InstagramDownloader._data_file(username)

        # ── Load progress lama ──
        existing = load_json(data_file)
        existing_posts = existing.get("posts", []) if existing else []
        downloaded = {p["shortcode"] for p in existing_posts if "shortcode" in p}

        remaining = [sc for sc in shortcodes if sc not in downloaded]
        if not remaining:
            on_log(f"✅ @{username}: semua {len(shortcodes)} post sudah didownload")
            return

        on_log(f"📥 @{username}: download {len(remaining)} post "
               f"(skip {len(downloaded)}, workers={max_workers})")

        metadata_list = list(existing_posts)
        lock = threading.Lock()
        progress = {"done": 0, "success": 0, "errors": 0, "streak": 0}
        last_save = {"count": len(existing_posts)}

        def _snapshot():
            return {
                "username": username,
                "extraction_date": (
                    existing.get("extraction_date", current_time())
                    if existing else current_time()
                ),
                "download_date": current_time(),
                "total_posts": len(shortcodes),
                "total_downloaded": len(metadata_list),
                "shortcodes": shortcodes,
                "posts": list(metadata_list),
            }

        def _save_now():
            with lock:
                save_json(data_file, _snapshot())
                last_save["count"] = len(metadata_list)

        # ── Worker: proses 1 shortcode ──
        def _process_one(shortcode):
            if stop_event.is_set():
                return None
            try:
                loader = InstagramDownloader.create_instaloader(config, user_folder)
                post = instaloader.Post.from_shortcode(loader.context, shortcode)

                caption = post.caption or "No caption"
                post_type = "reel" if post.is_video else "photo"

                # Thumbnail URL (helper level class)
                thumbnail_url = InstagramDownloader._get_thumb_url(post)

                metadata = {
                    "shortcode": shortcode,
                    "url": f"https://www.instagram.com/p/{shortcode}/",
                    "type": post_type,
                    "date_utc": post.date_utc.strftime("%Y-%m-%d %H:%M:%S"),
                    "year": post.date_utc.strftime("%Y"),
                    "likes": post.likes,
                    "comments": post.comments,
                    "caption": caption,
                    "is_video": post.is_video,
                    "owner_username": post.owner_username,
                    "thumbnail_url": thumbnail_url,
                }

                target = os.path.join(user_folder, post_type, metadata["year"])
                ensure_dirs(target)

                # ── Download file utama ──
                if post.is_video:
                    InstagramDownloader._download_video(
                        post, shortcode, target, loader, config, on_log
                    )
                    tpath = InstagramDownloader._download_thumb(
                        post, shortcode, user_folder, loader, on_log=on_log,
                    )
                    if tpath:
                        metadata["thumbnail"] = tpath
                else:
                    original = loader.dirname_pattern
                    loader.dirname_pattern = target
                    try:
                        loader.download_post(post, target="")
                    finally:
                        loader.dirname_pattern = original

                    tpath = InstagramDownloader._download_thumb(
                        post, shortcode, user_folder, loader, on_log=on_log,
                    )
                    if tpath:
                        metadata["thumbnail"] = tpath

                InstagramDownloader._save_caption(
                    target, post, shortcode, post_type, caption
                )

                with lock:
                    metadata_list.append(metadata)
                    progress["done"] += 1
                    progress["success"] += 1
                    progress["streak"] = 0
                    done = progress["done"]
                    total = len(remaining)

                on_log(f"✅ [{done}/{total}] {shortcode}")
                on_progress(done, total, f"@{username}: {done}/{total}")

                if done - last_save["count"] >= 5:
                    _save_now()

                if delay > 0 and not stop_event.is_set():
                    time.sleep(delay)

                return metadata

            except Exception as e:
                with lock:
                    progress["done"] += 1
                    progress["errors"] += 1
                    progress["streak"] += 1
                    done = progress["done"]
                    total = len(remaining)
                    streak = progress["streak"]

                on_log(f"❌ [{done}/{total}] {shortcode}: {str(e)[:100]}")

                if streak >= MAX_CONSECUTIVE_ERRORS:
                    on_log(f"⚠️  {MAX_CONSECUTIVE_ERRORS} error berturut — "
                           f"kemungkinan rate-limit, tidur 30s")
                    time.sleep(30)
                    with lock:
                        progress["streak"] = 0
                return None

        # ══════════════════════════════════════════════════
        # JALANKAN
        # ══════════════════════════════════════════════════
        try:
            with ThreadPoolExecutor(max_workers=max_workers) as ex:
                futures = {ex.submit(_process_one, sc): sc for sc in remaining}
                for fut in as_completed(futures):
                    if stop_event.is_set():
                        for f in futures:
                            f.cancel()
                        on_log("⏸️ Dihentikan oleh user")
                        break
                    try:
                        fut.result()
                    except Exception as e:
                        on_log(f"⚠️  Worker crash: {str(e)[:120]}")

            _save_now()

        except KeyboardInterrupt:
            on_log("⏸️ Dihentikan (Ctrl+C)")

        on_log(f"📊 @{username}: {progress['success']} berhasil, "
               f"{progress['errors']} gagal")

    # ══════════════════════════════════════════════════════
    # VIDEO
    # ══════════════════════════════════════════════════════
    @staticmethod
    def _download_video(post, shortcode, target, loader, config, on_log):
        filename = f"{post.date_utc.strftime('%Y-%m-%d_%H-%M-%S')}_UTC.mp4"
        filepath = os.path.join(target, filename)
        if os.path.exists(filepath) and os.path.getsize(filepath) > 0:
            return True, filepath

        if YTDLP_AVAILABLE:
            cookies_path = None
            try:
                url = f"https://www.instagram.com/reel/{shortcode}/"
                cmd = [
                    "yt-dlp", "--format", "best",
                    "--output", filepath,
                    "--no-playlist", "--quiet", "--no-warnings",
                    "--socket-timeout", "30",
                ]
                if config and config.sessionid:
                    fd, cookies_path = tempfile.mkstemp(suffix=".txt", prefix="igc_")
                    with os.fdopen(fd, "w") as f:
                        f.write("# Netscape HTTP Cookie File\n")
                        f.write(f".instagram.com\tTRUE\t/\tTRUE\t0\tsessionid\t{config.sessionid}\n")
                        if config.csrf_token:
                            f.write(f".instagram.com\tTRUE\t/\tTRUE\t0\tcsrftoken\t{config.csrf_token}\n")
                    cmd.extend(["--cookies", cookies_path])
                cmd.append(url)

                result = subprocess.run(cmd, capture_output=True, text=True,
                                        timeout=YTDLP_TIMEOUT)
                if result.returncode == 0 and os.path.exists(filepath):
                    return True, filepath

            except subprocess.TimeoutExpired:
                on_log(f"   ⏱️  yt-dlp timeout: {shortcode}")
            except Exception:
                pass
            finally:
                if cookies_path and os.path.exists(cookies_path):
                    try:
                        os.remove(cookies_path)
                    except Exception:
                        pass

        # Fallback instaloader
        original = loader.dirname_pattern
        loader.dirname_pattern = target
        try:
            loader.download_post(post, target="")
        finally:
            loader.dirname_pattern = original
        return True, None

    # ══════════════════════════════════════════════════════
    # THUMBNAIL — pakai post.url
    # ══════════════════════════════════════════════════════
    @staticmethod
    def _download_thumb(post, shortcode, user_folder, loader, on_log=None):
        on_log = on_log or (lambda m: None)
        try:
            thumb_folder = os.path.join(user_folder, "thumbnails")
            ensure_dirs(thumb_folder)
            path = os.path.join(thumb_folder, f"{shortcode}_thumb.jpg")

            if os.path.exists(path) and os.path.getsize(path) > 0:
                return path

            url = InstagramDownloader._get_thumb_url(post)

            if not url:
                on_log(f"   ⚠️  Thumbnail URL kosong: {shortcode}")
                return None

            r = loader.context._session.get(
                url, stream=True, timeout=30,
                headers={"User-Agent": USER_AGENT},
            )
            r.raise_for_status()

            tmp = path + ".tmp"
            with open(tmp, "wb") as f:
                for chunk in r.iter_content(8192):
                    if chunk:
                        f.write(chunk)
            os.replace(tmp, path)
            return path
        except Exception as e:
            on_log(f"   ⚠️  Thumbnail gagal {shortcode}: {str(e)[:80]}")
            return None

    # ══════════════════════════════════════════════════════
    # CAPTION
    # ══════════════════════════════════════════════════════
    @staticmethod
    def _save_caption(folder, post, shortcode, post_type, caption):
        try:
            filename = (
                f"{post.date_utc.strftime('%Y-%m-%d_%H-%M-%S')}"
                f"_UTC_{shortcode}_caption.txt"
            )
            path = os.path.join(folder, filename)
            if os.path.exists(path):
                return

            with open(path, "w", encoding="utf-8") as f:
                f.write(f"Post: https://www.instagram.com/p/{shortcode}/\n")
                f.write(f"Date: {post.date_utc.strftime('%Y-%m-%d %H:%M:%S')} UTC\n")
                f.write(f"Likes: {post.likes}\n")
                f.write(f"Type: {post_type}\n")
                f.write("=" * 60 + "\n\n")
                f.write(caption)
        except Exception:
            pass