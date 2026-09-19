"""Config utilities."""
import json
import os


def load_json(path, default=None):
    try:
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return default if default is not None else {}


def save_json(path, data):
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        return True
    except Exception:
        return False


class BaseConfig:
    def __init__(self, filepath, defaults=None):
        self.filepath = filepath
        self.defaults = defaults or {}
        self.data = load_json(filepath, self.defaults.copy())

    def get(self, key, default=""):
        return str(self.data.get(key, default) or "").strip()

    def set(self, **kwargs):
        self.data.update(kwargs)
        return save_json(self.filepath, self.data)

    def reload(self):
        self.data = load_json(self.filepath, self.defaults.copy())
