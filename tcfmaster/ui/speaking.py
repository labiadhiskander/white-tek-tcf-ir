"""Épreuve d'expression orale : examinateur simulé, enregistrement, transcription."""
from __future__ import annotations

import time
from pathlib import Path

from PySide6.QtCore import QThread, QTimer, Signal
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QMessageBox, QPlainTextEdit, QProgressBar,
                               QPushButton, QStackedWidget, QVBoxLayout, QWidget)

from tcfmaster.db.models import SECTION_EO, Attempt, Exam, SpeakingTask
from tcfmaster.services import exam_service as ES
from tcfmaster.services import speaking_service as SS
from tcfmaster.services.recorder import RecorderUnavailable, recording_path, speech_profile
from tcfmaster.ui.exam_session import register_step
from tcfmaster.ui.widgets import Card, CountdownTimer, disclaimer_label

RUN_SYNC = False          # les tests exécutent la transcription sans fil séparé


class _Job(QThread):
    done = Signal(object)

    def __init__(self, fn):
        super().__init__()
        self.fn = fn

    def run(self) -> None:
        try:
            self.done.emit(self.fn())
        except Exception as exc:          # remonté à l'interface, détail au journal
            self.done.emit(exc)


def run_background(owner, fn, callback) -> None:
    if RUN_SYNC:
        try:
            callback(fn())
        except Exception as exc:
            callback(exc)
        return
    job = _Job(fn)
    job.done.connect(callback)
    job.finished.connect(job.deleteLater)
    owner._jobs = [j for j in getattr(owner, "_jobs", []) if j.isRunning()] + [job]
    job.start()


def analyse_recording(stt, audio_path: str | None, manual_text: str) -> dict:
    """Transcription + profil sonore (exécuté hors du fil de l'interface)."""
    out = {"transcript": manual_text.strip(), "confidence": None, "profile": None,
           "stt_error": None}
    if audio_path and Path(audio_path).is_file():
        out["profile"] = speech_profile(Path(audio_path))
        if stt is not None and not out["transcript"]:
            try:
                tr = stt.transcribe(Path(audio_path))
                out["transcript"], out["confidence"] = tr.text, tr.confidence
            except Exception as exc:
                out["stt_error"] = str(exc)
        elif stt is None and not out["transcript"]:
            out["stt_error"] = ("Reconnaissance vocale indisponible (modèle français non "
                                "installé) : saisissez ce que vous avez dit.")
    return out


