"""Épreuve d'expression écrite : éditeur avec compteur de mots, 3 tâches, 30 minutes."""
from __future__ import annotations

import time

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QMessageBox, QPlainTextEdit, QPushButton,
                               QTabWidget, QTextBrowser, QVBoxLayout, QWidget)

from tcfmaster.content.validator import count_words
from tcfmaster.db.models import SECTION_EE, Attempt, Exam, WritingTask
from tcfmaster.services import exam_service as ES
from tcfmaster.services import writing_service as WS
from tcfmaster.ui.exam_session import register_step
from tcfmaster.ui.widgets import Card, CountdownTimer, disclaimer_label

OK_COLOR, LOW_COLOR, HIGH_COLOR = "#2E8B57", "#C0392B", "#C98A0B"


class WritingEditor(QWidget):
    """Consigne + zone de saisie + compteur de mots coloré."""
    changed = Signal()

    def __init__(self, task: WritingTask, show_tips: bool = True, parent=None):
        super().__init__(parent)
        self.task_id = task.id
        self.min_words, self.max_words = task.min_words, task.max_words
        lay = QVBoxLayout(self)
        card = Card(f"Tâche {task.task_number} – {task.task_type}")
        consigne = QLabel(task.instructions)
        consigne.setWordWrap(True)
        card.lay.addWidget(consigne)
        lim = QLabel(f"Entre {task.min_words} et {task.max_words} mots.")
        lim.setObjectName("Muted")
        card.lay.addWidget(lim)
        if show_tips and task.tips:
            tip = QLabel("💡 " + task.tips)
            tip.setWordWrap(True)
            tip.setObjectName("Muted")
            card.lay.addWidget(tip)
        lay.addWidget(card)
        self.edit = QPlainTextEdit()
        self.edit.setPlaceholderText("Rédigez votre texte ici…")
        self.edit.setMinimumHeight(220)
        self.edit.textChanged.connect(self._update)
        lay.addWidget(self.edit, 1)
        self.counter = QLabel()
        lay.addWidget(self.counter)
        self._update()

    def text(self) -> str:
        return self.edit.toPlainText()

    def word_count(self) -> int:
        return count_words(self.text())

    def _update(self) -> None:
        n = self.word_count()
        if n < self.min_words:
            color, msg = LOW_COLOR, f"encore {self.min_words - n} mot(s) au minimum"
        elif n > self.max_words:
            color, msg = HIGH_COLOR, f"{n - self.max_words} mot(s) de trop"
        else:
            color, msg = OK_COLOR, "longueur conforme"
        self.counter.setText(f"<b style='color:{color}'>{n} mot(s)</b> · {msg}")
        self.changed.emit()


class WritingRunner(QWidget):
    """Les trois tâches d'un examen sous un chronomètre commun (30 min)."""
    finished = Signal(int)

    def __init__(self, ctx, attempt_id: int, exam_id: int, mode: str,
                 time_limit: int | None = None, finalize: bool = False, parent=None):
        super().__init__(parent)
        self.ctx, self.attempt_id, self.mode, self.finalize = ctx, attempt_id, mode, finalize
        self._done = False
        self._started = time.monotonic()
        with ctx.db.session() as s:
            exam = s.get(Exam, exam_id)
            tasks = sorted(exam.writing_tasks, key=lambda t: t.task_number)
            self.task_ids = [t.id for t in tasks]
            lay = QVBoxLayout(self)
            top = QHBoxLayout()
            title = QLabel("Expression écrite – 3 tâches")
            title.setObjectName("H2")
            top.addWidget(title, 1)
            self.timer = CountdownTimer(time_limit or ES.time_limit(SECTION_EE))
            self.timer.expired.connect(self._on_timeout)
            top.addWidget(self.timer)
            lay.addLayout(top)
            self.tabs = QTabWidget()
            self.editors = [WritingEditor(t, show_tips=mode == ES.MODE_TRAINING) for t in tasks]
        for i, ed in enumerate(self.editors):
            self.tabs.addTab(ed, f"Tâche {i + 1}")
            ed.changed.connect(lambda i=i: self._retitle(i))
        lay.addWidget(self.tabs, 1)
        nav = QHBoxLayout()
        nav.addWidget(disclaimer_label(
            "Conseil : environ 5 min pour la tâche 1, 10 min pour la tâche 2, "
            "15 min pour la tâche 3. Gardez 2 min pour relire."), 1)
        self.finish_btn = QPushButton("Terminer et faire corriger")
        self.finish_btn.setObjectName("Primary")
        self.finish_btn.clicked.connect(self._confirm_finish)
        nav.addWidget(self.finish_btn)
        lay.addLayout(nav)
        self.timer.start()

    def _retitle(self, i: int) -> None:
        self.tabs.setTabText(i, f"Tâche {i + 1} ({self.editors[i].word_count()} mots)")

    def _confirm_finish(self) -> None:
        empty = [str(i + 1) for i, e in enumerate(self.editors) if not e.text().strip()]
        if empty and QMessageBox.question(
                self, "Terminer", f"Tâche(s) {', '.join(empty)} vide(s) : elles vaudront 0. "
                "Terminer quand même ?") != QMessageBox.Yes:
            return
        self.finish()

    def _on_timeout(self) -> None:
        self.finish()

    def finish(self) -> None:
        if self._done:
            return
        self._done = True
        self.timer.stop()
        spent = time.monotonic() - self._started
        with self.ctx.db.session() as s:
            for ed in self.editors:
                if ed.text().strip():
                    WS.submit(s, ed.task_id, ed.text(), spent / len(self.editors),
                              self.attempt_id)
            self._result = WS.attempt_result(s, self.attempt_id, self.task_ids)
            if self.finalize:
                a = s.get(Attempt, self.attempt_id)
                ES.finish_attempt(s, a, {SECTION_EE: self._result})
        self.finished.emit(self.attempt_id)

    def result(self) -> dict | None:
        return getattr(self, "_result", None)


@register_step(SECTION_EE)
def _ee_step(ctx, attempt_id, exam_id, mode, audio=None):
    return WritingRunner(ctx, attempt_id, exam_id, mode)


class WritingReportView(QTextBrowser):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(420)
        self.setOpenExternalLinks(False)
