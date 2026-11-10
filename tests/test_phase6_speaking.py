"""Phase 6 : expression orale (enregistrement, transcription, évaluation)."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import math
import re
import struct
import wave
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication
from sqlalchemy import select

from tcfmaster.content.seeder import seed_all
from tcfmaster.core import levels as L
from tcfmaster.core.app_context import AppContext
from tcfmaster.core.logging_setup import setup_logging
from tcfmaster.db.models import Attempt, Exam, SpeakingSubmission
from tcfmaster.services import exam_service as ES
from tcfmaster.services import settings as S
from tcfmaster.services import speaking_eval as SE
from tcfmaster.services import speaking_service as SS
from tcfmaster.services import stt as STT
from tcfmaster.services.recorder import speech_profile

GOOD_T3 = (
    "pour ma part je pense que le télétravail est une bonne chose mais il faut le "
    "limiter d'abord il permet de gagner du temps de transport par exemple dans ma ville "
    "beaucoup de gens passent deux heures par jour dans les bouchons ensuite on est souvent "
    "plus concentré à la maison de plus les entreprises économisent des bureaux cependant "
    "il ne faut pas oublier que le travail est aussi un lieu de rencontre certes on peut "
    "parler en visioconférence mais ce n'est pas la même chose bien que ce soit pratique "
    "on risque de se sentir isolé c'est pourquoi je propose deux ou trois jours de "
    "télétravail par semaine et le reste au bureau ainsi on garde le lien avec les "
    "collègues tout en profitant de la souplesse en conclusion le télétravail est un "
    "progrès à condition de garder un équilibre entre la maison et l'entreprise "
) * 2


def write_wav(path: Path, pattern: list[tuple[float, bool]], rate: int = 16000) -> None:
    """Écrit une alternance de « parole » (sinusoïde) et de silence."""
    frames = bytearray()
    for dur, voiced in pattern:
        for i in range(int(dur * rate)):
            v = int(9000 * math.sin(2 * math.pi * 180 * i / rate)) if voiced else 0
            frames += struct.pack("<h", v)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(rate)
        w.writeframes(bytes(frames))


class FakeRecorder:
    def __init__(self):
        self.recording, self.paused_calls, self._path = False, [], None

    def start(self, path):
        self._path, self.recording = Path(path), True

    def pause(self, on):
        self.paused_calls.append(on)

    def stop(self):
        write_wav(self._path, [(2.0, True), (1.5, False), (2.0, True)])
        self.recording = False
        return 5.5

    def level(self):
        return 0.5


class FakeSTT:
    name = "factice"

    def __init__(self, text=GOOD_T3):
        self.text, self.calls = text, 0

    def transcribe(self, path):
        self.calls += 1
        return STT.Transcript(self.text, [STT.Word("pour", 0, 0.3, 0.8)], self.name)


# ----------------------------------------------------------------- analyse
def test_speech_profile_measures_speech_and_pauses(tmp_path):
    p = tmp_path / "a.wav"
    write_wav(p, [(1.0, True), (2.0, False), (1.0, True), (0.5, False), (1.0, True)])
    prof = speech_profile(p)
    assert prof["duration_s"] == 5.5
    assert 2.7 <= prof["speech_s"] <= 3.3
    assert prof["long_pauses"] == 1


def test_find_model_locates_vosk_folder(tmp_path):
    (tmp_path / "modeles" / STT.MODEL_NAME / "am").mkdir(parents=True)
    assert STT.find_model([None, tmp_path / "rien", tmp_path / "modeles"]) == \
        tmp_path / "modeles" / STT.MODEL_NAME
    assert STT.find_model([tmp_path / "rien"]) is None


# ------------------------------------------------------------- évaluation
def test_good_opinion_speech_reaches_b2():
    ev = SE.evaluate_oral(GOOD_T3, 3, 210, {"duration_s": 200, "speech_s": 170,
                                            "long_pauses": 1}, 0.85)
    assert L.meets_target(ev.level), (ev.note20, ev.criteria)
    assert ev.note20 <= SE.AUTO_CAP
    assert all(p.status == "présent" for p in ev.points)
    assert ev.disclaimer == L.DISCLAIMER and "transcription" in ev.caveat


def test_short_hesitant_speech_is_capped():
    ev = SE.evaluate_oral("euh je je m'appelle ali euh je travaille euh je sais pas euh",
                          1, 180, {"duration_s": 60, "speech_s": 25, "long_pauses": 6})
    assert ev.note20 <= 6 and not L.meets_target(ev.level)
    assert ev.hesitations >= 4 and ev.repetitions_immediate >= 1
    assert ev.priorities


def test_oral_ignores_spelling_rules_and_softens_negation():
    issues = SE.oral_issues("je sais pas si il vient")
    rules = {i.rule: i.severity for i in issues}
    assert rules.get("negation-incomplete") == "conseil"
    assert "si-il" in rules
    assert "debut-majuscule" not in rules and "point-final" not in rules


def test_empty_speech_scores_zero():
    assert SE.evaluate_oral("", 2, 210).note20 == 0


def test_task_points_depend_on_task():
    ev = SE.evaluate_oral("bonjour madame est-ce que je pourrais avoir une réduction je "
                          "comprends mais je vous propose de payer en deux fois d'accord "
                          "merci beaucoup", 2, 210, {"duration_s": 200, "speech_s": 150})
    assert all(p.status == "présent" for p in ev.points)


# ------------------------------------------------------- persistance / UI
@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def ctx(db, tmp_paths, qapp):
    with db.session() as s:
        seed_all(s)
    c = AppContext(paths=tmp_paths, db=db, log=setup_logging(tmp_paths.logs))
    c.recorder, c.stt = FakeRecorder(), FakeSTT()
    import tcfmaster.ui.speaking as SPK
    SPK.RUN_SYNC = True
    return c


def _exam(s):
    return s.execute(select(Exam).order_by(Exam.code)).scalars().first()


def test_submit_respects_keep_recordings(ctx, tmp_path):
    with ctx.db.session() as s:
        t = sorted(_exam(s).speaking_tasks, key=lambda t: t.task_number)[2]
        wav = tmp_path / "r.wav"
        write_wav(wav, [(1, True)])
        sub = SS.submit(s, t.id, GOOD_T3, audio_path=wav, duration_s=200)
        assert sub.audio_path and wav.exists()
        S.set_(s, "keep_recordings", False)
        wav2 = tmp_path / "r2.wav"
        write_wav(wav2, [(1, True)])
        sub2 = SS.submit(s, t.id, GOOD_T3, audio_path=wav2, duration_s=200)
        assert sub2.audio_path is None and not wav2.exists()
        assert sub2.transcript == GOOD_T3            # la transcription est gardée
        SS.delete_submission(s, sub.id)
        assert not wav.exists() and s.get(SpeakingSubmission, sub.id) is None


def test_speaking_runner_training_with_fake_devices(ctx):
    from tcfmaster.ui.speaking import SpeakingRunner
    with ctx.db.session() as s:
        t = sorted(_exam(s).speaking_tasks, key=lambda t: t.task_number)[2]
        tid, n_prompts = t.id, len(t.examiner_prompts)
    r = SpeakingRunner(ctx, None, [tid], ES.MODE_TRAINING)
    w = r.current()
    assert w.timer.total == 210
    done = []
    r.finished.connect(done.append)
    w.start()
    assert w.dialogue[0]["who"] == "examinateur"
    for _ in range(n_prompts + 2):                  # ne dépasse jamais la dernière relance
        w.next_prompt()
    assert len([d for d in w.dialogue if d["who"] == "examinateur"]) == n_prompts
    w.stop()
    assert done == [0] and ctx.stt.calls == 1
    with ctx.db.session() as s:
        sub = s.get(SpeakingSubmission, r.submission_ids[0])
        assert sub.transcript == GOOD_T3 and sub.audio_path
        assert Path(sub.audio_path).parent == ctx.paths.recordings
        assert sub.evaluation["extra"]["profile"]["long_pauses"] == 1
        assert sub.dialogue[-1]["who"] == "candidat"


def test_examiner_voice_pauses_the_recording(ctx):
    from PySide6.QtCore import QObject, Signal
    from tcfmaster.ui.speaking import SpeakingRunner

    class Audio(QObject):
        started, finished, failed = Signal(), Signal(), Signal(str)

        def play_text(self, *a, **k):
            self.started.emit()
            self.finished.emit()

        def stop(self):
            pass
    ctx.audio = Audio()
    with ctx.db.session() as s:
        tid = sorted(_exam(s).speaking_tasks, key=lambda t: t.task_number)[0].id
    r = SpeakingRunner(ctx, None, [tid], ES.MODE_TRAINING)
    r.current().start()
    assert ctx.recorder.paused_calls[:2] == [True, False]
    r.current().stop()


def test_manual_transcript_without_microphone_or_stt(ctx):
    from tcfmaster.ui.speaking import SpeakingRunner
    ctx.recorder, ctx.stt = None, None
    with ctx.db.session() as s:
        tid = sorted(_exam(s).speaking_tasks, key=lambda t: t.task_number)[0].id
    r = SpeakingRunner(ctx, None, [tid], ES.MODE_TRAINING)
    w = r.current()
    assert not w.manual.isHidden()
    w.start()
    w.manual.setPlainText("je m'appelle sara je travaille comme infirmière parce que j'aime "
                          "aider les autres plus tard j'aimerais vivre au canada")
    w.stop()
    with ctx.db.session() as s:
        sub = s.get(SpeakingSubmission, r.submission_ids[0])
        assert sub.audio_path is None and "infirmière" in sub.transcript
        assert all(p["status"] == "présent" for p in sub.evaluation["points"])


def test_speaking_exam_three_tasks_and_result(ctx):
    from tcfmaster.ui.speaking import SpeakingRunner
    with ctx.db.session() as s:
        exam = _exam(s)
        ids = [t.id for t in sorted(exam.speaking_tasks, key=lambda t: t.task_number)]
        aid = ES.start_attempt(s, exam.id, ["EO"], ES.MODE_EXAM).id
    r = SpeakingRunner(ctx, aid, ids, ES.MODE_EXAM, finalize=True)
    assert sum(w.duration for w in r.widgets) == 600
    for _ in range(3):
        w = r.current()
        w.start()
        assert w._auto.isActive()                    # relances automatiques en examen
        w.stop()
    with ctx.db.session() as s:
        a = s.get(Attempt, aid)
        assert set(a.results["EO"]["tasks"]) == {"1", "2", "3"}
        assert a.results["disclaimer"] == L.DISCLAIMER
        assert len(a.speaking_submissions) == 3


def test_speaking_page_report_reevaluate_and_delete(ctx, monkeypatch):
    from tcfmaster.ui.pages.speaking_page import SpeakingPage
    p = SpeakingPage(ctx)
    p.refresh()
    assert "micro détecté" in p.device_info.text()
    p.task.setCurrentIndex(2)
    r = p.start_training()
    r.current().start()
    r.current().stop()
    html = p.report.toPlainText()
    assert "Note estimée" in html and "France Éducation international" in html
    assert p.play_btn.isVisibleTo(p) and not p.fix_box.isHidden()
    p.fix_box.setPlainText("je pense que c'est bien")
    p._reevaluate()
    assert "réévaluée" in p.report.toPlainText()
    p._delete_audio()
    with ctx.db.session() as s:
        assert s.get(SpeakingSubmission, p.current_sub).audio_path is None
    p.back()
    assert p.history.count() == 1
    p.history.setCurrentRow(0)
    from PySide6.QtWidgets import QMessageBox
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.Yes))
    p._delete_selected()
    assert p.history.count() == 0


def test_exam_session_registers_oral_step():
    import tcfmaster.ui.pages.exam_pages  # noqa: F401
    from tcfmaster.ui.exam_session import STEP_FACTORIES
    assert {"CO", "CE", "EE", "EO"} <= set(STEP_FACTORIES)


def test_report_never_hides_disclaimer():
    from tcfmaster.ui.speaking_report import oral_html
    ev = SE.evaluate_oral(GOOD_T3, 3, 210, {"duration_s": 200, "speech_s": 170}).to_dict()
    html = oral_html(ev, GOOD_T3)
    assert re.search("pas un résultat officiel", html)
