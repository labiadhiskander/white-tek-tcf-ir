"""Phase 4 : audio des documents de compréhension orale."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import json
import math
import struct
import wave
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication
from sqlalchemy import select

from tcfmaster.content.seeder import content_dir, seed_all
from tcfmaster.core.app_context import AppContext
from tcfmaster.core.logging_setup import setup_logging
from tcfmaster.db.models import Exam, Question
from tcfmaster.services import audio as A
from tcfmaster.services import exam_service as ES


class FakeBackend:
    """Moteur factice : écrit une sinusoïde (fréquence selon la voix)."""
    name = "factice"

    def __init__(self, voices=None, rate=16000, fail=False):
        self._voices = voices if voices is not None else [
            A.VoiceInfo("hortense", "Microsoft Hortense", "fr-FR", "F"),
            A.VoiceInfo("paul", "Microsoft Paul", "fr-FR", "H"),
            A.VoiceInfo("caroline", "Microsoft Caroline", "fr-CA", "F"),
            A.VoiceInfo("zira", "Microsoft Zira", "en-US", "F"),
        ]
        self.rate, self.fail = rate, fail
        self.calls: list[tuple[str, str]] = []

    def voices(self):
        return self._voices

    def synthesize(self, text, voice, rate, out: Path):
        if self.fail:
            raise A.TTSUnavailable("panne simulée")
        self.calls.append((voice.id, text))
        freq = 220 if voice.gender == "H" else 330
        n = int(self.rate * 0.2)
        with wave.open(str(out), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(self.rate)
            w.writeframes(b"".join(struct.pack("<h", int(8000 * math.sin(2 * math.pi * freq * i
                                                                           / self.rate)))
                                   for i in range(n)))


# ------------------------------------------------------------------ découpage
def test_parse_dialogue_with_accents():
    segs = A.parse_document("H: Bonjour, ça va ? / F: Très bien, merci. / H: Tant mieux.",
                            ["H:fr-FR", "F:fr-CA"])
    assert [(s.gender, s.locale) for s in segs] == [("H", "fr-FR"), ("F", "fr-CA"),
                                                    ("H", "fr-FR")]
    assert segs[1].text == "Très bien, merci."


def test_parse_monologue_and_unmarked_text():
    assert A.parse_document("F: Le train part à 8 h.", ["F:fr-BE"]) == [
        A.Segment("F", "fr-BE", "Le train part à 8 h.")]
    assert A.parse_document("Texte sans locuteur.") == [
        A.Segment("F", "fr-FR", "Texte sans locuteur.")]
    assert A.parse_document("   ") == []


def test_every_real_co_document_splits_into_turns():
    for path in sorted((content_dir() / "exams").glob("*.json")):
        exam = json.loads(path.read_text(encoding="utf-8"))
        for q in exam["CO"]:
            segs = A.parse_document(q["document"], q.get("speakers"))
            assert segs, f"{path.stem} CO {q['position']}"
            assert all(s.text and not s.text.startswith(("H:", "F:")) for s in segs)
            genders = {sp.split(":")[0] for sp in q.get("speakers") or []}
            assert {s.gender for s in segs} <= genders, f"{path.stem} CO {q['position']}"


# ---------------------------------------------------------------------- voix
def test_describe_voice_recognises_windows_voices():
    v = A.describe_voice(r"HKEY\...\TTS_MS_FR-CA_CAROLINE_11.0",
                         "Microsoft Caroline Desktop - French (Canada)")
    assert (v.locale, v.gender) == ("fr-CA", "F")
    v = A.describe_voice("x", "Microsoft Paul - French (France)")
    assert (v.locale, v.gender) == ("fr-FR", "H")
    v = A.describe_voice("french", "french", [b"\x05fr"], "male")
    assert v.is_french and v.gender == "H"
    assert not A.describe_voice("en", "Microsoft David - English", [], "male").is_french


def test_choose_voice_prefers_gender_then_accent():
    voices = FakeBackend().voices()
    assert A.choose_voice(voices, "H", "fr-CA").id == "paul"
    assert A.choose_voice(voices, "F", "fr-CA").id == "caroline"
    assert A.choose_voice(voices, "F", "fr-CH").id == "hortense"
    assert A.choose_voice(voices[3:], "F", "fr-FR") is None


# ------------------------------------------------------------------- génération
def test_generator_builds_and_caches_a_dialogue(tmp_path):
    be = FakeBackend()
    gen = A.AudioGenerator(be, tmp_path / "cache")
    doc, sp = "H: Bonjour. / F: Bonsoir.", ["H:fr-FR", "F:fr-CA"]
    assert not gen.is_ready(doc, sp)
    out = gen.ensure(doc, sp)
    assert out.is_file() and gen.is_ready(doc, sp)
    assert [c[0] for c in be.calls] == ["paul", "caroline"]
    with wave.open(str(out)) as w:
        assert w.getframerate() == A.TARGET_RATE and w.getnchannels() == 1
        dur = w.getnframes() / w.getframerate()
    assert 0.8 < dur < 0.9            # 2 × 0,2 s + silence de 0,45 s
    assert not list((tmp_path / "cache").glob("*.tmp.wav"))
    gen.ensure(doc, sp)               # deuxième fois : depuis le cache
    assert len(be.calls) == 2
    gen.rate = 200                    # un autre débit = un autre fichier
    assert not gen.is_ready(doc, sp)
    assert gen.clear_cache() == 1


def test_recorded_file_has_priority(tmp_path):
    rec = tmp_path / "res" / "co1.wav"
    rec.parent.mkdir()
    FakeBackend().synthesize("x", A.VoiceInfo("p", "p", "fr-FR", "H"), 170, rec)
    be = FakeBackend()
    gen = A.AudioGenerator(be, tmp_path / "cache", resource_dir=tmp_path / "res")
    assert gen.ensure("H: Bonjour.", None, "co1.wav") == rec and be.calls == []


def test_generator_reports_missing_engine_or_french_voice(tmp_path):
    with pytest.raises(A.TTSUnavailable, match="Aucun moteur"):
        A.AudioGenerator(None, tmp_path).ensure("F: Bonjour.")
    with pytest.raises(A.TTSUnavailable, match="voix française"):
        A.AudioGenerator(FakeBackend(voices=[A.VoiceInfo("z", "Zira", "en-US", "F")]),
                         tmp_path).ensure("F: Bonjour.")


def test_concat_handles_mixed_formats(tmp_path):
    a, b = tmp_path / "a.wav", tmp_path / "b.wav"
    FakeBackend(rate=16000).synthesize("x", A.VoiceInfo("p", "p", "fr", "H"), 170, a)
    with wave.open(str(b), "wb") as w:      # stéréo 44,1 kHz
        w.setnchannels(2); w.setsampwidth(2); w.setframerate(44100)
        w.writeframes(b"\x00\x10\x00\x10" * 4410)
    out = A.concat_wavs([a, b], tmp_path / "o.wav", pause_s=0)
    with wave.open(str(out)) as w:
        assert abs(w.getnframes() / A.TARGET_RATE - 0.3) < 0.01


# ---------------------------------------------------------------- interface
@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def ctx(db, tmp_paths, content_root, qapp):
    with db.session() as s:
        seed_all(s, content_root)
    return AppContext(paths=tmp_paths, db=db, log=setup_logging(tmp_paths.logs))


class FakeAudio:
    """Service audio factice, avec les mêmes signaux que AudioService."""
    def __init__(self):
        from PySide6.QtCore import QObject, Signal

        class _S(QObject):
            preparing = Signal()
            started = Signal()
            finished = Signal()
            failed = Signal(str)
        self._s = _S()
        for n in ("preparing", "started", "finished", "failed"):
            setattr(self, n, getattr(self._s, n))
        self.played, self.stops = [], 0

    def play_question(self, q):
        self.played.append(q.id)

    def stop(self):
        self.stops += 1


def _runner(ctx, mode, audio):
    from tcfmaster.ui.mcq_runner import McqRunner
    with ctx.db.session() as s:
        exam = s.execute(select(Exam)).scalar_one()
        qids = [q.id for q in exam.questions_for("CO")]
        aid = ES.start_attempt(s, exam.id, ["CO"], mode).id
    return McqRunner(ctx, aid, "CO", qids, mode, audio=audio, time_limit=600), qids


def test_failed_audio_gives_the_single_listening_back(ctx):
    audio = FakeAudio()
    r, qids = _runner(ctx, ES.MODE_EXAM, audio)
    r._play()
    assert audio.played == [qids[0]] and not r.play_btn.isEnabled()
    audio.failed.emit("Aucune voix française n'est installée.")
    assert r.play_btn.isEnabled() and "voix française" in r.play_info.text()
    assert "Transcription" not in r.document.toPlainText()   # jamais en mode examen
    r._play(); audio.started.emit()
    assert "Lecture" in r.play_info.text()
    audio.finished.emit()
    assert not r.play_btn.isEnabled()                         # écoute consommée
    r.select("A"); r.next()
    assert audio.stops >= 1
    r.finish()


def test_training_mode_shows_transcript_when_audio_fails(ctx):
    audio = FakeAudio()
    r, qids = _runner(ctx, ES.MODE_TRAINING, audio)
    r._play()
    audio.failed.emit("panne")
    assert "Audio indisponible" in r.document.toPlainText()
    r.finish()


def test_audio_service_generates_in_background(ctx, qapp, tmp_path):
    from PySide6.QtCore import QEventLoop, QTimer
    from tcfmaster.services.wiring import pregenerate_all, wire
    wire(ctx, FakeBackend())
    svc = ctx.audio
    events = []
    for n in ("preparing", "started", "failed"):
        getattr(svc, n).connect(lambda *a, n=n: events.append(n))
    loop = QEventLoop()
    svc.started.connect(loop.quit)
    svc.failed.connect(loop.quit)
    QTimer.singleShot(5000, loop.quit)
    with ctx.db.session() as s:
        q = s.execute(select(Question).where(Question.section == "CO")).scalars().first()
        svc.play_question(q)
    loop.exec()
    assert events[0] == "preparing" and events[-1] in ("started", "failed")
    assert svc.generator.is_ready(q.document, q.speakers)
    ready, errors = pregenerate_all(ctx, svc.generator)
    assert ready == 25 and errors == []
    svc.shutdown()


def test_settings_page_shows_audio_card(ctx):
    from tcfmaster.services.wiring import wire
    from tcfmaster.ui.pages.misc_pages import SettingsPage
    wire(ctx, FakeBackend())
    p = SettingsPage(ctx)
    p.refresh()
    assert "Hortense" in p.audio_card.engine_info.text()
    p.audio_card.rate.setValue(190)
    assert ctx.audio.generator.rate == 190


def test_built_co_questions_name_their_optional_recording():
    exam = json.loads((content_dir() / "exams" / "exam_01.json").read_text(encoding="utf-8"))
    assert exam["CO"][6]["audio_file"] == "exam-01_co07.wav"
    assert all("audio_file" not in q for q in exam["CE"])


def test_vocabulary_listen_button_uses_audio_service(ctx):
    from tcfmaster.ui.pages.learning_pages import VocabularyPage

    class Rec:
        def __init__(self):
            self.texts = []

        def play_text(self, doc, speakers=None, audio_file=None):
            self.texts.append(doc)
    with ctx.db.session() as s:
        seed_all(s)                      # contenu réel (expressions)
    ctx.audio = Rec()
    p = VocabularyPage(ctx)
    p.refresh()
    p.exp_list.setCurrentRow(0)
    p._exp_listen()
    assert ctx.audio.texts and ctx.audio.texts[0].startswith("F: ")
