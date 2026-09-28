r"""
Facebook Reels Quality Repair Tool
====================================
Re-download semua video Facebook dari DB yang resolusinya rendah,
ganti dengan kualitas tertinggi yang tersedia.

Berbasis data yang sudah ada — tidak perlu scroll ulang.
Video ID diambil dari filename yang sudah tersimpan di DB.

Usage:
    # Preview (dry-run) — hanya lihat apa yang akan dilakukan
    python repair_facebook_quality.py --dry-run

    # Test pada 5 video pertama
    python repair_facebook_quality.py --apply --limit 5

    # Full run
    python repair_facebook_quality.py --apply

    # Force re-download semua, bahkan yang sudah HD
    python repair_facebook_quality.py --apply --force
"""
import os
import re
import sys
import time
import shutil
import sqlite3
import tempfile
import argparse
import subprocess
from pathlib import Path

ROOT = Path(__file__).parent.resolve()
sys.path.insert(0, str(ROOT))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


# ══════════════════════════════════════════════════════════
# CONFIG
# ══════════════════════════════════════════════════════════

DB_CANDIDATES = [
    ROOT.parent / "website-wails" / "build" / "bin" / "media_library.db",
    ROOT / "website-wails" / "build" / "bin" / "media_library.db",
    ROOT / "build" / "bin" / "media_library.db",
    ROOT / "media_library.db",
    Path(os.getcwd()) / "media_library.db",
]

# Target resolusi minimal (shortest side dalam pixel)
# Video portrait 1072x1906 → shortest = 1072
# Video landscape 1920x1080 → shortest = 1080
# Kita target >= 1000 px di sisi pendek
DEFAULT_MIN_SHORT_SIDE = 1000

# Format selector — handle portrait & landscape
YTDLP_FORMAT = (
    "bestvideo[height<=1920][width<=1080]+bestaudio/"
    "bestvideo[height<=1080][width<=1920]+bestaudio/"
    "bestvideo+bestaudio/"
    "best"
)


def find_db():
    for p in DB_CANDIDATES:
        if p.exists():
            return str(p)
    return None


def find_cookies():
    """Cari file cookies Facebook yang sudah di-generate."""
    candidates = [
        ROOT / "data" / "facebook" / "cookies.txt",
        ROOT.parent / "data" / "facebook" / "cookies.txt",
    ]
    for c in candidates:
        if c.exists():
            return str(c)
    return None


# ══════════════════════════════════════════════════════════
# REPAIR CLASS
# ══════════════════════════════════════════════════════════

