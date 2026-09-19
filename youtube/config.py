"""YouTube upload config."""
from shared.config import BaseConfig
from shared.paths import YOUTUBE_CONFIG


class YouTubeConfig(BaseConfig):
    def __init__(self, filepath=YOUTUBE_CONFIG):
        super().__init__(filepath, defaults={
            "channel_name": "",
            "privacy": "unlisted",
            "category": "22",
            "title_template": "{filename}",
            "description_template": "Source: @{username} ({source})",
            "tags": "shorts, viral, video",
            "made_for_kids": False,
            "default_language": "id",
            # Chrome profile setup
            "chrome_user_data_path": "",   # path ke Chrome "User Data"
            "chrome_profile_folder": "Default",  # folder name
        })

    @property
    def privacy(self): return self.get("privacy") or "unlisted"

    @property
    def category(self): return self.get("category") or "22"

    @property
    def title_template(self): return self.get("title_template") or "{filename}"

    @property
    def description_template(self):
        return self.get("description_template") or ""

    @property
    def tags(self): return self.get("tags") or ""

    @property
    def made_for_kids(self):
        return str(self.get("made_for_kids")).lower() in ("true", "1", "yes")

    @property
    def chrome_user_data_path(self):
        return self.get("chrome_user_data_path")

    @property
    def chrome_profile_folder(self):
        return self.get("chrome_profile_folder") or "Default"

    def is_profile_configured(self):
        import os
        p = self.chrome_user_data_path
        return bool(p) and os.path.exists(p)