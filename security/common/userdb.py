"""Server-side registration database (lab 6): identifier, salt, password hash image."""

import datetime
import json
import os


class UserDB:
    def __init__(self, path):
        self.path = path
        self.users = {}
        self.load()

    def load(self):
        if os.path.isfile(self.path):
            with open(self.path, "r", encoding="utf-8") as fh:
                self.users = json.load(fh).get("users", {})
        else:
            self.users = {}

    def save(self):
        os.makedirs(os.path.dirname(os.path.abspath(self.path)), exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as fh:
            json.dump({"users": self.users}, fh, ensure_ascii=False, indent=2)

    def add(self, user_id, salt_hex, hash_hex):
        self.users[user_id] = {
            "salt": salt_hex,
            "pwd_hash": hash_hex,
            "enrolled_at": datetime.datetime.now().isoformat(timespec="seconds"),
        }
        self.save()

    def get(self, user_id):
        return self.users.get(user_id)

    def ids(self):
        return sorted(self.users)