class FacebookQualityRepair:
    def __init__(self, db_path, apply=False, limit=0,
                 force=False, min_short_side=DEFAULT_MIN_SHORT_SIDE,
                 keep_original=False):
        self.db_path = db_path
        self.apply = apply
        self.limit = limit
        self.force = force
        self.min_short_side = min_short_side
        self.keep_original = keep_original
        self.cookies = find_cookies()

        self.stats = {
            "total": 0,
            "processed": 0,
            "upgraded": 0,
            "skipped_good": 0,
            "skipped_missing": 0,
            "failed_download": 0,
            "failed_verify": 0,
            "db_updated": 0,
        }

    # ─── DB ───
    def conn(self):
        c = sqlite3.connect(self.db_path, timeout=30, isolation_level=None)
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("PRAGMA busy_timeout=10000")
        return c

    def get_facebook_entries(self):
        """Return list of (id, filename, full_path, thumbnail) untuk semua FB video."""
        with self.conn() as c:
            return c.execute("""
                SELECT id, filename, full_path, COALESCE(thumbnail, '')
                FROM media
                WHERE platform = 'Facebook' AND type = 'video'
                ORDER BY id ASC
            """).fetchall()

    def update_db_thumbnail(self, media_id, new_thumb_path):
        try:
            with self.conn() as c:
                c.execute("UPDATE media SET thumbnail=? WHERE id=?",
                          (new_thumb_path, media_id))
            self.stats["db_updated"] += 1
            return True
        except Exception as e:
            print(f"  ⚠️  DB update error: {e}")
            return False

    # ─── FFprobe ───
    def get_resolution(self, path):
        """Return (width, height) atau None."""
        try:
            r = subprocess.run(
                ["ffprobe", "-v", "error",
                 "-select_streams", "v:0",
                 "-show_entries", "stream=width,height",
                 "-of", "csv=s=x:p=0", path],
                capture_output=True, text=True, timeout=15,
            )
            parts = r.stdout.strip().split("x")
            if len(parts) == 2:
                return int(parts[0]), int(parts[1])
        except Exception:
            pass
        return None

    def needs_upgrade(self, path):
        """Cek apakah video perlu di-upgrade."""
        if self.force:
            return True, "forced"
        res = self.get_resolution(path)
        if not res:
            return True, "cannot probe"
        w, h = res
        short = min(w, h)
        if short < self.min_short_side:
            return True, f"{w}x{h} (short={short} < {self.min_short_side})"
        return False, f"{w}x{h} (already OK)"

    # ─── URL Reconstruction ───
    def extract_video_id(self, filename):
        """
        Extract FB video ID dari filename.
        Format: '{id}_{title}.mp4' atau '{id}.mp4'
        """
        stem = os.path.splitext(filename)[0]
        m = re.match(r"^(\d{10,})", stem)
        return m.group(1) if m else None

    def build_url(self, video_id):
        return f"https://m.facebook.com/watch/?v={video_id}"

    # ─── Download ───
    def download_to_temp(self, video_id, temp_dir):
        """Download ke temp folder. Return dict of paths, atau (None, error)."""
        url = self.build_url(video_id)
        output_tpl = os.path.join(temp_dir, f"{video_id}.%(ext)s")

        cmd = [
            "yt-dlp",
            "--impersonate", "chrome-131",
            "--format", YTDLP_FORMAT,
            "--output", output_tpl,
            "--write-info-json",
            "--write-thumbnail",
            "--convert-thumbnails", "jpg",
            "--merge-output-format", "mp4",
            "--no-warnings",
            "--no-check-certificate",
            "--geo-bypass",
            "--retries", "2",
            "--fragment-retries", "2",
            "--socket-timeout", "30",
        ]

        if self.cookies and os.path.exists(self.cookies):
            cmd.extend(["--cookies", self.cookies])

        cmd.append(url)

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=300,
                encoding="utf-8",
                errors="replace",
            )
            if result.returncode != 0:
                err = (result.stderr or "")[-500:]
                return None, f"yt-dlp exit {result.returncode}: {err}"
        except subprocess.TimeoutExpired:
            return None, "timeout 300s"
        except Exception as e:
            return None, f"exception: {str(e)[:200]}"

        mp4 = os.path.join(temp_dir, f"{video_id}.mp4")
        info = os.path.join(temp_dir, f"{video_id}.info.json")
        thumb_jpg = os.path.join(temp_dir, f"{video_id}.jpg")
        thumb_webp = os.path.join(temp_dir, f"{video_id}.webp")

        if not os.path.exists(mp4):
            return None, "no mp4 produced"

        thumb = None
        if os.path.exists(thumb_jpg):
            thumb = thumb_jpg
        elif os.path.exists(thumb_webp):
            thumb = thumb_webp

        return {
            "mp4": mp4,
            "info": info if os.path.exists(info) else None,
            "thumb": thumb,
        }, None

    # ─── Replace ───
    def replace_mp4(self, old_path, new_mp4):
        """Replace file .mp4 lama dengan yang baru (nama file sama)."""
        if self.keep_original:
            backup = old_path + ".original"
            if not os.path.exists(backup):
                try:
                    shutil.copy2(old_path, backup)
                except Exception as e:
                    print(f"  ⚠️  Backup failed: {e}")

        # os.replace = atomic (Windows & Unix)
        try:
            os.replace(new_mp4, old_path)
            return True
        except Exception as e:
            print(f"  ❌ Replace mp4 failed: {e}")
            return False

    def replace_info(self, old_mp4_path, new_info):
        """Replace .info.json sibling."""
        if not new_info or not os.path.exists(new_info):
            return False
        base = os.path.splitext(old_mp4_path)[0]
        target = base + ".info.json"
        try:
            os.replace(new_info, target)
            return True
        except Exception:
            return False

    def replace_thumbnail(self, old_mp4_path, new_thumb):
        """
        Replace thumbnail. Handle perbedaan extension (webp → jpg).
        Return path ke thumbnail baru (untuk DB update), atau None.
        """
        if not new_thumb or not os.path.exists(new_thumb):
            return None

        base = os.path.splitext(old_mp4_path)[0]

        # Cek thumbnail lama
        old_thumb = None
        for ext in (".jpg", ".jpeg", ".webp", ".png"):
            candidate = base + ext
            if os.path.exists(candidate):
                old_thumb = candidate
                break

        new_ext = os.path.splitext(new_thumb)[1].lower()
        new_target = base + new_ext

        try:
            os.replace(new_thumb, new_target)
        except Exception as e:
            print(f"  ⚠️  Replace thumb failed: {e}")
            return None

        # Hapus thumbnail lama kalau beda path
        if old_thumb and old_thumb != new_target:
            try:
                os.remove(old_thumb)
            except Exception:
                pass

        return new_target

    # ─── Process One ───
    def process_one(self, row):
        media_id, filename, full_path, old_thumb = row

        video_id = self.extract_video_id(filename)
        if not video_id:
            print(f"  ⚠️  Cannot extract ID from: {filename}")
            return "skip_id"

        if not os.path.exists(full_path):
            print(f"  ⚠️  File not found: {full_path}")
            self.stats["skipped_missing"] += 1
            return "skip_missing"

        # Cek apakah perlu upgrade
        need, reason = self.needs_upgrade(full_path)
        if not need:
            print(f"  ⏭️  Skip — {reason}")
            self.stats["skipped_good"] += 1
            return "skip_good"

        old_size = os.path.getsize(full_path)
        old_res = self.get_resolution(full_path)
        print(f"  📊 Current: {old_res[0]}x{old_res[1]} ({old_size / 1024:.0f} KB) — {reason}")

        if not self.apply:
            print(f"  [DRY] Would download: {self.build_url(video_id)}")
            return "dry"

        # Download to temp
        temp_dir = tempfile.mkdtemp(prefix="fb_repair_")
        try:
            print(f"  ⬇️  Downloading from {self.build_url(video_id)}...")
            files, err = self.download_to_temp(video_id, temp_dir)

            if not files:
                print(f"  ❌ Download failed: {err}")
                self.stats["failed_download"] += 1
                return "fail_dl"

            # Verify new file
            new_res = self.get_resolution(files["mp4"])
            new_size = os.path.getsize(files["mp4"])

            if not new_res:
                print(f"  ❌ Cannot verify new resolution")
                self.stats["failed_verify"] += 1
                return "fail_verify"

            # Compare resolutions
            old_pixels = old_res[0] * old_res[1] if old_res else 0
            new_pixels = new_res[0] * new_res[1]

            if new_pixels <= old_pixels:
                print(f"  ⚠️  New resolution not better: {new_res[0]}x{new_res[1]} "
                      f"<= {old_res[0]}x{old_res[1]} — skip replace")
                self.stats["skipped_good"] += 1
                return "no_gain"

            print(f"  ✅ New: {new_res[0]}x{new_res[1]} ({new_size / 1024:.0f} KB) "
                  f"— upgrade {old_pixels} → {new_pixels} px")

            # Replace
            if not self.replace_mp4(full_path, files["mp4"]):
                self.stats["failed_verify"] += 1
                return "fail_replace"

            self.replace_info(full_path, files["info"])

            new_thumb_path = self.replace_thumbnail(full_path, files["thumb"])
            if new_thumb_path:
                self.update_db_thumbnail(media_id, new_thumb_path)

            self.stats["upgraded"] += 1
            return "ok"

        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    # ─── Run ───
    def run(self):
        print("=" * 65)
        print("📘 Facebook Quality Repair")
        print("=" * 65)
        print(f"DB          : {self.db_path}")
        print(f"Cookies     : {self.cookies or '(none)'}")
        print(f"Mode        : {'APPLY' if self.apply else 'DRY-RUN'}")
        print(f"Force       : {self.force}")
        print(f"Min short   : {self.min_short_side} px")
        print(f"Limit       : {self.limit if self.limit > 0 else 'no limit'}")
        print(f"Keep backup : {self.keep_original}")
        print("=" * 65)
        print()

        entries = self.get_facebook_entries()
        self.stats["total"] = len(entries)

        if not entries:
            print("⚠️  Tidak ada video Facebook di DB.")
            return

        print(f"📊 Total video Facebook di DB: {len(entries)}")
        print()

        start = time.time()
        for idx, row in enumerate(entries, 1):
            if self.limit > 0 and idx > self.limit:
                print(f"\n⏸️  Limit {self.limit} tercapai, stop.")
                break

            media_id, filename, full_path, _ = row
            print(f"[{idx}/{len(entries)}] #{media_id} {filename[:60]}")
            self.stats["processed"] += 1

            try:
                self.process_one(row)
            except KeyboardInterrupt:
                print("\n⏸️  Dibatalkan user")
                break
            except Exception as e:
                print(f"  ❌ Unexpected error: {str(e)[:200]}")
                self.stats["failed_download"] += 1

            # Delay antar video (rate limit FB)
            if idx < len(entries) and self.apply:
                time.sleep(3)

            print()

        elapsed = time.time() - start
        self.print_summary(elapsed)

    def print_summary(self, elapsed):
        print("=" * 65)
        print("📊 SUMMARY")
        print("=" * 65)
        s = self.stats
        print(f"   Total di DB          : {s['total']}")
        print(f"   Diproses             : {s['processed']}")
        print(f"   ✅ Di-upgrade         : {s['upgraded']}")
        print(f"   ⏭️  Sudah bagus        : {s['skipped_good']}")
        print(f"   ⚠️  File hilang        : {s['skipped_missing']}")
        print(f"   ❌ Download gagal    : {s['failed_download']}")
        print(f"   ❌ Verify/replace    : {s['failed_verify']}")
        print(f"   💾 DB updated        : {s['db_updated']}")
        print(f"   ⏱️  Waktu: {elapsed:.1f}s")
        print("=" * 65)
        if not self.apply:
            print()
            print("ℹ️  Ini DRY-RUN. Jalankan dengan --apply untuk eksekusi.")


