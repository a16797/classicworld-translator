"""End to end with real keystrokes: a stand-in game window, the global hotkey, typing, auto-return, Ctrl+V.

    .venv/Scripts/python tests/e2e_focus.py [path-to-CWTranslator.exe]

Without an exe it runs app.py from source. Uses a throwaway APPDATA.
"""
from __future__ import annotations

import ctypes
import json
import os
import subprocess
import sys
import tempfile
import time
from ctypes import wintypes
from pathlib import Path

HERE = Path(__file__).resolve().parent
user32 = ctypes.WinDLL("user32", use_last_error=True)
user32.GetForegroundWindow.restype = wintypes.HWND
user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]

INPUT_KEYBOARD, KEYUP, UNICODE = 1, 0x2, 0x4
VK = {"ctrl": 0x11, "alt": 0x12, "enter": 0x0D, "f11": 0x7A, "v": 0x56}


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD), ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t)]


class INPUT(ctypes.Structure):
    class _U(ctypes.Union):
        _fields_ = [("ki", KEYBDINPUT), ("pad", ctypes.c_byte * 32)]
    _anonymous_ = ("u",)
    _fields_ = [("type", wintypes.DWORD), ("u", _U)]


def send(*events: tuple[int, int, int]) -> None:
    array = (INPUT * len(events))(*[INPUT(INPUT_KEYBOARD, INPUT._U(ki=KEYBDINPUT(vk, scan, flags, 0, 0)))
                                    for vk, scan, flags in events])
    user32.SendInput(len(events), array, ctypes.sizeof(INPUT))


def chord(*names: str) -> None:
    codes = [VK[n] for n in names]
    send(*[(c, 0, 0) for c in codes], *[(c, 0, KEYUP) for c in reversed(codes)])


def type_text(text: str) -> None:
    for ch in text:
        send((0, ord(ch), UNICODE), (0, ord(ch), UNICODE | KEYUP))
        time.sleep(0.01)


def title() -> str:
    buffer = ctypes.create_unicode_buffer(256)
    user32.GetWindowTextW(user32.GetForegroundWindow(), buffer, 256)
    return buffer.value


def main() -> int:
    appdata = tempfile.mkdtemp(prefix="cwt-e2e-")
    settings = Path(appdata) / "CWTranslator"
    settings.mkdir()
    (settings / "settings.json").write_text(json.dumps({
        "setup_done": True, "hotkey": "Ctrl+Alt+F11", "return_delay_ms": 300}), encoding="utf-8")
    # Like a fresh machine: no key or corpus overrides from this computer's environment.
    env = {k: v for k, v in os.environ.items()
           if k not in ("DEEPSEEK_API_KEY", "OPENROUTER_API_KEY", "JEV_API_KEY", "CW_CORPUS_PATH", "CW_SKILL_DIR")}
    env["APPDATA"] = appdata
    out = Path(appdata) / "game.txt"
    exe = sys.argv[1] if len(sys.argv) > 1 else None
    command = [exe, "--background"] if exe else [sys.executable, str(HERE.parent / "app.py"), "--background"]
    app = subprocess.Popen(command, env=env)
    game = subprocess.Popen([sys.executable, str(HERE / "fake_game.py"), str(out)])
    steps = {}
    try:
        time.sleep(4)
        if app.poll() is not None:
            # Single instance: a copy that is already running made ours exit.
            print(json.dumps({"ok": False, "aborted": "another ClassicWorld 翻译助手 is already running; close it first"},
                             ensure_ascii=False))
            return 2
        # Windows only lets the process with the latest input take the foreground:
        # tap Alt first, then bring the stand-in game forward.
        hwnd = user32.FindWindowW(None, "FAKE GAME")
        for _ in range(5):
            chord("alt")
            user32.SetForegroundWindow(hwnd)
            time.sleep(0.3)
            if title() == "FAKE GAME":
                break
        steps["start_foreground"] = title()
        if steps["start_foreground"] != "FAKE GAME":
            print(json.dumps({"ok": False, "aborted": "could not focus the stand-in game; no keys sent", **steps},
                             ensure_ascii=False))
            return 2
        chord("ctrl", "alt", "f11")
        time.sleep(0.6)
        steps["after_hotkey"] = title()
        type_text("收蓝魔法鞋")
        chord("enter")
        time.sleep(1.5)
        steps["after_translate"] = title()
        if steps["after_translate"] != "FAKE GAME":
            raise RuntimeError("focus did not return to the stand-in game; not pasting")
        chord("ctrl", "v")
        time.sleep(0.8)
        steps["pasted"] = out.read_text(encoding="utf-8") if out.exists() else ""
        # Hotkey again while the app is in front hides it (toggle) and returns.
        chord("ctrl", "alt", "f11"); time.sleep(0.5)
        steps["toggle_show"] = title()
        chord("ctrl", "alt", "f11"); time.sleep(0.5)
        steps["toggle_hide"] = title()
        # A second copy must not start; it shows the running one instead.
        second = subprocess.run(command[:-1], env=env, timeout=20)
        time.sleep(0.8)
        steps["second_instance_exit"] = second.returncode
        steps["second_instance_foreground"] = title()
    except RuntimeError as error:
        steps["aborted"] = str(error)
    finally:
        game.terminate()
        app.terminate()
    ok = "aborted" not in steps and (steps["start_foreground"] == "FAKE GAME" and steps["after_hotkey"] == "ClassicWorld 翻译助手"
          and steps["after_translate"] == "FAKE GAME" and steps["pasted"] == "B> Blue Magicshoes"
          and steps["toggle_show"] == "ClassicWorld 翻译助手" and steps["toggle_hide"] == "FAKE GAME"
          and steps["second_instance_exit"] == 0 and steps["second_instance_foreground"] == "ClassicWorld 翻译助手")
    print(json.dumps({"ok": ok, **steps}, ensure_ascii=False, indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
