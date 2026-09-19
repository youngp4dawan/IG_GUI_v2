"""Instagram config."""
from shared.config import BaseConfig
from shared.paths import INSTAGRAM_CONFIG


class InstagramConfig(BaseConfig):
    def __init__(self, filepath=INSTAGRAM_CONFIG):
        super().__init__(filepath, defaults={
            "username": "", "sessionid": "",
            "csrftoken": "", "ds_user_id": "",
        })

    @property
    def username(self): return self.get("username")

    @property
    def sessionid(self): return self.get("sessionid")

    @property
    def csrf_token(self): return self.get("csrftoken")

    @property
    def ds_user_id(self): return self.get("ds_user_id")

    def is_valid(self):
        return bool(self.sessionid)

    def get_cookies_list(self):
        c = [{"name": "sessionid", "value": self.sessionid, "domain": ".instagram.com"}]
        if self.csrf_token:
            c.append({"name": "csrftoken", "value": self.csrf_token, "domain": ".instagram.com"})
        if self.ds_user_id:
            c.append({"name": "ds_user_id", "value": self.ds_user_id, "domain": ".instagram.com"})
        return c

    def apply_to_instaloader(self, loader):
        from shared.utils import USER_AGENT
        for dom in [".instagram.com", "instagram.com"]:
            loader.context._session.cookies.set("sessionid", self.sessionid, domain=dom)
            if self.csrf_token:
                loader.context._session.cookies.set("csrftoken", self.csrf_token, domain=dom)
            if self.ds_user_id:
                loader.context._session.cookies.set("ds_user_id", self.ds_user_id, domain=dom)
        h = {"User-Agent": USER_AGENT, "Accept-Language": "en-US,en;q=0.9"}
        if self.csrf_token:
            h["X-CSRFToken"] = self.csrf_token
        loader.context._session.headers.update(h)
