"""Enchaînement des épreuves d'un examen blanc (CO → CE → EE → EO).

Chaque épreuve est un widget fourni par une « fabrique » enregistrée dans
`STEP_FACTORIES`. Une fabrique reçoit (ctx, attempt_id, exam_id, mode) et renvoie
un widget qui émet `finished(int)` et expose éventuellement `result()` pour
les épreuves d'expression (note sur 20).
"""
from __future__ import annotations

from typing import Callable

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (QLabel, QPushButton, QStackedWidget, QVBoxLayout, QWidget)

from tcfmaster.db.models import SECTION_DURATIONS_S, SECTION_LABELS, Attempt, Exam
from tcfmaster.services import exam_service as ES
from tcfmaster.ui.mcq_runner import McqRunner
from tcfmaster.ui.widgets import Card, fmt_seconds

StepFactory = Callable[..., QWidget]
STEP_FACTORIES: dict[str, StepFactory] = {}


def register_step(section: str):
    def deco(fn):
        STEP_FACTORIES[section] = fn
        return fn
    return deco


def _mcq_factory(section):
    def make(ctx, attempt_id, exam_id, mode, audio=None):
        with ctx.db.session() as s:
            exam = s.get(Exam, exam_id)
            qids = [q.id for q in exam.questions_for(section)]
        return McqRunner(ctx, attempt_id, section, qids, mode, audio=audio, finalize=False)
    return make


STEP_FACTORIES["CO"] = _mcq_factory("CO")
STEP_FACTORIES["CE"] = _mcq_factory("CE")


class ExamSession(QWidget):
    finished = Signal(int)

    def __init__(self, ctx, exam_id: int, sections: list[str], mode: str, audio=None,
                 parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.exam_id = exam_id
        self.sections = [s for s in sections if s in STEP_FACTORIES]
        self.mode = mode
        self.audio = audio
        self.extra: dict = {}
        self.step = -1
        with ctx.db.session() as s:
            self.attempt_id = ES.start_attempt(s, exam_id, self.sections, mode).id
            self.exam_title = s.get(Exam, exam_id).title
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.stack = QStackedWidget()
        lay.addWidget(self.stack)
        self._intro()

    def _intro(self) -> None:
        self.step += 1
        if self.step >= len(self.sections):
            self._finish()
            return
        sec = self.sections[self.step]
        card = Card(f"{self.exam_title} – épreuve {self.step + 1}/{len(self.sections)}")
        info = {
            "CO": "25 questions · 4 propositions · une seule bonne réponse. "
                  + ("Chaque document ne peut être écouté qu'une fois."
                     if self.mode == ES.MODE_EXAM else "Réécoute autorisée."),
            "CE": "25 questions · 4 propositions · une seule bonne réponse.",
            "EE": "3 tâches : 30–60 mots, 40–90 mots, 40–90 mots.",
            "EO": "3 tâches : entretien dirigé (3 min), interaction (3 min 30), "
                  "opinion (3 min 30).",
        }[sec]
        t = QLabel(f"<h2>{SECTION_LABELS[sec]}</h2><p>Durée : "
                   f"{fmt_seconds(SECTION_DURATIONS_S[sec])} min</p><p>{info}</p>")
        t.setWordWrap(True)
        card.lay.addWidget(t)
        go = QPushButton("Commencer l'épreuve")
        go.setObjectName("Primary")
        go.clicked.connect(lambda: self._start_step(sec))
        card.lay.addWidget(go)
        self.intro_button = go
        self.stack.addWidget(card)
        self.stack.setCurrentWidget(card)

    def _start_step(self, sec: str) -> None:
        w = STEP_FACTORIES[sec](self.ctx, self.attempt_id, self.exam_id, self.mode,
                               audio=self.audio)
        w.finished.connect(lambda *_: self._step_done(sec, w))
        self.current = w
        self.stack.addWidget(w)
        self.stack.setCurrentWidget(w)

    def _step_done(self, sec: str, w) -> None:
        if hasattr(w, "result"):
            r = w.result()
            if r:
                self.extra[sec] = r
        self._intro()

    def _finish(self) -> None:
        with self.ctx.db.session() as s:
            a = s.get(Attempt, self.attempt_id)
            ES.finish_attempt(s, a, self.extra)
        self.finished.emit(self.attempt_id)
