"""Phase 3 : le contenu réel livré avec l'application est valide et se charge."""
from __future__ import annotations

import json
import random
from collections import Counter

import pytest
from sqlalchemy import func, select

from tcfmaster.content import validator as V
from tcfmaster.content.seeder import content_dir, seed_all
from tcfmaster.db.models import (Exam, Expression, GrammarChapter, GrammarExercise, PlanDay,
                                 Question, Verb, VocabWord)
from tcfmaster.services import learning as LS

ROOT = content_dir()


def test_content_directory_is_built():
    assert (ROOT / "exams").is_dir(), "lancer tools/build_content.py"
    assert len(list((ROOT / "exams").glob("*.json"))) >= 20


@pytest.mark.parametrize("path", sorted((ROOT / "exams").glob("*.json")), ids=lambda p: p.stem)
def test_each_exam_is_valid_and_balanced(path):
    exam = json.loads(path.read_text(encoding="utf-8"))
    assert V.validate_exam(exam) == []
    for sec in ("CO", "CE"):
        assert len(exam[sec]) == 25
        levels = Counter(q["level"] for q in exam[sec])
        assert levels["B1"] + levels["B2"] >= 15, "calibrage principal B1/B2"
        # la bonne réponse n'est pas toujours à la même place
        assert len({next(c["label"] for c in q["choices"] if c["correct"])
                    for q in exam[sec]}) >= 3
        for q in exam[sec]:
            assert q["explanation"] and all(c.get("rationale") for c in q["choices"])
    assert [t["task_number"] for t in exam["EE"]] == [1, 2, 3]
    assert [t["task_number"] for t in exam["EO"]] == [1, 2, 3]


def test_exam_documents_are_not_recycled():
    seen = {}
    for path in sorted((ROOT / "exams").glob("*.json")):
        exam = json.loads(path.read_text(encoding="utf-8"))
        for sec in ("CO", "CE"):
            for q in exam[sec]:
                key = q["document"][:120]
                assert key not in seen, f"{path.stem} recycle un document de {seen.get(key)}"
                seen[key] = path.stem


def test_full_seed_of_real_content(db):
    with db.session() as s:
        rep = seed_all(s)
        assert rep.errors == []
        assert rep.exams >= 20
        assert rep.grammar_chapters == 23
        assert rep.verbs >= 150
        assert rep.plan_days == 84
        # questions d'examen uniquement (les collections B2 v1.1 ont leurs propres questions)
        assert s.scalar(select(func.count()).select_from(Question)
                        .where(Question.exam_id.is_not(None))) == rep.exams * 50
        assert s.scalar(select(func.count()).select_from(GrammarExercise)) >= 230
    # Second passage : idempotent, aucun doublon
    with db.session() as s:
        seed_all(s)
        assert s.scalar(select(func.count()).select_from(Exam)) == rep.exams
        assert s.scalar(select(func.count()).select_from(GrammarChapter)) == 23


def test_grammar_programme_covers_the_specification(db):
    required = ["présent", "passé composé", "imparfait", "plus-que-parfait", "futur simple",
                "futur antérieur", "conditionnel", "subjonctif", "voix passive",
                "discours", "pronoms personnels", "pronoms relatifs", "prépositions",
                "articles", "accords", "adjectifs", "adverbes", "négation", "comparaison",
                "hypothèse", "phrases complexes", "concordance", "connecteurs"]
    with db.session() as s:
        seed_all(s)
        titles = " ".join(t.lower() for t in s.scalars(select(GrammarChapter.title)))
        for r in required:
            assert r in titles, r
        for ch in s.scalars(select(GrammarChapter)):
            assert len(ch.exercises) >= 10
            assert ch.simple_examples and ch.b2_examples
            for ex in ch.exercises:
                assert len(ex.explanation) > 30, f"correction trop courte : {ch.slug}"


def test_conjugation_tables_and_quiz(db):
    with db.session() as s:
        seed_all(s)
        v = s.scalar(select(Verb).where(Verb.infinitive == "aller"))
        c = v.conjugations
        assert c["present"][5] == "ils vont"
        assert c["futur_simple"][0] == "j'irai"
        assert c["subjonctif_present"][0] == "que j'aille"
        assert c["passe_compose"][3] == "nous sommes allé(e)s"
        lever = s.scalar(select(Verb).where(Verb.infinitive == "se lever")).conjugations
        assert lever["imperatif"] == ["lève-toi", "levons-nous", "levez-vous"]
        assert s.scalar(select(Verb).where(Verb.infinitive == "commencer")
                        ).conjugations["imparfait"][3] == "nous commencions"
        q = LS.conjugation_quiz(s, rng=random.Random(3))
        assert LS.check_conjugation(q["answer"], q["answer"])[0]
    assert LS.check_conjugation("sommes allées", "nous sommes allé(e)s")[0]


def test_plan_has_weekly_mock_exams(db):
    with db.session() as s:
        seed_all(s)
        mocks = s.scalars(select(PlanDay).where(PlanDay.is_mock_exam.is_not(None))).all()
        assert len(mocks) == 12
        assert sum("complet" in m.is_mock_exam for m in mocks) >= 5
        for d in s.scalars(select(PlanDay)):
            assert all({"minutes", "module", "description"} <= set(a) for a in d.activities)


def test_vocabulary_library_meets_the_specification(db):
    """Cahier des charges : 1000 expressions, 2000 mots, 500 phrases complexes,
    300 exemples d'argumentation, 200 connecteurs, chacun avec exercice corrigé."""
    with db.session() as s:
        seed_all(s)
        counts = dict(s.execute(select(Expression.kind, func.count())
                                .group_by(Expression.kind)).all())
        assert counts.get("expression", 0) >= 1000
        assert counts.get("phrase_complexe", 0) >= 500
        assert counts.get("argumentation", 0) >= 300
        assert counts.get("connecteur", 0) >= 200
        assert s.scalar(select(func.count()).select_from(VocabWord)) >= 2000
        for e in s.scalars(select(Expression)):
            assert e.meaning and e.example and e.simple_equivalent and e.level
            assert e.exercise and e.exercise_answer, e.text
        themes = {w.theme for w in s.scalars(select(VocabWord))}
        assert len(themes) >= 20
