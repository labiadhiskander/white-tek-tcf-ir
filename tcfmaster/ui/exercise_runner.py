"""Déroulement d'une série d'exercices de collection (CO ou CE B2).

  * Mode entraînement : l'utilisateur répond, valide, et la correction détaillée
    de l'exercice s'affiche immédiatement (bonne réponse, justification,
    explication de chaque proposition, transcription, vocabulaire, pièges).
  * Mode examen : aucune correction pendant l'épreuve, une seule écoute en CO,
    chronomètre proportionnel au format officiel ; les corrections détaillées
    et les conseils s'affichent à la fin.
"""
from __future__ import annotations

import time

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (QButtonGroup, QHBoxLayout, QLabel, QMessageBox, QPushButton,
                               QRadioButton, QTextBrowser, QVBoxLayout, QWidget)

from tcfmaster.db.models import SECTION_CO, SECTION_LABELS, Attempt, Exercise, Question
from tcfmaster.services import collections as COL
from tcfmaster.services import correction as C
from tcfmaster.services import exam_service as ES
from tcfmaster.ui import correction_view as CV
from tcfmaster.ui.widgets import Card, CountdownTimer, disclaimer_label


class ExerciseRunner(QWidget):
    finished = Signal(int)

    def __init__(self, ctx, attempt_id: int, exercise_ids: list[int], mode: str,
                 audio=None, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.attempt_id = attempt_id
        self.ex_ids = list(exercise_ids)
        self.mode = mode
        self.audio = audio
        self.idx = 0
        self.locked: set[int] = set()          # exercices corrigés (entraînement)
        self.plays: dict[int, int] = {}
        self.answers: dict[int, str | None] = {}
        self._done = False
        self._t0 = time.monotonic()
        with ctx.db.session() as s:
            first = s.get(Exercise, self.ex_ids[0])
            self.section = first.section
            nq = len(COL.question_ids(s, self.ex_ids))

        lay = QVBoxLayout(self)
        lay.setSpacing(10)
        top = QHBoxLayout()
        self.title = QLabel()
        self.title.setObjectName("H2")
        self.title.setWordWrap(True)
        top.addWidget(self.title, 1)
        lbl = QLabel("Mode examen" if mode == ES.MODE_EXAM else "Mode entraînement")
        lbl.setObjectName("Muted")
        top.addWidget(lbl)
        self.timer = CountdownTimer(COL.time_limit(self.section, nq))
        self.timer.expired.connect(self._on_timeout)
        top.addWidget(self.timer)
        lay.addLayout(top)

        doc = Card()
        self.doc_type = QLabel()
        self.doc_type.setObjectName("Muted")
        self.doc_type.setWordWrap(True)
        doc.lay.addWidget(self.doc_type)
        prow = QHBoxLayout()
        self.play_btn = QPushButton("▶  Écouter l'enregistrement")
        self.play_btn.setObjectName("Primary")
        self.play_btn.clicked.connect(self._play)
        self.play_info = QLabel()
        self.play_info.setObjectName("Muted")
        prow.addWidget(self.play_btn)
        prow.addWidget(self.play_info, 1)
        doc.lay.addLayout(prow)
        self.document = QTextBrowser()
        self.document.setMinimumHeight(240)
        doc.lay.addWidget(self.document)
        lay.addWidget(doc)

        self.qcard = Card("Questions")
        self.qbox = QVBoxLayout()
        self.qcard.lay.addLayout(self.qbox)
        lay.addWidget(self.qcard)
        self.groups: list[tuple[int, QButtonGroup, list[QRadioButton]]] = []

        self.feedback = QTextBrowser()
        self.feedback.setMinimumHeight(420)
        self.feedback.setVisible(False)
        lay.addWidget(self.feedback)

        nav = QHBoxLayout()
        self.check_btn = QPushButton("Valider mes réponses")
        self.check_btn.setObjectName("Primary")
        self.check_btn.clicked.connect(self.check)
        self.check_btn.setVisible(mode == ES.MODE_TRAINING)
        self.next_btn = QPushButton("Exercice suivant ▶")
        self.next_btn.clicked.connect(self.next)
        self.finish_btn = QPushButton("Terminer la série")
        self.finish_btn.clicked.connect(self._confirm_finish)
        nav.addStretch(1)
        nav.addWidget(self.check_btn)
        nav.addWidget(self.next_btn)
        nav.addWidget(self.finish_btn)
        lay.addLayout(nav)
        lay.addWidget(disclaimer_label(
            "Quatre propositions, une seule bonne réponse. Les résultats sont des estimations "
            "pédagogiques, jamais des résultats officiels du TCF."))
        self._show()
        self.timer.start()

    # ------------------------------------------------------------ affichage
    @property
    def current_id(self) -> int:
        return self.ex_ids[self.idx]

    def _clear_questions(self) -> None:
        while self.qbox.count():
            it = self.qbox.takeAt(0)
            w = it.widget()
            if w is not None:
                w.hide()                 # sinon l'ancien texte reste visible jusqu'à sa destruction
                w.setParent(None)
                w.deleteLater()
        self.groups = []

    def _show(self) -> None:
        self._clear_questions()
        with self.ctx.db.session() as s:
            ex = s.get(Exercise, self.current_id)
            locked = ex.id in self.locked
            self.title.setText(f"{SECTION_LABELS[self.section]} B2 – exercice {self.idx + 1} / "
                               f"{len(self.ex_ids)} · {ex.title}")
            self.doc_type.setText(f"{ex.doc_type.capitalize()}"
                                  + (f" — {ex.context}" if ex.context else ""))
            is_co = ex.section == SECTION_CO
            self.play_btn.setVisible(is_co)
            self.play_info.setVisible(is_co)
            if not is_co:
                self.document.setPlainText(ex.document)
            elif locked:
                self.document.setPlainText("Transcription :\n\n" + ex.document)
            else:
                self.document.setPlainText(
                    "Écoutez l'enregistrement. La transcription sera accessible après "
                    "l'exercice, dans la correction.")
            self._update_play_info()
            for n, q in enumerate(ex.questions, 1):
                lbl = QLabel(f"{n}. {q.prompt}")
                lbl.setWordWrap(True)
                lbl.setObjectName("H3")
                self.qbox.addWidget(lbl)
                grp = QButtonGroup(self)
                btns = []
                for c in q.choices:
                    rb = QRadioButton(f"{c.label}.  {c.text}")
                    rb.setMinimumHeight(26)
                    rb.setProperty("label", c.label)
                    rb.setChecked(self.answers.get(q.id) == c.label)
                    rb.setEnabled(not locked)
                    grp.addButton(rb)
                    self.qbox.addWidget(rb)
                    btns.append(rb)
                self.groups.append((q.id, grp, btns))
            if locked:
                self._render_feedback(s, ex)
            else:
                self.feedback.setVisible(False)
        last = self.idx == len(self.ex_ids) - 1
        self.next_btn.setText("Terminer et voir les résultats" if last else "Exercice suivant ▶")
        self.check_btn.setEnabled(not locked)
        self._t0 = time.monotonic()

    def _update_play_info(self) -> None:
        n = self.plays.get(self.current_id, 0)
        if self.mode == ES.MODE_EXAM:
            self.play_btn.setEnabled(n == 0)
            self.play_info.setText("Une seule écoute en mode examen." if n == 0
                                   else "Enregistrement déjà écouté.")
        else:
            self.play_btn.setEnabled(True)
            self.play_info.setText(f"Réécoute autorisée (écoutes : {n}).")

    def _play(self) -> None:
        if self.mode == ES.MODE_EXAM and self.plays.get(self.current_id, 0) >= 1:
            return
        self.plays[self.current_id] = self.plays.get(self.current_id, 0) + 1
        if self.audio is not None:
            with self.ctx.db.session() as s:
                ex = s.get(Exercise, self.current_id)
                self.audio.play_text(ex.document, ex.speakers, ex.audio_file)
        self._update_play_info()

    def _render_feedback(self, s, ex: Exercise) -> None:
        corr = C.correct_exercise(ex, {qid: self.answers.get(qid) for qid, _, _ in self.groups})
        for (qid, _grp, btns), qc in zip(self.groups, corr.questions):
            for b in btns:
                lbl = b.property("label")
                if lbl == qc.correct_answer:
                    b.setText(b.text().split("  ✔")[0] + "  ✔")
                elif lbl == qc.user_answer:
                    b.setText(b.text().split("  ✘")[0] + "  ✘")
        self.feedback.setHtml(CV.exercise_html(corr, show_document=ex.section == SECTION_CO))
        self.feedback.setVisible(True)

    # ------------------------------------------------------------- réponses
    def selected(self) -> dict[int, str | None]:
        out = {}
        for qid, grp, _ in self.groups:
            b = grp.checkedButton()
            out[qid] = b.property("label") if b else None
        return out

    def select(self, position: int, label: str) -> None:
        """Coche une proposition (1re question = position 1) ; utilisé par les tests."""
        _qid, _grp, btns = self.groups[position - 1]
        for b in btns:
            if b.property("label") == label:
                b.setChecked(True)

    def _save_current(self) -> None:
        if self.current_id in self.locked:
            return
        spent = (time.monotonic() - self._t0) / max(1, len(self.groups))
        with self.ctx.db.session() as s:
            a = s.get(Attempt, self.attempt_id)
            for qid, label in self.selected().items():
                self.answers[qid] = label
                COL.record(s, a, s.get(Question, qid), label, spent)

    # ------------------------------------------------------------- actions
    def check(self) -> None:
        if self.mode != ES.MODE_TRAINING or self.current_id in self.locked:
            return
        self._save_current()
        self.locked.add(self.current_id)
        self._show()

    def next(self) -> None:
        self._save_current()
        if self.audio is not None:
            self.audio.stop()
        if self.idx < len(self.ex_ids) - 1:
            self.idx += 1
            self._show()
        else:
            self.finish()

    def _confirm_finish(self) -> None:
        self._save_current()
        with self.ctx.db.session() as s:
            total = len(COL.question_ids(s, self.ex_ids))
        missing = total - len([v for v in self.answers.values() if v])
        if missing and QMessageBox.question(
                self, "Terminer", f"{missing} question(s) sans réponse. Terminer quand même ?"
        ) != QMessageBox.Yes:
            return
        self.finish()

    def _on_timeout(self) -> None:
        if not self._done:
            self._save_current()
            self.finish()

    def finish(self) -> None:
        if self._done:
            return
        self._done = True
        self.timer.stop()
        if self.audio is not None:
            self.audio.stop()
        with self.ctx.db.session() as s:
            COL.finish_series(s, s.get(Attempt, self.attempt_id))
        self.finished.emit(self.attempt_id)