# =========================================================================
class SpeakingTaskWidget(QWidget):
    """Une tâche : consigne, relances de l'examinateur, enregistrement chronométré."""
    recorded = Signal(dict)

    def __init__(self, ctx, task: SpeakingTask, mode: str, parent=None):
        super().__init__(parent)
        self.ctx, self.mode = ctx, mode
        self.task_id, self.task_number = task.id, task.task_number
        self.duration = task.duration_s
        self.prompts = list(task.examiner_prompts or [])
        self.prompt_idx = -1
        self.dialogue: list[dict] = []
        self.audio_path: Path | None = None
        self._t0 = 0.0
        self._state = "idle"
        self.recorder = getattr(ctx, "recorder", None)
        training = mode == ES.MODE_TRAINING

        lay = QVBoxLayout(self)
        card = Card(f"Tâche {task.task_number} – {task.title}")
        sc = QLabel(task.scenario)
        sc.setWordWrap(True)
        card.lay.addWidget(sc)
        role = QLabel(f"Rôle de l'examinateur : {task.examiner_role} · durée "
                      f"{task.duration_s // 60} min {task.duration_s % 60:02d} s")
        role.setObjectName("Muted")
        card.lay.addWidget(role)
        if training and task.useful_phrases:
            ph = QLabel("💡 Phrases utiles : " + " · ".join(task.useful_phrases))
            ph.setWordWrap(True)
            ph.setObjectName("Muted")
            card.lay.addWidget(ph)
        lay.addWidget(card)

        ex = Card("L'examinateur")
        self.prompt_lbl = QLabel("Appuyez sur « Commencer » : l'examinateur vous posera la "
                                 "première question.")
        self.prompt_lbl.setWordWrap(True)
        self.prompt_lbl.setObjectName("H2")
        ex.lay.addWidget(self.prompt_lbl)
        prow = QHBoxLayout()
        self.repeat_btn = QPushButton("🔊 Réécouter")
        self.repeat_btn.clicked.connect(self._speak_current)
        self.repeat_btn.setVisible(training)
        self.next_btn = QPushButton("Question suivante ▶")
        self.next_btn.clicked.connect(self.next_prompt)
        self.next_btn.setEnabled(False)
        prow.addWidget(self.repeat_btn)
        prow.addWidget(self.next_btn)
        prow.addStretch(1)
        ex.lay.addLayout(prow)
        lay.addWidget(ex)

        rec = QHBoxLayout()
        self.rec_btn = QPushButton("● Commencer")
        self.rec_btn.setObjectName("Primary")
        self.rec_btn.clicked.connect(self.toggle)
        rec.addWidget(self.rec_btn)
        self.meter = QProgressBar()
        self.meter.setRange(0, 100)
        self.meter.setTextVisible(False)
        self.meter.setMaximumWidth(200)
        rec.addWidget(self.meter)
        self.rec_info = QLabel()
        self.rec_info.setObjectName("Muted")
        rec.addWidget(self.rec_info, 1)
        self.timer = CountdownTimer(self.duration, low_threshold=30)
        self.timer.expired.connect(self.stop)
        rec.addWidget(self.timer)
        lay.addLayout(rec)

        self.manual = QPlainTextEdit()
        self.manual.setPlaceholderText(
            "Transcription manuelle : si le micro ou la reconnaissance vocale ne sont pas "
            "disponibles, tapez ici ce que vous dites (ou diriez).")
        self.manual.setMaximumHeight(110)
        self.manual.setVisible(self.recorder is None or training)
        lay.addWidget(self.manual)
        lay.addStretch(1)
        if self.recorder is None:
            self.rec_info.setText("⚠ Micro indisponible : la tâche se fait par écrit.")
        else:
            self.rec_info.setText("Conseil : utilisez un casque pour que la voix de "
                                  "l'examinateur ne soit pas enregistrée.")

        self._meter_timer = QTimer(self)
        self._meter_timer.timeout.connect(self._update_meter)
        self._auto = QTimer(self)
        self._auto.timeout.connect(self.next_prompt)
        audio = getattr(ctx, "audio", None)
        if audio is not None and hasattr(audio, "started") and self.recorder is not None:
            audio.started.connect(self._pause_rec)
            audio.finished.connect(self._resume_rec)
            audio.failed.connect(self._resume_rec)

    # ------------------------------------------------------------ examinateur
    def _speak_current(self) -> None:
        audio = getattr(self.ctx, "audio", None)
        if audio is not None and 0 <= self.prompt_idx < len(self.prompts):
            audio.play_text("H: " + self.prompts[self.prompt_idx], ["H:fr-FR"])

    def next_prompt(self) -> None:
        if self._state != "recording" or self.prompt_idx + 1 >= len(self.prompts):
            self.next_btn.setEnabled(False)
            return
        self.prompt_idx += 1
        text = self.prompts[self.prompt_idx]
        self.prompt_lbl.setText(text)
        self.dialogue.append({"who": "examinateur", "text": text,
                              "t": round(time.monotonic() - self._t0, 1)})
        self._speak_current()
        self.next_btn.setEnabled(self.prompt_idx + 1 < len(self.prompts))

    def _pause_rec(self) -> None:
        if self._state == "recording" and self.recorder is not None:
            self.recorder.pause(True)

    def _resume_rec(self, *_):
        if self.recorder is not None:
            self.recorder.pause(False)

    # ------------------------------------------------------------ enregistrement
    def toggle(self) -> None:
        if self._state == "idle":
            self.start()
        elif self._state == "recording":
            self.stop()

    def start(self) -> None:
        if self._state != "idle":
            return
        if self.recorder is not None:
            self.audio_path = recording_path(self.ctx.paths.recordings, self.task_number)
            try:
                self.recorder.start(self.audio_path)
            except RecorderUnavailable as exc:
                self.recorder, self.audio_path = None, None
                self.manual.setVisible(True)
                self.rec_info.setText(f"⚠ {exc} La tâche se fait par écrit.")
            else:
                self._meter_timer.start(100)
        self._state = "recording"
        self._t0 = time.monotonic()
        self.rec_btn.setText("■ Terminer la tâche")
        self.timer.start()
        self.next_prompt()
        if self.mode == ES.MODE_EXAM and len(self.prompts) > 1:
            self._auto.start(int(self.duration * 1000 / len(self.prompts)))

    def stop(self) -> None:
        if self._state != "recording":
            return
        self._state = "done"
        self.timer.stop()
        self._auto.stop()
        self._meter_timer.stop()
        audio = getattr(self.ctx, "audio", None)
        if audio is not None:
            audio.stop()
        duration = time.monotonic() - self._t0
        if self.recorder is not None and self.audio_path is not None:
            duration = self.recorder.stop() or duration
        self.meter.setValue(0)
        self.rec_btn.setEnabled(False)
        self.next_btn.setEnabled(False)
        self.rec_btn.setText("Tâche terminée")
        self.recorded.emit({"task_id": self.task_id,
                            "audio_path": str(self.audio_path) if self.audio_path else None,
                            "duration_s": round(duration, 1), "dialogue": self.dialogue,
                            "manual_text": self.manual.toPlainText()})

    def _update_meter(self) -> None:
        if self.recorder is not None:
            self.meter.setValue(int(self.recorder.level() * 100))


