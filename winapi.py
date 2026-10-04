"""Small Win32 helpers via ctypes: global hotkey, focus switching, DPAPI, single instance, autostart."""
from __future__ import annotations

import ctypes
import sys
import threading
import winreg
from ctypes import wintypes

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)

MOD_ALT, MOD_CONTROL, MOD_SHIFT, MOD_WIN, MOD_NOREPEAT = 0x1, 0x2, 0x4, 0x8, 0x4000
WM_HOTKEY, WM_QUIT = 0x0312, 0x0012
SW_RESTORE = 9

user32.GetForegroundWindow.restype = wintypes.HWND
user32.SetForegroundWindow.argtypes = [wintypes.HWND]
user32.IsWindow.argtypes = [wintypes.HWND]
user32.IsIconic.argtypes = [wintypes.HWND]
user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
user32.BringWindowToTop.argtypes = [wintypes.HWND]
user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
user32.GetWindowThreadProcessId.restype = wintypes.DWORD
user32.AttachThreadInput.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.BOOL]
user32.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT]
user32.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
user32.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT]
user32.PostThreadMessageW.argtypes = [wintypes.DWORD, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
user32.MonitorFromWindow.restype = wintypes.HANDLE
kernel32.GetCurrentThreadId.restype = wintypes.DWORD
kernel32.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
kernel32.CreateMutexW.restype = wintypes.HANDLE
kernel32.CreateEventW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.BOOL, wintypes.LPCWSTR]
kernel32.CreateEventW.restype = wintypes.HANDLE
kernel32.SetEvent.argtypes = [wintypes.HANDLE]
kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
kernel32.LocalFree.argtypes = [wintypes.HLOCAL]


def set_dpi_aware() -> None:
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except (AttributeError, OSError):
        pass


# ---------------------------------------------------------------- hotkey

KEY_NAMES = {"SPACE": 0x20, "TAB": 0x09, "ENTER": 0x0D, "`": 0xC0, "INSERT": 0x2D, "HOME": 0x24, "END": 0x23,
             "PAGEUP": 0x21, "PAGEDOWN": 0x22, **{f"F{i}": 0x6F + i for i in range(1, 13)}}
MOD_NAMES = {"CTRL": MOD_CONTROL, "CONTROL": MOD_CONTROL, "ALT": MOD_ALT, "SHIFT": MOD_SHIFT, "WIN": MOD_WIN}


def parse_hotkey(text: str) -> tuple[int, int]:
    """'Ctrl+Alt+Q' -> (modifiers, virtual key). Raises ValueError with a Chinese message."""
    parts = [p.strip().upper() for p in text.replace("＋", "+").split("+") if p.strip()]
    if not parts:
        raise ValueError("请填写快捷键，例如 Ctrl+Alt+Q")
    mods, key = 0, parts[-1]
    for part in parts[:-1]:
        if part not in MOD_NAMES:
            raise ValueError(f"不认识的组合键：{part}（可用 Ctrl / Alt / Shift / Win）")
        mods |= MOD_NAMES[part]
    if len(key) == 1 and ("A" <= key <= "Z" or "0" <= key <= "9"):
        vk = ord(key)
    elif key in KEY_NAMES:
        vk = KEY_NAMES[key]
    else:
        raise ValueError(f"不支持的按键：{key}（可用字母、数字、F1–F12、Space 等）")
    if not mods and not key.startswith("F"):
        raise ValueError("单个字母或数字会影响正常打字，请加上 Ctrl 或 Alt")
    return mods, vk


class HotkeyThread(threading.Thread):
    """Owns one RegisterHotKey registration and its message loop.

    RegisterHotKey is delivered by the system even when an elevated game window
    is in the foreground, unlike low-level keyboard hooks.
    """

    HOTKEY_ID = 1

    def __init__(self, text: str, on_press) -> None:
        super().__init__(daemon=True, name="hotkey")
        self.mods, self.vk = parse_hotkey(text)
        self.on_press = on_press
        self.ready = threading.Event()
        self.error: str | None = None
        self._thread_id = 0

    def run(self) -> None:
        self._thread_id = kernel32.GetCurrentThreadId()
        if not user32.RegisterHotKey(None, self.HOTKEY_ID, self.mods | MOD_NOREPEAT, self.vk):
            self.error = "快捷键已被其他程序占用，请在设置里换一个"
            self.ready.set()
            return
        self.ready.set()
        msg = wintypes.MSG()
        try:
            while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                if msg.message == WM_HOTKEY and msg.wParam == self.HOTKEY_ID:
                    self.on_press(user32.GetForegroundWindow())
        finally:
            user32.UnregisterHotKey(None, self.HOTKEY_ID)

    def stop(self) -> None:
        if self._thread_id:
            user32.PostThreadMessageW(self._thread_id, WM_QUIT, 0, 0)


def start_hotkey(text: str, on_press) -> HotkeyThread:
    thread = HotkeyThread(text, on_press)
    thread.start()
    thread.ready.wait(2)
    return thread


# ---------------------------------------------------------------- windows & focus

def foreground_window() -> int:
    return user32.GetForegroundWindow() or 0