# ══════════════════════════════════════════════════════════
# ENTRY
# ══════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="Repair kualitas video Facebook di DB — re-download resolusi tinggi.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Contoh:
    python repair_facebook_quality.py --dry-run
    python repair_facebook_quality.py --apply --limit 5
    python repair_facebook_quality.py --apply
    python repair_facebook_quality.py --apply --force
        """,
    )
    parser.add_argument("--apply", action="store_true",
                        help="Eksekusi (default: dry-run)")
    parser.add_argument("--limit", type=int, default=0,
                        help="Limit jumlah video (0 = semua)")
    parser.add_argument("--force", action="store_true",
                        help="Re-download semua, bahkan yang sudah HD")
    parser.add_argument("--min-short-side", type=int, default=DEFAULT_MIN_SHORT_SIDE,
                        help=f"Target minimal sisi pendek (default: {DEFAULT_MIN_SHORT_SIDE})")
    parser.add_argument("--keep-original", action="store_true",
                        help="Simpan file lama sebagai .original")

    args = parser.parse_args()

    db = find_db()
    if not db:
        print("❌ media_library.db tidak ditemukan di:")
        for p in DB_CANDIDATES:
            print(f"   - {p}")
        sys.exit(1)

    # Sanity check: yt-dlp & ffmpeg tersedia
    for tool in ("yt-dlp", "ffmpeg", "ffprobe"):
        if shutil.which(tool) is None:
            print(f"❌ '{tool}' tidak ditemukan di PATH. Install dulu.")
            sys.exit(1)

    repair = FacebookQualityRepair(
        db_path=db,
        apply=args.apply,
        limit=args.limit,
        force=args.force,
        min_short_side=args.min_short_side,
        keep_original=args.keep_original,
    )

    try:
        repair.run()
    except KeyboardInterrupt:
        print("\n⏸️  Dibatalkan")


if __name__ == "__main__":
    main()