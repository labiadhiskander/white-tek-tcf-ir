"""Écrit packaging/version_info.txt (métadonnées Windows de l'exécutable)."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tcfmaster import APP_NAME, __version__  # noqa: E402

TEMPLATE = """VSVersionInfo(
  ffi=FixedFileInfo(filevers=({v}, 0), prodvers=({v}, 0), mask=0x3f, flags=0x0,
                    OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[
    StringFileInfo([StringTable('040C04B0', [
      StringStruct('CompanyName', 'WHITE-TEK'),
      StringStruct('FileDescription', '{name}'),
      StringStruct('FileVersion', '{s}'),
      StringStruct('InternalName', 'WhiteTekTCF'),
      StringStruct('OriginalFilename', 'WhiteTekTCF.exe'),
      StringStruct('ProductName', '{name}'),
      StringStruct('ProductVersion', '{s}')])]),
    VarFileInfo([VarStruct('Translation', [1036, 1200])])
  ]
)
"""


def main() -> int:
    parts = (__version__.split("-")[0].split(".") + ["0", "0", "0"])[:3]
    out = ROOT / "packaging" / "version_info.txt"
    out.write_text(TEMPLATE.format(v=", ".join(parts), s=__version__, name=APP_NAME),
                   encoding="utf-8")
    print(f"{out} ({__version__})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
