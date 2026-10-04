"""Per-user settings in %APPDATA%/CWTranslator. The API key is DPAPI-encrypted, never stored in plain text."""
from __future__ import annotations

import base64
import json
import os
import re
from pathlib import Path

import winapi

USER_DIR = Path(os.environ.get("APPDATA") or Path.home()) / "CWTranslator"
SETTINGS_FILE = USER_DIR / "settings.json"

DEFAULTS = {
    "hotkey": "Ctrl+Alt+Q",
    "model": "deepseek-flash",
    "api_key_protected": "",
    "use_environment_key": True,
    "auto_return": True,       # hide and switch back to the game after a translation
    "return_delay_ms": 900,    # time to glance at the result first
    "autostart": False,
    "show_timing": False,
    "chat_limit": 70,          # warn above this many characters
    "timeout_s": 12,
    "setup_done": False,
}


# Earlier default values that were written to disk as if chosen by the user.
# Ctrl+Alt+T clashed with QQ's file transfer shortcut.
LEGACY_DEFAULTS = {"hotkey": "Ctrl+Alt+T"}


def validate_api_key(key: str) -> str:
    """Reject whitespace/control characters before constructing an HTTP header."""
    key = key.strip()
    if not re.fullmatch(r"[A-Za-z0-9_-]{16,512}", key):
        raise ValueError("Key 格式不正确，请重新复制完整 Key（不要带空格或换行）")
    return key


class Settings:
    def __init__(self) -> None:
        self.data = dict(DEFAULTS)
        try:
            stored = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
            if isinstance(stored, dict):
                self.data.update({k: v for k, v in stored.items()
                                  if k in DEFAULTS and type(v) is type(DEFAULTS[k])
                                  and LEGACY_DEFAULTS.get(k) != v})
            for name, low, high in (("timeout_s", 1, 60), ("return_delay_ms", 0, 10000),
                                   ("chat_limit", 1, 1000)):
                if not low <= self.data[name] <= high:
                    self.data[name] = DEFAULTS[name]
            if not re.fullmatch(r"[A-Za-z0-9._:/-]{1,128}", self.data["model"]):
                self.data["model"] = DEFAULTS["model"]
            try:
                winapi.parse_hotkey(self.data["hotkey"])
            except ValueError:
                self.data["hotkey"] = DEFAULTS["hotkey"]
        except (OSError, ValueError, AttributeError):
            pass

    def __getitem__(self, name: str):
        return self.data[name]

    def __setitem__(self, name: str, value) -> None:
        self.data[name] = value

    def save(self) -> None:
        USER_DIR.mkdir(parents=True, exist_ok=True)
        tmp = SETTINGS_FILE.with_suffix(".tmp")
        # Only what differs from the defaults, so later default changes still apply.
        changed = {k: v for k, v in self.data.items() if DEFAULTS[k] != v}
        tmp.write_text(json.dumps(changed, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(SETTINGS_FILE)

    # The saved key wins; environment fallback can be disabled by the user.
    @property
    def api_key(self) -> str:
        if self.data["api_key_protected"]:
            try:
                protected = base64.b64decode(self.data["api_key_protected"], validate=True)
                return validate_api_key(winapi.unprotect(protected).decode("utf-8"))
            except (OSError, ValueError):
                return ""
        if self.data["use_environment_key"] and os.environ.get("DEEPSEEK_API_KEY"):
            try:
                return validate_api_key(os.environ["DEEPSEEK_API_KEY"])
            except ValueError:
                pass
        return ""

    @property
    def key_source(self) -> str:
        if self.data["api_key_protected"]:
            return "saved" if self.api_key else "saved_unavailable"
        if self.data["use_environment_key"] and os.environ.get("DEEPSEEK_API_KEY"):
            return "environment" if self.api_key else "environment_invalid"
        return "none"

    def set_api_key(self, key: str) -> None:
        key = key.strip()
        if key:
            key = validate_api_key(key)
        self.data["api_key_protected"] = (
            base64.b64encode(winapi.protect(key.encode("utf-8"))).decode("ascii") if key else "")
        if not key:
            # Clearing must stop using credentials, not silently resume another key.
            self.data["use_environment_key"] = False
