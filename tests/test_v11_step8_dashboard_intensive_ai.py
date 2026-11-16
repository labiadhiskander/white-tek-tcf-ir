"""v1.1 étape 8 : programme intensif 30 jours, tableau de bord enrichi, IA locale."""
import importlib.util
import io
import json
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import select

from tcfmaster.content.seeder import content_dir, seed_all
from tcfmaster.core import levels as L
from tcfmaster.db.models import (Attempt, Collection, Exam, Exercise, IntensiveDay,
                                 ReviewItem, WritingTask)
from tcfmaster.services import collections as COL
from tcfmaster.services import intensive as IS
from tcfmaster.services import progress as PR
from tcfmaster.services import review as RV
from tcfmaster.services import settings as S
from tcfmaster.services import writing_service as WS
from tcfmaster.services.ai import local_llm as LL
from tcfmaster.services.ai.base import AIUnavailable, Conversation
from tcfmaster.services.ai.tutor import PROVIDER_LOCAL_LLM, PROVIDERS, TutorService

SKILLS = ("Compréhension orale", "Compréhension écrite", "Expression écrite",
          "Expression orale")


def _intensive():
    return json.loads((content_dir() / "intensive.json").read_text(encoding="utf-8"))


def _builder():
    path = Path(__file__).resolve().parents[1] / "tools" / "build_intensive.py"
    spec = importlib.util.spec_from_file_location("build_intensive", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ------------------------------------------------------------- contenu
def test_intensive_program_four_skills_daily_and_mock_days():
    days = _intensive()
    assert [d["day"] for d in days] == list(range(1, 31))
    for d in days:
        mods = [a["module"] for a in d["activities"]]
        assert all(sk in mods for sk in SKILLS), d["day"]
        assert all(a["minutes"] > 0 and a["description"] and a["ref"] for a in d["activities"])
    mocks = {d["day"]: d["exam_code"] for d in days if d["is_mock_exam"]}
    assert sorted(mocks) == [10, 20, 29]
    exam_codes = {json.loads(p.read_text(encoding="utf-8"))["code"]
                  for p in (content_dir() / "exams").glob("*.json")}
    assert set(mocks.values()) <= exam_codes and all(c.startswith("B2-BLANC") for c in
                                                     mocks.values())
    total = sum(a["minutes"] for d in days for a in d["activities"])
    assert 90 * 30 <= total <= 150 * 30          # environ deux heures par jour


def test_intensive_json_is_up_to_date_and_references_real_content():
    mod = _builder()
    assert mod.build() == _intensive()          # régénérer : python tools/build_intensive.py
    assert mod.check(mod.build()) == []
    co_ce = set()
    for sec in ("co", "ce"):
        for p in (content_dir() / "collections" / sec).glob("*.json"):
            co_ce.add(json.loads(p.read_text(encoding="utf-8"))["title"])
    for day, spec in mod.DAYS.items():
        assert spec[1] in co_ce and spec[2] in co_ce, day


@pytest.fixture
def seeded(db):
    with db.session() as s:
        rep = seed_all(s)
    assert rep.errors == []
    assert rep.intensive_days == 30
    return db


def test_intensive_progress_survives_reseed_and_reset(seeded):
    with seeded.session() as s:
        d1 = s.execute(select(IntensiveDay).where(IntensiveDay.day == 1)).scalar_one()
        assert IS.start_date(s) is None
        IS.toggle(s, d1.id, 0, True)
        IS.toggle(s, d1.id, 1, True)
        IS.toggle(s, d1.id, 1, True)               # idempotent
        assert IS.start_date(s) == date.today()    # démarrage automatique
        p = IS.progress(s)
        assert p["done"] == 2 and p["current_day"] == 1 and p["calendar_day"] == 1
        for i in range(len(d1.activities)):
            IS.toggle(s, d1.id, i, True)
        assert IS.progress(s)["current_day"] == 2
        assert IS.progress(s)["days_complete"] == 1
    with seeded.session() as s:
        seed_all(s)                                 # mise à jour du contenu
    with seeded.session() as s:
        assert IS.completed_count(s) == len(_intensive()[0]["activities"])
        IS.toggle(s, s.execute(select(IntensiveDay.id).where(IntensiveDay.day == 2))
                  .scalar_one(), 0, True)
        IS.toggle(s, s.execute(select(IntensiveDay.id).where(IntensiveDay.day == 2))
                  .scalar_one(), 0, False)
        assert IS.calendar_day(s, date.today() + timedelta(days=40)) == 30
        IS.reset(s)
        assert IS.completed_count(s) == 0 and IS.start_date(s) is None


def test_mock_day_is_ticked_by_a_finished_mock_exam(seeded):
    with seeded.session() as s:
        IS.start(s)
        exam = s.execute(select(Exam).where(Exam.code == "B2-BLANC-01")).scalar_one()
        res = {"CO": {"correct": 20, "total": 25, "level": "B2"},
               "CE": {"correct": 19, "total": 25, "level": "B2"},
               "EE": {"note20": 12.5, "level": "B2"}, "EO": {"note20": 11.0, "level": "B1"}}
        s.add(Attempt(exam_id=exam.id, mode="examen", sections=["CO", "CE", "EE", "EO"],
                      started_at=datetime.now(), finished_at=datetime.now(), results=res))
        s.flush()
        assert IS.sync_mock_days(s) == 4
        assert IS.sync_mock_days(s) == 0
        d10 = s.execute(select(IntensiveDay).where(IntensiveDay.day == 10)).scalar_one()
        assert IS.done_map(s)[d10.id] == {0, 1, 2, 3}     # l'analyse reste à cocher
        mocks = IS.progress(s)["mocks"]
        assert [m["done"] for m in mocks] == [True, False, False]
        hist = PR.mock_history(s)
        assert hist[0]["code"] == "B2-BLANC-01" and hist[0]["complete"]
        assert hist[0]["cells"]["CO"] == "20/25 (B2)" and hist[0]["cells"]["EO"] == "11.0/20 (B1)"


# ------------------------------------------------------------- vocabulaire à revoir
def _missed_series(s):
    ex = next(e for e in s.execute(select(Exercise).join(Collection)).scalars()
              if e.vocabulary)
    a = COL.start_series(s, [ex.id], "entrainement")
    for q in ex.questions:
        wrong = next(c for c in q.choices if not c.is_correct)
        COL.record(s, a, q, wrong.label)
    COL.finish_series(s, a)
    return ex


def test_missed_questions_feed_spaced_vocabulary(seeded):
    with seeded.session() as s:
        ex = _missed_series(s)
        c = RV.lexicon_counts(s)
        assert c["total"] == len(ex.vocabulary) and c["due"] == c["total"]
        due = RV.lexicon_due(s)
        assert due[0]["term"] == ex.vocabulary[0]["terme"] and ex.code in due[0]["source"]
        RV.review(s, RV.LEXICON, due[0]["item_id"], 5)
        assert RV.lexicon_counts(s)["due"] == c["total"] - 1
        # manqué de nouveau : revu dès aujourd'hui
        it = s.execute(select(ReviewItem).where(ReviewItem.item_id == due[0]["item_id"])
                       ).scalar_one()
        assert it.due > date.today()
        RV.enqueue_lexicon(s, ex)
        assert it.due == date.today()
        d = PR.dashboard(s)
        assert d["exercises"]["series"] == 1 and d["exercises"]["questions"] == len(ex.questions)
        recs = PR.recommendations(s)
        assert any(r.page == "vocab" and "documents manqués" in r.text for r in recs)


def test_late_intensive_program_is_recommended(seeded):
    with seeded.session() as s:
        IS.start(s, date.today() - timedelta(days=5))
        recs = PR.recommendations(s)
        late = [r for r in recs if r.page == "intensive"]
        assert late and late[0].priority == 1 and "5 jour(s) de retard" in late[0].text


# ------------------------------------------------------------- IA locale
class FakeResp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class FakeOpener:
    def __init__(self, models=("mistral:latest", "llama3.1:8b"), reply="Bonjour !",
                 exc=None):
        self.calls, self.models, self.reply, self.exc = [], list(models), reply, exc

    def open(self, req, timeout=None):
        body = json.loads(req.data.decode()) if req.data else None
        self.calls.append((req.get_method(), req.full_url, body))
        if self.exc:
            raise self.exc
        if req.full_url.endswith("/models"):
            data = {"object": "list", "data": [{"id": m} for m in self.models]}
        else:
            data = {"choices": [{"message": {"role": "assistant", "content": self.reply}}]}
        return FakeResp(json.dumps(data).encode())


def test_local_llm_engine_request_shape_and_model_choice():
    op = FakeOpener(reply="<think>raisonnement caché</think>Bonjour, parlons du travail.")
    eng = LL.LocalLLMEngine("localhost:11434", "", opener=op)
    assert eng.base_url == "http://localhost:11434/v1"
    r = eng.opening(Conversation(mode="conversation"))
    assert r.text == "Bonjour, parlons du travail."
    assert eng.model == "llama3.1:8b"              # premier modèle installé (ordre alpha)
    method, url, body = op.calls[-1]
    assert method == "POST" and url == "http://localhost:11434/v1/chat/completions"
    assert body["model"] == "llama3.1:8b" and body["stream"] is False
    assert body["messages"][0]["role"] == "system" and "TCF IRN" in body["messages"][0]["content"]
    assert body["messages"][1]["role"] == "user"
    assert "IA locale joignable" in eng.ping()


def test_local_llm_errors_become_ai_unavailable():
    nf = urllib.error.HTTPError("u", 404, "not found", {}, io.BytesIO(b"model not found"))
    with pytest.raises(AIUnavailable, match="introuvable"):
        LL.LocalLLMEngine(LL.DEFAULT_URL, "absent", opener=FakeOpener(exc=nf))._call("s", [])
    down = urllib.error.URLError("refused")
    with pytest.raises(AIUnavailable, match="injoignable"):
        LL.LocalLLMEngine(LL.DEFAULT_URL, "m", opener=FakeOpener(exc=down)).list_models()
    with pytest.raises(AIUnavailable, match="Aucun modèle"):
        LL.LocalLLMEngine(LL.DEFAULT_URL, "", opener=FakeOpener(models=()))._model()
    with pytest.raises(AIUnavailable, match="absent du serveur"):
        LL.LocalLLMEngine(LL.DEFAULT_URL, "phi3", opener=FakeOpener()).ping()
    with pytest.raises(AIUnavailable):
        LL.normalize_url("ftp://serveur")


def test_local_addresses_and_proxy_bypass():
    assert LL.normalize_url("") == LL.DEFAULT_URL
    assert LL.normalize_url("http://127.0.0.1:1234/") == "http://127.0.0.1:1234/v1"
    assert LL.is_local("http://localhost:1234/v1") and LL.is_local("192.168.1.20:11434")
    assert not LL.is_local("https://api.exemple.com/v1")
    eng = LL.LocalLLMEngine("http://localhost:11434/v1", "m")
    # Aucun gestionnaire de proxy : les variables HTTP(S)_PROXY du système sont ignorées.
    assert not any(isinstance(h, urllib.request.ProxyHandler) for h in eng.opener.handlers)


@pytest.fixture
def llm_service(seeded):
    op = FakeOpener(reply="1. Consigne respectée.\n\n2. « je suis allé » → correct.")
    svc = TutorService(seeded, local_llm_factory=lambda url, model: LL.LocalLLMEngine(
        url, model, opener=op))
    with seeded.session() as s:
        S.set_(s, "ai_provider", PROVIDER_LOCAL_LLM)
        S.set_(s, "local_ai_model", "mistral:latest")
    return svc, op


def test_tutor_uses_local_llm_without_consent_and_falls_back(llm_service, seeded):
    svc, op = llm_service
    assert PROVIDER_LOCAL_LLM in PROVIDERS
    assert svc.online_engine() is not None and not svc.needs_consent()
    assert "IA locale" in svc.status() and "votre ordinateur" in svc.status()
    conv = svc.new_conversation("conversation")
    r = svc.opening(conv)
    assert r.engine.startswith("IA locale") and op.calls[-1][2]["model"] == "mistral:latest"
    op.exc = urllib.error.URLError("arrêté")
    r = svc.send(conv, "Je pense que le télétravail est utile.")
    assert "injoignable" in r.notice                 # repli sur le tuteur hors ligne
    with seeded.session() as s:
        S.set_(s, "local_ai_url", "https://ia.exemple.com/v1")
    assert svc.needs_consent()                       # adresse distante : consentement
    op.exc = None
    assert svc.list_local_models("http://localhost:11434/v1") == ["llama3.1:8b",
                                                                  "mistral:latest"]


def test_deepen_writing_keeps_local_grade_and_disclaimer(llm_service, seeded):
    svc, op = llm_service
    with seeded.session() as s:
        t = s.execute(select(WritingTask).where(WritingTask.task_number == 1)).scalars().first()
        text = ("Bonjour Marc, je t'écris pour te proposer une sortie samedi au parc. "
                "On pourrait pique-niquer vers midi. Dis-moi si tu es disponible. À bientôt !")
        sub = WS.submit(s, t.id, text)
        sid, note = sub.id, sub.note20
    out = svc.deepen("EE", sid)
    assert out.endswith(L.DISCLAIMER)
    body = op.calls[-1][2]
    user = body["messages"][1]["content"]
    assert "Bonjour Marc" in user and f"{t.min_words} à {t.max_words}" in user
    assert f"{note:.1f}/20" in user and "ne propose AUCUNE autre note" in \
        body["messages"][0]["content"]
    with pytest.raises(ValueError):
        svc.deepen("CO", sid)
    with seeded.session() as s:
        S.set_(s, "ai_provider", "local")
    with pytest.raises(AIUnavailable):
        svc.deepen("EE", sid)


# ------------------------------------------------------------- interface
@pytest.fixture
def qapp():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


@pytest.fixture
def ctx(seeded, tmp_paths, qapp, monkeypatch):
    from tcfmaster.core.app_context import AppContext
    from tcfmaster.core.logging_setup import setup_logging
    from tcfmaster.ui import speaking as SPK
    monkeypatch.setattr(SPK, "RUN_SYNC", True)
    return AppContext(paths=tmp_paths, db=seeded, log=setup_logging(tmp_paths.logs))


def test_intensive_page_and_dashboard(ctx):
    from tcfmaster.ui.main_window import MENU
    from tcfmaster.ui.pages.dashboard_page import DashboardPage
    from tcfmaster.ui.pages.intensive_page import IntensivePage
    assert "intensive" in [m[0] for m in MENU]
    p = IntensivePage(ctx)
    p.refresh()
    assert p.days.count() == 30 and len(p.boxes) == 5
    assert p.start_btn.isVisible() or not p.isVisible()
    p.boxes[0].setChecked(True)
    with ctx.db.session() as s:
        assert IS.completed_count(s) == 1 and IS.start_date(s) == date.today()
    p.days.setCurrentRow(9)
    assert "Examen blanc B2 n° 1" in p.day_title.text() and "B2-BLANC-01" in p.mock_info.text()
    p.reset(confirm=False)
    with ctx.db.session() as s:
        assert IS.completed_count(s) == 0
        _missed_series(s)
    d = DashboardPage(ctx)
    d.refresh()
    assert "1 série" in d.kpis["exercises"].value.text()
    assert "•" in d.lexicon.text()
    assert d.mock_empty.isVisibleTo(d) and not d.mock_table.isVisibleTo(d)


def test_deepen_button_and_ai_settings(ctx, llm_service):
    from tcfmaster.ui.ai_settings import AISettingsCard
    from tcfmaster.ui.pages.writing_page import WritingPage
    svc, op = llm_service
    ctx.tutor = svc
    card = AISettingsCard(ctx)
    card.refresh()
    assert card.llm_box.isVisibleTo(card) and card.llm_url.text() == LL.DEFAULT_URL
    assert not card.key.isEnabled()
    card._models_listed(["llama3.1:8b", "mistral:latest"])
    assert card.llm_model.currentText() == "mistral:latest"   # choix conservé
    card.llm_preset.setCurrentIndex(card.llm_preset.findData("lmstudio"))
    card._preset_chosen()
    with ctx.db.session() as s:
        assert S.get(s, "local_ai_url") == "http://localhost:1234/v1"
    wp = WritingPage(ctx)
    wp.refresh()
    with ctx.db.session() as s:
        t = s.execute(select(WritingTask).where(WritingTask.task_number == 3)).scalars().first()
        tid = t.id
    wp.open_task(tid)
    wp.editor.edit.setPlainText("D'un côté, le télétravail fait gagner du temps. De l'autre, "
                                "il isole. À mon avis, deux jours par semaine suffisent.")
    wp.submit_training()
    assert wp.deepen_btn.isVisibleTo(wp)
    wp.deepen_btn.run()
    assert "Correction approfondie" in wp.report.toHtml()
    assert wp.deepen_btn.last_text.endswith(L.DISCLAIMER)
