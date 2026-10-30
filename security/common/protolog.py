"""Timestamped log to console and to a file: this is the lab's work protocol."""

import datetime
import os


class ProtocolLog:
    def __init__(self, path=None, tag=""):
        self.path = path
        self.tag = tag
        if path:
            os.makedirs(os.path.dirname(path), exist_ok=True)

    def __call__(self, event, message=""):
        stamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        prefix = f"[{self.tag}] " if self.tag else ""
        line = f"{stamp} {prefix}{event:<18} {message}".rstrip()
        print(line, flush=True)
        if self.path:
            with open(self.path, "a", encoding="utf-8") as fh:
                fh.write(line + "\n")

    def banner(self, text):
        self("", "")
        self("=" * 12, text)
