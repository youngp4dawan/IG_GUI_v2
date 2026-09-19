"""
Chrome Profile Detector
========================
Detect & save Chrome profile path ke config.
Tidak copy file — pakai profile asli langsung.
"""
import os
import json
import subprocess
from pathlib import Path


def get_chrome_user_data_path():
    """Return path ke Chrome User Data (Windows)."""
    local = os.environ.get("LOCALAPPDATA", "")
    candidates = [
        Path(local) / "Google" / "Chrome" / "User Data",
        Path(local) / "Google" / "Chrome Beta" / "User Data",
        Path(local) / "Google" / "Chrome SxS" / "User Data",
    ]
    for c in candidates:
        if c.exists():
            return c
    return None


def list_chrome_profiles():
    """Scan semua Chrome profile yang tersedia."""
    user_data = get_chrome_user_data_path()
    if not user_data:
        return []

    profiles = []

    # Baca Local State untuk nama + email profile
    local_state_path = user_data / "Local State"
    profile_map = {}
    if local_state_path.exists():
        try:
            with open(local_state_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            info_cache = data.get("profile", {}).get("info_cache", {})
            for folder, info in info_cache.items():
                profile_map[folder] = {
                    "name": info.get("name", folder),
                    "email": info.get("user_name", ""),
                }
        except Exception:
            pass

    # Scan folder
    for item in user_data.iterdir():
        if not item.is_dir():
            continue
        if item.name == "Default" or item.name.startswith("Profile "):
            prefs = item / "Preferences"
            if not prefs.exists():
                continue

            info = profile_map.get(item.name, {})
            profiles.append({
                "folder": item.name,
                "name": info.get("name", item.name),
                "email": info.get("email", ""),
                "path": str(item),
            })

    profiles.sort(key=lambda p: (p["folder"] != "Default", p["folder"]))
    return profiles


def is_chrome_running():
    try:
        result = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq chrome.exe"],
            capture_output=True, text=True, timeout=5,
        )
        return "chrome.exe" in result.stdout.lower()
    except Exception:
        return False


def kill_chrome():
    try:
        subprocess.run(["taskkill", "/F", "/IM", "chrome.exe"],
                        capture_output=True, timeout=10)
        return True
    except Exception:
        return False


def save_profile_to_config(user_data_path, profile_folder):
    """Save profile path ke youtube.json."""
    from shared.paths import YOUTUBE_CONFIG
    from shared.config import load_json, save_json

    config = load_json(YOUTUBE_CONFIG, {})
    config["chrome_user_data_path"] = str(user_data_path)
    config["chrome_profile_folder"] = profile_folder
    return save_json(YOUTUBE_CONFIG, config)


def get_saved_profile():
    from shared.paths import YOUTUBE_CONFIG
    from shared.config import load_json
    c = load_json(YOUTUBE_CONFIG, {})
    return {
        "user_data_path": c.get("chrome_user_data_path", ""),
        "profile_folder": c.get("chrome_profile_folder", "Default"),
    }

def validate_profile():
    """Cek profile yang disave masih valid."""
    info = get_saved_profile()
    if not info["user_data_path"]:
        return False, "Profile belum di-setup"

    path = Path(info["user_data_path"])
    if not path.exists():
        return False, f"Path tidak ada: {info['user_data_path']}"

    profile_path = path / info["profile_folder"]
    if not profile_path.exists():
        return False, f"Profile '{info['profile_folder']}' tidak ada"

    has_cookies = (
        (profile_path / "Cookies").exists() or
        (profile_path / "Network" / "Cookies").exists()
    )
    if not has_cookies:
        return False, "Cookies tidak ditemukan di profile"

    return True, f"OK — {info['profile_folder']}"

def check_profile_exists():
    """Wrapper untuk backward compat."""
    ok, _ = validate_profile()
    return ok

def prepare_automation_profile(source_user_data, source_profile_folder):
    """
    Copy Chrome profile ke folder automation (non-standard).
    Chrome 136+ butuh folder non-standard untuk remote debugging.
    
    Returns:
        (success, automation_path or error_msg)
    """
    from pathlib import Path
    import shutil
    
    # Folder automation (non-standard)
    automation_root = Path.home() / "ChromeAutomationProfile"
    
    # Bersihkan folder lama
    if automation_root.exists():
        try:
            shutil.rmtree(automation_root, ignore_errors=True)
        except Exception:
            pass
    
    automation_root.mkdir(parents=True, exist_ok=True)
    
    src_user_data = Path(source_user_data)
    src_profile = src_user_data / source_profile_folder
    
    if not src_profile.exists():
        return False, f"Profile '{source_profile_folder}' tidak ada"
    
    # Copy ke automation_profile/Default (selalu rename jadi Default)
    dst_profile = automation_root / "Default"
    dst_profile.mkdir(parents=True, exist_ok=True)
    
    # Copy essential files
    files_to_copy = [
        "Cookies", "Cookies-journal",
        "Login Data", "Login Data-journal",
        "Preferences", "Secure Preferences",
        "Web Data", "Web Data-journal",
        "History", "History-journal",
    ]
    
    for fname in files_to_copy:
        src_file = src_profile / fname
        if src_file.exists():
            try:
                shutil.copy2(src_file, dst_profile / fname)
            except Exception:
                pass
    
    # Copy Network folder (Chrome 96+ simpan Cookies di sini)
    network_src = src_profile / "Network"
    if network_src.exists():
        try:
            shutil.copytree(network_src, dst_profile / "Network")
        except Exception:
            pass
    
    # Copy Local State (encryption key)
    local_state = src_user_data / "Local State"
    if local_state.exists():
        try:
            shutil.copy2(local_state, automation_root / "Local State")
        except Exception:
            pass
    
    # Verifikasi
    cookies_check = (dst_profile / "Cookies").exists() or \
                    (dst_profile / "Network" / "Cookies").exists()
    
    if not cookies_check:
        return False, "Cookies tidak ter-copy"
    
    return True, str(automation_root)