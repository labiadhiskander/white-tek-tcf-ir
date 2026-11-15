"""v1.1 – étape 3 : 100 exercices CE B2 en 13 thèmes, tous corrigés (justification, vocabulaire,
expressions idiomatiques, pièges)."""
import json
from collections import Counter

from tcfmaster.content import validator as V
from tcfmaster.content.seeder import content_dir

CE_DIR = content_dir() / "collections" / "ce"
THEMES = ["presse", "argumentatifs", "ditoriaux", "bats", "environnement", "conomie",
          "travail", "ducation", "technologie", "culture", "sant", "actualit", "administratifs"]


def _collections():
    return [json.loads(f.read_text(encoding="utf-8")) for f in sorted(CE_DIR.glob("*.json"))]


def test_at_least_100_ce_exercises_in_13_themes():
    cols = _collections()
    assert len(cols) == 13
    assert sum(len(c["items"]) for c in cols) >= 100
    blob = " ".join(c["slug"] + " " + c["title"].lower() for c in cols)
    assert all(t in blob for t in THEMES)
    codes = [it["code"] for c in cols for it in c["items"]]
    assert len(codes) == len(set(codes))


def test_every_ce_exercise_is_b2_and_fully_corrected():
    for c in _collections():
        for it in c["items"]:
            assert it["level"] == "B2"
            assert V.count_words(it["document"]) >= 120, it["code"]
            assert len(it["vocabulary"]) >= 3 and it["expressions"] and it["traps"], it["code"]
            for q in it["questions"]:
                assert [ch["label"] for ch in q["choices"]] == list("ABCD"), it["code"]
                good = [ch for ch in q["choices"] if ch["correct"]]
                assert len(good) == 1, it["code"]
                assert all(ch["rationale"] for ch in q["choices"]), it["code"]
                assert q["explanation"], it["code"]


def test_ce_correct_answers_are_balanced():
    pos = Counter(ch["label"] for c in _collections() for it in c["items"]
                  for q in it["questions"] for ch in q["choices"] if ch["correct"])
    assert max(pos.values()) - min(pos.values()) <= max(4, sum(pos.values()) // 50)
