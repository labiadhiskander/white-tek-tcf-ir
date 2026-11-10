"""Page « Conversation avec l'IA » : professeur, conversation libre, examinateur."""
from __future__ import annotations

import html
import time
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (QButtonGroup, QComboBox, QHBoxLayout, QLabel, QMessageBox,
                               QPlainTextEdit, QPushButton, QRadioButton, QTextBrowser)

from tcfmaster.services.ai.base import (MODE_EXAMINER, MODE_LABELS, MODE_TEACHER, MODES,
                                        TutorReply)
from tcfmaster.services.ai.tutor import PRIVACY_NOTICE
from tcfmaster.ui.ai_settings import tutor_service
from tcfmaster.ui.speaking import analyse_recording, run_background
from tcfmaster.ui.speaking_report import oral_html
from tcfmaster.ui.widgets import Card, Page, disclaimer_label

TUTOR_BG, LEARNER_BG, NOTICE = "#EEF3FB", "#E9F7EF", "#B9770E"


def _bubble(who: str, text: str, bg: str, align: str = "left") -> str:
    body = html.escape(text).replace("\n", "<br>")
    return (f"<table width='100%' cellpadding=8 style='margin:4px 0'><tr><td align='{align}'>"
            f"<div style='background:{bg};'><b>{html.escape(who)}</b><br>{body}</div>"
            f"</td></tr></table>")


