"""v1.1 étape 7 : vidéothèque (liens officiels, vérification) et administration."""
import collections
import json
import urllib.error

import pytest
from sqlalchemy import select

from tcfmaster.content import validator as V
from tcfmaster.content.seeder import content_dir, seed_all
from tcfmaster.db.models import (ORIGIN_ADMIN, STATUS_DRAFT, STATUS_VALID, Exercise,
                                 SpeakingTask, Video, WritingTask)
from tcfmaster.services import admin as AD
from tcfmaster.services import collections as COL
from tcfmaster.services import videos as VS


def _videos():
    return json.loads((content_dir() / "videos.json").read_text(encoding="utf-8"))


# ------------------------------------------------------------- contenu
def test_video_library_covers_12_categories_with_official_links():
    vids = _videos()
    assert len(V.VIDEO_CATEGORIES) == 12
    cats = collections.Counter(v["category"] for v in vids)
    assert set(cats) == set(V.VIDEO_CATEGORIES)
    assert all(n >= 2 for n in cats.values())
    assert len({v["code"] for v in vids}) == len(vids)
    for v in vids:
        assert V.validate_video(v) == [], v["code"]
        assert V.url_allowed(v["url"]), v["url"]
        assert v["level"] == "B2"


def test_every_video_exercise_is_fully_corrected_and_balanced():
    pos = collections.Counter()
    for v in _videos():
        for q in v["exercise"]:
            assert len(q["choices"]) == 4 and len(set(q["choices"])) == 4
            assert all(r.strip() for r in q["rationales"]) and q["explanation"].strip()
            pos[q["answer"]] += 1
    assert set(pos) == {0, 1, 2, 3}
    assert max(pos.values()) - min(pos.values()) <= 2


def test_url_policy():
    assert V.url_allowed("https://apprendre.tv5monde.com/fr")
    assert not V.url_allowed("http://apprendre.tv5monde.com/fr")          # https imposé
    assert not V.url_allowed("https://tv5monde.com.example.org/x")         # faux domaine
    assert not V.url_allowed("https://exemple.com/video.mp4")


# ------------------------------------------------------------- base
@pytest.fixture
def seeded(db):
    with db.session() as s:
        rep = seed_all(s)
    assert rep.errors == []
    assert rep.videos == len(_videos())
    return db


def test_seed_is_idempotent_and_keeps_admin_edits(seeded):
    db = seeded
    with db.session() as s:
        v = s.execute(select(Video).where(Video.code == "VID-B2-001")).scalar_one()
        data = {"title": "Ma fiche", "category": v.category, "source": v.source,
                "url": v.url, "duration": v.duration, "description": v.description,
                "status": STATUS_VALID}
        saved, errs = VS.save_video(s, data, v.id)
        assert errs == [] and saved.locally_modified
    with db.session() as s:
        seed_all(s)
        v = s.execute(select(Video).where(Video.code == "VID-B2-001")).scalar_one()
        assert v.title == "Ma fiche"
        assert s.execute(select(Video)).scalars().all().__len__() == len(_videos())


def test_link_check_hides_broken_links(seeded):
    db = seeded
    bad = "https://www.ina.fr/"

    def fake(url):
        return (url != bad, "HTTP 404" if url == bad else "HTTP 200")

    with db.session() as s:
        before = len(VS.list_videos(s))
        res = VS.check_links(s, fetch=fake)
        assert res["erreur"] >= 1 and res["ok"] >= 1
        visible = VS.list_videos(s)
        assert all(v.url != bad for v in visible)
        assert len(visible) == before - res["erreur"]
        lib = COL.library(s, COL.FILTER_VIDEOS)
        assert len(lib) == len(visible)
        assert all(v.link_checked_at for v in VS.list_videos(s, include_hidden=True))
        assert "erreur" in VS.link_label(
            s.execute(select(Video).where(Video.url == bad)).scalars().first())


def test_check_url_handles_errors(monkeypatch):
    calls = []

    def fake_open(req, timeout):
        calls.append(req.get_method())
        if req.get_method() == "HEAD":
            raise urllib.error.HTTPError(req.full_url, 405, "no head", {}, None)

        class R:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False
        return R()

    monkeypatch.setattr(VS.urllib.request, "urlopen", fake_open)
    assert VS.check_url("https://www.ina.fr/") == (True, "HTTP 200")
    assert calls == ["HEAD", "GET"]

    def down(req, timeout):
        raise urllib.error.URLError("hors ligne")

    monkeypatch.setattr(VS.urllib.request, "urlopen", down)
    ok, detail = VS.check_url("https://www.ina.fr/")
    assert not ok and "inaccessible" in detail