# =========================================================================
class SpeakingRunner(QWidget):
    """Enchaîne les tâches demandées (1 à 3), puis transcrit et évalue."""
    finished = Signal(int)

    def __init__(self, ctx, attempt_id: int | None, task_ids: list[int], mode: str,
                 finalize: bool = False, parent=None):
        super().__init__(parent)
        self.ctx, self.attempt_id, self.task_ids = ctx, attempt_id, task_ids
        self.mode, self.finalize = mode, finalize
        self.infos: list[dict] = []
        self.submission_ids: list[int] = []
        self._done = False
        lay = QVBoxLayout(self)
        self.stack = QStackedWidget()
        lay.addWidget(self.stack, 1)
        self.status = QLabel()
        self.status.setObjectName("Muted")
        lay.addWidget(self.status)
        lay.addWidget(disclaimer_label(
            "Les enregistrements restent sur votre ordinateur. Vous pouvez les supprimer à "
            "tout moment (Paramètres > Confidentialité)."))
        self.widgets: list[SpeakingTaskWidget] = []
        with ctx.db.session() as s:
            for tid in task_ids:
                w = SpeakingTaskWidget(ctx, s.get(SpeakingTask, tid), mode)
                w.recorded.connect(self._on_recorded)
                self.widgets.append(w)
                self.stack.addWidget(w)

    def current(self) -> SpeakingTaskWidget:
        return self.widgets[len(self.infos)] if len(self.infos) < len(self.widgets) else None

    def _on_recorded(self, info: dict) -> None:
        self.infos.append(info)
        if len(self.infos) < len(self.widgets):
            self.stack.setCurrentIndex(len(self.infos))
            self.status.setText(f"Tâche {len(self.infos)} terminée.")
            return
        self.status.setText("Analyse de vos réponses (transcription et évaluation)…")
        stt = getattr(self.ctx, "stt", None)
        infos = list(self.infos)
        run_background(self, lambda: [analyse_recording(stt, i["audio_path"], i["manual_text"])
                                      for i in infos], self._on_analysed)

    def _on_analysed(self, results) -> None:
        if isinstance(results, Exception):
            QMessageBox.warning(self, "Expression orale", f"Analyse impossible : {results}")
            results = [{"transcript": i["manual_text"], "confidence": None, "profile": None,
                        "stt_error": str(results)} for i in self.infos]
        self.errors = [r["stt_error"] for r in results if r.get("stt_error")]
        with self.ctx.db.session() as s:
            for info, r in zip(self.infos, results):
                dialogue = list(info["dialogue"])
                if r["transcript"]:
                    dialogue.append({"who": "candidat", "text": r["transcript"]})
                sub = SS.submit(s, info["task_id"], r["transcript"], profile=r["profile"],
                                audio_path=info["audio_path"], stt_confidence=r["confidence"],
                                duration_s=info["duration_s"], dialogue=dialogue,
                                attempt_id=self.attempt_id)
                self.submission_ids.append(sub.id)
            if self.attempt_id is not None:
                self._result = SS.attempt_result(s, self.attempt_id, self.task_ids)
                if self.finalize:
                    a = s.get(Attempt, self.attempt_id)
                    ES.finish_attempt(s, a, {SECTION_EO: self._result})
        self._done = True
        self.finished.emit(self.attempt_id or 0)

    def result(self) -> dict | None:
        return getattr(self, "_result", None)


@register_step(SECTION_EO)
def _eo_step(ctx, attempt_id, exam_id, mode, audio=None):
    with ctx.db.session() as s:
        exam = s.get(Exam, exam_id)
        ids = [t.id for t in sorted(exam.speaking_tasks, key=lambda t: t.task_number)]
    return SpeakingRunner(ctx, attempt_id, ids, mode)
