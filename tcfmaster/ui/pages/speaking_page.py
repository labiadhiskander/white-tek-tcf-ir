"""Page « Expression orale » : entraînement par tâche ou épreuve complète (10 min)."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QComboBox, QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
                               QMessageBox, QPlainTextEdit, QPushButton, QSplitter,
                               QStackedWidget, QTextBrowser, QVBoxLayout, QWidget)

from tcfmaster.db.models import SECTION_EO, Exam, SpeakingSubmission
from tcfmaster.services import exam_service as ES
from tcfmaster.services import speaking_service as SS
from tcfmaster.ui.speaking import SpeakingRunner
from tcfmaster.ui.speaking_report import oral_html
from tcfmaster.ui.widgets import Card, Page, disclaimer_label


class SpeakingPage(Page):
    def __init__(self, ctx):
        super().__init__(ctx, "Expression orale",
                         "Entretien dirigé (3 min), exercice en interaction (3 min 30), "
                         "opinion argumentée (3 min 30), face à un examinateur simulé.")
        self.stack = QStackedWidget()
        self.body.addWidget(self.stack)
        self.runner: SpeakingRunner | None = None
        self.current_sub: int | None = None

        # --- sélection
        sel = QWidget()
        sl = QVBoxLayout(sel)
        sl.setContentsMargins(0, 0, 0, 0)
        card = Card("Choisir un sujet")
        row = QHBoxLayout()
        self.exam = QComboBox()
        self.task = QComboBox()
        for n, lab in ((1, "Tâche 1 – entretien dirigé"), (2, "Tâche 2 – interaction"),
                       (3, "Tâche 3 – opinion")):
            self.task.addItem(lab, n)
        row.addWidget(self.exam, 3)
        row.addWidget(self.task, 2)
        card.lay.addLayout(row)
        self.device_info = QLabel()
        self.device_info.setWordWrap(True)
        self.device_info.setObjectName("Muted")
        card.lay.addWidget(self.device_info)
        b = QHBoxLayout()
        self.train_btn = QPushButton("S'entraîner sur cette tâche")
        self.train_btn.setObjectName("Primary")
        self.train_btn.clicked.connect(self.start_training)
        self.exam_btn = QPushButton("Épreuve complète : 3 tâches (10 min)")
        self.exam_btn.clicked.connect(self.start_exam)
        b.addWidget(self.train_btn)
        b.addWidget(self.exam_btn)
        b.addStretch(1)
        card.lay.addLayout(b)
        card.lay.addWidget(disclaimer_label(
            "La note est une estimation pédagogique automatique ; ce n'est pas un résultat "
            "officiel de France Éducation international."))
        sl.addWidget(card)
        hist = Card("Mes productions orales")
        split = QSplitter()
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        self.history = QListWidget()
        self.history.currentItemChanged.connect(self._show_history)
        ll.addWidget(self.history, 1)
        self.delete_btn = QPushButton("Supprimer la production et son enregistrement")
        self.delete_btn.clicked.connect(self._delete_selected)
        ll.addWidget(self.delete_btn)
        split.addWidget(left)
        self.history_view = QTextBrowser()
        split.addWidget(self.history_view)
        split.setStretchFactor(1, 2)
        split.setMinimumHeight(340)
        hist.lay.addWidget(split)
        sl.addWidget(hist, 1)
        self.stack.addWidget(sel)
        self.select_view = sel

        # --- rapport
        rep = QWidget()
        rl = QVBoxLayout(rep)
        rl.setContentsMargins(0, 0, 0, 0)
        self.report = QTextBrowser()
        self.report.setMinimumHeight(380)
        rl.addWidget(self.report, 1)
        self.fix_box = QPlainTextEdit()
        self.fix_box.setMaximumHeight(110)
        self.fix_box.setPlaceholderText("Corrigez ici la transcription si la reconnaissance "
                                        "vocale s'est trompée, puis réévaluez.")
        rl.addWidget(self.fix_box)
        rb = QHBoxLayout()
        back = QPushButton("◀ Retour aux sujets")
        back.clicked.connect(self.back)
        self.reeval_btn = QPushButton("Réévaluer avec cette transcription")
        self.reeval_btn.clicked.connect(self._reevaluate)
        self.play_btn = QPushButton("🔊 Réécouter mon enregistrement")
        self.play_btn.clicked.connect(self._play)
        self.del_audio_btn = QPushButton("Supprimer l'enregistrement")
        self.del_audio_btn.clicked.connect(self._delete_audio)
        for w in (back, self.reeval_btn, self.play_btn, self.del_audio_btn):
            rb.addWidget(w)
        rb.addStretch(1)
        rl.addLayout(rb)
        self.stack.addWidget(rep)
        self.report_view = rep

    # -------------------------------------------------------------- état
    def refresh(self) -> None:
        cur = self.exam.currentData()
        self.exam.clear()
        with self.ctx.db.session() as s:
            for e in ES.list_exams(s):
                if e.speaking_tasks:
                    self.exam.addItem(f"{e.code} – {e.title}", e.id)
        self.exam.setCurrentIndex(max(0, self.exam.findData(cur)))
        mic = "✔ micro détecté" if getattr(self.ctx, "recorder", None) else \
            "⚠ micro non détecté (réponses tapées au clavier)"
        stt = "✔ reconnaissance vocale hors ligne" if getattr(self.ctx, "stt", None) else \
            "⚠ modèle de reconnaissance vocale absent (transcription à saisir)"
        self.device_info.setText(f"{mic} · {stt}")
        ok = self.exam.count() > 0
        self.train_btn.setEnabled(ok)
        self.exam_btn.setEnabled(ok)
        self._load_history()

    def _load_history(self) -> None:
        self.history.clear()
        with self.ctx.db.session() as s:
            for w in SS.history(s):
                t = w.task
                code = (t.exam.code if t.exam else t.code or "?") if t else "?"
                mark = " 🎙" if w.audio_path else ""
                it = QListWidgetItem(f"{w.created_at:%d/%m %H:%M} · {code} T"
                                     f"{t.task_number if t else '?'} · {w.note20 or 0:.1f}/20"
                                     f"{mark}")
                it.setData(Qt.UserRole, w.id)
                self.history.addItem(it)
        self.delete_btn.setEnabled(self.history.count() > 0)
        if not self.history.count():
            self.history_view.setHtml("<p>Vos productions orales apparaîtront ici.</p>")

    def _show_history(self, it, _prev=None) -> None:
        if it is None:
            return
        with self.ctx.db.session() as s:
            w = s.get(SpeakingSubmission, it.data(Qt.UserRole))
            if w:
                self.history_view.setHtml(oral_html(w.evaluation or {}, w.transcript,
                                                    dialogue=w.dialogue,
                                                    has_audio=bool(w.audio_path)))

    def _delete_selected(self) -> None:
        it = self.history.currentItem()
        if not it or QMessageBox.question(
                self, "Supprimer", "Supprimer définitivement cette production et son "
                "enregistrement ?") != QMessageBox.Yes:
            return
        with self.ctx.db.session() as s:
            SS.delete_submission(s, it.data(Qt.UserRole))
        self._load_history()

    def _selected_exam(self, s) -> Exam | None:
        return s.get(Exam, self.exam.currentData()) if self.exam.currentData() else None

    # ------------------------------------------------------------ lancement
    def _run(self, runner: SpeakingRunner) -> SpeakingRunner:
        if self.runner is not None:
            self.stack.removeWidget(self.runner)
            self.runner.deleteLater()
        self.runner = runner
        runner.finished.connect(lambda *_: self._show_runner_report())
        self.stack.addWidget(runner)
        self.stack.setCurrentWidget(runner)
        return runner

    def open_task(self, task_id: int) -> SpeakingRunner:
        """Ouvre directement une situation (banque B2 ou examen), depuis la bibliothèque."""
        return self._run(SpeakingRunner(self.ctx, None, [task_id], ES.MODE_TRAINING))

    def start_training(self) -> SpeakingRunner | None:
        with self.ctx.db.session() as s:
            exam = self._selected_exam(s)
            if exam is None:
                return None
            t = next((t for t in exam.speaking_tasks
                      if t.task_number == self.task.currentData()), None)
            if t is None:
                return None
            tid = t.id
        return self._run(SpeakingRunner(self.ctx, None, [tid], ES.MODE_TRAINING))

    def start_exam(self) -> SpeakingRunner | None:
        with self.ctx.db.session() as s:
            exam = self._selected_exam(s)
            if exam is None:
                return None
            ids = [t.id for t in sorted(exam.speaking_tasks, key=lambda t: t.task_number)]
            aid = ES.start_attempt(s, exam.id, [SECTION_EO], ES.MODE_EXAM).id
        return self._run(SpeakingRunner(self.ctx, aid, ids, ES.MODE_EXAM, finalize=True))

    def _show_runner_report(self) -> None:
        r = self.runner
        parts = []
        if r.attempt_id and r.result():
            res = r.result()
            parts.append(f"<h2>Expression orale – note estimée {res['note20']:.1f} / 20 "
                         f"({res['level']})</h2>")
        if getattr(r, "errors", None):
            parts.append("<p style='color:#C0392B'>" + "<br>".join(set(r.errors)) + "</p>")
        with self.ctx.db.session() as s:
            for sid in r.submission_ids:
                w = s.get(SpeakingSubmission, sid)
                t = w.task
                parts.append(oral_html(w.evaluation or {}, w.transcript,
                                       f"Tâche {t.task_number} – {t.title}" if t else "",
                                       w.dialogue, bool(w.audio_path)))
                parts.append("<hr>")
            self.current_sub = r.submission_ids[-1] if r.submission_ids else None
            last = s.get(SpeakingSubmission, self.current_sub) if self.current_sub else None
            self.fix_box.setPlainText(last.transcript if last else "")
        single = len(r.submission_ids) == 1
        for w in (self.fix_box, self.reeval_btn):
            w.setVisible(single)
        self._update_audio_buttons()
        self.report.setHtml("".join(parts))
        self.stack.setCurrentWidget(self.report_view)

    def _update_audio_buttons(self) -> None:
        has = False
        if self.current_sub:
            with self.ctx.db.session() as s:
                w = s.get(SpeakingSubmission, self.current_sub)
                has = bool(w and w.audio_path)
        self.play_btn.setVisible(has)
        self.del_audio_btn.setVisible(has)

    # ------------------------------------------------------------ actions
    def _reevaluate(self) -> None:
        if not self.current_sub:
            return
        with self.ctx.db.session() as s:
            w = s.get(SpeakingSubmission, self.current_sub)
            dialogue = [d for d in (w.dialogue or []) if d.get("who") != "candidat"]
            text = self.fix_box.toPlainText()
            dialogue.append({"who": "candidat", "text": text})
            w = SS.submit(s, w.task_id, text, dialogue=dialogue,
                          stt_confidence=(w.evaluation or {}).get("stt_confidence"),
                          submission_id=w.id)
            t = w.task
            self.report.setHtml(oral_html(w.evaluation, w.transcript,
                                          f"Tâche {t.task_number} – {t.title} (réévaluée)",
                                          w.dialogue, bool(w.audio_path)))

    def _play(self) -> None:
        audio = getattr(self.ctx, "audio", None)
        with self.ctx.db.session() as s:
            w = s.get(SpeakingSubmission, self.current_sub) if self.current_sub else None
            path = w.audio_path if w else None
        if audio is not None and path:
            audio.stop()
            audio.play_file(path)

    def _delete_audio(self) -> None:
        if not self.current_sub:
            return
        with self.ctx.db.session() as s:
            w = s.get(SpeakingSubmission, self.current_sub)
            if w:
                SS.delete_audio_file(w)
        self._update_audio_buttons()

    def back(self) -> None:
        self.stack.setCurrentWidget(self.select_view)
        self.refresh()
