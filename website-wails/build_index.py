"""
🚀 BUILD INDEX SCRIPT
Run this script once to build SQLite database index.
Much faster than JSON for queries!

Usage: python build_index.py
"""

import sqlite3
import json
import os
import re
from pathlib import Path
from datetime import datetime
import time

# Try to import cv2 for thumbnail generation
try:
    import cv2
    HAS_CV2 = True
except ImportError:
    HAS_CV2 = False
    print("⚠️  OpenCV (cv2) not installed. Video thumbnails will not be generated.")
    print("   Install with: pip install opencv-python")

# Configuration - relative to scrapping folder
SCRAPPING_ROOT = Path(__file__).parent.parent
TWITTER_DOWNLOADS = SCRAPPING_ROOT / "twitter" / "twitter_downloads"
INSTAGRAM_DOWNLOADS = SCRAPPING_ROOT / "instagram" / "Download"
TIKTOK_DOWNLOADS = SCRAPPING_ROOT / "tiktok" / "tiktok_downloads"
DB_FILE = Path(__file__).parent / "media_library.db"

# Video extensions for detection
VIDEO_EXTS = {'.mp4', '.avi', '.mov', '.wmv', '.flv', '.mkv', '.webm', '.m4v', '.mpeg', '.mpg'}
IMAGE_EXTS = {'.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp', '.svg', '.ico'}

