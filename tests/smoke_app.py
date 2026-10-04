"""Drive the real window without a person: translate, copy, remember, settings, quit.

Uses a throwaway APPDATA so the real settings are untouched.
    .venv/Scripts/python tests/smoke_app.py [--network]
"""
from __future__ import annotations

import ctypes
import json
import os
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ["APPDATA"] = tempfile.mkdtemp(prefix="cwt-smoke-")
NETWORK = "--network" in sys.argv
if not NETWORK:
    os.environ.pop("DEEPSEEK_API_KEY", None)

settings_dir = Path(os.environ["APPDATA"]) / "CWTranslator"
settings_dir.mkdir(parents=True)
(settings_dir / "settings.json").write_text(json.dumps({"setup_done": True, "hotkey": "Ctrl+Alt+F11",
                                                        "show_timing": True}), encoding="utf-8")

import app  # noqa: E402


def clipboard() -> str:
    user32, kernel32 = ctypes.windll.user32, ctypes.windll.kernel32
    user32.GetClipboardData.restype = ctypes.c_void_p
    kernel32.GlobalLock.restype = ctypes.c_void_p
    kernel32.GlobalLock.argtypes = [ctypes.c_void_p]
    kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]
    for _ in range(10):
        if user32.OpenClipboard(None):
            break
        time.sleep(0.02)
    else:
        raise RuntimeError("Clipboard remained locked during test readback")
    try:
        handle = user32.GetClipboardData(13)
        if not handle:
            return ""
        pointer = kernel32.GlobalLock(handle)
        try:
            return ctypes.wstring_at(pointer) if pointer else ""
        finally:
            kernel32.GlobalUnlock(handle)
    finally:
        user32.CloseClipboard()


cases = [("废弃都市组队任务来法师三缺一", "R> KPQ mage 3/4", "phrasebook"),  # default phrasebook
         ("收蓝魔法鞋", "B> Blue Magicshoes", "direct")]
if NETWORK:
    cases += [("法师求组玩具城组队任务", "J> LPQ mage", "generation"), ("法师求组玩具城组队任务", "J> LPQ mage", "cache")]
else:
    cases += [("这句词库里肯定没有的新话", None, "error")]

window = app.App(background=True)
report, failures = [], []


def wait_result(seq: int, timeout: float = 20) -> None:
    end = time.time() + timeout
    while time.time() < end:
        window.root.update()
        if window.status.cget("text") not in ("翻译中…", "正在加载词库…"):
            return
        time.sleep(0.02)


def run() -> None:
    assert window.hotkey is not None, "hotkey failed to register"
    window.show(0)
    for text, expected, route in cases:
        window.input.delete(0, "end")
        window.input.insert(0, text)
        window.translate()
        wait_result(window.seq)
        status, output = window.status.cget("text"), window.output.get()
        report.append({"input": text, "output": output, "status": status})
        if route == "error":
            ok = "Key" in status
        else:
            ok = output == expected and clipboard() == expected and app.ROUTE_NAMES[route] in status
        if not ok:
            failures.append(report[-1])
        window.cancel_return()
        window.show(0)
    # Copy an edited translation: it is copied, saved for next time, and the window stays open.
    window.input.delete(0, "end"); window.input.insert(0, "来个牧师")
    window.output.delete(0, "end"); window.output.insert(0, "LF cleric pls")
    window.copy_output()
    window.root.update()
    if clipboard() != "LF cleric pls" or window.root.state() != "normal" or "已记住" not in window.status.cget("text"):
        failures.append({"copy_edited": clipboard(), "state": window.root.state(), "status": window.status.cget("text")})
    window.input.delete(0, "end"); window.input.insert(0, "来个牧师！")
    window.translate(); wait_result(window.seq)
    if window.output.get() != "LF cleric pls" or app.ROUTE_NAMES["phrasebook"] not in window.status.cget("text"):
        failures.append({"remember": window.output.get(), "status": window.status.cget("text")})
    # Typing a fragment lists similar ready-made lines; picking one copies it.
    window.input.delete(0, "end"); window.input.insert(0, "招人")
    end = time.time() + 2
    while time.time() < end and not window.suggest_frame.winfo_ismapped():
        window.root.update(); time.sleep(0.02)
    listed = list(window.suggest_box.get(0, "end"))
    lines = [item for item in window.suggest_items if item is not None]
    headers = [row.strip(" ▍") for row, item in zip(listed, window.suggest_items) if item is None]
    if not lines or not all("招人" in item.zh for item in lines[:3]) or "推荐" not in headers:
        failures.append({"suggestions": listed})
    else:
        # ↓ from the input lands on the first real line, skipping the group header.
        window.focus_suggestions()
        first = window.suggest_box.curselection()[0]
        expected = window.suggest_items[first]
        window.pick_suggestion()
        if expected is None or clipboard() != expected.en or window.suggest_frame.winfo_ismapped():
            failures.append({"pick": clipboard(), "expected": expected and expected.en,
                             "output": window.output.get(), "status": window.status.cget("text"),
                             "list_shown": bool(window.suggest_frame.winfo_ismapped())})
        elif window.engine.usage.count(expected.zh, expected.en) != 1:
            failures.append({"usage_not_counted": expected.zh})
    report.append({"suggestions_for_招人": listed[:3]})
    # Player wording sits in 推荐, the first group; name lookups follow.
    window.input.delete(0, "end"); window.input.insert(0, "蜗牛")
    window.update_suggestions()
    titles = [row.strip(" ▍") for row, item in zip(window.suggest_box.get(0, "end"), window.suggest_items) if item is None]
    if titles[:2] != ["推荐", "物品"]:
        failures.append({"group_order": titles})
    # Editing or clearing the input drops the old result and the list.
    window.input.delete(0, "end"); window.input.insert(0, "收蓝魔法鞋")
    window.translate(); wait_result(window.seq)
    window.input.delete(0, "end"); window.input.insert(0, "收蓝魔法鞋再来")
    window.root.update()
    edited_output = window.output.get()
    window.input.delete(0, "end")
    for _ in range(10):
        window.root.update(); time.sleep(0.02)
    if edited_output or window.output.get() or window.suggest_frame.winfo_ismapped() or window.status.cget("text"):
        failures.append({"stale_after_edit": edited_output, "after_clear": window.output.get(),
                         "list_shown": window.suggest_frame.winfo_ismapped()})
    window.open_settings()
    window.root.update()
    window.quit()


def run_safely() -> None:
    try:
        run()
    except Exception as error:
        failures.append({"test_error": type(error).__name__})
        window.quit()


window.root.after(100, run_safely)
window.root.mainloop()
print(json.dumps({"report": report, "failures": failures}, ensure_ascii=False, indent=2))
sys.exit(1 if failures else 0)
