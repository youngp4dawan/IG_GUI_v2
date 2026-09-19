r"""
YouTube Upload Worker Service
==============================
Polling database `youtube_queue`, upload 1-per-1, update status.

Fitur:
- Auto-launch Chrome debug kalau belum jalan
- Auto-stop kalau Chrome debug ditutup
- Auto-rescue orphan 'uploading' saat start
- Auto-reconnect driver sebelum upload
- Safe Unicode handling
"""
import os
import sys
import time
import json
import signal
import sqlite3
from pathlib import Path

# ⚡ FIX: paksa stdout/stderr ke UTF-8
try:
    if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if sys.stderr.encoding and sys.stderr.encoding.lower() != "utf-8":
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# Setup path
ROOT = Path(__file__).parent.resolve()
sys.path.insert(0, str(ROOT))


DB_CANDIDATES = [
    ROOT.parent / "website-wails" / "build" / "bin" / "media_library.db",
    ROOT / "website-wails" / "build" / "bin" / "media_library.db",
    ROOT / "build" / "bin" / "media_library.db",
    ROOT / "media_library.db",
    ROOT / "dist" / "media_library.db",
    ROOT / "MediaViewer" / "media_library.db",
    ROOT.parent / "media_library.db",
    Path(os.getcwd()) / "media_library.db",
]


def find_db():
    for p in DB_CANDIDATES:
        if p.exists():
            return str(p)
    return None


def _safe_bytes_to_str(b):
    if isinstance(b, str):
        return b
    try:
        return b.decode("utf-8", errors="replace")
    except Exception:
        return str(b)


