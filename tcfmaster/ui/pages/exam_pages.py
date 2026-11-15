"""Pages : Commencer un examen, Examens blancs, Compréhension orale / écrite."""
from __future__ import annotations

import random

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QComboBox, QHBoxLayout, QHeaderView, QLabel, QPushButton,
                               QSpinBox, QStackedWidget, QTableWidget, QTableWidgetItem,
                               QVBoxLayout, QWidget)
from sqlalchemy import select

from tcfmaster.db.models import SECTION_LABELS, Attempt, Question
from tcfmaster.services import exam_service as ES
from tcfmaster.ui import speaking as _speaking  # noqa: F401 (enregistre l'épreuve EO)
from tcfmaster.ui import writing as _writing  # noqa: F401 (enregistre l'épreuve EE)
from tcfmaster.ui.exam_session import STEP_FACTORIES, ExamSession
from tcfmaster.ui.mcq_runner import McqRunner
from tcfmaster.ui.results_view import ResultsView
from tcfmaster.ui.widgets import Card, Page, disclaimer_label


class _RunnerPage(Page):
    """Page à trois états : sélection → déroulement → résultats."""

    def __init__(self, ctx, title, subtitle):
        super().__init__(ctx, title, subtitle)
        self.stack = QStackedWidget()
        self.body.addWidget(self.stack)
        self.select_view = QWidget()
        self.select_lay = QVBoxLayout(self.select_view)
        self.select_lay.setContentsMargins(0, 0, 0, 0)
        self.select_lay.setSpacing(14)
        self.stack.addWidget(self.select_view)
        self.results_box = QWidget()
        rl = QVBoxLayout(self.results_box)
        rl.setContentsMargins(0, 0, 0, 0)
        self.results = ResultsView(ctx)
        rl.addWidget(self.results)
        back = QPushButton("◀ Retour")
        back.clicked.connect(self.back_to_selection)
        rl.addWidget(back, alignment=Qt.AlignLeft)
        self.stack.addWidget(self.results_box)
        self.running = None

    def run_widget(self, w) -> None:
        if self.running is not None:
            self.stack.removeWidget(self.running)
            self.running.deleteLater()
        self.running = w
        w.finished.connect(self.show_results)
        self.stack.addWidget(w)
        self.stack.setCurrentWidget(w)

    def show_results(self, attempt_id: int) -> None:
        with self.ctx.db.session() as s:
            res = s.get(Attempt, attempt_id).results or {}
            if res.get("kind") == "collection":      # série d'exercices B2 (v1.1)
                from tcfmaster.services import correction as C
                from tcfmaster.ui import correction_view as CV
                self.results.setHtml(CV.session_html(C.session_correction(s, attempt_id)))
            else:
                self.results.show_attempt(attempt_id)
        self.stack.setCurrentWidget(self.results_box)
        self.last_attempt_id = attempt_id

    def back_to_selection(self) -> None:
        self.stack.setCurrentWidget(self.select_view)
        self.refresh()


def _exam_combo(ctx) -> QComboBox:
    cb = QComboBox()
    with ctx.db.session() as s:
        for e in ES.list_exams(s):
            cb.addItem(f"{e.code} – {e.title} ({e.level})", e.id)
    return cb


class StartExamPage(_RunnerPage):
    def __init__(self, ctx):
        super().__init__(ctx, "Commencer un examen",
                         "Examen blanc complet en conditions réelles : CO 20 min, CE 35 min, "
                         "EE 30 min, EO 10 min.")
        card = Card("Choisir un examen")
        self.combo = _exam_combo(ctx)
        card.lay.addWidget(self.combo)
        row = QHBoxLayout()
        self.mode = QComboBox()
        self.mode.addItem("Conditions réelles (mode examen)", ES.MODE_EXAM)
        self.mode.addItem("Entraînement (réécoute, sans pression)", ES.MODE_TRAINING)
        row.addWidget(QLabel("Mode :"))
        row.addWidget(self.mode, 1)
        card.lay.addLayout(row)
        self.go = QPushButton("Démarrer l'examen complet")
        self.go.setObjectName("Primary")
        self.go.clicked.connect(self.start)
        card.lay.addWidget(self.go)
        card.lay.addWidget(disclaimer_label(
            "Les résultats sont des estimations pédagogiques et non des résultats officiels "
            "de France Éducation international."))
        self.select_lay.addWidget(card)
        self.select_lay.addStretch(1)

    def refresh(self):
        cur = self.combo.currentData()
        self.combo.clear()
        with self.ctx.db.session() as s:
            for e in ES.list_exams(s):
                self.combo.addItem(f"{e.code} – {e.title} ({e.level})", e.id)
        if cur is not None:
            i = self.combo.findData(cur)
            if i >= 0:
                self.combo.setCurrentIndex(i)
        self.go.setEnabled(self.combo.count() > 0)

    def start(self, exam_id: int | None = None, sections: list[str] | None = None,
              mode: str | None = None):
        exam_id = exam_id or self.combo.currentData()
        if exam_id is None:
            return
        sess = ExamSession(self.ctx, exam_id, sections or ["CO", "CE", "EE", "EO"],
                           mode or self.mode.currentData(),
                           audio=getattr(self.ctx, "audio", None))
        self.run_widget(sess)
        return sess


