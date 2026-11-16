"""v1.1 – étape 4 : 102 sujets EE B2 originaux (34 par tâche), réponses modèles dans les
limites officielles de mots, correction complète et analyse syntaxique."""
import json
from collections import Counter

from tcfmaster.content import validator as V
from tcfmaster.content.seeder import content_dir
from tcfmaster.services import writing_eval as W

EE_DIR = content_dir() / "collections" / "ee"
LIMITS = {1: (30, 60), 2: (40, 90), 3: (40, 90)}


def _items():
    return [it for f in sorted(EE_DIR.glob("*.json"))
            for it in json.loads(f.read_text(encoding="utf-8"))["items"]]


def test_at_least_100_ee_subjects_balanced_over_three_tasks():
    items = _items()
    assert len(items) >= 100
    per_task = Counter(it["task_number"] for it in items)
    assert set(per_task) == {1, 2, 3}
    assert min(per_task.values()) >= 33
    codes = [it["code"] for it in items]
    assert len(codes) == len(set(codes))
    assert len({it["instructions"] for it in items}) == len(items)   # sujets distincts


def test_models_strictly_respect_official_word_limits():
    for it in _items():
        lo, hi = LIMITS[it["task_number"]]
        assert (it["min_words"], it["max_words"]) == (lo, hi), it["code"]
        n = V.count_words(it["model_answer"])
        assert lo <= n <= hi, (it["code"], n)
        # le moteur de correction compte exactement comme le compteur de l'interface
        assert W.evaluate(it["model_answer"], it["task_number"], lo, hi).word_count == n


def test_every_subject_is_b2_and_fully_corrected():
    for it in _items():
        assert it["level"] == "B2", it["code"]
        assert it["instructions"] and it["model_commentary"], it["code"]
        assert len(it["expected_points"]) >= 2 and it["tips"], it["code"]


def test_models_have_no_detected_error_and_use_complex_syntax():
    for it in _items():
        errs = [i for i in W.find_issues(it["model_answer"]) if i.severity == W.ERROR]
        assert not errs, (it["code"], [e.excerpt for e in errs])
        notes = W.syntax_notes(it["model_answer"])
        assert len(notes) == 1 and not notes[0].startswith("0 "), (it["code"], notes)


def test_syntax_analysis_flags_weak_constructions():
    notes = W.syntax_notes("Je pense ça. Je crois ça. Je veux ça. Je veux venir demain avec "
                           "toi au cinéma ce soir")
    joined = " ".join(notes)
    assert "Aucune subordonnée" in joined
    assert "commencent par « je »" in joined
    assert "ponctuation finale" in joined
    long = "Je pense que " + "nous devrions vraiment " * 15 + "partir."
    assert any("découpez" in x for x in W.syntax_notes(long))
    ev = W.evaluate("Bonjour, je viens demain parce que je suis libre.", 1, 30, 60)
    assert ev.to_dict()["syntax"]
    assert W.evaluate("", 1, 30, 60).syntax == []
