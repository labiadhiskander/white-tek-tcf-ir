"""Fenêtre principale : menu latéral à 15 entrées + pages."""
from __future__ import annotations

from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
                               QMainWindow, QStackedWidget, QVBoxLayout, QWidget)

from tcfmaster import APP_NAME, __version__
from tcfmaster.services import settings as S
from tcfmaster.ui.pages import custom_page as CP
from tcfmaster.ui.pages import dashboard_page as DP
from tcfmaster.ui.pages import exam_pages as EP
from tcfmaster.ui.pages import learning_pages as LP
from tcfmaster.ui.pages import misc_pages as MP
from tcfmaster.ui.pages import speaking_page as SP
from tcfmaster.ui.pages import tutor_page as TP
from tcfmaster.ui.pages import writing_page as WP

# (clé, icône, libellé, fabrique)
MENU = [
    ("dashboard", "◧", "Tableau de bord", lambda c: DP.DashboardPage(c)),
    ("start", "▶", "Commencer un examen", lambda c: EP.StartExamPage(c)),
    ("mock", "☰", "Examens blancs", lambda c: EP.MockExamsPage(c)),
    ("co", "🎧", "Compréhension orale", lambda c: EP.ComprehensionPage(c, "CO")),
    ("ce", "📄", "Compréhension écrite", lambda c: EP.ComprehensionPage(c, "CE")),
    ("ee", "✎", "Expression écrite", lambda c: WP.WritingPage(c)),
    ("eo", "🎤", "Expression orale", lambda c: SP.SpeakingPage(c)),
    ("vocab", "Aa", "Vocabulaire B2", lambda c: LP.VocabularyPage(c)),
    ("grammar", "§", "Grammaire", lambda c: LP.GrammarPage(c)),
    ("conj", "⇄", "Conjugaison", lambda c: LP.ConjugationPage(c)),
    ("ai", "💬", "Conversation avec l'IA", lambda c: TP.TutorPage(c)),
    ("custom", "★", "Exercices personnalisés", lambda c: CP.CustomExercisesPage(c)),
    ("history", "⏲", "Historique et résultats", lambda c: MP.HistoryPage(c)),
    ("plan", "📅", "Mon programme de préparation", lambda c: MP.PlanPage(c)),
    ("settings", "⚙", "Paramètres", lambda c: MP.SettingsPage(c)),
]


class MainWindow(QMainWindow):
    def __init__(self, ctx, menu=None):
        super().__init__()
        self.ctx = ctx
        self.setWindowTitle(f"{APP_NAME}  ·  v{__version__}")
        self.resize(1360, 860)
        root = QWidget()
        lay = QHBoxLayout(root)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        side = QWidget()
        side.setObjectName("Sidebar")
        side.setFixedWidth(270)
        sl = QVBoxLayout(side)
        sl.setContentsMargins(0, 0, 0, 10)
        brand = QLabel("WHITE-TEK")
        brand.setObjectName("Brand")
        sub = QLabel("TCF IRN · B2 MASTER")
        sub.setObjectName("BrandSub")
        sl.addWidget(brand)
        sl.addWidget(sub)
        self.nav = QListWidget()
        self.nav.setObjectName("Nav")
        self.nav.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        sl.addWidget(self.nav, 1)
        lay.addWidget(side)

        self.stack = QStackedWidget()
        self.stack.setObjectName("Content")
        lay.addWidget(self.stack, 1)
        self.setCentralWidget(root)

        self.pages: dict[str, QWidget] = {}
        for key, icon, label, factory in (menu or MENU):
            page = factory(ctx)
            self.pages[key] = page
            self.stack.addWidget(page)
            it = QListWidgetItem(f"{icon}   {label}")
            it.setData(256, key)
            self.nav.addItem(it)
        self.nav.currentRowChanged.connect(self._go)
        self.nav.setCurrentRow(0)

        self._backup_timer = QTimer(self)
        self._backup_timer.timeout.connect(self._auto_backup)
        with ctx.db.session() as s:
            minutes = int(S.get(s, "backup_interval_min") or 30)
        self._backup_timer.start(max(5, minutes) * 60 * 1000)

    def _go(self, row: int) -> None:
        page = self.stack.widget(row)
        self.stack.setCurrentIndex(row)
        try:
            page.refresh()
        except Exception:  # une erreur de page ne doit pas fermer l'application
            self.ctx.log.exception("Erreur d'affichage de la page")

    def open_page(self, key: str) -> QWidget:
        keys = list(self.pages)
        self.nav.setCurrentRow(keys.index(key))
        return self.pages[key]

    def _auto_backup(self) -> None:
        with self.ctx.db.session() as s:
            enabled = S.get(s, "auto_backup")
        if enabled:
            try:
                self.ctx.db.backup("auto")
            except Exception:
                self.ctx.log.exception("Échec de la sauvegarde automatique")

    def closeEvent(self, event) -> None:
        self._auto_backup()
        self.ctx.db.close()
        super().closeEvent(event)
