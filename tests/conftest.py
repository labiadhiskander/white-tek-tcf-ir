import json
from pathlib import Path

import pytest

from tcfmaster.core.paths import AppPaths
from tcfmaster.db.database import Database


def make_question(pos: int, level: str = "B1", correct: str = "B") -> dict:
    return {
        "position": pos, "level": level, "doc_type": "annonce", "skill": "détail",
        "document": f"Document de test numéro {pos}.",
        "prompt": f"Question {pos} ?",
        "choices": [{"label": l, "text": f"Réponse {l} {pos}", "correct": l == correct,
                     "rationale": "r"} for l in "ABCD"],
        "explanation": "Explication détaillée.",
    }


def make_exam(code: str = "TEST-01") -> dict:
    return {
        "code": code, "title": "Examen de test", "level": "B2",
        "CO": [make_question(i) for i in range(1, 26)],
        "CE": [make_question(i, "B2") for i in range(1, 26)],
        "EE": [
            {"task_number": 1, "task_type": "décrire", "instructions": "x",
             "min_words": 30, "max_words": 60,
             "model_answer": " ".join(["mot"] * 45)},
            {"task_number": 2, "task_type": "raconter", "instructions": "x",
             "min_words": 40, "max_words": 90, "model_answer": " ".join(["mot"] * 70)},
            {"task_number": 3, "task_type": "opinion", "instructions": "x",
             "min_words": 40, "max_words": 90, "model_answer": " ".join(["mot"] * 80)},
        ],
        "EO": [
            {"task_number": n, "title": f"T{n}", "scenario": "s", "duration_s": d,
             "examiner_prompts": ["Bonjour"]}
            for n, d in ((1, 180), (2, 210), (3, 210))
        ],
    }


@pytest.fixture
def tmp_paths(tmp_path) -> AppPaths:
    return AppPaths(tmp_path / "data").ensure()


@pytest.fixture
def db(tmp_paths) -> Database:
    d = Database(tmp_paths.database, tmp_paths.backups).open()
    yield d
    d.close()


@pytest.fixture
def content_root(tmp_path) -> Path:
    root = tmp_path / "content"
    (root / "exams").mkdir(parents=True)
    (root / "exams" / "test.json").write_text(json.dumps(make_exam(), ensure_ascii=False),
                                              encoding="utf-8")
    return root
