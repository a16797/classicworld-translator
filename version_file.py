"""Write build/version_info.txt so CWTranslator.exe shows its X.Y.Z version under Properties -> Details.

    .venv/Scripts/python version_file.py
"""
from __future__ import annotations

import re
from pathlib import Path

HERE = Path(__file__).resolve().parent


def main() -> None:
    version = re.search(r'^APP_VERSION = "([^"]+)"', (HERE / "app.py").read_text(encoding="utf-8"), re.M).group(1)
    if not re.fullmatch(r"\d+\.\d+\.\d+", version):
        raise SystemExit(f"APP_VERSION must be X.Y.Z, got {version!r}")
    numbers = tuple(int(n) for n in version.split(".")) + (0,)
    text = f"""VSVersionInfo(
  ffi=FixedFileInfo(filevers={numbers}, prodvers={numbers}, mask=0x3f, flags=0x0, OS=0x40004,
                    fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[
    StringFileInfo([StringTable('080404b0', [
      StringStruct('ProductName', 'ClassicWorld 翻译助手'),
      StringStruct('FileDescription', 'ClassicWorld 翻译助手'),
      StringStruct('FileVersion', '{version}'),
      StringStruct('ProductVersion', '{version}'),
      StringStruct('OriginalFilename', 'CWTranslator.exe')])]),
    VarFileInfo([VarStruct('Translation', [0x0804, 1200])])
  ]
)
"""
    out = HERE / "build" / "version_info.txt"
    out.parent.mkdir(exist_ok=True)
    out.write_text(text, encoding="utf-8")
    print(version)


if __name__ == "__main__":
    main()
