r"""
Group Downloader — dipanggil Wails saat user klik "Download New Posts".

Usage:
    python group_downloader.py <group_id> <platforms_csv>

Contoh:
    python group_downloader.py 1 instagram,tiktok

Karakteristik:
- LINEAR: satu akun diproses sampai selesai, baru lanjut akun berikutnya
- Fokus: cek post baru, download hanya yang belum ada
- Update last_check_at & last_download_at per akun
- Update idol_group_runs untuk progress
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


class GroupDownloader:
    def __init__(self, db_path, group_id, platforms, delay=1.0):
        self.db_path = db_path
        self.group_id = group_id
        self.platforms = platforms
        self.delay = delay
        self.stop = False
        self.run_id = None

    # ══════════════════════════════════════════════════════
    # DB helpers
    # ══════════════════════════════════════════════════════
    def conn(self):
        c = sqlite3.connect(self.db_path, timeout=30, isolation_level=None)
        c.text_factory = _safe_decode
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("PRAGMA busy_timeout=10000")
        return c

    def get_descendant_ids(self, root_id):
        """Return list semua descendant group ID (termasuk root)."""
        ids = [root_id]
        with self.conn() as c:
            stack = [root_id]
            while stack:
                cur = stack.pop()
                rows = c.execute(
                    "SELECT id FROM idol_groups WHERE parent_id = ?", (cur,)
                ).fetchall()
                for (child_id,) in rows:
                    ids.append(child_id)
                    stack.append(child_id)
        return ids

    def get_accounts(self):
        """Ambil accounts (aktif) dari group + semua descendant, filter platform."""
        group_ids = self.get_descendant_ids(self.group_id)
        placeholders = ",".join("?" * len(group_ids))
        plat_holders = ",".join("?" * len(self.platforms))

        with self.conn() as c:
            rows = c.execute(f"""
                SELECT a.id, a.group_id, a.platform, a.username,
                       g.name as member_name
                FROM idol_accounts a
                JOIN idol_groups g ON a.group_id = g.id
                WHERE a.group_id IN ({placeholders})
                  AND a.enabled = 1
                  AND a.platform IN ({plat_holders})
                ORDER BY g.sort_order, g.name, a.platform, a.username
            """, group_ids + self.platforms).fetchall()
        return rows

    def create_run(self, total):
        with self.conn() as c:
            cur = c.execute("""
                INSERT INTO idol_group_runs
                (group_id, status, total_accounts, started_at)
                VALUES (?, 'running', ?, datetime('now'))
            """, (self.group_id, total))
            self.run_id = cur.lastrowid
        return self.run_id

    def update_run(self, **kwargs):
        if not self.run_id:
            return
        sets, args = [], []
        for k, v in kwargs.items():
            sets.append(f"{k} = ?")
            args.append(v)
        args.append(self.run_id)
        with self.conn() as c:
            c.execute(f"UPDATE idol_group_runs SET {', '.join(sets)} WHERE id = ?", args)

    def finalize_run(self, status):
        if not self.run_id:
            return
        with self.conn() as c:
            c.execute("""
                UPDATE idol_group_runs
                SET status = ?, finished_at = datetime('now')
                WHERE id = ?
            """, (status, self.run_id))

    def mark_checked(self, account_id, had_new=False):
        with self.conn() as c:
            if had_new:
                c.execute("""
                    UPDATE idol_accounts
                    SET last_check_at = datetime('now'),
                        last_download_at = datetime('now')
                    WHERE id = ?
                """, (account_id,))
            else:
                c.execute("""
                    UPDATE idol_accounts SET last_check_at = datetime('now')
                    WHERE id = ?
                """, (account_id,))

    # ══════════════════════════════════════════════════════
    # PLATFORM: Instagram
    # ══════════════════════════════════════════════════════
    def process_instagram(self, username):
        """
        Return (success, new_found, new_downloaded).
        Linear: extract -> filter new -> download new -> save cache.
        """
        from instagram.extractor import InstagramExtractor
        from instagram.downloader import InstagramDownloader
        from instagram.config import InstagramConfig

        print(f"   IG: @{username}", flush=True)

        # 1. Load cache shortcode yang ada
        cached = InstagramExtractor.load_cached_shortcodes(username)
        print(f"      Cache: {len(cached)} shortcode lama", flush=True)

        cfg = InstagramConfig()

        # 2. Extract (fast-path kalau cache lengkap)
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
            err = result.get("error", "extract failed")
            raise Exception(f"Extract gagal: {err}")

        shortcodes = result.get("links", [])
        cached_set = set(cached)
        new_codes = [sc for sc in shortcodes if sc not in cached_set]

        print(f"      Total post: {len(shortcodes)} | Baru: {len(new_codes)}", flush=True)

        if not new_codes:
            return True, 0, 0

        # 3. Update cache dulu
        InstagramExtractor.save_results(username, shortcodes, result.get("stats"))

        # 4. Download hanya yang baru — LINEAR (workers=1)
        print(f"      Downloading {len(new_codes)} post baru (linear)...", flush=True)

        InstagramDownloader.download_user(
            shortcodes,
            username,
            config=cfg,
            stop_event=None,
            on_log=lambda m: print(f"      {m}", flush=True),
            on_progress=lambda c, t, m: None,
            max_workers=1,
            download_delay=0.5,
        )

        return True, len(new_codes), len(new_codes)

    # ══════════════════════════════════════════════════════
    # PLATFORM: TikTok
    # ══════════════════════════════════════════════════════
    def process_tiktok(self, username):
        """
        Return (success, new_found, new_downloaded).
        """
        from tiktok.downloader import TikTokDownloader

        print(f"   TikTok: @{username}", flush=True)

        url = TikTokDownloader.normalize_url("@" + username)

        # Cek archive sebelum
        exists_before, count_before, _ = TikTokDownloader.get_archive_info(url)
        print(f"      Archive sebelum: {count_before} video", flush=True)

        # Download (pakai archive -> auto-skip duplikat)
        ok = TikTokDownloader.download(
            url,
            quality="hd",
            use_archive=True,
            on_log=lambda m: print(f"      {m}", flush=True),
        )

        # Cek archive sesudah
        exists_after, count_after, _ = TikTokDownloader.get_archive_info(url)
        new_found = max(0, count_after - count_before)
        print(f"      Archive sesudah: {count_after} | Baru: {new_found}", flush=True)

        return bool(ok), new_found, new_found

    # ══════════════════════════════════════════════════════
    # MAIN LOOP (LINEAR)
    # ══════════════════════════════════════════════════════
    def run(self):
        accounts = self.get_accounts()
        total = len(accounts)

        print("=" * 60, flush=True)
        print(f"Group Downloader", flush=True)
        print(f"Group ID: {self.group_id}", flush=True)
        print(f"Platform: {', '.join(self.platforms)}", flush=True)
        print(f"Total akun: {total}", flush=True)
        print("=" * 60, flush=True)
        print("", flush=True)

        if total == 0:
            print("Tidak ada akun aktif untuk di-proses", flush=True)
            return

        self.create_run(total)

        checked = 0
        new_found = 0
        new_downloaded = 0
        errors = []

        for idx, (acc_id, gid, platform, username, member_name) in enumerate(accounts, 1):
            if self.stop:
                print("Stop requested", flush=True)
                break

            print("", flush=True)
            print(f"-> [{idx}/{total}] {member_name} — @{username}", flush=True)
            print("-" * 55, flush=True)

            try:
                if platform == "instagram":
                    _, nf, nd = self.process_instagram(username)
                elif platform == "tiktok":
                    _, nf, nd = self.process_tiktok(username)
                else:
                    print(f"   Platform belum didukung: {platform}", flush=True)
                    continue

                checked += 1
                new_found += nf
                new_downloaded += nd
                self.mark_checked(acc_id, had_new=(nd > 0))

                self.update_run(
                    checked_accounts=checked,
                    new_posts_found=new_found,
                    new_posts_downloaded=new_downloaded,
                )

                if nd > 0:
                    print(f"   Selesai — {nd} post baru diunduh", flush=True)
                else:
                    print(f"   Tidak ada post baru", flush=True)

            except Exception as e:
                err = str(e)[:200]
                errors.append(f"{member_name}/{platform}/@{username}: {err}")
                print(f"   ERROR: {err}", flush=True)

            # Delay antar akun (LINEAR)
            if idx < total and not self.stop:
                time.sleep(self.delay)

        # Finalize
        final_status = "done" if not self.stop else "cancelled"
        self.update_run(
            checked_accounts=checked,
            new_posts_found=new_found,
            new_posts_downloaded=new_downloaded,
            error="\n".join(errors[:20]) if errors else "",
        )
        self.finalize_run(final_status)

        print("", flush=True)
        print("=" * 60, flush=True)
        print(f"SELESAI", flush=True)
        print(f"   Akun dicek:    {checked}/{total}", flush=True)
        print(f"   Post baru:     {new_found}", flush=True)
        print(f"   Post diunduh:  {new_downloaded}", flush=True)
        if errors:
            print(f"   Error:         {len(errors)}", flush=True)
        print("=" * 60, flush=True)


# ══════════════════════════════════════════════════════════
# ENTRY
# ══════════════════════════════════════════════════════════
def main():
    if len(sys.argv) < 3:
        print("Usage: python group_downloader.py <group_id> <platforms_csv>")
        sys.exit(1)

    try:
        group_id = int(sys.argv[1])
    except ValueError:
        print("group_id harus angka")
        sys.exit(1)

    platforms = [p.strip().lower() for p in sys.argv[2].split(",") if p.strip()]
    valid = {"instagram", "tiktok"}
    platforms = [p for p in platforms if p in valid]
    if not platforms:
        print("Tidak ada platform valid (instagram, tiktok)")
        sys.exit(1)

    db = find_db()
    if not db:
        print("media_library.db tidak ditemukan")
        for p in DB_CANDIDATES:
            print(f"   - {p}")
        sys.exit(1)

    dl = GroupDownloader(db, group_id, platforms, delay=1.0)

    def handler(sig, frame):
        print("", flush=True)
        print("Stop signal received", flush=True)
        dl.stop = True

    signal.signal(signal.SIGINT, handler)
    signal.signal(signal.SIGTERM, handler)

    try:
        dl.run()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()