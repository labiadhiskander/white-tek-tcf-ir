"""Phase 1 : base de données, contenu, scoring, sauvegarde/restauration."""
import copy
import json
import sqlite3
from datetime import date

import pytest
from sqlalchemy import select

from conftest import make_exam
from tcfmaster.content import validator as V
from tcfmaster.content.seeder import import_exam, seed_all
from tcfmaster.core import levels as L
from tcfmaster.db.database import Database, integrity_ok
from tcfmaster.db.models import Answer, Exam, Question, ReviewItem
from tcfmaster.services import exam_service as ES
from tcfmaster.services import progress, review, settings


# ---------------------------------------------------------------- validator
def test_valid_exam_passes():
    assert V.validate_exam(make_exam()) == []


def test_two_correct_answers_detected():
    ex = make_exam()
    ex["CO"][3]["choices"][0]["correct"] = True
    errs = V.validate_exam(ex)
    assert any("2 bonne(s) réponse(s)" in e for e in errs)


def test_wrong_question_count_detected():
    ex = make_exam()
    ex["CE"].pop()
    assert any("24 questions" in e for e in V.validate_exam(ex))


def test_word_limits_enforced():
    ex = make_exam()
    ex["EE"][0]["model_answer"] = " ".join(["mot"] * 61)
    assert any("61 mots" in e for e in V.validate_exam(ex))
    ex = make_exam()
    ex["EE"][1]["max_words"] = 120
    assert any("limites" in e for e in V.validate_exam(ex))


def test_speaking_durations_enforced():
    ex = make_exam()
    ex["EO"][2]["duration_s"] = 180
    assert any("210" in e for e in V.validate_exam(ex))


def test_count_words_french():
    assert V.count_words("L'école est porte-monnaie, aujourd’hui !") == 4
    assert V.count_words("") == 0


# ------------------------------------------------------------------ seeding
def test_seed_and_idempotent(db, content_root):
    with db.session() as s:
        rep = seed_all(s, content_root)
        assert rep.exams == 1 and rep.errors == []
    with db.session() as s:
        ids = sorted(q.id for q in s.execute(select(Question)).scalars())
        assert len(ids) == 50
        seed_all(s, content_root)
    with db.session() as s:
        assert sorted(q.id for q in s.execute(select(Question)).scalars()) == ids


def test_content_update_preserves_ids_and_history(db):
    data = make_exam()
    with db.session() as s:
        exam = import_exam(s, data)
        s.flush()
        a = ES.start_attempt(s, exam.id, ["CO"])
        q = exam.questions_for("CO")[0]
        ES.record_answer(s, a, q, "B")
        qid = q.id
    data2 = copy.deepcopy(data)
    data2["CO"][0]["prompt"] = "Question corrigée ?"
    with db.session() as s:
        import_exam(s, data2)
    with db.session() as s:
        q = s.get(Question, qid)
        assert q.prompt == "Question corrigée ?"
        assert s.execute(select(Answer)).scalar_one().question_id == qid


def test_invalid_exam_skipped_in_strict_mode(db, tmp_path):
    root = tmp_path / "c"
    (root / "exams").mkdir(parents=True)
    bad = make_exam("BAD")
    bad["CO"][0]["choices"][2]["correct"] = True
    (root / "exams" / "bad.json").write_text(json.dumps(bad), encoding="utf-8")
    with db.session() as s:
        rep = seed_all(s, root)
        assert rep.exams == 0 and rep.errors
        assert s.execute(select(Exam)).first() is None


# ------------------------------------------------------------------ scoring
def test_levels_bands():
    assert L.comprehension_level(399) == "B1"
    assert L.comprehension_level(400) == "B2"
    assert L.expression_level(9.5) == "B1"
    assert L.expression_level(10) == "B2"
    assert L.expression_level(14) == "C1"


def test_full_attempt_scoring(db, content_root):
    with db.session() as s:
        seed_all(s, content_root)
        exam = s.execute(select(Exam)).scalar_one()
        a = ES.start_attempt(s, exam.id, ["CO", "CE"], ES.MODE_EXAM)
        for q in exam.questions_for("CO"):
            ES.record_answer(s, a, q, "B")          # tout juste
        for q in exam.questions_for("CE")[:10]:
            ES.record_answer(s, a, q, "A")          # 10 faux, 15 sans réponse
        res = ES.finish_attempt(s, a, {"EE": {"note20": 11}})
        assert res["CO"] == {"score": 699, "level": "C2", "correct": 25, "total": 25}
        assert res["CE"]["correct"] == 0 and res["CE"]["total"] == 25
        assert res["EE"]["level"] == "B2"
        assert "officiel" in res["disclaimer"]
        with pytest.raises(RuntimeError):
            ES.record_answer(s, a, exam.questions_for("CO")[0], "A")


