"""Déroulement d'une épreuve QCM (CO ou CE), en mode examen ou entraînement."""
from __future__ import annotations

import time

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (QButtonGroup, QHBoxLayout, QLabel, QMessageBox,
                               QProgressBar, QPushButton, QTextBrowser, QVBoxLayout,
                               QWidget)

from tcfmaster.db.models import SECTION_CO, SECTION_LABELS, Attempt, Question
from tcfmaster.services import exam_service as ES
from tcfmaster.services import settings as S
from tcfmaster.ui.widgets import Card, CountdownTimer, disclaimer_label


class McqRunner(QWidget):
    """Affiche les questions une à une ; émet `finished(attempt_id)`."""
    finished = Signal(int)

    def __init__(self, ctx, attempt_id: int, section: str, question_ids: list[int],
                 mode: str, time_limit: int | None = None, audio=None,
                 finalize: bool = True, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.attempt_id = attempt_id
        self.section = section
        self.qids = question_ids
        self.mode = mode
        self.audio = audio
        self.finalize = finalize
        self.idx = 0
        self.answers: dict[int, str | None] = {}
        self.locked: set[int] = set()
        self.plays: dict[int, int] = {}
        self._q_started = time.monotonic()
        self._done = False
        with ctx.db.session() as s:
            self.immediate = (mode == ES.MODE_TRAINING
                              and S.get(s, "correction_mode") == "immediate")

        lay = QVBoxLayout(self)
        lay.setSpacing(10)
        top = QHBoxLayout()
        self.title = QLabel()
        self.title.setObjectName("H2")
        top.addWidget(self.title, 1)
        mode_lbl = QLabel("Mode examen" if mode == ES.MODE_EXAM else "Mode entraînement")
        mode_lbl.setObjectName("Muted")
        top.addWidget(mode_lbl)
        self.timer = CountdownTimer(time_limit or ES.time_limit(section))
        self.timer.expired.connect(self._on_timeout)
        top.addWidget(self.timer)
        lay.addLayout(top)
        self.progress = QProgressBar()
        self.progress.setRange(0, len(question_ids))
        self.progress.setFormat("%v / %m")
        lay.addWidget(self.progress)

        self.doc_card = Card()
        self.doc_type = QLabel()
        self.doc_type.setObjectName("Muted")
        self.doc_card.lay.addWidget(self.doc_type)
        self.play_btn = QPushButton("▶  Écouter le document")
        self.play_btn.setObjectName("Primary")
        self.play_btn.clicked.connect(self._play)
        self.play_info = QLabel()
        self.play_info.setObjectName("Muted")
        prow = QHBoxLayout()
        prow.addWidget(self.play_btn)
        prow.addWidget(self.play_info, 1)
        self.doc_card.lay.addLayout(prow)
        self.document = QTextBrowser()
        self.document.setMinimumHeight(160)
        self.doc_card.lay.addWidget(self.document)
        lay.addWidget(self.doc_card, 1)

        qcard = Card()
        self.prompt = QLabel()
        self.prompt.setWordWrap(True)
        self.prompt.setObjectName("H2")
        qcard.lay.addWidget(self.prompt)
        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        self.choice_btns: list[QPushButton] = []
        for i in range(4):
            b = QPushButton()
            b.setObjectName("Choice")
            b.setCheckable(True)
            self.group.addButton(b, i)
            qcard.lay.addWidget(b)
            self.choice_btns.append(b)
        self.feedback = QTextBrowser()
        self.feedback.setVisible(False)
        self.feedback.setMinimumHeight(130)
        qcard.lay.addWidget(self.feedback)
        lay.addWidget(qcard)

        nav = QHBoxLayout()
        self.prev_btn = QPushButton("◀ Précédente")
        self.prev_btn.clicked.connect(self.prev)
        self.prev_btn.setVisible(mode == ES.MODE_TRAINING)
        nav.addWidget(self.prev_btn)
        nav.addStretch(1)
        self.check_btn = QPushButton("Vérifier")
        self.check_btn.clicked.connect(self.check)
        self.check_btn.setVisible(self.immediate)
        nav.addWidget(self.check_btn)
        self.next_btn = QPushButton("Valider et continuer ▶")
        self.next_btn.setObjectName("Primary")
        self.next_btn.clicked.connect(self.next)
        nav.addWidget(self.next_btn)
        self.finish_btn = QPushButton("Terminer l'épreuve")
        self.finish_btn.clicked.connect(self._confirm_finish)
        nav.addWidget(self.finish_btn)
        lay.addLayout(nav)
        lay.addWidget(disclaimer_label(
            "Format TCF IRN : 25 questions, 4 propositions, une seule bonne réponse."))
        self._show()
        self.timer.start()

    # ------------------------------------------------------------- helpers
    def _question(self, s) -> Question:
        return s.get(Question, self.qids[self.idx])

    def _show(self) -> None:
        with self.ctx.db.session() as s:
            q = self._question(s)
            self.title.setText(f"{SECTION_LABELS[self.section]} – question "
                               f"{self.idx + 1} / {len(self.qids)}  ·  {q.level}")
            self.doc_type.setText(q.doc_type.capitalize())
            is_co = self.section == SECTION_CO
            self.play_btn.setVisible(is_co)
            self.play_info.setVisible(is_co)
            reveal = (not is_co) or (self.mode == ES.MODE_TRAINING and q.id in self.locked)
            if reveal:
                self.document.setPlainText(q.document if not is_co
                                           else "Transcription :\n\n" + q.document)
            else:
                self.document.setPlainText(
                    "Écoutez le document. La transcription sera affichée dans la correction.")
            self._update_play_info(q.id)
            self.prompt.setText(q.prompt)
            chosen = self.answers.get(q.id)
            self.group.setExclusive(False)
            for b, c in zip(self.choice_btns, q.choices):
                b.setText(f"{c.label}.  {c.text}")
                b.setProperty("label", c.label)
                b.setChecked(c.label == chosen)
                b.setObjectName("Choice")
                b.setEnabled(q.id not in self.locked)
                b.style().unpolish(b); b.style().polish(b)
            self.group.setExclusive(True)
            self.feedback.setVisible(False)
            if q.id in self.locked:
                self._render_feedback(q)
        self.progress.setValue(len([a for a in self.answers.values() if a]))
        self.prev_btn.setEnabled(self.idx > 0)
        last = self.idx == len(self.qids) - 1
        self.next_btn.setText("Valider et terminer" if last else "Valider et continuer ▶")
        self._q_started = time.monotonic()

    def _update_play_info(self, qid: int) -> None:
        n = self.plays.get(qid, 0)
        if self.mode == ES.MODE_EXAM:
            self.play_btn.setEnabled(n == 0)
            self.play_info.setText("Une seule écoute en mode examen." if n == 0
                                   else "Document déjà écouté.")
        else:
            self.play_btn.setEnabled(True)
            self.play_info.setText(f"Réécoute autorisée (écoutes : {n}).")

    def _play(self) -> None:
        qid = self.qids[self.idx]
        if self.mode == ES.MODE_EXAM and self.plays.get(qid, 0) >= 1:
            return
        self.plays[qid] = self.plays.get(qid, 0) + 1
        if self.audio is not None:
            with self.ctx.db.session() as s:
                self.audio.play_question(self._question(s))
        self._update_play_info(qid)

    def selected_label(self) -> str | None:
        b = self.group.checkedButton()
        return b.property("label") if b else None

    def select(self, label: str) -> None:
        for b in self.choice_btns:
            if b.property("label") == label:
                b.setChecked(True)

    def _save_current(self) -> None:
        qid = self.qids[self.idx]
        if qid in self.locked:
            return
        label = self.selected_label()
        self.answers[qid] = label
        with self.ctx.db.session() as s:
            a = s.get(Attempt, self.attempt_id)
            ES.record_answer(s, a, s.get(Question, qid), label,
                             time.monotonic() - self._q_started)

    def _render_feedback(self, q: Question) -> None:
        chosen = self.answers.get(q.id)
        right = q.correct_choice.label
        for b in self.choice_btns:
            lbl = b.property("label")
            if lbl == right:
                b.setObjectName("ChoiceRight")
            elif lbl == chosen:
                b.setObjectName("ChoiceWrong")
            b.style().unpolish(b); b.style().polish(b)
        ok = chosen == right
        html = [f"<b>{'✔ Bonne réponse' if ok else '✘ Réponse incorrecte'}</b> – "
                f"la bonne réponse est <b>{right}</b>.<br><br>{q.explanation}<br><ul>"]
        for c in q.choices:
            if c.rationale:
                html.append(f"<li><b>{c.label}</b> : {c.rationale}</li>")
        html.append("</ul>")
        self.feedback.setHtml("".join(html))
        self.feedback.setVisible(True)

    # ------------------------------------------------------------- actions
    def check(self) -> None:
        if self.selected_label() is None:
            return
        self._save_current()
        qid = self.qids[self.idx]
        self.locked.add(qid)
        self._show()

    def next(self) -> None:
        self._save_current()
        if self.idx < len(self.qids) - 1:
            self.idx += 1
            self._show()
        else:
            self.finish()

    def prev(self) -> None:
        if self.mode != ES.MODE_TRAINING or self.idx == 0:
            return
        self._save_current()
        self.idx -= 1
        self._show()

    def _confirm_finish(self) -> None:
        unanswered = len(self.qids) - len([a for a in self.answers.values() if a])
        if unanswered and QMessageBox.question(
                self, "Terminer", f"{unanswered} question(s) sans réponse. Terminer quand même ?"
        ) != QMessageBox.Yes:
            return
        self._save_current()
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
        if self.finalize:
            with self.ctx.db.session() as s:
                a = s.get(Attempt, self.attempt_id)
                if a.finished_at is None:
                    ES.finish_attempt(s, a)
        self.finished.emit(self.attempt_id)