def generate_video_thumbnail(video_path, thumbnail_path):
    """Generate thumbnail from first frame of video"""
    if not HAS_CV2:
        return False
    
    try:
        # Open video
        cap = cv2.VideoCapture(str(video_path))
        if not cap.isOpened():
            return False
        
        # Read first frame
        ret, frame = cap.read()
        cap.release()
        
        if not ret or frame is None:
            return False
        
        # Resize to max 400px width while keeping aspect ratio
        height, width = frame.shape[:2]
        max_width = 400
        if width > max_width:
            ratio = max_width / width
            new_size = (max_width, int(height * ratio))
            frame = cv2.resize(frame, new_size, interpolation=cv2.INTER_AREA)
        
        # Save thumbnail
        thumbnail_path.parent.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(str(thumbnail_path), frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
        return True
        
    except Exception as e:
        print(f"      ⚠️ Thumbnail error: {e}")
        return False

def get_media_type(filename):
    """Detect media type from filename"""
    if not filename:
        return 'unknown'
    ext = Path(filename).suffix.lower()
    if ext in VIDEO_EXTS:
        return 'video'
    if ext in IMAGE_EXTS:
        return 'photo'
    return 'unknown'

def extract_hashtags(caption):
    """Extract hashtags from caption"""
    if not caption:
        return []
    return re.findall(r'#(\w+)', caption)

def create_database():
    """Create SQLite database with optimized schema"""
    print("🔧 Creating database schema...")
    
    conn = sqlite3.connect(str(DB_FILE))
    c = conn.cursor()
    
    # Drop existing tables (including FTS)
    c.execute("DROP TABLE IF EXISTS media_fts")
    c.execute("DROP TABLE IF EXISTS media_tags")
    c.execute("DROP TABLE IF EXISTS tags")
    c.execute("DROP TABLE IF EXISTS media")
    
    # Main media table with indexes
    c.execute("""
        CREATE TABLE media (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            platform TEXT NOT NULL,
            account TEXT NOT NULL,
            type TEXT NOT NULL,
            filename TEXT,
            folder TEXT,
            year TEXT,
            timestamp TEXT,
            caption TEXT,
            likes INTEGER DEFAULT 0,
            url TEXT,
            full_path TEXT,
            thumbnail TEXT
        )
    """)
    
    # Tags table
    c.execute("""
        CREATE TABLE tags (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL
        )
    """)
    
    # Many-to-many relation
    c.execute("""
        CREATE TABLE media_tags (
            media_id INTEGER,
            tag_id INTEGER,
            PRIMARY KEY (media_id, tag_id),
            FOREIGN KEY (media_id) REFERENCES media(id),
            FOREIGN KEY (tag_id) REFERENCES tags(id)
        )
    """)
    
    # Create indexes for fast queries
    c.execute("CREATE INDEX idx_media_platform ON media(platform)")
    c.execute("CREATE INDEX idx_media_account ON media(account)")
    c.execute("CREATE INDEX idx_media_type ON media(type)")
    c.execute("CREATE INDEX idx_media_year ON media(year)")
    c.execute("CREATE INDEX idx_media_timestamp ON media(timestamp DESC)")
    c.execute("CREATE INDEX idx_tags_name ON tags(name)")
    
    # Full-text search for captions (super fast!)
    c.execute("""
        CREATE VIRTUAL TABLE media_fts USING fts5(
            caption,
            content='media',
            content_rowid='id'
        )
    """)
    
    conn.commit()
    return conn

def load_twitter(conn):
    """Load Twitter data"""
    if not TWITTER_DOWNLOADS.exists():
        return 0
    
    print(f"\n📁 Scanning Twitter: {TWITTER_DOWNLOADS}")
    c = conn.cursor()
    count = 0
    thumb_count = 0
    
    for account_folder in TWITTER_DOWNLOADS.iterdir():
        if not account_folder.is_dir():
            continue
            
        progress_file = account_folder / "progress_v2.json"
        if not progress_file.exists():
            continue
        
        # Create thumbnails folder for this account
        thumb_folder = account_folder / "thumbnails"
            
        try:
            with open(progress_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            for media in data.get('media_data', []):
                filename = media.get('filename', '')
                media_type = get_media_type(filename)
                if media_type == 'unknown':
                    media_type = media.get('type', 'photo')
                
                caption = media.get('caption', '')
                full_path = account_folder / media.get('folder', '')
                
                # Generate thumbnail for videos
                thumbnail_path = ''
                if media_type == 'video' and full_path.exists():
                    thumb_name = Path(filename).stem + '_thumb.jpg'
                    thumb_file = thumb_folder / thumb_name
                    
                    # Only generate if doesn't exist
                    if not thumb_file.exists():
                        if generate_video_thumbnail(full_path, thumb_file):
                            thumb_count += 1
                    
                    if thumb_file.exists():
                        thumbnail_path = str(thumb_file)
                
                c.execute("""
                    INSERT INTO media (platform, account, type, filename, folder, year, timestamp, caption, full_path, thumbnail)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    'Twitter',
                    account_folder.name,
                    media_type,
                    filename,
                    media.get('folder', ''),
                    str(media.get('year', 'Unknown')),
                    media.get('timestamp', ''),
                    caption,
                    str(full_path),
                    thumbnail_path
                ))
                
                media_id = c.lastrowid
                
                # Insert into FTS
                c.execute("INSERT INTO media_fts(rowid, caption) VALUES (?, ?)", (media_id, caption))
                
                # Extract and insert tags
                tags = extract_hashtags(caption)
                for tag in tags:
                    c.execute("INSERT OR IGNORE INTO tags (name) VALUES (?)", (tag,))
                    c.execute("SELECT id FROM tags WHERE name = ?", (tag,))
                    tag_id = c.fetchone()[0]
                    c.execute("INSERT OR IGNORE INTO media_tags (media_id, tag_id) VALUES (?, ?)", (media_id, tag_id))
                
                count += 1
            
            print(f"   ✓ {account_folder.name}: {len(data.get('media_data', []))} media" + 
                  (f" ({thumb_count} thumbnails)" if thumb_count > 0 else ""))
            
        except Exception as e:
            print(f"   ✗ Error: {e}")
    
    conn.commit()
    return count

def load_instagram(conn):
    """Load Instagram data"""
    if not INSTAGRAM_DOWNLOADS.exists():
        return 0
    
    print(f"\n📁 Scanning Instagram: {INSTAGRAM_DOWNLOADS}")
    c = conn.cursor()
    count = 0
    thumb_count = 0
    
    for user_folder in INSTAGRAM_DOWNLOADS.iterdir():
        if not user_folder.is_dir():
            continue
            
        data_file = user_folder / f"{user_folder.name}_data.json"
        if not data_file.exists():
            continue
        
        # Thumbnails folder for this user
        thumb_folder = user_folder / "thumbnails"
            
        try:
            with open(data_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            posts_count = 0
            user_thumb_count = 0
            for post in data.get('posts', []):
                shortcode = post.get('shortcode', '')
                year = post.get('year', 'Unknown')
                post_type = post.get('type', 'photo')
                date_utc = post.get('date_utc', '')
                caption = post.get('caption', '')
                hashtags = post.get('hashtags', [])
                
                # Determine folder type
                folder_type = 'reel' if post_type == 'video' else 'photo'
                year_folder = user_folder / folder_type / str(year)
                
                if not year_folder.exists():
                    continue
                
                # Find caption files
                caption_files = list(year_folder.glob(f"*{shortcode}_caption.txt"))
                if not caption_files:
                    continue
                
                caption_file = caption_files[0]
                timestamp_part = caption_file.stem.replace(f"_{shortcode}_caption", "")
                
                # Find media files - try exact match first, then with suffix
                file_ext = '.mp4' if post_type == 'video' else '.jpg'
                
                # Try exact filename (e.g., "2024-01-03_12-31-58_UTC.jpg")
                exact_file = year_folder / f"{timestamp_part}{file_ext}"
                if exact_file.exists():
                    media_files = [exact_file]
                else:
                    # Try with suffix (e.g., "2024-01-03_12-31-58_UTC_1.jpg")
                    media_files = list(year_folder.glob(f"{timestamp_part}_*{file_ext}"))
                
                # Also check for other extensions
                if not media_files:
                    for ext in [file_ext] + list(VIDEO_EXTS) + list(IMAGE_EXTS):
                        exact_file = year_folder / f"{timestamp_part}{ext}"
                        if exact_file.exists():
                            media_files = [exact_file]
                            break
                        media_files = list(year_folder.glob(f"{timestamp_part}_*{ext}"))
                        if media_files:
                            break
                
                for media_file in media_files:
                    relative_path = media_file.relative_to(user_folder)
                    detected_type = get_media_type(media_file.name)
                    final_type = detected_type if detected_type != 'unknown' else post_type
                    
                    # Check for thumbnail (for videos)
                    thumbnail_path = ''
                    if final_type == 'video':
                        # Method 1: Check from metadata
                        if post.get('thumbnail') and Path(post['thumbnail']).exists():
                            thumbnail_path = post['thumbnail']
                        # Method 2: Look for shortcode_thumb.jpg in thumbnails folder
                        elif thumb_folder.exists():
                            thumb_file = thumb_folder / f"{shortcode}_thumb.jpg"
                            if thumb_file.exists():
                                thumbnail_path = str(thumb_file)
                        
                        if thumbnail_path:
                            user_thumb_count += 1
                    
                    c.execute("""
                        INSERT INTO media (platform, account, type, filename, folder, year, timestamp, caption, likes, url, full_path, thumbnail)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        'Instagram',
                        '@' + user_folder.name,
                        final_type,
                        media_file.name,
                        str(relative_path).replace('\\', '/'),
                        str(year),
                        date_utc,
                        caption,
                        post.get('likes', 0),
                        post.get('url', ''),
                        str(media_file),  # Full path to actual file
                        thumbnail_path
                    ))
                    
                    media_id = c.lastrowid
                    
                    # Insert into FTS
                    c.execute("INSERT INTO media_fts(rowid, caption) VALUES (?, ?)", (media_id, caption))
                    
                    # Insert tags
                    for tag in hashtags:
                        c.execute("INSERT OR IGNORE INTO tags (name) VALUES (?)", (tag,))
                        c.execute("SELECT id FROM tags WHERE name = ?", (tag,))
                        tag_id = c.fetchone()[0]
                        c.execute("INSERT OR IGNORE INTO media_tags (media_id, tag_id) VALUES (?, ?)", (media_id, tag_id))
                    
                    count += 1
                    posts_count += 1
            
            thumb_count += user_thumb_count
            print(f"   ✓ @{user_folder.name}: {posts_count} media" +
                  (f" ({user_thumb_count} thumbnails)" if user_thumb_count > 0 else ""))
            
        except Exception as e:
            print(f"   ✗ Error: {e}")
    
    conn.commit()
    print(f"   📷 Total thumbnails indexed: {thumb_count}")
    return count

def load_tiktok(conn):
    """Load TikTok data"""
    if not TIKTOK_DOWNLOADS.exists():
        return 0
    
    print(f"\n📁 Scanning TikTok: {TIKTOK_DOWNLOADS}")
    c = conn.cursor()
    count = 0
    
    for user_folder in TIKTOK_DOWNLOADS.iterdir():
        if not user_folder.is_dir() or not user_folder.name.startswith('@'):
            continue
            
        metadata_file = user_folder / "videos" / "metadata.json"
        if not metadata_file.exists():
            continue
            
        try:
            with open(metadata_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            for video in data:
                filename = video.get('filename', '')
                detected_type = get_media_type(filename)
                final_type = detected_type if detected_type != 'unknown' else 'video'
                
                try:
                    create_time = datetime.fromisoformat(video.get('create_time', ''))
                    year = str(create_time.year)
                except:
                    year = 'Unknown'
                
                caption = video.get('caption', '')
                tags = video.get('tags', [])
                
                # Build full path from relative folder path
                relative_folder = video.get('folder', '')
                videos_dir = user_folder / "videos"
                full_path = str(videos_dir / relative_folder) if relative_folder else ''
                
                # Build thumbnail path for TikTok videos
                thumbnail_path = ''
                relative_thumb = video.get('thumbnail', '')
                if relative_thumb:
                    thumb_full = videos_dir / relative_thumb
                    if thumb_full.exists():
                        thumbnail_path = str(thumb_full)
                
                c.execute("""
                    INSERT INTO media (platform, account, type, filename, folder, year, timestamp, caption, full_path, thumbnail)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    'TikTok',
                    user_folder.name,
                    final_type,
                    filename,
                    f"videos/{filename}",
                    year,
                    video.get('create_time', ''),
                    caption,
                    full_path,
                    thumbnail_path
                ))
                
                media_id = c.lastrowid
                
                # Insert into FTS
                c.execute("INSERT INTO media_fts(rowid, caption) VALUES (?, ?)", (media_id, caption))
                
                # Insert tags
                for tag in tags:
                    c.execute("INSERT OR IGNORE INTO tags (name) VALUES (?)", (tag,))
                    c.execute("SELECT id FROM tags WHERE name = ?", (tag,))
                    tag_id = c.fetchone()[0]
                    c.execute("INSERT OR IGNORE INTO media_tags (media_id, tag_id) VALUES (?, ?)", (media_id, tag_id))
                
                count += 1
            
            print(f"   ✓ {user_folder.name}: {len(data)} videos")
            
        except Exception as e:
            print(f"   ✗ Error: {e}")
    
    conn.commit()
    return count

def build_index():
    """Main function to build the index"""
    print("="*70)
    print("🚀 BUILDING MEDIA INDEX")
    print("="*70)
    
    start_time = time.time()
    
    # Create database
    conn = create_database()
    
    # Load all platforms
    twitter_count = load_twitter(conn)
    instagram_count = load_instagram(conn)
    tiktok_count = load_tiktok(conn)
    
    total = twitter_count + instagram_count + tiktok_count
    
    # Get stats
    c = conn.cursor()
    c.execute("SELECT COUNT(DISTINCT name) FROM tags")
    tag_count = c.fetchone()[0]
    
    c.execute("SELECT COUNT(DISTINCT account) FROM media")
    account_count = c.fetchone()[0]
    
    c.execute("SELECT COUNT(*) FROM media WHERE type = 'video'")
    video_count = c.fetchone()[0]
    
    c.execute("SELECT COUNT(*) FROM media WHERE type IN ('photo', 'image')")
    image_count = c.fetchone()[0]
    
    conn.close()
    
    elapsed = time.time() - start_time
    
    print("\n" + "="*70)
    print("✅ INDEX BUILD COMPLETE!")
    print("="*70)
    print(f"📊 Total Media: {total}")
    print(f"   📷 Instagram: {instagram_count}")
    print(f"   🎵 TikTok: {tiktok_count}")
    print(f"   🐦 Twitter: {twitter_count}")
    print(f"\n📸 Images: {image_count}")
    print(f"🎬 Videos: {video_count}")
    print(f"🏷️  Tags: {tag_count}")
    print(f"👤 Accounts: {account_count}")
    print(f"\n⏱️  Time: {elapsed:.2f} seconds")
    print(f"💾 Database: {DB_FILE}")
    print(f"📦 Size: {DB_FILE.stat().st_size / 1024 / 1024:.2f} MB")
    print("="*70)

if __name__ == '__main__':
    build_index()
