"""v1.1 étape 6 : 10 examens blancs complets, 100 % niveau B2."""
import collections
import json
import sys
from pathlib import Path

from tcfmaster.content import validator as V
from tcfmaster.content.seeder import content_dir
from tcfmaster.services import writing_eval as WE

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import build_content as BC  # noqa: E402


def _b2_exams():
    out = []
    for p in sorted((content_dir() / "exams").glob("exam_b2_*.json")):
        out.append(json.loads(p.read_text(encoding="utf-8")))
    return out


def test_ten_b2_exams_with_official_format():
    exams = _b2_exams()
    assert len(exams) == 10
    codes = [e["code"] for e in exams]
    assert codes == [f"B2-BLANC-{i:02d}" for i in range(1, 11)]
    for e in exams:
        assert e["series"] == "B2" and e["level"] == "B2"
        assert (len(e["CO"]), len(e["CE"]), len(e["EE"]), len(e["EO"])) == (25, 25, 3, 3)
        assert [t["duration_s"] for t in e["EO"]] == [180, 210, 210]


def test_every_item_is_b2_and_fully_corrected():
    for e in _b2_exams():
        assert BC.validate_b2_series(e) == [], e["code"]
        for sec in ("CO", "CE"):
            for q in e[sec]:
                assert q["level"] == "B2"
                assert len(q["choices"]) == 4
                assert sum(c["correct"] for c in q["choices"]) == 1
                assert all(c["rationale"].strip() for c in q["choices"])
                assert q["explanation"].strip()
        for t in e["EE"] + e["EO"]:
            assert t["level"] == "B2"
            assert t["model_answer"].strip() and t["model_commentary"].strip()
        for t in e["EO"]:
            assert t["tips"].strip() and t["examiner_prompts"]


def test_correct_answers_are_balanced():
    for e in _b2_exams():
        pos = collections.Counter(
            i for sec in ("CO", "CE") for q in e[sec]
            for i, c in enumerate(q["choices"]) if c["correct"])
        assert set(pos) == {0, 1, 2, 3}, e["code"]
        assert max(pos.values()) - min(pos.values()) <= 2, (e["code"], pos)


def test_ee_models_respect_word_limits():
    limits = {1: (30, 60), 2: (40, 90), 3: (40, 90)}
    for e in _b2_exams():
        for t in e["EE"]:
            lo, hi = limits[t["task_number"]]
            assert (t["min_words"], t["max_words"]) == (lo, hi)
            n = V.count_words(t["model_answer"])
            assert lo <= n <= hi, (e["code"], t["task_number"], n)
            ev = WE.evaluate(t["model_answer"], t["task_number"], lo, hi, t.get("expected_points"))
            assert ev.errors == [], (e["code"], t["task_number"])


def test_no_duplicates_between_exams_and_collections():
    entries = list(BC._collection_texts())
    for e in _b2_exams():
        entries += BC._exam_texts(e)
    assert V.find_duplicates(entries) == []
