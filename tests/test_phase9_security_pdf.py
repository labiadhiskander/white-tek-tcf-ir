"""Phase 9 : export PDF, sécurité (secrets, journaux), effacement des données."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import logging
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication, QMessageBox
from sqlalchemy import func, select

from tcfmaster.content.seeder import seed_all
from tcfmaster.core import levels as L
from tcfmaster.core.app_context import AppContext
from tcfmaster.core.logging_setup import setup_logging
from tcfmaster.db.models import (Answer, Attempt, ErrorLog, Exam, Profile, ReviewItem,
                                 SpeakingSubmission, StudySession, VocabWord,
                                 WritingSubmission)
from tcfmaster.services import exam_service as ES
from tcfmaster.services import pdf_export as PDF
from tcfmaster.services import privacy as PV
from tcfmaster.services import settings as S
from tcfmaster.services import speaking_service as SS
from tcfmaster.services import writing_service as WS

TEXT = ("Madame, je vous écris parce que je souhaite m'inscrire au cours de français. "
        "Si il est possible, je voudrais commencer le mois prochain. Cordialement.")


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def pdf_text(path: Path) -> str:
    """Texte brut d'un PDF non compressé (polices standard) pour les vérifications."""
    raw = Path(path).read_bytes()
    assert raw.startswith(b"%PDF")
    return raw.decode("latin-1")


def _full_attempt(s):
    exam = s.execute(select(Exam).order_by(Exam.code)).scalars().first()
    a = ES.start_attempt(s, exam.id, ["CO", "CE", "EE", "EO"], ES.MODE_EXAM)
    for q in exam.questions[:10]:
        ES.record_answer(s, a, q, "B")
    wt = sorted(exam.writing_tasks, key=lambda t: t.task_number)
    for t in wt:
        WS.submit(s, t.id, TEXT, attempt_id=a.id)
    st = exam.speaking_tasks[0]
    SS.submit(s, st.id, "bonjour je m'appelle Ana je travaille comme infirmière " * 4,
              duration_s=90, attempt_id=a.id)
    ES.finish_attempt(s, a, {"EE": WS.attempt_result(s, a.id, [t.id for t in wt]),
                             "EO": {"note20": 9.0, "level": "B1"}})
    return a


# ---------------------------------------------------------------- PDF
@pytest.fixture
def helvetica(monkeypatch):
    """Police standard : le texte reste lisible dans le PDF non compressé."""
    monkeypatch.setattr(PDF, "_FONTS", ("Helvetica", "Helvetica-Bold"))


def test_export_attempt_pdf(db, tmp_path, helvetica):
    with db.session() as s:
        seed_all(s)
        a = _full_attempt(s)
        out = PDF.export_attempt(s, a.id, tmp_path / "r.pdf", compress=False)
    txt = pdf_text(out)
    assert "Synth" in txt and "699" in txt
    assert "France" in txt and "officiel" in txt           # mention sur chaque page
    assert txt.count("officiel de France") >= 3              # synthèse + pages EE/EO
    assert "Expression" in txt and "Crit" in txt and "che 1" in txt   # « Tâche 1 »


def test_export_progress_pdf(db, tmp_path, helvetica):
    with db.session() as s:
        seed_all(s)
        _full_attempt(s)
        out = PDF.export_progress(s, tmp_path / "sub" / "bilan.pdf", compress=False)
    txt = pdf_text(out)
    assert "Bilan de progression" in txt and "Pas encore pr" in txt
    assert "Recommandations" in txt


def test_export_unknown_attempt(db, tmp_path):
    with db.session() as s, pytest.raises(ValueError):
        PDF.export_attempt(s, 999, tmp_path / "x.pdf")


def test_compressed_pdf_is_valid(db, tmp_path):
    with db.session() as s:
        seed_all(s)
        out = PDF.export_progress(s, tmp_path / "c.pdf")
    raw = out.read_bytes()
    assert raw.startswith(b"%PDF") and b"%%EOF" in raw[-64:]
    assert b"FlateDecode" in raw