def test_replay_only_in_training():
    assert ES.can_replay(ES.MODE_TRAINING)
    assert not ES.can_replay(ES.MODE_EXAM)
    assert ES.time_limit("CO") == 1200 and ES.time_limit("CE") == 2100
    assert ES.time_limit("EE") == 1800 and ES.time_limit("EO") == 600


# ---------------------------------------------------------------- readiness
def test_not_ready_after_single_good_score(db, content_root):
    with db.session() as s:
        seed_all(s, content_root)
        exam = s.execute(select(Exam)).scalar_one()
        a = ES.start_attempt(s, exam.id, ["CO", "CE"])
        for q in exam.questions:
            ES.record_answer(s, a, q, "B")
        ES.finish_attempt(s, a, {"EE": {"note20": 15}, "EO": {"note20": 15}})
        d = progress.dashboard(s)
        assert d["ready"] is False
        assert d["exams_done"] == 1
        assert d["co_rate"] == 100.0
        for _ in range(2):
            a = ES.start_attempt(s, exam.id, ["CO", "CE"])
            for q in exam.questions:
                ES.record_answer(s, a, q, "B")
            ES.finish_attempt(s, a, {"EE": {"note20": 12}, "EO": {"note20": 12}})
        assert progress.dashboard(s)["ready"] is True


def test_alert_below_b2(db, content_root):
    with db.session() as s:
        seed_all(s, content_root)
        exam = s.execute(select(Exam)).scalar_one()
        a = ES.start_attempt(s, exam.id, ["CO"])
        ES.finish_attempt(s, a, {"EE": {"note20": 7}})
        al = progress.dashboard(s)["alerts"]
        assert any("Expression écrite" in x and "inférieur" in x for x in al)


# ---------------------------------------------------------------- review
def test_spaced_repetition():
    it = ReviewItem(item_type="vocab", item_id=1, easiness=2.5, interval_days=0,
                    repetitions=0)
    d0 = date(2026, 1, 1)
    review.schedule(it, 5, d0); assert it.interval_days == 1
    review.schedule(it, 5, d0); assert it.interval_days == 6
    review.schedule(it, 4, d0); assert it.interval_days >= 15
    review.schedule(it, 1, d0); assert it.interval_days == 1 and it.repetitions == 0


# ---------------------------------------------------------------- settings
def test_settings_roundtrip(db):
    with db.session() as s:
        assert settings.get(s, "correction_mode") == "fin"
        settings.set_(s, "correction_mode", "immediate")
    with db.session() as s:
        assert settings.get(s, "correction_mode") == "immediate"


# ---------------------------------------------------------- backup/restore
def test_backup_and_restore(db, content_root):
    with db.session() as s:
        seed_all(s, content_root)
    b = db.backup("manuel")
    assert integrity_ok(b)
    with db.session() as s:
        s.delete(s.execute(select(Exam)).scalar_one())
    with db.session() as s:
        assert s.execute(select(Exam)).first() is None
    db.restore(b)
    with db.session() as s:
        assert s.execute(select(Exam)).scalar_one().code == "TEST-01"


def test_auto_recovery_from_corruption(tmp_paths, content_root):
    d = Database(tmp_paths.database, tmp_paths.backups).open()
    with d.session() as s:
        seed_all(s, content_root)
    d.backup("auto")
    d.close()
    for suffix in ("-wal", "-shm"):
        p = tmp_paths.database.parent / (tmp_paths.database.name + suffix)
        if p.exists():
            p.unlink()
    raw = bytearray(tmp_paths.database.read_bytes())
    raw[0:16] = b"CORRUPTED!!!!!!!"
    tmp_paths.database.write_bytes(bytes(raw))
    assert not integrity_ok(tmp_paths.database)
    d2 = Database(tmp_paths.database, tmp_paths.backups).open()
    with d2.session() as s:
        assert s.execute(select(Exam)).scalar_one().code == "TEST-01"
    d2.close()


def test_backup_rotation(db):
    for _ in range(20):
        db.backup("auto")
    assert len(list(db.backup_dir.glob("tcfmaster-auto-*.sqlite3"))) == 15


def test_bootstrap(tmp_paths, monkeypatch):
    from tcfmaster.core.app_context import bootstrap
    ctx = bootstrap(tmp_paths)
    assert ctx.db.schema_version() == "2"   # v1.1 : schéma 2 (collections B2)
    con = sqlite3.connect(str(tmp_paths.database))
    assert con.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    con.close()
    ctx.db.close()
