"""Page « Expression écrite » : entraînement tâche par tâche ou épreuve complète."""
from __future__ import annotations

import time

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QComboBox, QHBoxLayout, QListWidget, QListWidgetItem,
                               QPushButton, QSplitter, QStackedWidget, QVBoxLayout, QWidget)
from sqlalchemy import select

from tcfmaster.db.models import SECTION_EE, Attempt, Exam, WritingSubmission, WritingTask
from tcfmaster.services import exam_service as ES
from tcfmaster.services import writing_service as WS
from tcfmaster.ui.widgets import Card, Page, disclaimer_label
from tcfmaster.ui.writing import WritingEditor, WritingReportView, WritingRunner
from tcfmaster.ui.writing_report import evaluation_html


class WritingPage(Page):
    def __init__(self, ctx):
        super().__init__(ctx, "Expression écrite",
                         "Trois tâches : message (30–60 mots), récit ou description "
                         "(40–90 mots), argumentation (40–90 mots). Correction détaillée.")
        self.stack = QStackedWidget()
        self.body.addWidget(self.stack)
        self._t0 = time.monotonic()

        # --- sélection
        sel = QWidget()
        sl = QVBoxLayout(sel)
        sl.setContentsMargins(0, 0, 0, 0)
        card = Card("Choisir un sujet")
        row = QHBoxLayout()
        self.exam = QComboBox()
        self.task = QComboBox()
        for n, lab in ((1, "Tâche 1 – message"), (2, "Tâche 2 – récit / description"),
                       (3, "Tâche 3 – argumentation")):
            self.task.addItem(lab, n)
        row.addWidget(self.exam, 3)
        row.addWidget(self.task, 2)
        card.lay.addLayout(row)
        btns = QHBoxLayout()
        self.train_btn = QPushButton("S'entraîner sur cette tâche (sans limite de temps)")
        self.train_btn.setObjectName("Primary")
        self.train_btn.clicked.connect(self.start_training)
        self.exam_btn = QPushButton("Épreuve complète : 3 tâches en 30 min")
        self.exam_btn.clicked.connect(self.start_exam)
        btns.addWidget(self.train_btn)
        btns.addWidget(self.exam_btn)
        btns.addStretch(1)
        card.lay.addLayout(btns)
        card.lay.addWidget(disclaimer_label(
            "La note est une estimation pédagogique produite automatiquement ; ce n'est pas "
            "un résultat officiel de France Éducation international."))
        sl.addWidget(card)
        hist = Card("Mes productions")
        split = QSplitter()
        self.history = QListWidget()
        self.history.setMinimumWidth(300)
        self.history.currentItemChanged.connect(self._show_history)
        split.addWidget(self.history)
        self.history_view = WritingReportView()
        split.addWidget(self.history_view)
        split.setStretchFactor(1, 2)
        split.setMinimumHeight(360)
        hist.lay.addWidget(split)
        sl.addWidget(hist, 1)
        self.stack.addWidget(sel)
        self.select_view = sel

        # --- entraînement sur une tâche
        tr = QWidget()
        self.train_lay = QVBoxLayout(tr)
        self.train_lay.setContentsMargins(0, 0, 0, 0)
        self.editor: WritingEditor | None = None
        tb = QHBoxLayout()
        back = QPushButton("◀ Retour")
        back.clicked.connect(self.back)
        self.submit_btn = QPushButton("Faire corriger mon texte")
        self.submit_btn.setObjectName("Primary")
        self.submit_btn.clicked.connect(self.submit_training)
        tb.addWidget(back)
        tb.addStretch(1)
        tb.addWidget(self.submit_btn)
        self.train_bar = tb
        self.stack.addWidget(tr)
        self.train_view = tr

        # --- rapport
        rep = QWidget()
        rl = QVBoxLayout(rep)
        rl.setContentsMargins(0, 0, 0, 0)
        self.report = WritingReportView()
        rl.addWidget(self.report, 1)
        rb = QHBoxLayout()
        b1 = QPushButton("◀ Retour aux sujets")
        b1.clicked.connect(self.back)
        self.retry_btn = QPushButton("Réécrire ce texte")
        self.retry_btn.clicked.connect(self._retry)
        rb.addWidget(b1)
        rb.addWidget(self.retry_btn)
        rb.addStretch(1)
        rl.addLayout(rb)
        self.stack.addWidget(rep)
        self.report_view = rep
        self.runner: WritingRunner | None = None
        self._last_text = ""

    # ---------------------------------------------------------------- état
    def refresh(self) -> None:
        cur = self.exam.currentData()
        self.exam.blockSignals(True)
        self.exam.clear()
        with self.ctx.db.session() as s:
            for e in ES.list_exams(s):
                if e.writing_tasks:
                    self.exam.addItem(f"{e.code} – {e.title}", e.id)
        i = self.exam.findData(cur)
        self.exam.setCurrentIndex(max(0, i))
        self.exam.blockSignals(False)
        ok = self.exam.count() > 0
        self.train_btn.setEnabled(ok)
        self.exam_btn.setEnabled(ok)
        self._load_history()

    def _load_history(self) -> None:
        self.history.clear()
        with self.ctx.db.session() as s:
            for w in WS.history(s):
                t = w.task
                exam = (t.exam.code if t.exam else t.code or "?") if t else "?"
                it = QListWidgetItem(f"{w.created_at:%d/%m %H:%M} · {exam} T{t.task_number if t else '?'}"
                                     f" · {w.note20 or 0:.1f}/20 ({w.level or '-'})")
                it.setData(Qt.UserRole, w.id)
                self.history.addItem(it)
        if not self.history.count():
            self.history_view.setHtml("<p>Vos productions corrigées apparaîtront ici.</p>")

    def _show_history(self, it, _prev=None) -> None:
        if it is None:
            return
        with self.ctx.db.session() as s:
            w = s.get(WritingSubmission, it.data(Qt.UserRole))
            if w:
                self.history_view.setHtml(evaluation_html(w.evaluation or {}, w.text))

    def _task(self, s) -> WritingTask | None:
        exam = s.get(Exam, self.exam.currentData()) if self.exam.currentData() else None
        if exam is None:
            return None
        return next((t for t in exam.writing_tasks if t.task_number == self.task.currentData()),
                    None)

    # ------------------------------------------------------- entraînement
    def open_task(self, task_id: int):
        """Ouvre directement un sujet (banque B2 ou examen), depuis la bibliothèque."""
        self._forced_task = task_id
        try:
            self.start_training()
        finally:
            self._forced_task = None
        return self.editor

    def start_training(self, text: str = "") -> None:
        with self.ctx.db.session() as s:
            forced = getattr(self, "_forced_task", None)
            if forced is None and self.editor is not None and text:
                forced = self.editor.task_id        # « Réécrire ce texte »
            t = s.get(WritingTask, forced) if forced else self._task(s)
            if t is None:
                return
            if self.editor is not None:
                self.train_lay.removeWidget(self.editor)
                self.editor.deleteLater()
            self.editor = WritingEditor(t, show_tips=True)
        if text:
            self.editor.edit.setPlainText(text)
        self.train_lay.insertWidget(0, self.editor, 1)
        if self.train_lay.count() == 1:
            self.train_lay.addLayout(self.train_bar)
        self._t0 = time.monotonic()
        self.stack.setCurrentWidget(self.train_view)

    def submit_training(self) -> None:
        if self.editor is None or not self.editor.text().strip():
            return
        text = self.editor.text()
        with self.ctx.db.session() as s:
            sub = WS.submit(s, self.editor.task_id, text, time.monotonic() - self._t0)
            t = sub.task
            title = (f"{t.exam.code} – tâche {t.task_number}" if t.exam
                     else f"{t.code or 'Sujet'} – tâche {t.task_number}")
            self.report.setHtml(evaluation_html(sub.evaluation, text, title))
        self._last_text = text
        self.retry_btn.setVisible(True)
        self.stack.setCurrentWidget(self.report_view)

    def _retry(self) -> None:
        self.start_training(self._last_text)

    # ------------------------------------------------------------ examen
    def start_exam(self) -> None:
        exam_id = self.exam.currentData()
        if exam_id is None:
            return
        with self.ctx.db.session() as s:
            aid = ES.start_attempt(s, exam_id, [SECTION_EE], ES.MODE_EXAM).id
        if self.runner is not None:
            self.stack.removeWidget(self.runner)
            self.runner.deleteLater()
        self.runner = WritingRunner(self.ctx, aid, exam_id, ES.MODE_EXAM, finalize=True)
        self.runner.finished.connect(self._exam_done)
        self.stack.addWidget(self.runner)
        self.stack.setCurrentWidget(self.runner)
        return self.runner

    def _exam_done(self, attempt_id: int) -> None:
        with self.ctx.db.session() as s:
            a = s.get(Attempt, attempt_id)
            res = (a.results or {}).get(SECTION_EE, {})
            parts = [f"<h2>Expression écrite – note estimée {res.get('note20', 0):.1f} / 20 "
                     f"({res.get('level', '')})</h2>"]
            subs = {w.task_id: w for w in s.execute(select(WritingSubmission).where(
                WritingSubmission.attempt_id == attempt_id)).scalars()}
            for tid in self.runner.task_ids:
                w = subs.get(tid)
                t = s.get(WritingTask, tid)
                if w is None:
                    parts.append(f"<h2>Tâche {t.task_number}</h2><p>Non rendue : 0 / 20.</p>")
                else:
                    parts.append(evaluation_html(w.evaluation, w.text,
                                                 f"Tâche {t.task_number} – {t.task_type}"))
                parts.append("<hr>")
        self.report.setHtml("".join(parts))
        self.retry_btn.setVisible(False)
        self.stack.setCurrentWidget(self.report_view)

    def back(self) -> None:
        self.stack.setCurrentWidget(self.select_view)
        self.refresh()
