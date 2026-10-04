"""ClassicWorld 翻译助手: hotkey, Chinese input, game-chat English on the clipboard."""
from __future__ import annotations

import os
import queue
import sys
import threading
import tkinter as tk
import webbrowser
from tkinter import ttk

import winapi

winapi.set_dpi_aware()

from engine import DATA_DIR, ROUTE_NAMES, Engine, Phrasebook  # noqa: E402
from settings import USER_DIR, Settings  # noqa: E402

APP_NAME = "ClassicWorld 翻译助手"
APP_VERSION = "1.0.2"  # X.Y.Z: X breaking change, Y new feature, Z fix
DEEPSEEK_KEYS_URL = "https://platform.deepseek.com/api_keys"
FONT = "Microsoft YaHei UI"
# Palette sampled from the game's own UI sprites (UI QuestCategory.img: teal #2288aa, light #bbddee,
# tan #997755 / #bbaa88 / #ddddcc). Colours only; no UI images are used.
COLORS = {
    "bg": "#f6f4ec", "field": "#ffffff", "wood": "#bbaa88", "wood_dark": "#997755", "text": "#2b3a42",
    "accent": "#2288aa", "accent_hover": "#3399bb", "accent_press": "#1a6e8a", "select": "#bbddee",
    "muted": "#7a776c", "ok": "#2e7d32", "error": "#c0392b",
}

FIELD_STYLE = {"relief": "flat", "bd": 0, "bg": COLORS["field"], "fg": COLORS["text"], "highlightthickness": 2,
               "highlightbackground": COLORS["wood"], "highlightcolor": COLORS["accent"],
               "insertbackground": COLORS["text"]}


def rounded_rect(canvas: tk.Canvas, x0, y0, x1, y1, r, **kw) -> int:
    """A smooth rounded rectangle as one canvas polygon."""
    points = [x0 + r, y0, x1 - r, y0, x1, y0, x1, y0 + r, x1, y1 - r, x1, y1,
              x1 - r, y1, x0 + r, y1, x0, y1, x0, y1 - r, x0, y0 + r, x0, y0]
    return canvas.create_polygon(points, smooth=True, **kw)


class RoundField(tk.Canvas):
    """A flat Entry inside a rounded wooden border that turns maple orange while focused."""

    def __init__(self, parent, scale: float, font, **entry_options) -> None:
        super().__init__(parent, bg=COLORS["bg"], highlightthickness=0, bd=0)
        self.ui = scale
        self.entry = tk.Entry(self, font=font, relief="flat", bd=0, bg=COLORS["field"], fg=COLORS["text"],
                              insertbackground=COLORS["text"], highlightthickness=0, **entry_options)
        self.pad = int(10 * scale)
        self.item = self.create_window(self.pad, 0, window=self.entry, anchor="w")
        self.color = COLORS["wood"]
        # Canvas defaults to ~10cm wide; size to the entry instead so the window stays compact.
        self.configure(height=self.entry.winfo_reqheight() + int(18 * scale),
                       width=self.entry.winfo_reqwidth() + 2 * self.pad)
        self.bind("<Configure>", lambda e: self.redraw())
        self.entry.bind("<FocusIn>", lambda e: self.set_color(COLORS["accent"]), add="+")
        self.entry.bind("<FocusOut>", lambda e: self.set_color(COLORS["wood"]), add="+")
        self.bind("<Button-1>", lambda e: self.entry.focus_set())

    def set_color(self, color: str) -> None:
        self.color = color
        self.redraw()

    def redraw(self) -> None:
        self.delete("border")
        w, h, s = self.winfo_width(), self.winfo_height(), self.ui
        line = max(2, int(2 * s))
        rounded_rect(self, line, line, w - line, h - line, int(10 * s), fill=COLORS["field"],
                     outline=self.color, width=line, tags="border")
        self.tag_lower("border")
        self.coords(self.item, self.pad, h / 2)
        self.itemconfigure(self.item, width=max(10, w - 2 * self.pad))


class RoundButton(tk.Canvas):
    """Rounded button drawn on a canvas: solid maple orange, or a wooden outline for secondary actions."""

    def __init__(self, parent, text: str, command, scale: float, solid: bool = True) -> None:
        super().__init__(parent, bg=COLORS["bg"], highlightthickness=0, bd=0, height=int(34 * scale), width=int(60 * scale),
                         cursor="hand2")
        self.text, self.command, self.ui, self.solid = text, command, scale, solid
        self.mode = "normal"
        self.bind("<Configure>", lambda e: self.redraw())
        self.bind("<Enter>", lambda e: self.set_mode("hover"))
        self.bind("<Leave>", lambda e: self.set_mode("normal"))
        self.bind("<ButtonPress-1>", lambda e: self.set_mode("pressed"))
        self.bind("<ButtonRelease-1>", self.release)

    def set_mode(self, state: str) -> None:
        self.mode = state
        self.redraw()

    def release(self, event) -> None:
        inside = 0 <= event.x <= self.winfo_width() and 0 <= event.y <= self.winfo_height()
        self.set_mode("hover" if inside else "normal")
        if inside:
            self.command()

    def redraw(self) -> None:
        self.delete("all")
        w, h, s = self.winfo_width(), self.winfo_height(), self.ui
        fill = {"normal": COLORS["accent"], "hover": COLORS["accent_hover"], "pressed": COLORS["accent_press"]}[self.mode]
        line = max(2, int(2 * s))
        if self.solid:
            rounded_rect(self, line, line, w - line, h - line, int(12 * s), fill=fill, outline=COLORS["accent_press"],
                         width=line)
            color = "#ffffff"
        else:
            back = COLORS["select"] if self.mode != "normal" else COLORS["field"]
            rounded_rect(self, line, line, w - line, h - line, int(12 * s), fill=back, outline=COLORS["wood"],
                         width=line)
            color = COLORS["wood_dark"]
        self.create_text(w / 2, h / 2 + (1 if self.mode == "pressed" else 0), text=self.text,
                         font=(FONT, 10, "bold"), fill=color)


