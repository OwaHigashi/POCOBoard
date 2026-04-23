"""Simple INI loader — compatible with M5Tab-Poco's config.ini style.

Supports `key = value` lines with `#` or `;` comments, inline comments after
`;`, booleans (true/false/yes/no/on/off/1/0), ints, and strings. Unknown keys
are kept as raw strings.
"""
from __future__ import annotations
import os


class Config:
    _TRUE = {"true", "yes", "on", "1"}
    _FALSE = {"false", "no", "off", "0"}

    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.error: str = ""
        self.path: str = ""

    def load(self, path: str) -> bool:
        self.path = path
        self.values.clear()
        self.error = ""
        if not os.path.isfile(path):
            self.error = f"not found: {path}"
            return False
        try:
            with open(path, "r", encoding="utf-8") as f:
                for raw in f:
                    line = raw.strip()
                    if not line or line.startswith("#") or line.startswith(";"):
                        continue
                    if "=" not in line:
                        continue
                    k, v = line.split("=", 1)
                    k = k.strip()
                    v = v.split(";", 1)[0].strip()
                    # also strip trailing "# comment" if any
                    v = v.split("#", 1)[0].strip()
                    if (v.startswith('"') and v.endswith('"')) or (
                        v.startswith("'") and v.endswith("'")
                    ):
                        v = v[1:-1]
                    self.values[k] = v
        except OSError as exc:
            self.error = str(exc)
            return False
        return True

    def get_str(self, key: str, default: str = "") -> str:
        return self.values.get(key, default)

    def get_int(self, key: str, default: int = 0) -> int:
        try:
            return int(self.values.get(key, default))
        except (TypeError, ValueError):
            return default

    def get_bool(self, key: str, default: bool = False) -> bool:
        v = self.values.get(key)
        if v is None:
            return default
        v = v.strip().lower()
        if v in self._TRUE:
            return True
        if v in self._FALSE:
            return False
        return default