class TutorPage(Page):
    def __init__(self, ctx):
        super().__init__(ctx, "Conversation avec l'IA",
                         "Un professeur qui corrige et explique, un partenaire de conversation "
                         "et un examinateur pour simuler l'épreuve orale.")
        self.conv = None
        self._busy = False
        self._recording_path: Path | None = None
        self._html: list[str] = []

        top = Card("Choisir un mode")
        self.mode_group = QButtonGroup(self)
        for i, m in enumerate(MODES):
            rb = QRadioButton(MODE_LABELS[m])
            rb.setProperty("mode", m)
            self.mode_group.addButton(rb, i)
            top.lay.addWidget(rb)
        self.mode_group.button(0).setChecked(True)
        self.mode_group.idToggled.connect(lambda *_: self._mode_changed())
        row = QHBoxLayout()
        self.task = QComboBox()
        self.task.addItem("Tâche au hasard", None)
        for n, lab in ((1, "Tâche 1 – entretien dirigé"), (2, "Tâche 2 – interaction"),
                       (3, "Tâche 3 – opinion")):
            self.task.addItem(lab, n)
        row.addWidget(self.task)
        self.new_btn = QPushButton("Nouvelle conversation")
        self.new_btn.setObjectName("Primary")
        self.new_btn.clicked.connect(self.new_conversation)
        row.addWidget(self.new_btn)
        row.addStretch(1)
        top.lay.addLayout(row)
        self.status = QLabel()
        self.status.setObjectName("Muted")
        self.status.setWordWrap(True)
        top.lay.addWidget(self.status)
        self.body.addWidget(top)

        chat = Card()
        self.chat = QTextBrowser()
        self.chat.setOpenExternalLinks(False)
        self.chat.setMinimumHeight(360)
        chat.lay.addWidget(self.chat, 1)
        self.notice = QLabel()
        self.notice.setWordWrap(True)
        self.notice.setStyleSheet(f"color:{NOTICE}")
        self.notice.hide()
        chat.lay.addWidget(self.notice)
        self.input = QPlainTextEdit()
        self.input.setMaximumHeight(110)
        self.input.setPlaceholderText("Écrivez votre message… (Ctrl+Entrée pour envoyer)")
        chat.lay.addWidget(self.input)
        b = QHBoxLayout()
        self.send_btn = QPushButton("Envoyer")
        self.send_btn.setObjectName("Primary")
        self.send_btn.clicked.connect(self.send)
        self.dictate_btn = QPushButton("🎤 Dicter")
        self.dictate_btn.setCheckable(True)
        self.dictate_btn.toggled.connect(self._dictate)
        self.listen_btn = QPushButton("🔊 Écouter la réponse")
        self.listen_btn.clicked.connect(self._listen)
        self.finish_btn = QPushButton("Terminer et évaluer")
        self.finish_btn.clicked.connect(self.finish)
        for w in (self.send_btn, self.dictate_btn, self.listen_btn, self.finish_btn):
            b.addWidget(w)
        b.addStretch(1)
        chat.lay.addLayout(b)
        chat.lay.addWidget(disclaimer_label(
            "Les corrections et notes du tuteur sont des estimations pédagogiques ; elles ne "
            "sont pas des résultats officiels de France Éducation international."))
        self.body.addWidget(chat, 1)
        QShortcut(QKeySequence("Ctrl+Return"), self.input, activated=self.send)
        self._last_tutor_text = ""
        self._mode_changed()

    # ---------------------------------------------------------------- état
    def mode(self) -> str:
        return self.mode_group.checkedButton().property("mode")

    def set_mode(self, mode: str) -> None:
        for btn in self.mode_group.buttons():
            if btn.property("mode") == mode:
                btn.setChecked(True)

    def _mode_changed(self) -> None:
        self.task.setVisible(self.mode() == MODE_EXAMINER)

    def refresh(self) -> None:
        svc = tutor_service(self.ctx)
        self.status.setText("Moteur : " + svc.status())
        has_mic = bool(getattr(self.ctx, "recorder", None)) and bool(getattr(self.ctx, "stt",
                                                                             None))
        self.dictate_btn.setVisible(has_mic)
        self.listen_btn.setVisible(getattr(self.ctx, "audio", None) is not None)
        self._update_buttons()

    def _update_buttons(self) -> None:
        active = self.conv is not None and not self.conv.state.get("ended")
        self.send_btn.setEnabled(active and not self._busy)
        self.input.setEnabled(active)
        self.finish_btn.setVisible(self.conv is not None and self.conv.mode == MODE_EXAMINER)
        self.finish_btn.setEnabled(active and not self._busy and bool(
            self.conv and self.conv.learner_texts()))
        self.new_btn.setEnabled(not self._busy)
        self.listen_btn.setEnabled(bool(self._last_tutor_text))

    def _append(self, fragment: str) -> None:
        self._html.append(fragment)
        self.chat.setHtml("".join(self._html))
        sb = self.chat.verticalScrollBar()
        sb.setValue(sb.maximum())

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        if busy:
            self.status.setText("Le tuteur réfléchit…")
        else:
            self.status.setText("Moteur : " + tutor_service(self.ctx).status())
        self._update_buttons()

    def _check_consent(self) -> bool:
        svc = tutor_service(self.ctx)
        if not svc.needs_consent():
            return True
        res = QMessageBox.question(
            self, "Confidentialité", PRIVACY_NOTICE + "\n\nUtiliser Claude (en ligne) ? "
            "Si vous refusez, le tuteur hors ligne répondra.")
        if res == QMessageBox.Yes:
            svc.give_consent()
        return res == QMessageBox.Yes

    # ---------------------------------------------------------------- actions
    def new_conversation(self) -> None:
        svc = tutor_service(self.ctx)
        try:
            self.conv = svc.new_conversation(self.mode(), self.task.currentData())
        except RuntimeError as exc:
            QMessageBox.warning(self, "Tuteur IA", str(exc))
            return
        self._html = []
        self._last_tutor_text = ""
        self.notice.hide()
        self._check_consent()
        conv = self.conv
        self._set_busy(True)
        run_background(self, lambda: svc.opening(conv), lambda r: self._on_reply(conv, r))

    def send(self) -> None:
        text = self.input.toPlainText().strip()
        if not text or self.conv is None or self._busy or self.conv.state.get("ended"):
            return
        self.input.clear()
        self._append(_bubble("Vous", text, LEARNER_BG, "right"))
        conv, svc = self.conv, tutor_service(self.ctx)
        self._set_busy(True)
        run_background(self, lambda: svc.send(conv, text), lambda r: self._on_reply(conv, r))

    def finish(self) -> None:
        if self.conv is None or self.conv.mode != MODE_EXAMINER or self._busy:
            return
        conv, svc = self.conv, tutor_service(self.ctx)
        self._set_busy(True)
        run_background(self, lambda: svc.finish_exam(conv), lambda r: self._on_reply(conv, r))

    def _on_reply(self, conv, r) -> None:
        if conv is not self.conv:          # réponse d'une conversation abandonnée
            return
        self._set_busy(False)
        if isinstance(r, Exception):
            self.notice.setText(f"Erreur : {r}")
            self.notice.show()
            return
        assert isinstance(r, TutorReply)
        who = "Examinateur" if conv.mode == MODE_EXAMINER else (
            "Professeur" if conv.mode == MODE_TEACHER else "Partenaire")
        self._append(_bubble(f"{who} · {r.engine}", r.text, TUTOR_BG))
        if r.evaluation:
            t = conv.task or {}
            self._append(oral_html(r.evaluation, " ".join(conv.learner_texts()),
                                   f"Tâche {t.get('task_number')} – {t.get('title')}",
                                   [{"who": "examinateur" if x.role == "tuteur" else "candidat",
                                     "text": x.text} for x in conv.turns[:-1]]))
        self._last_tutor_text = r.text
        if r.notice:
            self.notice.setText("⚠ " + r.notice)
            self.notice.show()
        else:
            self.notice.hide()
        self._update_buttons()
        if conv.mode == MODE_EXAMINER and not r.evaluation:     # l'examinateur parle
            self._listen()

    def _listen(self) -> None:
        audio = getattr(self.ctx, "audio", None)
        if audio is None or not self._last_tutor_text:
            return
        text = self._last_tutor_text.split("\n\n")[-1]
        for prefix in ("Examinateur :", "Agent immobilier :"):
            text = text.replace(prefix, "")
        audio.play_text(f"F: {text.strip()}")

    def _dictate(self, on: bool) -> None:
        rec = getattr(self.ctx, "recorder", None)
        if rec is None:
            return
        if on:
            self._recording_path = (Path(self.ctx.paths.recordings)
                                    / f"dictee_{time.strftime('%Y%m%d_%H%M%S')}.wav")
            try:
                rec.start(self._recording_path)
            except Exception as exc:
                self.dictate_btn.setChecked(False)
                QMessageBox.warning(self, "Micro", str(exc))
                return
            self.dictate_btn.setText("⏹ Arrêter la dictée")
            return
        self.dictate_btn.setText("🎤 Dicter")
        rec.stop()
        path, self._recording_path = self._recording_path, None
        stt = getattr(self.ctx, "stt", None)
        run_background(self, lambda: analyse_recording(stt, str(path), ""),
                       lambda res: self._dictated(path, res))

    def _dictated(self, path: Path | None, res) -> None:
        if path is not None:                 # la dictée n'est jamais conservée
            Path(path).unlink(missing_ok=True)
        if isinstance(res, Exception) or res.get("stt_error"):
            msg = res if isinstance(res, Exception) else res["stt_error"]
            QMessageBox.warning(self, "Dictée", str(msg))
            return
        cur = self.input.toPlainText().strip()
        self.input.setPlainText((cur + " " if cur else "") + res["transcript"])
        self.input.setFocus(Qt.OtherFocusReason)