class MockExamsPage(_RunnerPage):
    def __init__(self, ctx):
        super().__init__(ctx, "Examens blancs",
                         "Bibliothèque des examens complets. Lancez un examen entier ou une "
                         "seule épreuve.")
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["Code", "Titre", "Niveau", "Passages",
                                              "Dernier résultat", ""])
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setMinimumHeight(420)
        self.select_lay.addWidget(self.table)
        row = QHBoxLayout()
        self.section = QComboBox()
        self.section.addItem("Examen complet", None)
        for k, v in SECTION_LABELS.items():
            self.section.addItem(v, k)
        self.mode = QComboBox()
        self.mode.addItem("Mode examen", ES.MODE_EXAM)
        self.mode.addItem("Mode entraînement", ES.MODE_TRAINING)
        go = QPushButton("Lancer")
        go.setObjectName("Primary")
        go.clicked.connect(self.start_selected)
        row.addWidget(self.section)
        row.addWidget(self.mode)
        row.addStretch(1)
        row.addWidget(go)
        self.select_lay.addLayout(row)

    def refresh(self):
        with self.ctx.db.session() as s:
            exams = ES.list_exams(s)
            self.table.setRowCount(len(exams))
            for r, e in enumerate(exams):
                atts = list(s.execute(select(Attempt).where(
                    Attempt.exam_id == e.id, Attempt.finished_at.is_not(None))
                    .order_by(Attempt.finished_at)).scalars())
                last = ""
                if atts:
                    res = atts[-1].results or {}
                    last = " · ".join(f"{k} {v.get('level', '')}" for k, v in res.items()
                                      if isinstance(v, dict))
                for c, val in enumerate([e.code, e.title, e.level, str(len(atts)), last]):
                    it = QTableWidgetItem(val)
                    it.setData(Qt.UserRole, e.id)
                    self.table.setItem(r, c, it)

    def start_selected(self):
        row = self.table.currentRow()
        if row < 0:
            return
        exam_id = self.table.item(row, 0).data(Qt.UserRole)
        sec = self.section.currentData()
        sections = [sec] if sec else ["CO", "CE", "EE", "EO"]
        sections = [x for x in sections if x in STEP_FACTORIES]
        self.run_widget(ExamSession(self.ctx, exam_id, sections, self.mode.currentData(),
                                    audio=getattr(self.ctx, "audio", None)))


class ComprehensionPage(_RunnerPage):
    """Entraînement CO ou CE : collections thématiques B2 (v1.1) et questions d'examen."""

    def __init__(self, ctx, section: str):
        self.section = section
        sub = ("Conversations, messages, annonces, interviews, radio… Réécoute autorisée en "
               "entraînement." if section == "CO" else
               "Courriels, lettres, articles, annonces, textes argumentatifs…")
        super().__init__(ctx, SECTION_LABELS[section] + " B2", sub)
        from tcfmaster.ui.pages.library_page import CollectionLauncher
        self.collections = CollectionLauncher(ctx, section, self.start_series)
        self.select_lay.addWidget(self.collections)
        card = Card("Questions isolées des examens (banque v1.0)")
        row = QHBoxLayout()
        self.level = QComboBox()
        # v1.1 : préparation exclusivement B2, aucun parcours A1, A2 ou B1.
        for lab, val in (("B2 – objectif", "B2"), ("C1 – au-delà du B2", "C1")):
            self.level.addItem(lab, val)
        self.count = QSpinBox()
        self.count.setRange(5, 25)
        self.count.setValue(10)
        row.addWidget(QLabel("Niveau :"))
        row.addWidget(self.level)
        row.addWidget(QLabel("Questions :"))
        row.addWidget(self.count)
        row.addStretch(1)
        card.lay.addLayout(row)
        self.available = QLabel()
        self.available.setObjectName("Muted")
        card.lay.addWidget(self.available)
        go = QPushButton("Commencer l'entraînement")
        go.setObjectName("Primary")
        go.clicked.connect(self.start)
        card.lay.addWidget(go)
        self.select_lay.addWidget(card)
        self.select_lay.addStretch(1)
        self.level.currentIndexChanged.connect(self.refresh)

    def start_series(self, exercise_ids: list[int], mode: str):
        from tcfmaster.services import collections as COL
        from tcfmaster.ui.exercise_runner import ExerciseRunner
        with self.ctx.db.session() as s:
            aid = COL.start_series(s, exercise_ids, mode).id
        r = ExerciseRunner(self.ctx, aid, exercise_ids, mode,
                           audio=getattr(self.ctx, "audio", None))
        self.run_widget(r)
        return r

    def _pool(self, s) -> list[int]:
        q = select(Question.id).where(Question.section == self.section,
                                      Question.exam_id.is_not(None))
        if self.level.currentData():
            q = q.where(Question.level == self.level.currentData())
        return list(s.execute(q).scalars())

    def refresh(self):
        self.collections.refresh()
        with self.ctx.db.session() as s:
            self.available.setText(f"{len(self._pool(s))} questions disponibles.")

    def start(self):
        with self.ctx.db.session() as s:
            pool = self._pool(s)
            if not pool:
                return None
            qids = random.sample(pool, min(self.count.value(), len(pool)))
            # Tri par difficulté croissante, comme dans l'épreuve officielle.
            order = {"A1": 0, "A2": 1, "B1": 2, "B2": 3, "C1": 4, "C2": 5}
            qids.sort(key=lambda i: order.get(s.get(Question, i).level, 9))
            att = ES.start_attempt(s, None, [self.section], ES.MODE_TRAINING)
            aid = att.id
        limit = max(60, round(ES.time_limit(self.section) * len(qids) / 25))
        r = McqRunner(self.ctx, aid, self.section, qids, ES.MODE_TRAINING, time_limit=limit,
                      audio=getattr(self.ctx, "audio", None))
        self.run_widget(r)
        return r
