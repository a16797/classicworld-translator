"""Zip build/dist/CWTranslator as dist/ClassicWorld翻译助手-v<version>.zip.

PowerShell's Compress-Archive can store Chinese names in the local code page,
which shows up garbled when extracted elsewhere; zipfile always writes UTF-8.
"""
from __future__ import annotations

import re
import sys
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
PRODUCT = "ClassicWorld翻译助手"


def main() -> None:
    version = re.search(r'^APP_VERSION = "([^"]+)"', (HERE / "app.py").read_text(encoding="utf-8"), re.M).group(1)
    source = HERE / "build" / "dist" / "CWTranslator"
    target = HERE / "dist" / f"{PRODUCT}-v{version}.zip"
    target.parent.mkdir(exist_ok=True)
    target.unlink(missing_ok=True)
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in sorted(source.rglob("*")):
            if path.is_file():
                archive.write(path, f"{PRODUCT}/{path.relative_to(source).as_posix()}")
    print(f"{target} ({target.stat().st_size / 1048576:.1f} MB)")


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    main()
