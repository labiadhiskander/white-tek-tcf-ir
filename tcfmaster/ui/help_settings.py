"""Carte « Aide et mises à jour » des paramètres, et fenêtre du guide utilisateur."""
from __future__ import annotations

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QCheckBox, QDialog, QHBoxLayout, QLabel, QMessageBox,
                               QPushButton, QTextBrowser, QVBoxLayout)

from tcfmaster import APP_NAME, __version__
from tcfmaster.core.paths import resource_root
from tcfmaster.services import settings as S
from tcfmaster.services import updates as UP
from tcfmaster.ui.widgets import Card

GUIDE_FILE = "GUIDE_UTILISATEUR.md"


def guide_text() -> str:
    p = resource_root() / "docs" / GUIDE_FILE
    try:
        return p.read_text(encoding="utf-8")
    except OSError:
        return "# Guide utilisateur\n\nLe guide est introuvable dans cette installation."


class GuideDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Guide utilisateur – {APP_NAME}")
        self.resize(900, 760)
        lay = QVBoxLayout(self)
        self.view = QTextBrowser()
        self.view.setOpenExternalLinks(True)
        self.view.setMarkdown(guide_text())
        lay.addWidget(self.view)
        close = QPushButton("Fermer")
        close.clicked.connect(self.accept)
        lay.addWidget(close)


def update_url(ctx) -> str:
    with ctx.db.session() as s:
        return S.get(s, "update_url") or UP.DEFAULT_URL


def announce_update(parent, info: UP.UpdateInfo, quiet: bool) -> None:
    if info.error:
        if not quiet:
            QMessageBox.information(parent, "Mises à jour", info.error)
        return
    if not info.available:
        if not quiet:
            QMessageBox.information(parent, "Mises à jour",
                                    f"Vous utilisez la dernière version ({info.current}).")
        return
    res = QMessageBox.question(
        parent, "Mise à jour disponible",
        f"La version {info.latest} est disponible (version installée : {info.current}).\n\n"
        "Vos résultats et réglages sont conservés lors de la mise à jour.\n"
        "Ouvrir la page de téléchargement ?")
    if res == QMessageBox.Yes and info.url:
        QDesktopServices.openUrl(QUrl(info.url))


class HelpSettingsCard(Card):
    def __init__(self, ctx, parent=None):
        super().__init__("Aide et mises à jour", parent)
        self.ctx = ctx
        self.version = QLabel(f"{APP_NAME} · version {__version__}")
        self.lay.addWidget(self.version)
        self.auto = QCheckBox("Rechercher les mises à jour au démarrage")
        self.auto.toggled.connect(self._toggle)
        self.lay.addWidget(self.auto)
        row = QHBoxLayout()
        self.check_btn = QPushButton("Vérifier maintenant")
        self.check_btn.clicked.connect(self.check_now)
        guide = QPushButton("Ouvrir le guide utilisateur")
        guide.clicked.connect(lambda: GuideDialog(self).exec())
        logs = QPushButton("Ouvrir le dossier des journaux")
        logs.clicked.connect(lambda: QDesktopServices.openUrl(
            QUrl.fromLocalFile(str(self.ctx.paths.logs))))
        for b in (self.check_btn, guide, logs):
            row.addWidget(b)
        row.addStretch(1)
        self.lay.addLayout(row)

    def _toggle(self, on: bool) -> None:
        with self.ctx.db.session() as s:
            S.set_(s, "check_updates", bool(on))

    def refresh(self) -> None:
        with self.ctx.db.session() as s:
            on = bool(S.get(s, "check_updates"))
        self.auto.blockSignals(True)
        self.auto.setChecked(on)
        self.auto.blockSignals(False)

    def check_now(self) -> None:
        from tcfmaster.ui.speaking import run_background
        url = update_url(self.ctx)
        self.check_btn.setEnabled(False)
        run_background(self, lambda: UP.check(url), self._checked)

    def _checked(self, info) -> None:
        self.check_btn.setEnabled(True)
        if isinstance(info, Exception):
            info = UP.UpdateInfo(False, __version__, error=str(info))
        announce_update(self, info, quiet=False)
