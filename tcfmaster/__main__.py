"""Point d'entrée : python -m tcfmaster"""
from __future__ import annotations

import sys


def main() -> int:
    from PySide6.QtWidgets import QApplication, QMessageBox

    from tcfmaster import APP_NAME
    from tcfmaster.core.app_context import bootstrap
    from tcfmaster.db.database import DatabaseCorrupted
    from tcfmaster.ui.main_window import MainWindow
    from tcfmaster.ui.theme import STYLESHEET

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setStyleSheet(STYLESHEET)
    try:
        ctx = bootstrap()
    except DatabaseCorrupted as exc:
        QMessageBox.critical(None, APP_NAME, str(exc))
        return 1
    try:
        from tcfmaster.services.wiring import wire
        wire(ctx)
    except ImportError:
        pass
    win = MainWindow(ctx)
    win.show()
    code = app.exec()
    if getattr(ctx, "audio", None) is not None:
        ctx.audio.shutdown()
    return code


if __name__ == "__main__":
    sys.exit(main())