class Placeholder:
    """Gray hint text over an empty Entry, shown even while it has focus (works for password fields too)."""

    def __init__(self, entry: tk.Entry, text: str, variable: tk.StringVar | None = None) -> None:
        self.entry = entry
        if variable is None:
            variable = tk.StringVar(master=entry)
            entry.configure(textvariable=variable)
        self.variable = variable
        self.label = tk.Label(entry, text=text, fg="#a39d91", bg=entry.cget("bg"), font=(FONT, 10), cursor="xterm")
        self.label.bind("<Button-1>", lambda e: entry.focus_set())
        variable.trace_add("write", lambda *_: self.update())
        self.update()

    def update(self) -> None:
        if self.variable.get():
            self.label.place_forget()
        else:
            self.label.place(x=6, rely=0.5, anchor="w")


class HotkeyField:
    """Click the field, then press the key combination to use; no typing of key names."""

    MODIFIER_KEYS = {"Control_L", "Control_R", "Alt_L", "Alt_R", "Shift_L", "Shift_R", "Win_L", "Win_R"}
    SPECIAL = {"space": "Space", "Tab": "Tab", "Insert": "Insert", "Home": "Home", "End": "End",
               "Prior": "PageUp", "Next": "PageDown", "grave": "`"}

    def __init__(self, parent, value: str, on_focus, on_blur) -> None:
        self.value = value
        self.variable = tk.StringVar(value=value)
        self.entry = tk.Entry(parent, textvariable=self.variable, font=(FONT, 10), width=18, **FIELD_STYLE,
                              cursor="hand2", insertontime=0)
        self.error = ""
        self.entry.bind("<FocusIn>", lambda e: (on_focus(), self.variable.set("请按下组合键…")))
        self.entry.bind("<FocusOut>", lambda e: (self.variable.set(self.value), on_blur()))
        self.entry.bind("<KeyPress>", self.on_key)

    def on_key(self, event):
        if event.keysym in ("Tab", "Escape") and not event.state & 0x20005:
            return None  # let focus move / dialog handle it
        mods = [name for bit, name in ((0x4, "Ctrl"), (0x20000, "Alt"), (0x1, "Shift")) if event.state & bit]
        if event.keysym in self.MODIFIER_KEYS:
            self.variable.set("+".join(mods + ["…"]))
            return "break"
        key = event.keysym
        if len(key) == 1 and key.isalnum():
            key = key.upper()
        elif key.startswith("F") and key[1:].isdigit():
            pass
        else:
            key = self.SPECIAL.get(key, key)
        text = "+".join(mods + [key])
        try:
            winapi.parse_hotkey(text)
        except ValueError as problem:
            self.error = str(problem)
            self.variable.set(f"{text}（不可用）")
            return "break"
        self.error, self.value = "", text
        self.variable.set(text)
        self.entry.master.focus_set()  # done recording
        return "break"


