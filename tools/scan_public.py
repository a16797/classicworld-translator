"""Scan staged Git files or a package directory without displaying secret values."""
from __future__ import annotations
import os
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
PRIVATE_NAMES = {"settings.json", "settings.tmp", "cache.json", "usage.json", "我的喊话表.csv", "开发记录.md"}
SECRET_PATTERN = re.compile(rb"(?:sk-[A-Za-z0-9_-]{20,}|gh[pousr]_[A-Za-z0-9]{30,})")


def main() -> int:
    if len(sys.argv) > 1:
        paths = [p for p in Path(sys.argv[1]).resolve().rglob("*") if p.is_file()]
    else:
        names = subprocess.check_output(["git", "ls-files", "--cached", "-z"], cwd=ROOT).decode("utf-8").split("\0")
        paths = [ROOT / name for name in names if name]
    known = [v.encode() for k, v in os.environ.items()
             if k in ("DEEPSEEK_API_KEY", "OPENROUTER_API_KEY", "JEV_API_KEY") and len(v) >= 16]
    if os.name == "nt":
        sys.path.insert(0, str(ROOT))
        from settings import Settings
        saved = Settings().api_key
        if saved:
            known.append(saved.encode())
    failures = []
    for path in paths:
        raw = path.read_bytes()
        private = path.name in PRIVATE_NAMES or path.name.startswith(".env")
        secret = bool(SECRET_PATTERN.search(raw)) or any(v in raw for v in known)
        if private or secret:
            failures.append(path.name)
    if failures:
        print("Public scan FAILED (filenames only): " + ", ".join(sorted(set(failures))))
        return 1
    print(f"Public scan OK: {len(paths)} files; no detected credentials or private config/cache files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
