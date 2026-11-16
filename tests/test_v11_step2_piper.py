"""v1.1 – étape 2 : voix neuronales Piper (facultatives) avec repli sur les voix du système."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import json
import sys
import wave
import zipfile

import pytest

from tcfmaster.services import audio as A
from tcfmaster.services import piper_tts as PT
from tests.test_phase4_audio import FakeBackend

FAKE_PIPER = '''#!{py}
import sys, wave, json, pathlib
args = sys.argv[1:]
opt = {{args[i]: args[i + 1] for i in range(0, len(args) - 1, 2)}}
text = sys.stdin.buffer.read().decode("utf-8")
log = pathlib.Path(opt["--model"]).with_suffix(".log")
with open(log, "a", encoding="utf-8") as fh:
    fh.write(json.dumps({{"text": text, **opt}}) + "\\n")
if "PANNE" in text:
    sys.exit(3)
with wave.open(opt["--output_file"], "wb") as w:
    w.setnchannels(1); w.setsampwidth(2); w.setframerate(22050)
    w.writeframes(b"\\x00\\x10" * 4410)
'''


@pytest.fixture
def qapp():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


@pytest.fixture
def piper_env(tmp_path):
    if sys.platform == "win32":
        pytest.skip("programme factice écrit en script shell")
    pdir, vdir = tmp_path / "piper", tmp_path / "voix"
    pdir.mkdir()
    vdir.mkdir()
    exe = pdir / "piper"
    exe.write_text(FAKE_PIPER.format(py=sys.executable), encoding="utf-8")
    exe.chmod(0o755)
    (vdir / "fr_FR-siwis-medium.onnx").write_bytes(b"onnx")
    (vdir / "fr_FR-siwis-medium.onnx.json").write_text(
        json.dumps({"language": {"code": "fr_FR"}, "num_speakers": 1}), encoding="utf-8")
    (vdir / "fr_FR-upmc-medium.onnx").write_bytes(b"onnx")
    (vdir / "fr_FR-upmc-medium.onnx.json").write_text(
        json.dumps({"language": {"code": "fr_FR"}, "speaker_id_map": {"jessica": 0, "pierre": 1}}),
        encoding="utf-8")
    (vdir / "orphelin.onnx").write_bytes(b"sans configuration")
    return pdir, vdir


def test_catalog_uses_official_piper_voice_urls():
    assert {v.key for v in PT.CATALOG} >= {"fr_FR-siwis-medium", "fr_FR-tom-medium"}
    v = PT.CATALOG_BY_KEY["fr_FR-siwis-medium"]
    assert v.model_url == ("https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/"
                           "fr/fr_FR/siwis/medium/fr_FR-siwis-medium.onnx")
    assert v.config_url.endswith(".onnx.json") and v.card_url.endswith("/MODEL_CARD")
    assert PT.PIPER_DOWNLOADS["win32"].startswith("https://github.com/rhasspy/piper/releases/")


def test_installed_voices_reads_locale_gender_and_speakers(piper_env):
    _pdir, vdir = piper_env
    voices = PT.installed_voices(vdir)
    assert {(v.name, v.locale, v.gender) for v in voices} == {
        ("Piper fr_FR-siwis-medium", "fr-FR", "F"),
        ("Piper fr_FR-upmc-medium (jessica)", "fr-FR", "F"),
        ("Piper fr_FR-upmc-medium (pierre)", "fr-FR", "H")}
    assert all(v.is_french for v in voices)
    assert PT.installed_voices(vdir / "absent") == []


def test_length_scale_follows_rate():
    assert PT.PiperBackend.length_scale(170) == 1.0
    assert PT.PiperBackend.length_scale(136) > 1.0 > PT.PiperBackend.length_scale(210)
    assert 0.5 <= PT.PiperBackend.length_scale(10_000) and PT.PiperBackend.length_scale(1) <= 2


def test_dialogue_is_synthesized_with_piper_voices(piper_env, tmp_path):
    pdir, vdir = piper_env
    be = PT.PiperBackend(pdir / "piper", vdir)
    gen = A.AudioGenerator(be, tmp_path / "cache", rate=170)
    out = gen.ensure("H: Bonjour madame. / F: Bonjour monsieur, entrez.", ["H:fr-FR", "F:fr-CA"])
    with wave.open(str(out)) as w:
        assert w.getnframes() > 4410 * 2
    calls = [json.loads(line) for line in (vdir / "fr_FR-upmc-medium.log").read_text(
        encoding="utf-8").splitlines()]
    assert calls[0]["text"] == "Bonjour madame." and calls[0]["--speaker"] == "1"   # pierre
    siwis = vdir / "fr_FR-siwis-medium.log"
    female = siwis.read_text(encoding="utf-8") if siwis.exists() else ""
    assert "Bonjour monsieur" in female or any(c.get("--speaker") == "0" for c in calls)
    assert gen.cached_path("H: Bonjour madame. / F: Bonjour monsieur, entrez.",
                           ["H:fr-FR", "F:fr-CA"]) == out


def test_chain_falls_back_to_system_voice_when_piper_fails(piper_env, tmp_path):
    pdir, vdir = piper_env
    system = FakeBackend()
    chain = PT.ChainBackend(PT.PiperBackend(pdir / "piper", vdir), system)
    assert chain.name == "piper+factice"
    assert all(v.name.startswith("Piper") for v in chain.voices())
    gen = A.AudioGenerator(chain, tmp_path / "cache")
    gen.ensure("F: PANNE de synthèse.")
    assert chain.failures == 1 and system.calls and system.calls[0][0] == "hortense"


def test_build_backend_respects_engine_setting(piper_env):
    pdir, vdir = piper_env
    system = FakeBackend()
    assert PT.build_backend("systeme", [pdir], vdir, system) is system
    auto = PT.build_backend("auto", [pdir], vdir, system)
    assert isinstance(auto, PT.ChainBackend) and auto.fallback is system
    assert PT.build_backend("auto", [pdir], vdir / "vide", system) is system
    assert PT.build_backend("piper", [None], vdir / "vide", system) in (system,) or \
        PT.find_piper([None]) is not None


def test_zip_extraction_refuses_path_traversal(tmp_path):
    bad = tmp_path / "bad.zip"
    with zipfile.ZipFile(bad, "w") as zf:
        zf.writestr("../evil.txt", "x")
    with pytest.raises(ValueError):
        PT._safe_extract_zip(bad, tmp_path / "out")
    good = tmp_path / "good.zip"
    with zipfile.ZipFile(good, "w") as zf:
        zf.writestr("piper/piper.exe", "x")
    PT._safe_extract_zip(good, tmp_path / "out")
    assert (tmp_path / "out" / "piper" / "piper.exe").is_file()


def test_remove_voice(piper_env):
    _pdir, vdir = piper_env
    PT.remove_voice("fr_FR-siwis-medium", vdir)
    assert not (vdir / "fr_FR-siwis-medium.onnx").exists()
    assert not (vdir / "fr_FR-siwis-medium.onnx.json").exists()


def test_pregenerate_covers_collection_exercises(tmp_paths, db, qapp):
    from tcfmaster.content.seeder import seed_all
    from tcfmaster.core.app_context import AppContext
    from tcfmaster.core.logging_setup import setup_logging
    from tcfmaster.services.wiring import pregenerate_all
    with db.session() as s:
        seed_all(s)
    ctx = AppContext(paths=tmp_paths, db=db, log=setup_logging(tmp_paths.logs))
    seen = []

    class Gen:
        def ensure(self, doc, speakers, audio_file):
            seen.append(doc)

    ready, errors = pregenerate_all(ctx, Gen())
    assert not errors and ready == len(seen) >= 100
    from sqlalchemy import select
    from tcfmaster.db.models import Exercise
    with db.session() as s:
        docs = {e.document for e in s.execute(select(Exercise).where(
            Exercise.section == "CO")).scalars()}
    assert docs <= set(seen)


def test_audio_settings_card_lists_piper_voices(tmp_paths, db, qapp, monkeypatch):
    from tcfmaster.core.app_context import AppContext
    from tcfmaster.core.logging_setup import setup_logging
    from tcfmaster.services import settings as S
    from tcfmaster.services import wiring as W
    from tcfmaster.ui.audio_settings import AudioSettingsCard
    ctx = AppContext(paths=tmp_paths, db=db, log=setup_logging(tmp_paths.logs))
    monkeypatch.setattr(W, "default_backend", lambda: FakeBackend())
    W.wire(ctx, recorder=False, stt=False)
    card = AudioSettingsCard(ctx)
    card.refresh()
    assert card.engine.currentData() == "auto"
    assert "Piper" in card.piper_info.text() and "MODEL_CARD" in card.piper_info.text()
    assert card.piper_btn.isEnabled() and not card.piper_remove.isEnabled()
    card.engine.setCurrentIndex(card.engine.findData("systeme"))
    with db.session() as s:
        assert S.get(s, "tts_engine") == "systeme"
    assert ctx.audio.generator.backend.name == "factice"
    ctx.audio.shutdown()


def test_exercise_runner_gives_back_the_listen_when_audio_fails(tmp_paths, db, qapp):
    from PySide6.QtCore import QObject, Signal
    from sqlalchemy import select
    from tcfmaster.content.seeder import seed_all
    from tcfmaster.core.app_context import AppContext
    from tcfmaster.core.logging_setup import setup_logging
    from tcfmaster.db.models import Exercise
    from tcfmaster.services import collections as COL
    from tcfmaster.services import exam_service as ES
    from tcfmaster.ui.exercise_runner import ExerciseRunner

    class FailingAudio(QObject):
        preparing, started, finished = Signal(), Signal(), Signal()
        failed = Signal(str)

        def play_text(self, *_a):
            self.preparing.emit()
            self.failed.emit("Aucune voix française n'est installée.")

        def stop(self):
            pass

    with db.session() as s:
        seed_all(s)
        ex_id = s.execute(select(Exercise.id).where(Exercise.section == "CO")).scalars().first()
        aid = COL.start_series(s, [ex_id], ES.MODE_EXAM).id
    ctx = AppContext(paths=tmp_paths, db=db, log=setup_logging(tmp_paths.logs))
    r = ExerciseRunner(ctx, aid, [ex_id], ES.MODE_EXAM, audio=FailingAudio())
    r._play()
    assert r.plays[ex_id] == 0 and r.play_btn.isEnabled()
    assert "Aucune voix" in r.play_info.text()
    r.finish()