class QueueWorker:
    def __init__(self, db_path):
        self.db_path = db_path
        self.stop = False

        from youtube.uploader import YouTubeUploader, _check_debug_port
        from youtube.config import YouTubeConfig

        self._check_debug_port = _check_debug_port

        self.uploader = YouTubeUploader(
            config=YouTubeConfig(),
            on_log=lambda m: print(m, flush=True),
            on_progress=lambda c, t, m: print(f"[{c}/{t}] {m}", flush=True),
        )

    def conn(self):
        c = sqlite3.connect(self.db_path, timeout=30, isolation_level=None)
        c.text_factory = _safe_bytes_to_str
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("PRAGMA busy_timeout=10000")
        return c

    def chrome_alive(self):
        try:
            return self._check_debug_port()
        except Exception:
            return False

    def get_next_pending(self):
        with self.conn() as c:
            return c.execute("""
                SELECT id, video_path, thumbnail_path, title, description,
                       tags, privacy, made_for_kids, playlist
                FROM youtube_queue
                WHERE status = 'pending'
                ORDER BY created_at ASC
                LIMIT 1
            """).fetchone()

    def update_status(self, item_id, status, url="", error=""):
        with self.conn() as c:
            c.execute("""
                UPDATE youtube_queue
                SET status = ?,
                    youtube_url = ?,
                    error = ?,
                    attempts = attempts + 1,
                    started_at = CASE WHEN ? = 'uploading'
                                      THEN datetime('now') ELSE started_at END,
                    finished_at = CASE WHEN ? IN ('done','failed')
                                       THEN datetime('now') ELSE finished_at END
                WHERE id = ?
            """, (status, url, error, status, status, item_id))

    def _ensure_driver(self):
        if getattr(self.uploader, "driver", None) is None:
            print("🔌 Connect ke Chrome debug...", flush=True)
            self.uploader.driver = self.uploader._create_driver()
            print("   ✅ Driver connected", flush=True)

    def run(self):
        print("=" * 60, flush=True)
        print("🎬 YouTube Upload Worker", flush=True)
        print(f"📁 DB: {self.db_path}", flush=True)
        print("=" * 60, flush=True)
        print("", flush=True)

        # ⚡ Auto-rescue: reset item 'uploading' yang nyangkut
        try:
            with self.conn() as c:
                res = c.execute("""
                    UPDATE youtube_queue
                    SET status='pending',
                        error='reset: orphan from previous worker'
                    WHERE status='uploading'
                """)
                if res.rowcount and res.rowcount > 0:
                    print(f"♻️  Reset {res.rowcount} orphan 'uploading' → 'pending'",
                          flush=True)
        except Exception as e:
            print(f"⚠️  Auto-rescue error: {str(e)[:100]}", flush=True)

        # ⚡ Cek Chrome debug + auto-launch kalau belum jalan
        if not self.chrome_alive():
            print("⚠️  Chrome debug (port 9222) tidak aktif.", flush=True)
            print("   Mencoba auto-launch Chrome debug...", flush=True)
            try:
                from youtube.uploader import ensure_chrome_debug
                ok, was_running, msg = ensure_chrome_debug(
                    verbose_callback=lambda m: print("   " + m, flush=True)
                )
                if not ok:
                    print(f"❌ Gagal launch Chrome: {msg}", flush=True)
                    return
                print("✅ Chrome debug siap", flush=True)
                print("", flush=True)
                print("💡 Kalau ini pertama kali:", flush=True)
                print("   1. Login YouTube di Chrome yang terbuka", flush=True)
                print("   2. JANGAN tutup Chrome", flush=True)
                print("   3. Restart worker ini", flush=True)
                print("", flush=True)
            except Exception as e:
                print(f"❌ Auto-launch error: {str(e)[:150]}", flush=True)
                return

        print("🔍 Cek koneksi Chrome debug + login YouTube...", flush=True)
        try:
            logged_in = self.uploader.check_login()
            if not logged_in:
                print("", flush=True)
                print("⚠️  Login YouTube gagal / belum login.", flush=True)
                print("   Login dulu di Chrome, lalu jalankan ulang worker.", flush=True)
                print("", flush=True)
        except Exception as e:
            print(f"⚠️  Cek login error: {str(e)[:150]}", flush=True)

        idle_count = 0
        while not self.stop:
            if not self.chrome_alive():
                print("", flush=True)
                print("=" * 60, flush=True)
                print("🛑 Chrome debug sudah ditutup — worker berhenti", flush=True)
                print("=" * 60, flush=True)
                self.uploader.driver = None
                break

            try:
                item = self.get_next_pending()
            except Exception as e:
                print(f"❌ DB error: {str(e)[:200]}", flush=True)
                time.sleep(5)
                continue

            if not item:
                idle_count += 1
                if idle_count % 10 == 1:
                    print("💤 Queue kosong, menunggu...", flush=True)
                time.sleep(3)
                continue

            idle_count = 0
            (item_id, path, thumb, title, desc,
             tags_json, privacy, mfk, playlist) = item

            if not path or not os.path.exists(path):
                print(f"❌ #{item_id}: file not found: {path}", flush=True)
                self.update_status(item_id, "failed", error="file not found")
                continue

            print("", flush=True)
            print("─" * 60, flush=True)
            print(f"▶️  Uploading #{item_id}: {os.path.basename(path)}", flush=True)
            print(f"   Title: {(title or '')[:80]}", flush=True)
            print(f"   Privacy: {privacy}", flush=True)
            print("─" * 60, flush=True)

            self.update_status(item_id, "uploading")

            try:
                self._ensure_driver()
                tags = json.loads(tags_json) if tags_json else []

                ok = self.uploader._upload_one(
                    path,
                    title=title,
                    description=desc,
                    tags=tags,
                    privacy=privacy,
                )

                if ok:
                    self.update_status(item_id, "done")
                    print(f"✅ #{item_id} uploaded successfully", flush=True)
                else:
                    self.update_status(item_id, "failed", error="upload returned False")
                    print(f"❌ #{item_id} upload failed", flush=True)

            except Exception as e:
                err = str(e)[:500]
                self.update_status(item_id, "failed", error=err)
                print(f"❌ #{item_id} error: {str(e)[:200]}", flush=True)
                self.uploader.driver = None

                if not self.chrome_alive():
                    print("", flush=True)
                    print("=" * 60, flush=True)
                    print("🛑 Chrome ditutup saat upload — worker berhenti", flush=True)
                    print("=" * 60, flush=True)
                    break

        print("", flush=True)
        print("🛑 Worker stopped", flush=True)


def main():
    db = find_db()
    if not db:
        print("❌ media_library.db tidak ditemukan di:", flush=True)
        for p in DB_CANDIDATES:
            print(f"   - {p}", flush=True)
        sys.exit(1)

    worker = QueueWorker(db)

    def handler(sig, frame):
        print("", flush=True)
        print("⏸️  Stop signal received", flush=True)
        worker.stop = True

    signal.signal(signal.SIGINT, handler)
    signal.signal(signal.SIGTERM, handler)

    try:
        worker.run()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()