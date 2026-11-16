"""v1.1 – étape 2 : 100 exercices CO B2 en 12 collections thématiques, tous corrigés."""
import json
from collections import Counter

from tcfmaster.content import validator as V
from tcfmaster.content.seeder import content_dir

CO_DIR = content_dir() / "collections" / "co"
THEMES = {"actualit", "environnement", "conomie", "ducation", "sant", "technologie",
          "culture", "professionnelle", "relations", "bats", "moignages", "conf"}


def _collections():
    return [json.loads(f.read_text(encoding="utf-8")) for f in sorted(CO_DIR.glob("*.json"))]


def test_at_least_100_co_exercises_in_12_thematic_collections():
    cols = _collections()
    assert len(cols) == 12
    assert sum(len(c["items"]) for c in cols) >= 100
    slugs = " ".join(c["slug"] + " " + c["title"].lower() for c in cols)
    assert all(t in slugs for t in THEMES)
    codes = [it["code"] for c in cols for it in c["items"]]
    assert len(codes) == len(set(codes))


def test_every_co_exercise_has_transcript_speakers_and_full_correction():
    for c in _collections():
        for it in c["items"]:
            assert it["speakers"], it["code"]
            assert V.count_words(it["document"]) >= 60, it["code"]
            assert len(it["vocabulary"]) >= 3 and it["expressions"], it["code"]
            for q in it["questions"]:
                assert [ch["label"] for ch in q["choices"]] == list("ABCD"), it["code"]
                assert sum(ch["correct"] for ch in q["choices"]) == 1, it["code"]
                assert all(ch["rationale"] for ch in q["choices"]), it["code"]
                assert q["explanation"] and q["skill"], it["code"]


def test_correct_answer_positions_are_balanced():
    pos = Counter(ch["label"] for c in _collections() for it in c["items"]
                  for q in it["questions"] for ch in q["choices"] if ch["correct"])
    total = sum(pos.values())
    assert set(pos) == set("ABCD")
    assert max(pos.values()) - min(pos.values()) <= max(4, total // 50)
