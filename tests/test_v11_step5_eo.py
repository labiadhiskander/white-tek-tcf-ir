"""v1.1 – étape 5 : 102 situations EO B2 (34 par tâche), indices de prononciation tirés de
la reconnaissance vocale et réponse améliorée construite à partir de la transcription."""
import json
from collections import Counter

from sqlalchemy import select

from tcfmaster.content import validator as V
from tcfmaster.content.seeder import content_dir, seed_all
from tcfmaster.db.models import SpeakingTask
from tcfmaster.services import speaking_eval as SE
from tcfmaster.services import speaking_service as SS
from tcfmaster.services import writing_eval as WE
from tcfmaster.ui.speaking import analyse_recording
from tcfmaster.ui.speaking_report import oral_html

EO_DIR = content_dir() / "collections" / "eo"


def _items():
    return [it for f in sorted(EO_DIR.glob("*.json"))
            for it in json.loads(f.read_text(encoding="utf-8"))["items"]]


def test_at_least_100_eo_situations_balanced_over_three_tasks():
    items = _items()
    assert len(items) >= 100
    per_task = Counter(it["task_number"] for it in items)
    assert set(per_task) == {1, 2, 3} and min(per_task.values()) >= 33
    codes = [it["code"] for it in items]
    assert len(codes) == len(set(codes))
    assert len({it["title"] for it in items}) == len(items)


def test_every_situation_has_examiner_model_and_advice():
    for it in _items():
        assert not V.validate_speaking_subject(it), it["code"]
        assert it["level"] == "B2"
        assert len(it["examiner_prompts"]) >= 3, it["code"]       # examinateur virtuel
        assert len(it["useful_phrases"]) >= 3, it["code"]
        assert 70 <= V.count_words(it["model_answer"]) <= 130, it["code"]
        assert it["model_commentary"] and it["tips"], it["code"]
        errs = [i for i in WE.find_issues(it["model_answer"]) if i.severity == WE.ERROR]
        assert not errs, (it["code"], [e.excerpt for e in errs])


def test_improved_answer_cleans_the_transcript():
    raw = ("euh ben je je pense que du coup il y a pas de boulot ici, c'est pas cool, "
           "nous nous sommes trompés quoi")
    out = SE.improved_answer(raw)
    assert out.startswith("Je pense que")
    for bad in ("euh", "ben", "je je", "du coup", "boulot", "cool", " quoi"):
        assert bad not in out.lower()
    assert "il n'y a pas" in out and "ce n'est pas" in out
    assert "nous nous sommes" in out and out.endswith(".")
    assert SE.improved_answer("") == ""


def test_pronunciation_hints_from_word_confidence():
    words = [{"word": "maintenant", "conf": 0.4}, {"word": "rue", "conf": 0.5},
             {"word": "le", "conf": 0.2}, {"word": "travail", "conf": 0.95},
             {"word": "maintenant", "conf": 0.55}]
    pr = SE.pronunciation_hints(words)
    assert pr["unclear"] == ["maintenant", "rue"]          # mots courts ignorés, sans doublon
    assert pr["unclear_share"] == 0.6 and pr["advice"]
    assert "nasale" in " ".join(pr["advice"])
    clear = SE.pronunciation_hints([{"word": "bonjour", "conf": 0.99}])
    assert clear["unclear"] == [] and "claire" in clear["advice"][0]
    assert SE.pronunciation_hints(None) == {}


def test_submit_keeps_word_confidence_and_report_shows_everything(db):
    with db.session() as s:
        seed_all(s)
        t = s.execute(select(SpeakingTask).where(SpeakingTask.code == "EO-B2-070")).scalar_one()
        words = [{"word": "téléphone", "conf": 0.3}, {"word": "école", "conf": 0.9}]
        text = "euh je pense que le téléphone c'est pas une bonne chose à l'école " * 6
        sub = SS.submit(s, t.id, text, duration_s=180, stt_words=words)
        ev = sub.evaluation
        assert ev["pronunciation"]["unclear"] == ["téléphone"]
        assert ev["improved_answer"].startswith("Je pense que")
        assert ev["model_commentary"] and ev["tips"]
        # réévaluation de la même transcription : la confiance mot à mot est conservée
        sub = SS.submit(s, t.id, text, submission_id=sub.id)
        assert sub.evaluation["pronunciation"]["unclear"] == ["téléphone"]
        html = oral_html(sub.evaluation, text)
        for part in ("Prononciation", "Votre réponse améliorée", "Réponse modèle",
                     "Pourquoi c'est un B2", "Conseils"):
            assert part in html


def test_analyse_recording_passes_word_confidence(tmp_path):
    from tcfmaster.services import stt as STT

    class FakeSTT:
        def transcribe(self, path):
            return STT.Transcript("bonjour", [STT.Word("bonjour", 0, 0.4, 0.42)], "x")

    wav = tmp_path / "a.wav"
    import wave
    with wave.open(str(wav), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(b"\0\0" * 16000)
    out = analyse_recording(FakeSTT(), str(wav), "")
    assert out["words"] == [{"word": "bonjour", "conf": 0.42}]
