"""Bibliothèque B2 centralisée : filtres, recherche, lancement des exercices corrigés."""
from __future__ import annotations

import random

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QComboBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
                               QListWidget, QListWidgetItem, QPushButton, QSpinBox,
                               QStackedWidget, QTableWidget, QTableWidgetItem, QTextBrowser,
                               QVBoxLayout, QWidget)

from tcfmaster.db.models import SECTION_LABELS
from tcfmaster.services import collections as COL
from tcfmaster.services import correction as C
from tcfmaster.services import exam_service as ES
from tcfmaster.ui import correction_view as CV
from tcfmaster.ui.exercise_runner import ExerciseRunner
from tcfmaster.ui.widgets import Card, Page, disclaimer_label


class SeriesHost(QWidget):
    """Sélection → déroulement → corrections, pour les séries d'exercices."""
    done = Signal(int)

    def __init__(self, ctx, select_widget: QWidget, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.stack = QStackedWidget()
        lay.addWidget(self.stack)
        self.select_view = select_widget
        self.stack.addWidget(select_widget)
        box = QWidget()
        bl = QVBoxLayout(box)
        bl.setContentsMargins(0, 0, 0, 0)
        self.results = QTextBrowser()
        self.results.setMinimumHeight(480)
        bl.addWidget(self.results, 1)
        row = QHBoxLayout()
        back = QPushButton("◀ Retour")
        back.clicked.connect(self.back)
        self.retry_btn = QPushButton("Refaire en mode entraînement")
        self.retry_btn.clicked.connect(self._retry)
        row.addWidget(back)
        row.addWidget(self.retry_btn)
        row.addStretch(1)
        bl.addLayout(row)
        self.stack.addWidget(box)
        self.results_view = box
        self.runner: ExerciseRunner | None = None
        self.last_ids: list[int] = []
        self.last_attempt_id: int | None = None

    def start(self, exercise_ids: list[int], mode: str) -> ExerciseRunner | None:
        if not exercise_ids:
            return None
        with self.ctx.db.session() as s:
            aid = COL.start_series(s, exercise_ids, mode).id
        if self.runner is not None:
            self.stack.removeWidget(self.runner)
            self.runner.deleteLater()
        self.runner = ExerciseRunner(self.ctx, aid, exercise_ids, mode,
                                     audio=getattr(self.ctx, "audio", None))
        self.runner.finished.connect(self.show_results)
        self.stack.addWidget(self.runner)
        self.stack.setCurrentWidget(self.runner)
        self.last_ids = list(exercise_ids)
        return self.runner

    def show_results(self, attempt_id: int) -> None:
        with self.ctx.db.session() as s:
            self.results.setHtml(CV.session_html(C.session_correction(s, attempt_id)))
        self.last_attempt_id = attempt_id
        self.stack.setCurrentWidget(self.results_view)
        self.done.emit(attempt_id)

    def _retry(self) -> None:
        self.start(self.last_ids, ES.MODE_TRAINING)

    def back(self) -> None:
        self.stack.setCurrentWidget(self.select_view)


class CollectionLauncher(Card):
    """Choix d'une collection CO/CE, du nombre d'exercices et du mode."""

    def __init__(self, ctx, section: str, host_start, parent=None):
        super().__init__(f"Collections thématiques – {SECTION_LABELS[section]} B2", parent)
        self.ctx = ctx
        self.section = section
        self._start = host_start
        row = QHBoxLayout()
        self.collection = QComboBox()
        self.count = QSpinBox()
        self.count.setRange(1, 30)
        self.count.setValue(3)
        self.mode = QComboBox()
        self.mode.addItem("Mode entraînement (correction immédiate)", ES.MODE_TRAINING)
        self.mode.addItem("Mode examen (correction à la fin)", ES.MODE_EXAM)
        row.addWidget(self.collection, 3)
        row.addWidget(QLabel("Exercices :"))
        row.addWidget(self.count)
        row.addWidget(self.mode, 2)
        self.lay.addLayout(row)
        self.info = QLabel()
        self.info.setObjectName("Muted")
        self.lay.addWidget(self.info)
        self.go = QPushButton("Commencer")
        self.go.setObjectName("Primary")
        self.go.clicked.connect(self.start)
        self.lay.addWidget(self.go, alignment=Qt.AlignLeft)
        self.collection.currentIndexChanged.connect(self._update_info)

    def refresh(self) -> None:
        cur = self.collection.currentData()
        self.collection.blockSignals(True)
        self.collection.clear()
        self.collection.addItem("Toutes les collections (tirage au sort)", None)
        with self.ctx.db.session() as s:
            for c in COL.list_collections(s, self.section):
                n = len(COL.published_exercises(s, c.id))
                self.collection.addItem(f"{c.title} ({n})", c.id)
        i = self.collection.findData(cur)
        self.collection.setCurrentIndex(max(0, i))
        self.collection.blockSignals(False)
        self._update_info()

    def _pool(self, s) -> list[int]:
        return [e.id for e in COL.published_exercises(s, self.collection.currentData(),
                                                      self.section)]

    def _update_info(self) -> None:
        with self.ctx.db.session() as s:
            n = len(self._pool(s))
        self.info.setText(f"{n} exercice(s) corrigé(s) disponible(s).")
        self.go.setEnabled(n > 0)

    def start(self):
        with self.ctx.db.session() as s:
            pool = self._pool(s)
        if not pool:
            return None
        if self.collection.currentData() is None:
            ids = random.sample(pool, min(self.count.value(), len(pool)))
        else:
            ids = pool[:self.count.value()]
        return self._start(ids, self.mode.currentData())


class LibraryPage(Page):
    def __init__(self, ctx):
        super().__init__(ctx, "Bibliothèque B2",
                         "Toutes les collections corrigées : compréhension, expression, "
                         "examens blancs, vidéos, grammaire et vocabulaire.")
        sel = QWidget()
        sl = QHBoxLayout(sel)
        sl.setContentsMargins(0, 0, 0, 0)
        self.filters = QListWidget()
        self.filters.setObjectName("Filters")
        self.filters.setFixedWidth(240)
        it = QListWidgetItem("Tout afficher")
        it.setData(Qt.UserRole, None)
        self.filters.addItem(it)
        for key, label in COL.FILTERS.items():
            it = QListWidgetItem(label)
            it.setData(Qt.UserRole, key)
            self.filters.addItem(it)
        self.filters.currentRowChanged.connect(lambda _r: self.refresh())
        sl.addWidget(self.filters)
        right = QVBoxLayout()
        top = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Rechercher un thème, un titre, une collection…")
        self.search.textChanged.connect(lambda _t: self.refresh())
        self.mode = QComboBox()
        self.mode.addItem("Mode entraînement", ES.MODE_TRAINING)
        self.mode.addItem("Mode examen", ES.MODE_EXAM)
        top.addWidget(self.search, 1)
        top.addWidget(self.mode)
        right.addLayout(top)
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["Titre", "Collection", "Détail", "Faits",
                                              "Dernier résultat"])
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.Stretch)
        for c, w in ((1, 200), (2, 190), (3, 60), (4, 120)):
            self.table.setColumnWidth(c, w)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setMinimumHeight(460)
        self.table.cellDoubleClicked.connect(lambda _r, _c: self.open_selected())
        right.addWidget(self.table, 1)
        row = QHBoxLayout()
        self.count = QLabel()
        self.count.setObjectName("Muted")
        open_btn = QPushButton("Ouvrir")
        open_btn.setObjectName("Primary")
        open_btn.clicked.connect(self.open_selected)
        row.addWidget(self.count, 1)
        row.addWidget(open_btn)
        right.addLayout(row)
        right.addWidget(disclaimer_label(
            "Chaque exercice publié est accompagné de sa correction détaillée. Les notes "
            "automatiques sont des estimations pédagogiques, pas des résultats officiels."))
        sl.addLayout(right, 1)
        self.host = SeriesHost(ctx, sel)
        self.host.done.connect(lambda _a: None)
        self.body.addWidget(self.host)
        self.items: list[COL.LibraryItem] = []
        self.filters.setCurrentRow(0)

    def set_filter(self, key: str | None) -> None:
        for i in range(self.filters.count()):
            if self.filters.item(i).data(Qt.UserRole) == key:
                self.filters.setCurrentRow(i)
                return

    def refresh(self) -> None:
        it = self.filters.currentItem()
        fam = it.data(Qt.UserRole) if it else None
        with self.ctx.db.session() as s:
            self.items = COL.library(s, fam, self.search.text())
        self.table.setRowCount(len(self.items))
        for r, item in enumerate(self.items):
            vals = [item.title, item.collection, item.detail, str(item.done or ""), item.last]
            for c, v in enumerate(vals):
                self.table.setItem(r, c, QTableWidgetItem(v))
        self.count.setText(f"{len(self.items)} élément(s)")

    def _main_window(self):
        w = self.window()
        return w if hasattr(w, "open_page") else None

    def open_item(self, item: COL.LibraryItem):
        if item.kind == "exercise":
            return self.host.start([int(item.ref)], self.mode.currentData())
        mw = self._main_window()
        if mw is None:
            return None
        if item.kind == "writing":
            page = mw.open_page("ee")
            return page.open_task(int(item.ref))
        if item.kind == "speaking":
            page = mw.open_page("eo")
            return page.open_task(int(item.ref))
        if item.kind == "exam":
            return mw.open_page("mock")
        if item.kind == "grammar":
            return mw.open_page("grammar")
        if item.kind == "vocab":
            return mw.open_page("vocab")
        if item.kind == "video" and "videos" in mw.pages:
            page = mw.open_page("videos")
            return page.show_video(int(item.ref)) if hasattr(page, "show_video") else page
        return None

    def open_selected(self):
        row = self.table.currentRow()
        if 0 <= row < len(self.items):
            return self.open_item(self.items[row])
        return None