def test_video_answer_correction(seeded):
    with seeded.session() as s:
        v = s.execute(select(Video).where(Video.code == "VID-B2-017")).scalar_one()
        q = v.exercise[0]
        ok, text = VS.check_answer(v, 0, q["answer"])
        assert ok and q["explanation"] in text
        wrong = (q["answer"] + 1) % 4
        ok, text = VS.check_answer(v, 0, wrong)
        assert not ok and q["choices"][q["answer"]] in text and q["rationales"][wrong] in text


# ------------------------------------------------------------- administration
def test_pin_is_optional_and_hashed(seeded):
    with seeded.session() as s:
        assert not AD.has_pin(s) and AD.check_pin(s, "")
        AD.set_pin(s, "2468")
        from tcfmaster.services import settings as S
        assert "2468" not in json.dumps(S.all_settings(s))
        assert AD.check_pin(s, "2468") and not AD.check_pin(s, "1111")
        with pytest.raises(ValueError):
            AD.set_pin(s, "12")
        AD.set_pin(s, None)
        assert not AD.has_pin(s)


def test_admin_video_crud_and_policy(seeded):
    with seeded.session() as s:
        data = {"title": "Chaîne de mon école", "category": "Grammaire", "source": "École",
                "url": "https://www.example.org/cours", "duration": "10 min",
                "description": "Cours de grammaire.",
                "exercise": [{"prompt": "Question ?", "choices": ["a", "b", "c", "d"],
                              "rationales": ["oui", "non", "non", "non"], "answer": 0,
                              "explanation": "Parce que."}]}
        v, errs = VS.save_video(s, data)
        assert errs == [] and v.origin == ORIGIN_ADMIN and v.status == STATUS_DRAFT
        assert v not in VS.list_videos(s)              # brouillon : masqué
        AD.set_status(s, "video", v.id, True)
        assert v in VS.list_videos(s)
        _, errs = VS.save_video(s, dict(data, url="http://insecure.example.org"))
        assert errs
        _, errs = VS.save_video(s, dict(data, exercise=[]))
        assert any("exercice" in e for e in errs)
        assert AD.delete(s, "video", v.id) == "supprimé"
        s.flush()
        assert s.get(Video, v.id) is None
        builtin = s.execute(select(Video)).scalars().first()
        assert "masqué" in AD.delete(s, "video", builtin.id)
        assert builtin.status == STATUS_DRAFT and s.get(Video, builtin.id) is not None


def test_admin_edits_exercise_without_breaking_history(seeded):
    with seeded.session() as s:
        ex = s.execute(select(Exercise).where(Exercise.section == "CE")).scalars().first()
        n = len(ex.questions)
        qs = [{"prompt": q.prompt + " (modifié)", "explanation": q.explanation,
               "choices": [{"text": c.text, "rationale": c.rationale, "correct": c.is_correct}
                           for c in q.choices]} for q in ex.questions]
        assert AD.update_exercise(s, ex.id, {"title": "Titre admin", "questions": qs}) == []
        assert ex.locally_modified and ex.questions[0].prompt.endswith("(modifié)")
        bad = [dict(q, explanation="") for q in qs]
        assert AD.update_exercise(s, ex.id, {"questions": bad})
        assert AD.update_exercise(s, ex.id, {"questions": qs[:-1]}) if n > 1 else True
        ex_id = ex.id
    with seeded.session() as s:
        seed_all(s)
        assert s.get(Exercise, ex_id).title == "Titre admin"
        AD.restore_original(s, "exercise", ex_id)
    with seeded.session() as s:
        seed_all(s)
        assert s.get(Exercise, ex_id).title != "Titre admin"