def activate(hwnd: int) -> bool:
    """Bring a window to the front. Allowed right after our own hotkey or while we are foreground."""
    if not hwnd or not user32.IsWindow(hwnd):
        return False
    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, SW_RESTORE)
    if user32.SetForegroundWindow(hwnd):
        return True
    # Fallback: share input state with the current foreground thread for this call.
    current = user32.GetWindowThreadProcessId(user32.GetForegroundWindow(), None)
    ours = kernel32.GetCurrentThreadId()
    attached = current and current != ours and user32.AttachThreadInput(ours, current, True)
    try:
        user32.BringWindowToTop(hwnd)
        return bool(user32.SetForegroundWindow(hwnd))
    finally:
        if attached:
            user32.AttachThreadInput(ours, current, False)


class MONITORINFO(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT),
                ("rcWork", wintypes.RECT), ("dwFlags", wintypes.DWORD)]


def monitor_work_area(hwnd: int) -> tuple[int, int, int, int] | None:
    """(left, top, right, bottom) of the monitor showing hwnd, in physical pixels."""
    monitor = user32.MonitorFromWindow(hwnd or None, 2)  # MONITOR_DEFAULTTONEAREST
    info = MONITORINFO()
    info.cbSize = ctypes.sizeof(MONITORINFO)
    if not monitor or not user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
        return None
    r = info.rcMonitor
    return r.left, r.top, r.right, r.bottom


# ---------------------------------------------------------------- clipboard

CF_UNICODETEXT, GMEM_MOVEABLE = 13, 0x0002
user32.OpenClipboard.argtypes = [wintypes.HWND]
user32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
user32.SetClipboardData.restype = wintypes.HANDLE
kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
kernel32.GlobalAlloc.restype = wintypes.HGLOBAL
kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
kernel32.GlobalLock.restype = wintypes.LPVOID
kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
kernel32.GlobalFree.argtypes = [wintypes.HGLOBAL]


def set_clipboard(text: str) -> bool:
    """Put text on the system clipboard immediately (not Tk's delayed rendering)."""
    data = text.encode("utf-16-le") + b"\x00\x00"
    for _ in range(10):  # another program may briefly hold the clipboard
        if user32.OpenClipboard(None):
            break
        kernel32.Sleep(20)
    else:
        return False
    try:
        user32.EmptyClipboard()
        handle = kernel32.GlobalAlloc(GMEM_MOVEABLE, len(data))
        if not handle:
            return False
        pointer = kernel32.GlobalLock(handle)
        ctypes.memmove(pointer, data, len(data))
        kernel32.GlobalUnlock(handle)
        if not user32.SetClipboardData(CF_UNICODETEXT, handle):
            kernel32.GlobalFree(handle)
            return False
        return True
    finally:
        user32.CloseClipboard()


# ---------------------------------------------------------------- DPAPI (per-user encryption)

class DATA_BLOB(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]


def _blob(data: bytes) -> DATA_BLOB:
    buffer = ctypes.create_string_buffer(data, len(data))
    blob = DATA_BLOB(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_char)))
    blob._buffer = buffer  # keep alive
    return blob


def _crypt(func, data: bytes) -> bytes:
    source, result = _blob(data), DATA_BLOB()
    if not func(ctypes.byref(source), None, None, None, None, 0x1, ctypes.byref(result)):  # UI_FORBIDDEN
        raise OSError(ctypes.get_last_error(), "DPAPI failed")
    try:
        return ctypes.string_at(result.pbData, result.cbData)
    finally:
        kernel32.LocalFree(result.pbData)


def protect(data: bytes) -> bytes:
    return _crypt(crypt32.CryptProtectData, data)


def unprotect(data: bytes) -> bytes:
    return _crypt(crypt32.CryptUnprotectData, data)


# ---------------------------------------------------------------- single instance

MUTEX_NAME = "Local\\CWTranslator.SingleInstance"
SHOW_EVENT_NAME = "Local\\CWTranslator.Show"
ERROR_ALREADY_EXISTS = 183


def claim_single_instance() -> bool:
    """True for the first instance. A later instance asks the first to show itself."""
    kernel32.CreateMutexW(None, False, MUTEX_NAME)
    if ctypes.get_last_error() != ERROR_ALREADY_EXISTS:
        return True
    event = kernel32.CreateEventW(None, False, False, SHOW_EVENT_NAME)
    if event:
        kernel32.SetEvent(event)
    return False


def watch_show_requests(on_request) -> None:
    event = kernel32.CreateEventW(None, False, False, SHOW_EVENT_NAME)

    def loop() -> None:
        while kernel32.WaitForSingleObject(event, 0xFFFFFFFF) == 0:
            on_request()

    threading.Thread(target=loop, daemon=True, name="show-requests").start()


# ---------------------------------------------------------------- autostart

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_VALUE = "CWTranslator"


def autostart_command() -> str:
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}" --background'
    from pathlib import Path
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    return f'"{pythonw}" "{Path(__file__).with_name("app.py")}" --background'


def set_autostart(enabled: bool) -> None:
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
        if enabled:
            winreg.SetValueEx(key, RUN_VALUE, 0, winreg.REG_SZ, autostart_command())
        else:
            try:
                winreg.DeleteValue(key, RUN_VALUE)
            except FileNotFoundError:
                pass