class App:
    def __init__(self, background: bool) -> None:
        self.settings = Settings()
        self.engine = Engine(self.settings)
        self.events: queue.Queue = queue.Queue()
        self.prev_hwnd = 0
        self.return_job: str | None = None
        self.seq = 0
        self.placed = False
        self.hotkey: winapi.HotkeyThread | None = None
        self.tray = None

        self.root = tk.Tk()
        self.root.withdraw()
        self.root.title(APP_NAME)
        self.root.configure(bg=COLORS["bg"])
        self.root.resizable(False, False)
        self.root.attributes("-topmost", True, "-toolwindow", True)
        self.root.protocol("WM_DELETE_WINDOW", self.hide)
        self.scale = self.root.winfo_fpixels("1i") / 96  # pixel sizes follow the Windows display scale
        self.icon_image = None
        try:
            from PIL import ImageTk
            from icon import make_icon
            self.icon_image = ImageTk.PhotoImage(make_icon(64), master=self.root)
            self.root.iconphoto(True, self.icon_image)
        except Exception:  # a missing logo file must never stop the app
            pass
        self.build()

        threading.Thread(target=self.engine.preload, daemon=True, name="preload").start()
        self.start_tray()
        hotkey_ok = self.start_hotkey()
        winapi.watch_show_requests(lambda: self.events.put(("show", 0)))
        self.root.after(30, self.poll)
        if not self.settings["setup_done"]:
            self.root.after(150, self.open_wizard)
        elif not background or not hotkey_ok:
            # Opened by hand (or the hotkey is unusable): show the window right away.
            self.root.after(150, lambda: self.show(winapi.foreground_window()))
        if not background and hotkey_ok and self.settings["setup_done"]:
            self.root.after(400, lambda: self.set_status(
                f"已启动 · 游戏里按 {self.settings['hotkey']} 唤出"))

    # ------------------------------------------------------------ layout

    def style(self) -> None:
        """ttk theme for all windows: cream panels, wooden borders, maple-orange buttons."""
        style = ttk.Style(self.root)
        style.theme_use("clam")
        bg, text = COLORS["bg"], COLORS["text"]
        style.configure(".", background=bg, foreground=text, font=(FONT, 9))
        style.configure("TFrame", background=bg)
        style.configure("TLabel", background=bg, foreground=text, font=(FONT, 9))
        style.configure("Caption.TLabel", font=(FONT, 9, "bold"), foreground=COLORS["accent_press"])
        style.configure("TButton", font=(FONT, 9, "bold"), background=COLORS["accent"], foreground="#ffffff",
                        bordercolor=COLORS["accent_press"], lightcolor=COLORS["accent_hover"],
                        darkcolor=COLORS["accent_press"], focuscolor=COLORS["accent"], padding=(10, 4))
        style.map("TButton", background=[("pressed", COLORS["accent_press"]), ("active", COLORS["accent_hover"])])
        style.configure("Secondary.TButton", background=COLORS["field"], foreground=COLORS["wood_dark"],
                        bordercolor=COLORS["wood"], lightcolor=COLORS["field"], darkcolor=COLORS["field"])
        style.map("Secondary.TButton", background=[("pressed", COLORS["select"]), ("active", COLORS["select"])])
        style.configure("TCheckbutton", background=bg, foreground=text, font=(FONT, 9),
                        indicatorbackground=COLORS["field"], indicatorforeground=COLORS["accent_press"])
        style.map("TCheckbutton", background=[("active", bg)])
        style.configure("Vertical.TScrollbar", background=COLORS["wood"], troughcolor=COLORS["bg"],
                        bordercolor=COLORS["wood"], arrowcolor="#ffffff", lightcolor=COLORS["wood"],
                        darkcolor=COLORS["wood"])

    def build(self) -> None:
        self.style()
        s = self.scale

        frame = ttk.Frame(self.root, padding=(16, 12, 16, 10))
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="① 中文 · 回车翻译", style="Caption.TLabel").pack(anchor="w")
        field = RoundField(frame, s, (FONT, 13), width=38)
        field.pack(fill="x", pady=(3, 0))
        self.input = field.entry
        self.input.bind("<Return>", lambda e: self.translate())
        self.input.bind("<Down>", lambda e: self.focus_suggestions())
        self.input_hint = Placeholder(self.input, "如：废弃来法师三缺一 / 招人 / 柠檬")
        self.input_hint.variable.trace_add("write", lambda *_: self.schedule_suggest())

        # Fuzzy matches from the phrasebooks and dictionary, shown while typing.
        self.suggest_frame = ttk.Frame(frame)
        self.suggest_box = tk.Listbox(self.suggest_frame, font=(FONT, 10), height=8, width=1, activestyle="none",
                                      exportselection=False,
                                      relief="flat", bd=0, bg=COLORS["field"], fg=COLORS["text"],
                                      selectbackground=COLORS["select"], selectforeground=COLORS["text"],
                                      highlightthickness=max(1, int(s)), highlightbackground=COLORS["wood"],
                                      highlightcolor=COLORS["wood"])
        scrollbar = ttk.Scrollbar(self.suggest_frame, orient="vertical", command=self.suggest_box.yview)
        self.suggest_box.configure(yscrollcommand=scrollbar.set)
        self.suggest_box.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        self.suggest_box.bind("<ButtonRelease-1>", lambda e: self.pick_suggestion())
        self.suggest_box.bind("<Return>", lambda e: self.pick_suggestion())
        self.suggest_box.bind("<Up>", lambda e: self.move_suggestion(-1))
        self.suggest_box.bind("<Down>", lambda e: self.move_suggestion(1))
        self.suggest_items: list = []
        self.suggest_job: str | None = None
        self.suppress_suggest = False

        self.output_caption = ttk.Label(frame, text="② 英文黑话 · 已自动复制", style="Caption.TLabel")
        self.output_caption.pack(anchor="w", pady=(10, 0))
        result = RoundField(frame, s, ("Consolas", 15, "bold"))
        result.pack(fill="x", pady=(3, 0))
        self.output = result.entry
        self.output.bind("<Return>", lambda e: self.copy_output(return_to_game=True))
        self.output.bind("<FocusIn>", lambda e: self.cancel_return(), add="+")
        Placeholder(self.output, "结果在这里，可直接改")
        self.last_result = ""
        self.result_source = ""  # the input text that produced the current result

        row = ttk.Frame(frame)
        row.pack(fill="x", pady=(10, 0))
        RoundButton(row, "复制", self.copy_output, s).pack(side="left", fill="x", expand=True)
        RoundButton(row, "设置", self.open_settings, s, solid=False).pack(side="left", fill="x", expand=True,
                                                                        padx=(8, 0))

        self.status = ttk.Label(frame, text="", foreground=COLORS["muted"], wraplength=int(390 * s))
        self.status.pack(fill="x", pady=(6, 0))
        self.hint = ttk.Label(frame, foreground=COLORS["muted"], text="Esc 回游戏 · 改过的结果点复制后会记住")
        self.hint.pack(fill="x")

        self.root.bind("<Escape>", lambda e: self.hide())
        # Any typing or clicking means the user is still here: don't auto-return to the game.
        self.root.bind("<Key>", lambda e: self.cancel_return(), add="+")
        self.root.bind("<Button>", lambda e: self.cancel_return(), add="+")

    def set_status(self, text: str, kind: str = "muted") -> None:
        self.status.configure(text=text, foreground=COLORS[kind])

    # ------------------------------------------------------------ background services

    def stop_hotkey(self) -> None:
        if self.hotkey:
            self.hotkey.stop()
            self.hotkey.join(1)
            self.hotkey = None

    def start_hotkey(self) -> bool:
        """Register the saved hotkey; on failure say so in the window, not only the tray."""
        self.stop_hotkey()
        try:
            thread = winapi.start_hotkey(self.settings["hotkey"], lambda hwnd: self.events.put(("hotkey", hwnd)))
        except ValueError as error:
            problem = f"快捷键 {self.settings['hotkey']} 无效：{error}。点“设置”换一个"
        else:
            if not thread.error:
                self.hotkey = thread
                return True
            problem = f"快捷键 {self.settings['hotkey']} 被其他软件占用了，按了没反应。点“设置”换一个"
        self.set_status(problem, "error")
        self.notify(problem)
        return False

    def start_tray(self) -> None:
        try:
            import pystray
            from icon import make_icon
            image = make_icon(64)
        except Exception:  # no tray is better than no app
            return
        post = self.events.put
        menu = pystray.Menu(
            pystray.MenuItem(lambda item: f"显示窗口（{self.settings['hotkey']}）", lambda: post(("show", 0)), default=True),
            pystray.MenuItem("设置", lambda: post(("settings", 0))),
            pystray.MenuItem("打开我的喊话表", lambda: post(("phrasebook", 0))),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("退出", lambda: post(("quit", 0))),
        )
        self.tray = pystray.Icon("CWTranslator", image, f"{APP_NAME} v{APP_VERSION}", menu)
        self.tray.run_detached()

    def notify(self, message: str) -> None:
        if self.tray:
            try:
                self.tray.notify(message, APP_NAME)
            except Exception:
                pass

    def poll(self) -> None:
        """Hotkey, tray and worker threads talk to Tk only through this queue."""
        try:
            while True:
                event = self.events.get_nowait()
                kind = event[0]
                if kind == "hotkey":
                    self.toggle(event[1])
                elif kind == "show":
                    self.show(winapi.foreground_window())
                elif kind == "result":
                    self.on_result(*event[1:])
                elif kind == "key_test":
                    event[1](event[2])
                elif kind == "settings":
                    self.open_settings()
                elif kind == "phrasebook":
                    os.startfile(Phrasebook.ensure_user_file())
                elif kind == "quit":
                    self.quit()
                    return
        except queue.Empty:
            pass
        self.root.after(30, self.poll)

    # ------------------------------------------------------------ show / hide

    def own_hwnd(self) -> int:
        try:
            return int(self.root.wm_frame(), 16)
        except (tk.TclError, ValueError):
            return 0

    def toggle(self, foreground: int) -> None:
        if self.root.state() == "normal" and foreground == self.own_hwnd():
            self.hide()
        else:
            self.show(foreground)

    def show(self, foreground: int) -> None:
        own = self.own_hwnd()
        if foreground and foreground != own:
            self.prev_hwnd = foreground
        self.cancel_return()
        if not self.placed:
            self.place_window()
        self.root.deiconify()
        self.root.lift()
        self.root.attributes("-topmost", True)
        self.root.update_idletasks()
        winapi.activate(self.own_hwnd())
        self.input.focus_force()
        self.input.select_range(0, "end")
        self.input.icursor("end")
        self.engine.warm()

    def place_window(self) -> None:
        self.root.update_idletasks()
        area = winapi.monitor_work_area(self.prev_hwnd)
        width, height = self.root.winfo_reqwidth(), self.root.winfo_reqheight()
        if area:
            left, top, right, bottom = area
            x, y = left + (right - left - width) // 2, top + int((bottom - top) * 0.28)
        else:
            x, y = (self.root.winfo_screenwidth() - width) // 2, int(self.root.winfo_screenheight() * 0.28)
        self.root.geometry(f"+{x}+{y}")
        self.placed = True

    def hide(self, return_to_game: bool = True) -> None:
        self.cancel_return()
        # Hand the foreground to the game *before* hiding: only the foreground process may do so, and
        # once hidden Windows may already have given focus to whatever window sits behind us.
        if return_to_game and self.prev_hwnd:
            winapi.activate(self.prev_hwnd)
        self.root.withdraw()

    def cancel_return(self) -> None:
        if self.return_job:
            self.root.after_cancel(self.return_job)
            self.return_job = None

    # ------------------------------------------------------------ translating

    def translate(self) -> None:
        text = self.input.get().strip()
        if not text:
            return
        self.seq += 1
        seq = self.seq
        self.hide_suggestions()
        self.set_status("翻译中…" if self.engine.ready.is_set() else "正在加载词库…")

        def work() -> None:
            self.events.put(("result", seq, text, self.engine.translate(text)))

        threading.Thread(target=work, daemon=True, name="translate").start()

    def on_result(self, seq: int, text: str, result) -> None:
        if seq != self.seq:
            return  # a newer request superseded this one
        if self.input.get().strip() != text:
            return  # the input was cleared or changed while translating
        self.result_source = text
        if result.error:
            self.output.delete(0, "end")  # never leave an older translation that looks like this one's
            self.last_result = ""
            self.set_status(result.error, "error")
            return
        self.output.delete(0, "end")
        self.output.insert(0, result.text)
        self.last_result = result.text
        copied = winapi.set_clipboard(result.text)
        parts = ["已复制" if copied else "复制失败，请点复制", ROUTE_NAMES.get(result.route, result.route)]
        if self.settings["show_timing"]:
            parts.append(f"{result.ms:.0f} ms")
        kind = "ok" if copied else "error"
        limit = int(self.settings["chat_limit"])
        if len(result.text) > limit:
            parts.append(f"{len(result.text)} 字符，超过 {limit}，可能发不全")
            kind = "error"
        self.set_status(" · ".join(parts), kind)
        if copied and self.settings["auto_return"] and self.root.state() == "normal" and kind == "ok":
            self.return_job = self.root.after(int(self.settings["return_delay_ms"]), self.hide)

    def copy_output(self, return_to_game: bool = False) -> None:
        """Copy the (possibly edited) result. An edited result is saved to my phrasebook for next time."""
        self.cancel_return()
        zh, en = self.input.get().strip(), self.output.get().strip()
        if not en:
            self.set_status("结果是空的：先翻译或从列表选一句", "error")
            return
        if not winapi.set_clipboard(en):
            self.set_status("复制失败，请再点一次", "error")
            return
        self.engine.used(zh, en)
        if zh and en != self.last_result:
            self.engine.remember(zh, en)
            self.last_result = en
            self.set_status("已复制 · 已记住这个改法", "ok")
        else:
            self.set_status("已复制", "ok")
        if return_to_game:
            self.hide()

    # ------------------------------------------------------------ fuzzy suggestions

    def schedule_suggest(self) -> None:
        """Runs on every input change: drop a result that no longer matches the input, then refresh the list."""
        if self.suppress_suggest:
            return
        text = self.input.get().strip()
        if text != self.result_source and (self.output.get() or self.status.cget("text")):
            # Cleared or edited input: the old English must not look like this line's translation.
            self.output.delete(0, "end")
            self.last_result = self.result_source = ""
            self.cancel_return()
            self.set_status("")
        if not text:
            self.hide_suggestions()
            return
        if self.suggest_job:
            self.root.after_cancel(self.suggest_job)
        self.suggest_job = self.root.after(120, self.update_suggestions)

    def update_suggestions(self) -> None:
        """Grouped dropdown: a header row per group (not selectable), then its lines."""
        self.suggest_job = None
        groups = self.engine.suggest(self.input.get())
        # One entry per listbox row: None for a group header, else the Suggestion.
        self.suggest_items = []
        if not groups:
            self.hide_suggestions()
            return
        from engine import SOURCE_NAMES
        box = self.suggest_box
        box.delete(0, "end")
        for title, items in groups:
            box.insert("end", f" ▍{title}")
            box.itemconfigure("end", bg=COLORS["bg"], fg=COLORS["accent_press"], selectbackground=COLORS["bg"],
                              selectforeground=COLORS["accent_press"])
            self.suggest_items.append(None)
            for item in items:
                # In 推荐, only lines that are not player wording (a built trade line, an exact game name)
                # carry a tag, e.g. 〔物品〕柠檬 → Lemon.
                plain = title != "推荐" or item.source in ("mine", "phrasebook", "sample", "term")
                tag = "" if plain else f"〔{SOURCE_NAMES.get(item.source, '')}〕"
                box.insert("end", f"     {tag}{item.zh}  →  {item.en}")
                self.suggest_items.append(item)
        box.configure(height=min(10, len(self.suggest_items)))
        if not self.suggest_frame.winfo_ismapped():
            self.suggest_frame.pack(fill="x", pady=(2, 0), before=self.output_caption)

    def select_row(self, index: int) -> None:
        box = self.suggest_box
        box.selection_clear(0, "end")
        box.selection_set(index)
        box.activate(index)
        box.see(index)

    def move_suggestion(self, step: int):
        """Arrow keys in the list skip group headers; ↑ from the first line returns to the input."""
        current = self.suggest_box.curselection()
        index = current[0] if current else -1
        while True:
            index += step
            if index < 0:
                self.suggest_box.selection_clear(0, "end")
                self.input.focus_set()
                return "break"
            if index >= len(self.suggest_items):
                return "break"
            if self.suggest_items[index] is not None:
                self.select_row(index)
                return "break"

    def hide_suggestions(self) -> None:
        if self.suggest_job:
            self.root.after_cancel(self.suggest_job)
            self.suggest_job = None
        if self.suggest_frame.winfo_ismapped():
            self.suggest_frame.pack_forget()

    def focus_suggestions(self):
        if self.suggest_frame.winfo_ismapped() and any(self.suggest_items):
            self.suggest_box.focus_set()
            self.suggest_box.selection_clear(0, "end")
            return self.move_suggestion(1)
        return None

    def pick_suggestion(self) -> None:
        selection = self.suggest_box.curselection()
        if not selection or selection[0] >= len(self.suggest_items):
            return
        item = self.suggest_items[selection[0]]
        if item is None:  # a group header
            self.suggest_box.selection_clear(0, "end")
            return
        self.engine.used(item.zh, item.en)
        self.suppress_suggest = True
        self.input.delete(0, "end")
        self.input.insert(0, item.zh)
        self.suppress_suggest = False
        self.hide_suggestions()
        self.output.delete(0, "end")
        self.output.insert(0, item.en)
        self.last_result = item.en
        self.result_source = item.zh
        copied = winapi.set_clipboard(item.en)
        self.set_status("已复制 · 现成说法" if copied
                        else "复制失败，请点“复制”", "ok" if copied else "error")
        self.input.focus_set()
        self.input.icursor("end")

    # ------------------------------------------------------------ dialogs

    def dialog(self, title: str) -> tk.Toplevel:
        window = tk.Toplevel(self.root)
        window.title(title)
        window.configure(bg=COLORS["bg"])
        window.resizable(False, False)
        window.attributes("-topmost", True)
        return window

    def center(self, window: tk.Toplevel) -> None:
        window.update_idletasks()
        x = (window.winfo_screenwidth() - window.winfo_reqwidth()) // 2
        y = (window.winfo_screenheight() - window.winfo_reqheight()) // 3
        window.geometry(f"+{x}+{y}")
        window.lift()
        window.focus_force()

    def key_row(self, parent, status: str, hint: str):
        """Captioned key entry + test button + result label; returns the entry variable."""
        variable = tk.StringVar()
        ttk.Label(parent, text="DeepSeek API Key：把 Key 粘贴到下面的框里（Ctrl+V）",
                  style="Caption.TLabel").pack(anchor="w", pady=(10, 0))
        row = ttk.Frame(parent)
        row.pack(fill="x", pady=(2, 0))
        entry = tk.Entry(row, textvariable=variable, show="•", font=(FONT, 11), width=38, **FIELD_STYLE)
        entry.pack(side="left", fill="x", expand=True, ipady=3)
        Placeholder(entry, hint, variable)
        result = ttk.Label(parent, text=status, foreground=COLORS["muted"])

        def test() -> None:
            # An empty box falls back to the key already in use; say which one was tested.
            typed = variable.get().strip()
            key = typed or self.settings.api_key
            tested = "输入框里的 Key" if typed else {
                "saved": "输入框为空，测的是已保存的 Key", "environment": "输入框为空，测的是本机环境变量里的 Key"
            }.get(self.settings.key_source, "")
            if not key:
                result.configure(text="输入框是空的，请先粘贴 Key", foreground=COLORS["error"])
                return
            result.configure(text=f"测试中…（{tested}）", foreground=COLORS["muted"])

            def done(error: str) -> None:
                if result.winfo_exists():
                    result.configure(text=f"{tested}：{error or '可用 ✓'}", foreground=COLORS["error" if error else "ok"])

            threading.Thread(target=lambda: self.events.put(("key_test", done, self.engine.test_key(key))),
                             daemon=True).start()

        ttk.Button(row, text="测试", width=6, command=test).pack(side="left", padx=(6, 0))
        result.pack(fill="x", pady=(4, 0))
        entry.focus_set()
        return variable

    def open_wizard(self) -> None:
        window = self.dialog(f"{APP_NAME} · 首次设置")
        body = ttk.Frame(window, padding=18)
        body.pack(fill="both")
        ttk.Label(body, text=f"欢迎使用 {APP_NAME}", font=(FONT, 13, "bold")).pack(anchor="w")
        ttk.Label(body, wraplength=460, justify="left", text=(
            "常用喊话和词库里有的句子，本地就能直接翻译，不需要任何设置。\n"
            "没见过的新句子要用 DeepSeek 联网翻译，需要一个 DeepSeek API Key（按用量付费，聊天用量很小）。\n\n"
            "1. 点下面的按钮打开 DeepSeek 开放平台，注册登录并充值少量金额\n"
            "2. 在“API Keys”页面创建一个 Key（sk- 开头），复制\n"
            "3. 粘贴到下面，点“测试”，显示“可用”后点“保存”")).pack(anchor="w", pady=(6, 8))
        ttk.Button(body, text="打开 DeepSeek 申请页", style="Secondary.TButton", command=lambda: webbrowser.open(DEEPSEEK_KEYS_URL)).pack(anchor="w")
        status = "本机已配置环境变量里的 Key，可以直接点“先跳过”" if self.settings.key_source == "environment" else ""
        key = self.key_row(body, status, "粘贴 sk- 开头的 Key，然后点右边“测试”")
        ttk.Label(body, wraplength=460, justify="left", foreground=COLORS["muted"], text=(
            f"之后在游戏里按 {self.settings['hotkey']} 随时唤出窗口。游戏建议设为“无边框窗口”，切换最顺畅。")
                  ).pack(anchor="w", pady=(10, 0))
        buttons = ttk.Frame(body)
        buttons.pack(fill="x", pady=(12, 0))
        error = ttk.Label(body, text="", foreground=COLORS["error"], wraplength=460)
        error.pack(anchor="w")

        def finish(save_key: bool) -> None:
            try:
                if save_key and key.get().strip():
                    self.settings.set_api_key(key.get())
                self.settings["setup_done"] = True
                self.settings.save()
            except (OSError, ValueError):
                error.configure(text="Key 格式不正确或本机配置无法保存，请检查后重试")
                return
            key.set("")
            window.destroy()
            self.show(winapi.foreground_window())

        ttk.Button(buttons, text="保存", command=lambda: finish(True)).pack(side="right")
        ttk.Button(buttons, text="先跳过", style="Secondary.TButton", command=lambda: finish(False)).pack(side="right", padx=(0, 6))
        window.protocol("WM_DELETE_WINDOW", lambda: finish(False))
        self.center(window)

    def open_settings(self) -> None:
        self.cancel_return()
        window = self.dialog(f"{APP_NAME} · 设置")
        body = ttk.Frame(window, padding=18)
        body.pack(fill="both")

        source = {"saved": "已保存一个 Key（加密存放）。要换 Key 才需要填，留空表示不修改",
                  "saved_unavailable": "已保存的 Key 无法解密，请在这台电脑重新填写或清除",
                  "environment": "正在使用本机环境变量里的 Key。填写后改用这里的",
                  "environment_invalid": "本机环境变量里的 Key 格式不正确，请重新填写",
                  "none": "还没有 Key：只能翻译词库里已有的句子"}[self.settings.key_source]
        hint = "已保存，要换 Key 才需要粘贴新的" if self.settings.key_source == "saved" else "粘贴 sk- 开头的 Key，然后点右边“测试”"
        key = self.key_row(body, source, hint)
        link = ttk.Frame(body)
        link.pack(fill="x", pady=(4, 0))
        ttk.Button(link, text="打开 DeepSeek 申请页", style="Secondary.TButton", command=lambda: webbrowser.open(DEEPSEEK_KEYS_URL)).pack(side="left")
        clear = tk.BooleanVar(value=False)
        ttk.Checkbutton(link, text="清除 Key 并停用环境变量", variable=clear).pack(side="left", padx=(10, 0))
        environment = tk.BooleanVar(value=self.settings["use_environment_key"])
        ttk.Checkbutton(body, text="未保存 Key 时，允许使用本机 DEEPSEEK_API_KEY 环境变量",
                        variable=environment).pack(anchor="w", pady=(6, 0))
        ttk.Label(body, text=f"Key 加密配置：{USER_DIR / 'settings.json'}", foreground=COLORS["muted"],
                  wraplength=460).pack(anchor="w", pady=(4, 0))

        form = ttk.Frame(body)
        form.pack(fill="x", pady=(12, 0))
        # The global hotkey would swallow the keys being recorded, so pause it meanwhile.
        hotkey = HotkeyField(form, self.settings["hotkey"], on_focus=self.stop_hotkey,
                             on_blur=lambda: self.hotkey or self.start_hotkey())
        model = tk.StringVar(value=self.settings["model"])
        ttk.Label(form, text="唤出快捷键", style="Caption.TLabel").grid(row=0, column=0, sticky="w", pady=3)
        hotkey.entry.grid(row=0, column=1, sticky="w", padx=8, pady=3, ipady=2)
        ttk.Label(form, text="点一下左边的框，再直接按想用的组合键", foreground=COLORS["muted"]).grid(row=0, column=2, sticky="w")
        ttk.Label(form, text="模型", style="Caption.TLabel").grid(row=1, column=0, sticky="w", pady=3)
        tk.Entry(form, textvariable=model, font=(FONT, 10), width=18, **FIELD_STYLE).grid(
            row=1, column=1, sticky="w", padx=8, pady=3, ipady=2)
        ttk.Label(form, text="一般不用改；DeepSeek 改名时才需要修改", foreground=COLORS["muted"]).grid(row=1, column=2, sticky="w")

        auto_return = tk.BooleanVar(value=self.settings["auto_return"])
        autostart = tk.BooleanVar(value=self.settings["autostart"])
        timing = tk.BooleanVar(value=self.settings["show_timing"])
        for text, variable in (("翻译后自动隐藏并切回游戏", auto_return), ("开机自动启动（在托盘里待命）", autostart),
                               ("显示翻译耗时", timing)):
            ttk.Checkbutton(body, text=text, variable=variable).pack(anchor="w", pady=(4, 0))

        tools = ttk.Frame(body)
        tools.pack(fill="x", pady=(10, 0))
        ttk.Button(tools, text="打开我的喊话表", style="Secondary.TButton", command=lambda: os.startfile(Phrasebook.ensure_user_file())).pack(side="left")
        ttk.Button(tools, text="打开数据文件夹", style="Secondary.TButton", command=lambda: (USER_DIR.mkdir(parents=True, exist_ok=True),
                                                           os.startfile(USER_DIR))).pack(side="left", padx=(6, 0))

        info = self.engine.dictionary_info()
        about = (f"{APP_NAME} v{APP_VERSION} · 词库导出于 {info.get('exported_at', '加载中')[:10]}"
                 f" · {info.get('records', '?')} 条词条 · {info.get('direct_answers', '?')} 句原句直出")
        ttk.Label(body, text=about, foreground=COLORS["muted"]).pack(anchor="w", pady=(12, 0))
        error = ttk.Label(body, text="", foreground=COLORS["error"], wraplength=460)
        error.pack(anchor="w")

        def save() -> None:
            if hotkey.error:
                error.configure(text=f"快捷键不可用：{hotkey.error}")
                return
            import re
            if not re.fullmatch(r"[A-Za-z0-9._:/-]{1,128}", model.get().strip()):
                error.configure(text="模型名需为 1–128 个字母、数字或 . _ : / -")
                return
            try:
                if key.get().strip() and not clear.get():
                    from settings import validate_api_key
                    validate_api_key(key.get())
            except ValueError:
                error.configure(text="Key 格式不正确，请重新复制完整 Key（不要带空格或换行）")
                return
            hotkey_changed = hotkey.value != self.settings["hotkey"]
            model_changed = model.get().strip() != self.settings["model"]
            if hotkey_changed:
                # Only keep a combination Windows actually lets us register.
                old = self.settings["hotkey"]
                self.settings["hotkey"] = hotkey.value
                if not self.start_hotkey():
                    self.settings["hotkey"] = old
                    self.start_hotkey()
                    self.set_status("")
                    error.configure(text=f"{hotkey.value} 被其他软件占用了（比如微信、QQ），请换一个组合键")
                    return
                self.set_status(f"快捷键已改为 {hotkey.value}", "ok")
                if self.tray:
                    self.tray.update_menu()
            self.settings["model"] = model.get().strip()
            self.settings["auto_return"] = auto_return.get()
            self.settings["show_timing"] = timing.get()
            if autostart.get() != self.settings["autostart"]:
                try:
                    winapi.set_autostart(autostart.get())
                    self.settings["autostart"] = autostart.get()
                except OSError as problem:
                    error.configure(text=f"开机自启设置失败：{problem}")
                    return
            try:
                self.settings["use_environment_key"] = environment.get()
                if clear.get():
                    self.settings.set_api_key("")
                elif key.get().strip():
                    self.settings.set_api_key(key.get())
                self.settings.save()
            except (OSError, ValueError):
                error.configure(text="本机配置无法保存，请检查数据文件夹权限后重试")
                return
            if model_changed:
                self.engine.reset_cache_for_model()
            key.set("")
            window.destroy()

        def cancel() -> None:
            window.destroy()
            if not self.hotkey:
                self.start_hotkey()

        buttons = ttk.Frame(body)
        buttons.pack(fill="x", pady=(12, 0))
        ttk.Button(buttons, text="保存", command=save).pack(side="right")
        ttk.Button(buttons, text="取消", style="Secondary.TButton", command=cancel).pack(side="right", padx=(0, 6))
        window.protocol("WM_DELETE_WINDOW", cancel)
        self.center(window)

    # ------------------------------------------------------------ exit

    def quit(self) -> None:
        if self.hotkey:
            self.hotkey.stop()
        if self.tray:
            self.tray.stop()
        self.engine.client.close()
        self.root.destroy()

    def run(self) -> None:
        self.root.mainloop()


def main() -> None:
    if not winapi.claim_single_instance():
        return  # the running copy shows itself
    App(background="--background" in sys.argv).run()


if __name__ == "__main__":
    main()
