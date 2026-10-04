"""Regenerate data/: the chat dictionary (from the Skill corpus), default phrasebook and app icon.

    .venv/Scripts/python prepare_data.py
"""
from __future__ import annotations

import csv
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
DATA = HERE / "data"
SKILL = Path(os.environ.get("CW_SKILL_DIR", Path.home() / ".agents" / "skills" / "cw-chat-assistant"))
sys.path.insert(0, str(SKILL / "scripts"))

import export_chat_dict  # noqa: E402
import fast_translate  # noqa: E402
from icon import make_icon  # noqa: E402


def main() -> None:
    DATA.mkdir(exist_ok=True)
    info = export_chat_dict.export(DATA / "cw-chat-dict.sqlite3")
    phrases = {zh: short for zh, (short, _full) in fast_translate.LOCAL.items()}
    with (DATA / "默认喊话表.csv").open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.writer(file)
        writer.writerow(("中文", "英文简写"))
        writer.writerows(phrases.items())
    image = make_icon(256)
    image.save(DATA / "icon.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    image.save(DATA / "icon.png")
    print(json.dumps({"dictionary": info, "default_phrases": len(phrases)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    main()
