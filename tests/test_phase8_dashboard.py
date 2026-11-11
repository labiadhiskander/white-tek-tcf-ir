"""Phase 8 : tableau de bord, préparation prudente, régularité, recommandations."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from datetime import date, datetime, timedelta

import pytest
from PySide6.QtWidgets import QApplication
from sqlalchemy import select

from tcfmaster.content.seeder import seed_all
from tcfmaster.core.app_context import AppContext
from tcfmaster.core.logging_setup import setup_logging
from tcfmaster.db.models import (Attempt, ErrorLog, Exam, PlanDay, PlanProgress, ReviewItem,
                                 StudySession)
from tcfmaster.services import exam_service as ES
from tcfmaster.services import progress as PR


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def _attempt(s, exam, results, sections=("CO", "CE"), good=True):
    a = ES.start_attempt(s, exam.id, list(sections))
    for q in exam.questions:
        if q.section in sections:
            ES.record_answer(s, a, q, "B" if good else "A")
    ES.finish_attempt(s, a, results)
    return a


def test_ready_requires_full_mock_exams(db, content_root):
    with db.session() as s:
        seed_all(s, content_root)
        exam = s.execute(select(Exam)).scalar_one()
        # 3 bons résultats, mais seulement CO/CE : jamais « prêt »
        for _ in range(3):
            _attempt(s, exam, {})
        d = PR.dashboard(s)
        assert d["ready"] is False and d["full_exams"] == 0
        assert "examens blancs complets" in d["verdict"]
        # 1 examen complet ne suffit pas, même excellent
        _attempt(s, exam, {"EE": {"note20": 15}, "EO": {"note20": 15}})
        assert PR.dashboard(s)["ready"] is False


def test_single_great_score_is_never_enough(db, content_root):
    with db.session() as s:
        seed_all(s, content_root)
        exam = s.execute(select(Exam)).scalar_one()
        _attempt(s, exam, {"EE": {"note20": 19}, "EO": {"note20": 19}})
        d = PR.dashboard(s)
        assert d["ready"] is False
        rows = {r.section: r for r in d["readiness"]}
        assert rows["EE"].status == "à confirmer" and "Encore 2" in rows["EE"].advice


def test_recent_weak_result_blocks_readiness(db, content_root):
    with db.session() as s:
        seed_all(s, content_root)
        exam = s.execute(select(Exam)).scalar_one()
        for ee in (14, 14, 8, 14):
            _attempt(s, exam, {"EE": {"note20": ee}, "EO": {"note20": 12}})
        d = PR.dashboard(s)
        rows = {r.section: r for r in d["readiness"]}
        assert rows["EE"].status == "à confirmer" and rows["EE"].weakest_recent_level == "B1"
        assert rows["EO"].status == "stabilisé"
        assert d["ready"] is False and "Expression écrite" in d["verdict"]
        assert d["full_exams"] == 4


def test_activity_and_training_time(db, content_root):
    with db.session() as s:
        seed_all(s, content_root)
        exam = s.execute(select(Exam)).scalar_one()
        today = date.today()
        s.add(StudySession(module="grammaire:x", started_at=datetime.now(), duration_s=1200))
        s.add(StudySession(module="perso", started_at=datetime.now() - timedelta(days=40),
                           duration_s=600))
        a = _attempt(s, exam, {})
        a.started_at = datetime.now() - timedelta(days=2, minutes=30)
        a.finished_at = a.started_at + timedelta(minutes=30)
        b = _attempt(s, exam, {})            # tentative oubliée : plafonnée
        b.started_at = datetime.now() - timedelta(days=5)
        b.finished_at = datetime.now() - timedelta(days=1)
        act = PR.activity_by_day(s, 28, today)
        assert len(act) == 28 and act[today] == pytest.approx(20)
        assert act[today - timedelta(days=2)] == pytest.approx(30)
        assert act[today - timedelta(days=5)] == pytest.approx(PR.MAX_ATTEMPT_S / 60)
        assert PR.total_training_minutes(s) == 20 + 10 + 30 + PR.MAX_ATTEMPT_S // 60


def test_recommendations_are_concrete_and_prioritised(db, content_root):
    with db.session() as s:
        seed_all(s, content_root)
        exam = s.execute(select(Exam)).scalar_one()
        recs = PR.recommendations(s)
        assert {r.page for r in recs} >= {"co", "ce", "ee", "eo", "mock"}
        _attempt(s, exam, {"EE": {"note20": 7}, "EO": {"note20": 12}})
        for _ in range(6):
            s.add(ErrorLog(source="EE", category="Registre", excerpt="x", rule="[familier] x"))
        s.add(ReviewItem(item_type="vocab", item_id=1, due=date.today()))
        old = datetime.now() - timedelta(days=5)
        for a in s.execute(select(Attempt)).scalars():
            a.started_at = a.finished_at = old
        recs = PR.recommendations(s)
        texts = " | ".join(r.text for r in recs)
        assert recs[0].priority == 1
        assert "expression écrite" in texts and "Registre" in texts
        assert "à réviser" in texts and "5 jours" in texts
        assert any(r.page == "custom" and r.priority == 1 for r in recs)


def test_plan_progress(db):
    with db.session() as s:
        seed_all(s)
        pp = PR.plan_progress(s)
        assert pp["weeks"] == 12 and pp["done"] == 0 and pp["current_week"] == 1
        days = list(s.execute(select(PlanDay).where(PlanDay.week == 1)).scalars())
        for d in days:
            for i, _ in enumerate(d.activities):
                s.add(PlanProgress(plan_day_id=d.id, activity_index=i))
        s.flush()
        pp = PR.plan_progress(s)
        assert pp["current_week"] == 2 and 0 < pp["percent"] < 20


def test_dashboard_page_renders(db, tmp_paths, qapp):
    with db.session() as s:
        seed_all(s)
        exam = s.execute(select(Exam).order_by(Exam.code)).scalars().first()
        _attempt(s, exam, {"EE": {"note20": 9}, "EO": {"note20": 11}})
    ctx = AppContext(paths=tmp_paths, db=db, log=setup_logging(tmp_paths.logs))
    from tcfmaster.ui.pages.dashboard_page import DashboardPage, level_value
    p = DashboardPage(ctx)
    p.refresh()
    assert "Pas encore prêt" in p.verdict.text()
    assert p.table.rowCount() == 4 and p.table.item(2, 3).text() == "insuffisant"
    assert p.kpis["full"].value.text().startswith("1")
    assert p.kpis["ee"].value.text() == "9.0 / 20"
    assert p.rec_holder is not None and p.recs
    assert len(p.activity.series()) == 1
    assert level_value("EE", 10) == pytest.approx(4) and level_value("CO", 450) == 4.5
    p.refresh()                                   # un second rafraîchissement ne duplique rien
    assert p.rec_box.count() == 1
