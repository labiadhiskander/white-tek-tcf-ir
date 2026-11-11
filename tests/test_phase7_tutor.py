"""Phase 7 : tuteur IA (3 modes), clé API sécurisée et exercices personnalisés."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import random
from types import SimpleNamespace

import pytest
from PySide6.QtWidgets import QApplication, QLineEdit, QMessageBox
from sqlalchemy import func, select

from tcfmaster.content.seeder import seed_all
from tcfmaster.core import levels as L
from tcfmaster.core.app_context import AppContext
from tcfmaster.core.logging_setup import setup_logging
from tcfmaster.db.models import ErrorLog, Exam, Setting, StudySession
from tcfmaster.services import custom_exercises as CX
from tcfmaster.services import error_tracking as ET
from tcfmaster.services import settings as S
from tcfmaster.services import speaking_service as SS
from tcfmaster.services import writing_service as WS
from tcfmaster.services.ai import anthropic_engine as AE
from tcfmaster.services.ai.base import AIUnavailable, Conversation, Turn
from tcfmaster.services.ai.local import find_chapter_slug
from tcfmaster.services.ai.tutor import PROVIDER_ANTHROPIC, TutorService

BAD = "Il faut que tu vas au travail si il pleut."


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def seeded(db):
    with db.session() as s:
        seed_all(s)
    return db


class FakeKeyring:
    def __init__(self):
        self.store = {}

    def set_password(self, service, user, secret):
        self.store[(service, user)] = secret

    def get_password(self, service, user):
        return self.store.get((service, user))

    def delete_password(self, service, user):
        self.store.pop((service, user), None)


@pytest.fixture
def keyring(monkeypatch):
    kr = FakeKeyring()
    monkeypatch.setattr(S, "_keyring", lambda: kr)
    return kr


class FakeMessages:
    def __init__(self, text="Bonjour, je suis Claude.", stop="end_turn", exc=None):
        self.calls, self.text, self.stop, self.exc = [], text, stop, exc

    def create(self, **kw):
        self.calls.append(kw)
        if self.exc:
            raise self.exc
        return SimpleNamespace(stop_reason=self.stop,
                               content=[SimpleNamespace(type="thinking", thinking="…"),
                                        SimpleNamespace(type="text", text=self.text)])


def fake_client(**kw):
    m = FakeMessages(**kw)
    return SimpleNamespace(beta=SimpleNamespace(messages=m)), m


def online_service(db, keyring, client, consent=True):
    S.store_api_key(PROVIDER_ANTHROPIC, "sk-ant-test")
    with db.session() as s:
        S.set_(s, "ai_provider", PROVIDER_ANTHROPIC)
        S.set_(s, "ai_consent", consent)
    return TutorService(db, online_factory=lambda key, model, effort: AE.AnthropicEngine(
        key, model, effort, client=client), rng=random.Random(0))


# ---------------------------------------------------------------- tuteur local
def test_teacher_corrects_and_logs_errors(seeded):
    ts = TutorService(seeded, rng=random.Random(0))
    conv = ts.new_conversation("professeur")
    assert "professeur" in ts.opening(conv).text
    r = ts.send(conv, BAD)
    assert "s'il" in r.text and "Subjonctif" in r.text
    assert "Claude" in r.text                  # limites du tuteur local annoncées
    with seeded.session() as s:
        rows = list(s.execute(select(ErrorLog).where(ErrorLog.source == "IA")).scalars())
    assert {ET.rule_id(r) for r in rows} >= {"si-il", "subj-apres-conj"}
    assert any(r.category == "Le subjonctif présent et passé" for r in rows)
    # la correction stockée est sûre (jamais une simple piste)
    assert all("/" not in r.correction for r in rows)


def test_teacher_grammar_question_gives_lesson_and_checks_exercise(seeded):
    ts = TutorService(seeded, rng=random.Random(3))
    conv = ts.new_conversation("professeur")
    ts.opening(conv)
    r = ts.send(conv, "Quand utilise-t-on le subjonctif ?")
    assert "SUBJONCTIF" in r.text and "Petit exercice" in r.text
    assert conv.state.get("exercise")
    r = ts.send(conv, "zzz")
    assert "Réponse attendue" in r.text and "Correction" in r.text
    with seeded.session() as s:
        assert s.execute(select(func.count(ErrorLog.id)).where(
            ErrorLog.source == "grammaire")).scalar_one() == 1


def test_teacher_vocabulary_lookup(seeded):
    ts = TutorService(seeded)
    conv = ts.new_conversation("professeur")
    r = ts.send(conv, "Que veut dire loyer ?")
    assert "« loyer »" in r.text and "Exemple" in r.text


def test_chapter_keywords():
    assert find_chapter_slug("c'est quoi le discours indirect ?") == "discours-indirect"
    assert find_chapter_slug("Comment accorder le participe passé ?") == "accords"
    assert find_chapter_slug("Bonjour") is None


def test_conversation_follows_up_recasts_and_changes_topic(seeded):
    ts = TutorService(seeded, rng=random.Random(1))
    conv = ts.new_conversation("conversation")
    ts.opening(conv)
    t0 = conv.state["topic"]
    r = ts.send(conv, "Je pense que c'est important, d'abord pour la santé et ensuite pour "
                      "l'avenir de nos enfants, si il fait beau on sort.")
    assert "s'il" in r.text and "?" in r.text and conv.state["step"] == 1
    r = ts.send(conv, "autre sujet")
    assert conv.state["topic"] != t0 and "changeons" in r.text
    assert "Pourquoi" in ts.send(conv, "Oui.").text or "?" in conv.turns[-1].text


def test_examiner_simulation_and_estimated_evaluation(seeded):
    ts = TutorService(seeded, rng=random.Random(2))
    conv = ts.new_conversation("examinateur", task_number=3)
    assert conv.task["task_number"] == 3
    first = ts.opening(conv).text
    assert "Tâche 3" in first and conv.task["examiner_prompts"][0] in first
    r = ts.send(conv, "Oui.")
    assert "justifier" in r.text                      # relance si réponse trop courte
    long = ("À mon avis, c'est une bonne chose parce que cela crée des emplois. Par exemple, "
            "dans ma ville, beaucoup de familles vivent du tourisme. Cependant, il faut "
            "protéger les habitants et la nature. En conclusion, il faut trouver un équilibre.")
    r = ts.send(conv, long)
    assert conv.task["examiner_prompts"][1] in r.text
    fin = ts.finish_exam(conv)
    ev = fin.evaluation
    assert ev and 0 <= ev["note20"] <= 16 and ev["extra"]["typed"]
    assert L.DISCLAIMER in fin.text and "clavier" in ev["caveat"]
    assert conv.state["ended"]
    with pytest.raises(ValueError):
        ts.finish_exam(ts.new_conversation("professeur"))


# ---------------------------------------------------------------- moteur en ligne
def test_anthropic_request_shape_and_reply(seeded, keyring):
    client, m = fake_client()
    ts = online_service(seeded, keyring, client)
    assert "Claude" in ts.status()
    conv = ts.new_conversation("conversation")
    r = ts.opening(conv)
    assert r.text == "Bonjour, je suis Claude." and r.engine.startswith("Claude")
    r = ts.send(conv, BAD)
    kw = m.calls[-1]
    assert kw["model"] == "claude-opus-5-5"
    assert kw["thinking"] == {"type": "adaptive"}
    assert kw["output_config"] == {"effort": "medium"}
    assert kw["betas"] == [AE.FALLBACK_BETA] and kw["fallbacks"] == "default"
    assert "France Éducation international" in kw["system"]
    roles = [x["role"] for x in kw["messages"]]
    assert roles[0] == "user" and all(a != b for a, b in zip(roles, roles[1:]))
    assert kw["messages"][-1]["content"] == BAD
    # les erreurs sont tout de même journalisées par les règles locales
    assert r.corrections


def test_refusal_is_reported_politely(seeded, keyring):
    client, _ = fake_client(stop="refusal", text="")
    ts = online_service(seeded, keyring, client)
    conv = ts.new_conversation("professeur")
    assert ts.send(conv, "Bonjour").text == AE.REFUSAL_TEXT


def test_online_failure_falls_back_to_local(seeded, keyring):
    import anthropic
    exc = anthropic.APIConnectionError(request=None)
    client, _ = fake_client(exc=exc)
    ts = online_service(seeded, keyring, client)
    conv = ts.new_conversation("professeur")
    r = ts.send(conv, BAD)
    assert r.engine == "Tuteur hors ligne" and "connexion" in r.notice.lower()
    assert "s'il" in r.text


def test_privacy_consent_required_before_sending(seeded, keyring):
    client, m = fake_client()
    ts = online_service(seeded, keyring, client, consent=False)
    assert ts.needs_consent()
    conv = ts.new_conversation("professeur")
    ts.send(conv, BAD)
    assert m.calls == []                      # rien n'est envoyé sans accord
    ts.give_consent()
    ts.send(conv, "Merci")
    assert len(m.calls) == 1


def test_no_key_means_local_engine(seeded, keyring):
    with seeded.session() as s:
        S.set_(s, "ai_provider", PROVIDER_ANTHROPIC)
    ts = TutorService(seeded)
    assert ts.online_engine() is None and "aucune clé" in ts.status()
    with pytest.raises(AIUnavailable):
        AE.AnthropicEngine(None)
    with pytest.raises(AIUnavailable):
        ts.test_connection()


def test_api_key_never_stored_in_database(seeded, keyring):
    S.store_api_key(PROVIDER_ANTHROPIC, "sk-ant-secret-123")
    with seeded.session() as s:
        values = [r.value for r in s.execute(select(Setting)).scalars()]
    assert not any("sk-ant-secret" in (v or "") for v in values)
    assert S.load_api_key(PROVIDER_ANTHROPIC) == "sk-ant-secret-123"
    S.delete_api_key(PROVIDER_ANTHROPIC)
    assert S.load_api_key(PROVIDER_ANTHROPIC) is None


def test_messages_alternate_when_history_starts_with_tutor():
    eng = AE.AnthropicEngine(None, client=object())
    conv = Conversation("conversation", turns=[Turn("tuteur", "Bonjour"),
                                               Turn("apprenant", "a"), Turn("apprenant", "b")])
    msgs = eng._messages(conv)
    assert [m["role"] for m in msgs] == ["user", "assistant", "user"]
    assert msgs[-1]["content"] == "a\n\nb"


# ---------------------------------------------------------------- journal des erreurs
def _exam(s):
    return s.execute(select(Exam).order_by(Exam.code)).scalars().first()


def test_productions_feed_the_error_log_once(seeded):
    with seeded.session() as s:
        ex = _exam(s)
        wt, st = ex.writing_tasks[0], ex.speaking_tasks[0]
        WS.submit(s, wt.id, BAD + " " + "Je suis content de vous écrire. " * 5)
        n_ee = s.execute(select(func.count(ErrorLog.id)).where(ErrorLog.source == "EE")
                         ).scalar_one()
        sub = SS.submit(s, st.id, "il faut que tu vas si il pleut " * 5, duration_s=60)
        n_eo = s.execute(select(func.count(ErrorLog.id)).where(ErrorLog.source == "EO")
                         ).scalar_one()
        SS.submit(s, st.id, "il faut que tu vas si il pleut " * 5, submission_id=sub.id)
        n_eo2 = s.execute(select(func.count(ErrorLog.id)).where(ErrorLog.source == "EO")
                          ).scalar_one()
    assert n_ee >= 2 and n_eo >= 1 and n_eo2 == n_eo


# ---------------------------------------------------------------- exercices personnalisés
def test_custom_session_is_diagnostic_without_errors(seeded):
    with seeded.session() as s:
        items = CX.build_session(s, 8, random.Random(0))
    assert len(items) == 8 and all("Diagnostic" in i.origin for i in items)
    assert all(i.explanation and i.accepted for i in items)


def test_custom_session_targets_recurring_errors(seeded):
    ts = TutorService(seeded)
    conv = ts.new_conversation("professeur")
    for _ in range(3):
        ts.send(conv, BAD)
    with seeded.session() as s:
        ws = ET.weaknesses(s)
        assert {w.category for w in ws[:2]} == {"Le subjonctif présent et passé",
                                                "Orthographe"}
        items = CX.build_session(s, 10, random.Random(0))
    kinds = [i.kind for i in items]
    assert "correction" in kinds
    corr = next(i for i in items if i.kind == "correction")
    assert corr.accepted == ["s'il"] and "« si il »" in corr.prompt
    assert any(i.chapter == "subjonctif" and i.exercise_id for i in items)
    ok, _ = CX.check(corr, "s'il")
    assert ok
    qcm = next((i for i in items if i.options), None)
    if qcm:
        letter = "abcd"[qcm.options.index(qcm.accepted[0])] if qcm.accepted[0] in qcm.options \
            else None
        if letter:
            assert CX.check(qcm, letter)[0]
    with seeded.session() as s:
        before = s.execute(select(func.count(ErrorLog.id))).scalar_one()
        CX.record(s, corr, "si il", False)
        CX.record_session(s, 0.5, 60)
        assert s.execute(select(func.count(ErrorLog.id))).scalar_one() == before + 1
        assert s.execute(select(StudySession).where(StudySession.module == "perso")
                         ).scalar_one().score == 0.5


# ---------------------------------------------------------------- interface
@pytest.fixture
def ctx(seeded, tmp_paths, qapp):
    c = AppContext(paths=tmp_paths, db=seeded, log=setup_logging(tmp_paths.logs))
    import tcfmaster.ui.speaking as SPK
    SPK.RUN_SYNC = True
    return c


def test_tutor_page_teacher_and_examiner(ctx):
    from tcfmaster.ui.pages.tutor_page import TutorPage
    p = TutorPage(ctx)
    p.refresh()
    assert "hors ligne" in p.status.text()
    p.new_conversation()
    assert "professeur" in p.chat.toPlainText()
    p.input.setPlainText(BAD)
    p.send()
    assert "s'il" in p.chat.toPlainText() and not p.finish_btn.isVisible()
    p.set_mode("examinateur")
    p.task.setCurrentIndex(p.task.findData(2))
    p.new_conversation()
    assert p.conv.task["task_number"] == 2
    p.input.setPlainText("Bonjour, je cherche un appartement de trois pièces près d'une école "
                         "pour ma famille. Est-ce que les charges sont comprises ?")
    p.send()
    p.finish()
    assert "Note estimée" in p.chat.toPlainText()
    assert "France Éducation international" in p.chat.toPlainText()
    assert not p.send_btn.isEnabled()


def test_custom_page_runs_a_series(ctx):
    from tcfmaster.ui.pages.custom_page import CustomExercisesPage
    p = CustomExercisesPage(ctx)
    p.refresh()
    assert p.empty.isVisibleTo(p) and "diagnostic" in p.start_btn.text()
    p.count.setValue(5)
    p.start()
    for _ in range(5):
        ex = p.items[p.idx]
        if ex.options:
            p.opt_group.buttons()[0].setChecked(True)
        else:
            p.answer.setText(ex.accepted[0])
        p.validate()
        assert "Correction" in p.feedback.text()
        p.next()
    assert p.stack.currentWidget() is p.report_view
    assert "Bilan de la série" in p.report.toPlainText()


def test_settings_ai_card_uses_keyring(ctx, keyring, monkeypatch):
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: None)
    from tcfmaster.ui.pages.misc_pages import SettingsPage
    p = SettingsPage(ctx)
    p.refresh()
    card = p.ai_card
    assert card.key.echoMode() == QLineEdit.Password
    card.provider.setCurrentIndex(card.provider.findData(PROVIDER_ANTHROPIC))
    card.key.setText("sk-ant-ui")
    card._save_key()
    assert card.key.text() == "" and S.load_api_key(PROVIDER_ANTHROPIC) == "sk-ant-ui"
    assert "coffre" in card.key_info.text()
    card._delete_key()
    assert S.load_api_key(PROVIDER_ANTHROPIC) is None


def test_menu_has_no_pending_pages_for_phase7():
    from tcfmaster.ui.main_window import MENU
    keys = {k: f for k, _, _, f in MENU}
    import inspect
    for k in ("ai", "custom"):
        assert "PendingPage" not in inspect.getsource(keys[k])
