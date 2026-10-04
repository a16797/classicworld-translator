"""Stand-in for the game: one chat box that records what was pasted into it."""
import sys
import tkinter as tk
from pathlib import Path

out = Path(sys.argv[1])
root = tk.Tk()
root.title("FAKE GAME")
root.geometry("500x120+200+200")
entry = tk.Entry(root, font=("Consolas", 14))
entry.pack(fill="x", padx=20, pady=40)


def save() -> None:
    out.write_text(entry.get(), encoding="utf-8")
    root.after(100, save)


root.after(300, lambda: (root.lift(), root.focus_force(), entry.focus_set()))
save()
root.mainloop()