# ---------------------------------------------------------------- secrets
def test_redaction_masks_keys():
    s = "clé sk-ant-api03-ABCDEFGHIJKLMNOP et api_key=secret123 Authorization: Bearer xyz"
    out = PV.redact(s)
    assert "ABCDEFGH" not in out and "secret123" not in out and "xyz" not in out
    assert "api_key=***" in out


def test_logs_never_contain_api_keys(tmp_path):
    logger = setup_logging(tmp_path / "logs")
    handlers = [h for h in logger.handlers if isinstance(h, logging.FileHandler)]
    assert handlers and all(any(isinstance(f, PV.SecretFilter) for f in h.filters)
                            for h in logger.handlers)
    logger.warning("Échec avec la clé %s", "sk-ant-api03-TOPSECRETVALUE123")
    for h in handlers:
        h.flush()
    content = "".join(Path(h.baseFilename).read_text(encoding="utf-8") for h in handlers)
    assert "TOPSECRETVALUE" not in content and "clé masquée" in content


def test_settings_refuse_secrets(db):
    with db.session() as s:
        for key in ("api_key", "anthropic_api_key", "token", "password"):
            with pytest.raises(ValueError):
                S.set_(s, key, "sk-ant-xxx")
        S.set_(s, "ai_model", "claude-opus-5-5")          # les réglages normaux passent


def test_no_secret_in_source_tree():
    root = Path(__file__).resolve().parents[1] / "tcfmaster"
    for p in root.rglob("*.py"):
        txt = p.read_text(encoding="utf-8")
        assert "sk-ant-api" not in txt, p


# ---------------------------------------------------------------- effacement
def test_purge_learning_data_keeps_content(db, tmp_paths):
    rec = tmp_paths.recordings
    (rec / "eo_test.wav").write_bytes(b"RIFF")
    with db.session() as s:
        seed_all(s)
        _full_attempt(s)
        s.add(ErrorLog(source="EE", category="x"))
        s.add(ReviewItem(item_type="vocab", item_id=1))
        s.add(StudySession(module="perso", duration_s=60))
        s.execute(select(Profile)).scalars().first() or s.add(Profile())
        n_vocab = s.execute(select(func.count(VocabWord.id))).scalar_one()
    counts = PV.purge_learning_data(db, rec)
    assert counts["tentatives"] == 1 and counts["enregistrements"] == 1
    with db.session() as s:
        for model in (Attempt, Answer, WritingSubmission, SpeakingSubmission, ErrorLog,
                      ReviewItem, StudySession):
            assert s.execute(select(func.count(model.id))).scalar_one() == 0, model
        assert s.execute(select(func.count(VocabWord.id))).scalar_one() == n_vocab
    assert not any(rec.iterdir())
    assert any("avant-effacement" in b.name for b in db.list_backups())


# ---------------------------------------------------------------- interface
def test_history_and_dashboard_pdf_buttons(db, tmp_paths, qapp, monkeypatch, tmp_path):
    from PySide6.QtWidgets import QFileDialog

    from tcfmaster.ui.pages.dashboard_page import DashboardPage
    from tcfmaster.ui.pages.misc_pages import HistoryPage, SettingsPage
    with db.session() as s:
        seed_all(s)
        _full_attempt(s)
    ctx = AppContext(paths=tmp_paths, db=db, log=setup_logging(tmp_paths.logs))
    target = tmp_path / "hist.pdf"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **k: (str(target), ""))
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Yes)
    h = HistoryPage(ctx)
    h.refresh()
    h.table.selectRow(0)
    h._export()
    assert target.read_bytes().startswith(b"%PDF")
    d = DashboardPage(ctx)
    d.refresh()
    out = d.export_pdf(str(tmp_path / "bilan.pdf"))
    assert Path(out).read_bytes().startswith(b"%PDF")
    sp = SettingsPage(ctx)
    sp.refresh()
    sp._purge()
    with db.session() as s:
        assert s.execute(select(func.count(Attempt.id))).scalar_one() == 0
    assert L.DISCLAIMER
