"""Génère l'icône de l'application (tcfmaster/assets/app.ico et app.png).

    python tools/make_icon.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    from PySide6.QtCore import QRectF, Qt
    from PySide6.QtGui import QColor, QFont, QGuiApplication, QImage, QPainter, QPen
    app = QGuiApplication.instance() or QGuiApplication(sys.argv)
    out = ROOT / "tcfmaster" / "assets"
    out.mkdir(parents=True, exist_ok=True)
    size = 256
    img = QImage(size, size, QImage.Format_ARGB32)
    img.fill(Qt.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    p.setBrush(QColor("#13294B"))
    p.setPen(Qt.NoPen)
    p.drawRoundedRect(QRectF(8, 8, size - 16, size - 16), 48, 48)
    p.setPen(QPen(QColor("#4F9DDE"), 10))
    p.drawLine(48, 186, 208, 186)
    p.setPen(QColor("#FFFFFF"))
    f = QFont("DejaVu Sans", 92)
    f.setBold(True)
    p.setFont(f)
    p.drawText(QRectF(0, 22, size, 150), Qt.AlignCenter, "B2")
    f2 = QFont("DejaVu Sans", 26)
    f2.setBold(True)
    p.setFont(f2)
    p.drawText(QRectF(0, 192, size, 44), Qt.AlignCenter, "TCF IRN")
    p.end()
    img.save(str(out / "app.png"))
    ok = img.scaled(256, 256).save(str(out / "app.ico"))
    print("Icône générée" if ok else "Échec de l'écriture .ico")
    del app
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
