"""Phase 2 : interface graphique (exécutée hors écran)."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication, QMessageBox
from sqlalchemy import select

from tcfmaster.content.seeder import seed_all
from tcfmaster.core.app_context import AppContext
from tcfmaster.core.logging_setup import setup_logging
from tcfmaster.db.models import Attempt, Exam
from tcfmaster.services import exam_service as ES
from tcfmaster.services import settings as S


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    from tcfmaster.ui.theme import STYLESHEET
    app.setStyleSheet(STYLESHEET)
    return app


@pytest.fixture
def ctx(db, tmp_paths, content_root, qapp):
    with db.session() as s:
        seed_all(s, content_root)
    return AppContext(paths=tmp_paths, db=db, log=setup_logging(tmp_paths.logs))


def test_main_window_has_all_entries_and_all_pages_render(ctx):
    from tcfmaster.ui.main_window import MAIN_MENU_SIZE, MainWindow
    w = MainWindow(ctx)
    assert w.nav.count() == MAIN_MENU_SIZE >= 16   # 15 entrées v1.0 + bibliothèque B2
    for i in range(MAIN_MENU_SIZE):
        w.nav.setCurrentRow(i)
        assert w.stack.currentIndex() == i
    w.close()


def test_countdown_timer_expires(qapp):
    from tcfmaster.ui.widgets import CountdownTimer
    t = CountdownTimer(3, low_threshold=1)
    hit = []
    t.expired.connect(lambda: hit.append(1))
    t.advance(2)
    assert t.remaining == 1 and t.objectName() == "TimerLow" and not hit
    t.advance(5)
    assert t.remaining == 0 and hit == [1]


def test_mcq_runner_exam_mode(ctx):
    from tcfmaster.ui.mcq_runner import McqRunner
    with ctx.db.session() as s:
        exam = s.execute(select(Exam)).scalar_one()
        qids = [q.id for q in exam.questions_for("CO")]
        aid = ES.start_attempt(s, exam.id, ["CO"], ES.MODE_EXAM).id
    r = McqRunner(ctx, aid, "CO", qids, ES.MODE_EXAM)
    done = []
    r.finished.connect(done.append)
    assert not r.prev_btn.isVisible() or r.prev_btn.isHidden()
    assert r.timer.total == 20 * 60
    # une seule écoute en mode examen
    r._play(); assert not r.play_btn.isEnabled()
    for i in range(25):
        r.select("B" if i % 2 == 0 else "A")
        r.next()
    assert done == [aid]
    with ctx.db.session() as s:
        res = s.get(Attempt, aid).results
        assert res["CO"]["correct"] == 13 and res["CO"]["total"] == 25


def test_mcq_runner_timeout_finishes(ctx):
    from tcfmaster.ui.mcq_runner import McqRunner
    with ctx.db.session() as s:
        exam = s.execute(select(Exam)).scalar_one()
        qids = [q.id for q in exam.questions_for("CE")]
        aid = ES.start_attempt(s, exam.id, ["CE"], ES.MODE_EXAM).id
    r = McqRunner(ctx, aid, "CE", qids, ES.MODE_EXAM)
    assert r.timer.total == 35 * 60
    done = []
    r.finished.connect(done.append)
    r.select("B"); r.next()
    r.timer.advance(35 * 60)
    assert done == [aid]
    with ctx.db.session() as s:
        assert s.get(Attempt, aid).results["CE"]["correct"] == 1


def test_mcq_runner_training_immediate_correction(ctx):
    from tcfmaster.ui.mcq_runner import McqRunner
    with ctx.db.session() as s:
        S.set_(s, "correction_mode", "immediate")
        exam = s.execute(select(Exam)).scalar_one()
        qids = [q.id for q in exam.questions_for("CO")][:3]
        aid = ES.start_attempt(s, None, ["CO"], ES.MODE_TRAINING).id
    r = McqRunner(ctx, aid, "CO", qids, ES.MODE_TRAINING, time_limit=300)
    r._play(); r._play()
    assert r.play_btn.isEnabled()  # réécoute autorisée
    r.select("A"); r.check()
    assert r.feedback.isVisibleTo(r)
    assert "bonne réponse est" in r.feedback.toPlainText()
    assert "Transcription" in r.document.toPlainText()
    assert not r.choice_btns[0].isEnabled()


def test_full_exam_session_co_ce(ctx):
    from tcfmaster.ui.exam_session import ExamSession
    with ctx.db.session() as s:
        exam_id = s.execute(select(Exam)).scalar_one().id
    sess = ExamSession(ctx, exam_id, ["CO", "CE"], ES.MODE_EXAM)
    done = []
    sess.finished.connect(done.append)
    for _ in range(2):
        sess.intro_button.click()
        for _ in range(25):
            sess.current.select("B")
            sess.current.next()
    assert done == [sess.attempt_id]
    with ctx.db.session() as s:
        res = s.get(Attempt, sess.attempt_id).results
        assert res["CO"]["correct"] == 25 and res["CE"]["correct"] == 25


def test_comprehension_training_page(ctx):
    from tcfmaster.ui.pages.exam_pages import ComprehensionPage
    p = ComprehensionPage(ctx, "CE")
    p.refresh()
    assert "25 questions" in p.available.text()
    r = p.start()
    assert len(r.qids) == 10
    for _ in range(10):
        r.select("B"); r.next()
    assert "Résultats" in p.results.toPlainText()
    assert "Correction" in p.results.toPlainText()


def test_settings_page_backup(ctx, monkeypatch):
    from tcfmaster.ui.pages.misc_pages import SettingsPage
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
    p = SettingsPage(ctx)
    p.refresh()
    p._backup()
    assert p.backups.count() >= 1