def test_admin_writing_subject_enforces_word_limits(seeded):
    with seeded.session() as s:
        base = {"task_number": 1, "task_type": "message", "instructions": "Écrivez à un ami.",
                "expected_points": ["saluer", "inviter"], "model_commentary": "Clair.",
                "tips": "Soyez bref."}
        _, errs = AD.save_writing(s, dict(base, model_answer="Salut ! " * 70))
        assert errs                                   # 140 mots > 60
        model = ("Salut Paul, samedi je fête mon anniversaire à la maison. Viens à partir de "
                 "vingt heures avec tes amis si tu veux. Dis-moi vite si tu peux venir. À bientôt, Léa")
        t, errs = AD.save_writing(s, dict(base, model_answer=model))
        assert errs == [] and t.origin == ORIGIN_ADMIN and t.status == STATUS_DRAFT
        assert (t.min_words, t.max_words) == (30, 60)
        assert t.code.startswith("EE-PERSO-")
        assert t not in COL.bank_subjects(s, "EE")
        AD.set_status(s, "writing", t.id, True)
        assert t in COL.bank_subjects(s, "EE")


def test_admin_speaking_subject_uses_official_duration(seeded):
    with seeded.session() as s:
        t, errs = AD.save_speaking(s, {
            "task_number": 2, "title": "Réserver une salle", "scenario": "Vous appelez…",
            "examiner_prompts": ["C'est complet."], "model_answer": "Bonjour…",
            "model_commentary": "Interaction réaliste.", "tips": "Posez des questions."})
        assert errs == [] and t.duration_s == 210
        rows = AD.rows(s, "speaking", "EO-PERSO")
        assert [r.code for r in rows] == [t.code]
        assert isinstance(s.get(SpeakingTask, t.id), SpeakingTask)
        assert AD.rows(s, "writing") and all(isinstance(s.get(WritingTask, r.id), WritingTask)
                                             for r in AD.rows(s, "writing")[:3])


# ------------------------------------------------------------- interface
@pytest.fixture(scope="module")
def qapp():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


@pytest.fixture
def ctx(seeded, tmp_paths, qapp):
    from tcfmaster.core.app_context import AppContext
    from tcfmaster.core.logging_setup import setup_logging
    return AppContext(paths=tmp_paths, db=seeded, log=setup_logging(tmp_paths.logs))


def test_videos_page_filters_and_corrects(ctx, monkeypatch):
    from tcfmaster.ui import speaking as SPK
    from tcfmaster.ui.pages.videos_page import VideosPage
    monkeypatch.setattr(SPK, "RUN_SYNC", True)
    p = VideosPage(ctx)
    p.refresh()
    assert p.list.count() == len(_videos())
    p.category.setCurrentIndex(p.category.findData("Prononciation"))
    assert p.list.count() == 2
    assert "Prononciation" in p.detail.toPlainText()
    with ctx.db.session() as s:
        ans = s.get(Video, p.current_id).exercise[0]["answer"]
    assert p.answer(0, ans) is True
    assert "Bonne réponse" in p._feedback[0].text()
    monkeypatch.setattr(VS, "check_url", lambda url, timeout=10: (False, "HTTP 404"))
    p.check_links()
    assert p.list.count() == 0 and "en erreur" in p.status.text()


def test_admin_page_pin_and_tables(ctx):
    from tcfmaster.ui.pages.admin_page import AdminPage
    with ctx.db.session() as s:
        AD.set_pin(s, "1357")
    p = AdminPage(ctx)
    p.refresh()
    assert p.stack.currentWidget() is p.lock_view
    p.pin.setText("0000")
    assert p.unlock() is False
    p.pin.setText("1357")
    assert p.unlock() is True and p.stack.currentWidget() is p.main_view
    assert p.tables["video"].rowCount() == len(_videos())
    assert p.tables["exercise"].rowCount() >= 200
    p.tables["video"].selectRow(0)
    p.set_status("video", False)
    assert p.tables["video"].item(0, 3).text() == STATUS_DRAFT
    dlg = p.make_dialog("video", p.selected_id("video"))
    dlg.widgets["title"].setText("Titre modifié")
    assert p.save_dialog("video", p.selected_id("video"), dlg) == []
    p.tables["exercise"].selectRow(0)
    edlg = p.make_dialog("exercise", p.selected_id("exercise"))
    assert p.save_dialog("exercise", p.selected_id("exercise"), edlg) == []


def test_menu_has_video_library_and_admin(ctx):
    from tcfmaster.ui.main_window import MENU
    keys = [m[0] for m in MENU]
    assert "videos" in keys and "admin" in keys
