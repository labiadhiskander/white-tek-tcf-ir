"""v1.1 – étape 1 : schéma v2, migration sans perte, validateur, correction unifiée,
collections B2 et bibliothèque."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import json
import shutil
import sqlite3
from pathlib import Path

import pytest
from sqlalchemy import select

from tcfmaster.content import validator as V
from tcfmaster.content.seeder import content_dir, import_collection, seed_all
from tcfmaster.db.database import SCHEMA_VERSION, Database
from tcfmaster.db.models import (Attempt, Collection, ErrorLog, Exercise, Profile, Question,
                                 Setting, SpeakingTask, WritingSubmission, WritingTask)
from tcfmaster.services import collections as COL
from tcfmaster.services import correction as C
from tcfmaster.services import exam_service as ES
from tcfmaster.services import progress as P

FIXTURE_V10 = Path(__file__).parent / "fixtures" / "base_v1_0.sqlite3"
REAL_COLLECTIONS = content_dir() / "collections"


# ------------------------------------------------------------------ migration
def test_v10_database_is_migrated_without_any_loss(tmp_path):
    db_file = tmp_path / "tcfmaster.sqlite3"
    shutil.copy2(FIXTURE_V10, db_file)
    con = sqlite3.connect(db_file)
    before = {t: con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
              for t in ("exams", "questions", "choices", "attempts", "answers",
                        "writing_submissions", "error_log", "settings", "profile")}
    assert con.execute("SELECT value FROM schema_info WHERE key='schema_version'"
                       ).fetchone()[0] == "1"
    con.close()

    db = Database(db_file, tmp_path / "sauvegardes").open()
    try:
        assert db.schema_version() == SCHEMA_VERSION == "2"
        # sauvegarde complète prise avant la migration
        assert list((tmp_path / "sauvegardes").glob("tcfmaster-avant-migration-v1-*"))
        con = sqlite3.connect(db_file)
        after = {t: con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in before}
        cols = {r[1] for r in con.execute("PRAGMA table_info(questions)")}
        wcols = {r[1] for r in con.execute("PRAGMA table_info(writing_tasks)")}
        tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        con.close()
        assert after == before                         # aucune ligne perdue
        assert "exercise_id" in cols and {"code", "theme", "status"} <= wcols
        assert {"collections", "exercises", "videos", "intensive_days"} <= tables
        with db.session() as s:
            assert s.execute(select(Profile)).scalar_one().name == "Candidat v1.0"
            a = s.execute(select(Attempt)).scalar_one()
            assert a.results["CO"]["total"] == 25 and a.results["CO"]["correct"] == 10
            assert s.execute(select(WritingSubmission)).scalar_one().note20 == 12.0
            assert s.execute(select(ErrorLog)).scalar_one().correction == "les maisons"
            assert s.get(Setting, "theme").value == "sombre"
            # les anciennes tâches reçoivent les valeurs par défaut des nouvelles colonnes
            t = s.execute(select(WritingTask)).scalars().first()
            assert t.code is None and t.status == "valide"
    finally:
        db.close()
    # Réouverture : plus de migration, plus de sauvegarde supplémentaire
    n = len(list((tmp_path / "sauvegardes").glob("*")))
    Database(db_file, tmp_path / "sauvegardes").open().close()
    assert len(list((tmp_path / "sauvegardes").glob("*"))) == n


def test_fresh_database_is_schema_v2(db):
    assert db.schema_version() == "2"


# ------------------------------------------------------------------ validateur
def _exercise(**over):
    ex = {"code": "CE-T-01", "title": "t", "doc_type": "article", "level": "B2",
          "document": " ".join(["mot"] * 150),
          "questions": [{"prompt": "?", "explanation": "e", "skill": "implicite",
                         "choices": [{"label": l, "text": f"r{l}", "correct": l == "A",
                                      "rationale": "pourquoi"} for l in "ABCD"]}],
          "vocabulary": [{"terme": f"t{i}", "definition": "d"} for i in range(3)],
          "expressions": [{"expression": "x", "sens": "y"}],
          "traps": ["piège"]}
    ex.update(over)
    return ex


def test_validator_rejects_exercise_without_full_correction():
    assert V.validate_exercise(_exercise(), "CE") == []
    bad = _exercise()
    bad["questions"][0]["choices"][2]["rationale"] = ""
    assert any("explication manquante pour C" in e for e in V.validate_exercise(bad, "CE"))
    bad = _exercise()
    bad["questions"][0]["explanation"] = ""
    assert V.validate_exercise(bad, "CE")
    assert any("pièges" in e for e in V.validate_exercise(_exercise(traps=[]), "CE"))
    assert any("vocabulaire" in e for e in V.validate_exercise(_exercise(vocabulary=[]), "CE"))
    assert any("B2" in e for e in V.validate_exercise(_exercise(level="B1"), "CE"))
    two = _exercise()
    two["questions"][0]["choices"][1]["correct"] = True
    assert any("2 bonne(s)" in e for e in V.validate_exercise(two, "CE"))


def test_validator_enforces_official_word_limits_on_model_answers():
    t = {"code": "EE-X", "task_number": 1, "min_words": 30, "max_words": 60, "level": "B2",
         "task_type": "message", "instructions": "x", "tips": "t", "model_commentary": "c",
         "expected_points": ["a"], "model_answer": " ".join(["mot"] * 61)}
    assert any("61 mots" in e for e in V.validate_writing_subject(t))
    t["model_answer"] = " ".join(["mot"] * 60)
    assert V.validate_writing_subject(t) == []


def test_find_duplicates():
    errs = V.find_duplicates([("A", "Un texte."), ("B", "un TEXTE !"), ("C", "Autre")])
    assert len(errs) == 1 and "B" in errs[0]


# ------------------------------------------------------------------ contenu réel
def test_real_collections_are_valid_b2_and_corrected():
    files = sorted(REAL_COLLECTIONS.glob("*/*.json"))
    assert files
    docs = []
    for f in files:
        col = json.loads(f.read_text(encoding="utf-8"))
        assert V.validate_collection(col) == [], f.name
        for it in col["items"]:
            assert it.get("level", "B2") == "B2"
            docs.append((it["code"], it.get("document") or it.get("instructions")
                         or it.get("scenario")))
            if col["section"] == "EE":
                lo, hi = it["min_words"], it["max_words"]
                assert lo <= V.count_words(it["model_answer"]) <= hi, it["code"]
    assert V.find_duplicates(docs) == []


def test_sources_and_compiled_collections_are_in_sync():
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "bc", Path(__file__).parents[1] / "tools" / "build_collections.py")
    bc = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bc)
    for src in sorted(bc.SRC.glob("*/*.txt")):
        compiled = REAL_COLLECTIONS / src.parent.name / (src.stem + ".json")
        assert json.loads(compiled.read_text(encoding="utf-8")) == bc.build_file(src), src.name


@pytest.fixture
def seeded(db):
    with db.session() as s:
        rep = seed_all(s)
    return db, rep


def test_seed_real_content_without_errors_and_idempotent(seeded):
    db, rep = seeded
    assert rep.errors == []
    assert rep.collections >= 4 and rep.exercises >= 4
    with db.session() as s:
        n_q = s.execute(select(Question)).scalars().all()
        n_ex = len(s.execute(select(Exercise)).scalars().all())
        seed_all(s)
        assert len(s.execute(select(Question)).scalars().all()) == len(n_q)
        assert len(s.execute(select(Exercise)).scalars().all()) == n_ex
        ex = s.execute(select(Exercise)).scalars().first()
        assert ex.questions and all(q.exam_id is None for q in ex.questions)
        assert all(q.correct_choice is not None for q in ex.questions)


def test_locally_modified_exercise_is_never_overwritten(seeded):
    db, _ = seeded
    with db.session() as s:
        ex = s.execute(select(Exercise).where(Exercise.code == "CO-ENV-01")).scalar_one()
        ex.title = "Titre modifié par l'administrateur"
        ex.locally_modified = True
    with db.session() as s:
        data = json.loads((REAL_COLLECTIONS / "co" / "02_environnement_climat.json")
                          .read_text(encoding="utf-8"))
        data["items"][0]["title"] = "Nouveau titre livré par une mise à jour"
        import_collection(s, data)
    with db.session() as s:
        ex = s.execute(select(Exercise).where(Exercise.code == "CO-ENV-01")).scalar_one()
        assert ex.title == "Titre modifié par l'administrateur"


# ------------------------------------------------------------------ correction
def _series(db, section, mode, answers_fn):
    with db.session() as s:
        ids = [e.id for e in COL.published_exercises(s, section=section)][:2]
        a = COL.start_series(s, ids, mode)
        for i in ids:
            for q in s.get(Exercise, i).questions:
                COL.record(s, a, q, answers_fn(q))
        corr = COL.finish_series(s, a)
        return a.id, corr


def test_training_series_correction_and_results(seeded):
    db, _ = seeded
    aid, corr = _series(db, "CE", ES.MODE_TRAINING, lambda q: q.correct_choice.label)
    assert corr.correct == corr.total > 0 and corr.rate == 1.0
    q = corr.exercises[0].questions[0]
    assert q.is_correct and q.result == "Bonne réponse" and q.justification
    assert len(q.wrong_choices) == 3 and all(c.rationale for c in q.wrong_choices)
    assert corr.exercises[0].vocabulary and corr.exercises[0].traps
    with db.session() as s:
        res = s.get(Attempt, aid).results
        assert res["kind"] == "collection" and res["rate"] == 1.0


def test_exam_series_records_errors_and_does_not_count_as_official_estimate(seeded):
    db, _ = seeded

    def wrong(q):
        return next(c.label for c in q.choices if not c.is_correct)
    aid, corr = _series(db, "CO", ES.MODE_EXAM, wrong)
    assert corr.correct == 0 and corr.advice
    assert all(q.result == "Réponse incorrecte" for e in corr.exercises for q in e.questions)
    with db.session() as s:
        logs = s.execute(select(ErrorLog).where(ErrorLog.source == "CO")).scalars().all()
        assert len(logs) == corr.total
        # Une série de collection n'alimente pas l'estimation « prêt pour le B2 »
        assert P.skill_statuses(s)["CO"].history == []
        assert COL.success_rate(s, "CO") == (0, corr.total)


def test_unanswered_question_is_reported():
    class Ch:
        def __init__(self, label, ok):
            self.label, self.text, self.is_correct, self.rationale = label, label, ok, "r"

    class Q:
        id, position, prompt, skill, explanation = 1, 1, "?", "implicite", "e"
        choices = [Ch(l, l == "B") for l in "ABCD"]
        correct_choice = choices[1]
    c = C.correct_question(Q(), None)
    assert c.result == "Sans réponse" and not c.is_correct


def test_production_correction_view():
    from tcfmaster.services import writing_eval as WE
    ev = WE.evaluate("Je suis aller au marché hier et j'ai acheter des pommes.", 1, 30, 60)
    p = C.production_correction(ev.to_dict(), "texte", "Modèle B2", "EE")
    assert p["original"] == "texte" and p["model_answer"] == "Modèle B2"
    assert p["appreciation"] and "officiel" in p["disclaimer"]


def test_library_filters(seeded):
    db, _ = seeded
    with db.session() as s:
        everything = COL.library(s)
        assert {i.family for i in everything} >= {"CO", "CE", "EE", "EO", "GRAM", "VOC"}
        co = COL.library(s, "CO")
        assert co and all(i.kind == "exercise" for i in co)
        ee = COL.library(s, "EE")
        assert ee and all(i.kind == "writing" for i in ee)
        assert COL.library(s, "CE", search="vélo")
        c = COL.counts(s)
        assert c["CO"] >= 2 and c["EE"] >= 3 and c["EO"] >= 3
        assert COL.time_limit("CO", 25) == 20 * 60 and COL.time_limit("CE", 25) == 35 * 60


def test_bank_subjects_are_separate_from_exams(seeded):
    db, _ = seeded
    with db.session() as s:
        ee = COL.bank_subjects(s, "EE")
        eo = COL.bank_subjects(s, "EO", task_number=2)
        assert ee and all(t.exam_id is None and t.code for t in ee)
        assert eo and all(isinstance(t, SpeakingTask) and t.task_number == 2 for t in eo)
        assert s.execute(select(Collection).where(Collection.section == "EE")).scalars().all()


# ------------------------------------------------------------------ interface
@pytest.fixture(scope="module")
def qapp():
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    from tcfmaster.ui.theme import STYLESHEET
    app.setStyleSheet(STYLESHEET)
    return app


@pytest.fixture
def ctx(seeded, tmp_paths, qapp):
    from tcfmaster.core.app_context import AppContext
    from tcfmaster.core.logging_setup import setup_logging
    db, _ = seeded
    return AppContext(paths=tmp_paths, db=db, log=setup_logging(tmp_paths.logs))


def test_exercise_runner_training_shows_correction_immediately(ctx):
    from tcfmaster.ui.exercise_runner import ExerciseRunner
    with ctx.db.session() as s:
        ids = [e.id for e in COL.published_exercises(s, section="CO")][:1]
        aid = COL.start_series(s, ids, ES.MODE_TRAINING).id
    r = ExerciseRunner(ctx, aid, ids, ES.MODE_TRAINING)
    assert "transcription sera accessible" in r.document.toPlainText()
    assert not r.feedback.isVisibleTo(r)
    r.select(1, "A")
    r.check()
    assert r.feedback.isVisibleTo(r)
    txt = r.feedback.toPlainText()
    for part in ("Votre réponse", "Bonne réponse", "Justification", "Explication",
                 "Vocabulaire avancé", "Transcription"):
        assert part in txt
    assert r.document.toPlainText().startswith("Transcription")
    done = []
    r.finished.connect(done.append)
    r.next()
    assert done == [aid]


def test_exercise_runner_exam_mode_hides_correction_until_the_end(ctx):
    from tcfmaster.ui.exercise_runner import ExerciseRunner
    with ctx.db.session() as s:
        ids = [e.id for e in COL.published_exercises(s, section="CE")][:2]
        aid = COL.start_series(s, ids, ES.MODE_EXAM).id
    r = ExerciseRunner(ctx, aid, ids, ES.MODE_EXAM)
    assert not r.check_btn.isVisibleTo(r)
    r.select(1, "B")
    r.check()                        # sans effet en mode examen
    assert not r.feedback.isVisibleTo(r)
    r.next()
    assert not r.feedback.isVisibleTo(r)
    r.next()
    with ctx.db.session() as s:
        res = s.get(Attempt, aid).results
        assert res["kind"] == "collection" and res["total"] >= 6


def test_library_page_opens_items(ctx):
    from tcfmaster.ui.main_window import MainWindow
    w = MainWindow(ctx)
    lib = w.open_page("library")
    lib.set_filter("CE")
    assert lib.table.rowCount() >= 2
    lib.table.selectRow(0)
    runner = lib.open_selected()
    assert runner is not None and runner.section == "CE"
    lib.host.back()
    lib.set_filter("EE")
    lib.table.selectRow(0)
    editor = lib.open_selected()
    assert editor is not None and w.stack.currentWidget() is w.pages["ee"]
    w.open_page("library")
    lib.set_filter("EO")
    lib.table.selectRow(0)
    assert lib.open_selected() is not None and w.stack.currentWidget() is w.pages["eo"]
    w.close()


def test_comprehension_page_runs_a_collection_and_shows_unified_correction(ctx):
    from tcfmaster.ui.pages.exam_pages import ComprehensionPage
    p = ComprehensionPage(ctx, "CO")
    p.refresh()
    assert p.collections.collection.count() >= 2
    p.collections.collection.setCurrentIndex(1)
    p.collections.count.setValue(2)
    r = p.collections.start()
    for _ in range(len(r.ex_ids)):
        r.next()
    txt = p.results.toPlainText()
    assert "Résultats" in txt and "Conseils d'amélioration" in txt and "Justification" in txt
    assert "officiel" in txt
