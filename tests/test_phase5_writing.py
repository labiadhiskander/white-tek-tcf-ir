"""Phase 5 : correction de l'expression écrite."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import json
import statistics

import pytest
from PySide6.QtWidgets import QApplication
from sqlalchemy import select

from tcfmaster.content.seeder import content_dir, seed_all
from tcfmaster.core import levels as L
from tcfmaster.core.app_context import AppContext
from tcfmaster.core.logging_setup import setup_logging
from tcfmaster.db.models import Attempt, Exam
from tcfmaster.services import exam_service as ES
from tcfmaster.services import writing_eval as WE
from tcfmaster.services import writing_service as WS


def rules_hit(text):
    return {i.rule for i in WE.find_issues(text)}


@pytest.mark.parametrize("text,rule,fixed", [
    ("Je viendrai si il fait beau.", "si-il", "Je viendrai s'il fait beau."),
    ("Les gens est contents.", "gens-singulier", "Les gens sont contents."),
    ("Il y a beaucoup des problèmes.", "beaucoup-des", "Il y a beaucoup de problèmes."),
    ("Hier, je ai mangé.", "elision", "Hier, j'ai mangé."),
    ("C'est tres bien.", "accents", "C'est très bien."),
    ("Demain on vas au cinéma.", "aller-present", "Demain on va au cinéma."),
    ("Malgré qu'il pleuve, je sors.", "malgre-que", "Bien qu'il pleuve, je sors."),
    ("C'est plus pire qu'avant.", "plus-pire", "C'est pire qu'avant."),
    ("Je suis entrain de lire.", "entrain", "Je suis en train de lire."),
    ("Vous faisez du sport.", "vous-faisez", "Vous faites du sport."),
    ("J'arrive a partir de midi.", "a-cause", "J'arrive à partir de midi."),
    ("Bonjour.je suis là.", "espace-apres", "Bonjour. Je suis là."),
])
def test_rules_detect_and_fix(text, rule, fixed):
    issues = WE.find_issues(text)
    assert rule in {i.rule for i in issues}
    assert WE.apply_fixes(text, issues) == fixed


@pytest.mark.parametrize("text,rule", [
    ("Bien qu'il est fatigué, il travaille.", "subj-apres-conj"),
    ("Il faut que tu vas à la mairie.", "subj-apres-conj"),
    ("Si j'aurais su, je serais venu.", "si-conditionnel"),
    ("Hier, elle a allée au marché.", "auxiliaire-etre"),
    ("Je sais pas quoi faire.", "negation-incomplete"),
    ("C'est jamais facile.", "negation-incomplete"),
    ("Après qu'il soit parti, nous avons dîné.", "apres-que-subj"),
    ("Il faut pallier à ce problème.", "pallier-a"),
    ("On mangeons ensemble.", "on-nous"),
    ("Mon boulot est sympa.", "familier"),
    ("Ça fait sens.", "faire-sens"),
])
def test_rules_detect_without_autofix(text, rule):
    assert rule in rules_hit(text)


@pytest.mark.parametrize("text", [
    "Il a beaucoup travaillé, si bien qu'il a réussi.",
    "Je me demande si je pourrais venir demain.",
    "Le télétravail présente plus d'avantages que d'inconvénients.",
    "Ils sont plus grands que nous.",
    "Elle a démissionné, ce que personne n'avait prévu.",
    "Je fais suite à votre annonce.",
    "Si je courais plus vite, je gagnerais.",
    "Si tu pleurais moins, tu irais mieux.",
    "Bien qu'il soit tard, je reste.",
    "Il s'est très bien débrouillé.",
    "Je suis allée chez mes parents, puis je suis rentrée.",
    "Nous ne savons pas, mais nous essayons.",
    "Le prix est de 3,5 euros.",
])
def test_correct_sentences_are_not_flagged(text):
    serious = {i.rule for i in WE.find_issues(text) if i.severity == WE.ERROR}
    assert serious == set(), serious


def _all_tasks():
    for path in sorted((content_dir() / "exams").glob("*.json")):
        exam = json.loads(path.read_text(encoding="utf-8"))
        for t in exam["EE"]:
            yield path.stem, t


def test_model_answers_have_no_detected_error_and_score_b2_or_more():
    notes = []
    for stem, t in _all_tasks():
        ev = WE.evaluate(t["model_answer"], t["task_number"], t["min_words"], t["max_words"],
                         t.get("expected_points"))
        assert ev.errors == [], (stem, t["task_number"], [(i.rule, i.excerpt) for i in ev.errors])
        assert L.meets_target(ev.level), (stem, t["task_number"], ev.note20)
        notes.append(ev.note20)
    assert len(notes) == 60
    assert 12 <= statistics.mean(notes) <= WE.AUTO_CAP


def test_poor_text_scores_below_b2_with_priorities():
    bad = ("salut marie , si il fait beau samedi on vas faire un pique-nique. Je sais pas si "
           "tu peux venir mais ça serait cool. les gens est tres sympa. Si j'aurais une voiture "
           "je viendrais. Bien que il est tard je t'écris. Hier je ai allé au parc")
    ev = WE.evaluate(bad, 1, 30, 60, ["salutation", "invitation (jour, heure)", "formule finale"])
    assert ev.note20 < 10 and not L.meets_target(ev.level)
    assert len(ev.errors) >= 8
    assert ev.priorities and len(ev.priorities) <= 3
    assert ev.disclaimer == L.DISCLAIMER
    assert "s'il" in ev.corrected_text and "Les gens sont très" in ev.corrected_text


def test_length_and_empty_text_rules():
    assert WE.evaluate("", 1, 30, 60).note20 == 0
    short = WE.evaluate("Bonjour Paul, je viens samedi. À bientôt.", 1, 30, 60,
                        ["salutation", "formule finale"])
    assert short.note20 <= 5 and "trop court" in short.criteria_comments["tache"]
    long_text = " ".join(["Je pense que ce projet est utile pour la ville."] * 15)
    ev = WE.evaluate(long_text, 3, 40, 90)
    assert "trop long" in ev.criteria_comments["tache"]
    assert ev.repetitions


def test_expected_points_detection():
    pts = WE.check_points("Bonjour Sophie, je t'invite samedi à 19 h chez moi. Bisous, Léa",
                          ["salutation", "date et heure", "formule finale", "conclusion"])
    status = {p.label: p.status for p in pts}
    assert status == {"salutation": "présent", "date et heure": "présent",
                      "formule finale": "présent", "conclusion": "absent"}


def test_evaluation_is_json_serialisable():
    ev = WE.evaluate("Certes, ce projet coûte cher. Cependant, il est utile.", 3, 40, 90)
    json.dumps(ev.to_dict(), ensure_ascii=False)


# ------------------------------------------------------------ persistance / UI
@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def ctx(db, tmp_paths, qapp):
    with db.session() as s:
        seed_all(s)
    return AppContext(paths=tmp_paths, db=db, log=setup_logging(tmp_paths.logs))


def _exam(s):
    return s.execute(select(Exam).order_by(Exam.code)).scalars().first()


def test_submit_training_and_history(ctx):
    with ctx.db.session() as s:
        t = sorted(_exam(s).writing_tasks, key=lambda t: t.task_number)[0]
        sub = WS.submit(s, t.id, t.model_answer, 120)
        assert sub.note20 > 0 and sub.evaluation["disclaimer"] == L.DISCLAIMER
        assert sub.attempt_id is None
        assert WS.history(s, t.id)[0].id == sub.id


def test_writing_runner_full_flow(ctx):
    from tcfmaster.ui.writing import WritingRunner
    with ctx.db.session() as s:
        exam = _exam(s)
        models = [t.model_answer for t in sorted(exam.writing_tasks, key=lambda t: t.task_number)]
        aid = ES.start_attempt(s, exam.id, ["EE"], ES.MODE_EXAM).id
        eid = exam.id
    r = WritingRunner(ctx, aid, eid, ES.MODE_EXAM, finalize=True)
    assert r.timer.total == 30 * 60
    r.editors[0].edit.setPlainText(models[0])
    r.editors[1].edit.setPlainText(models[1])        # tâche 3 laissée vide
    assert "mots" in r.tabs.tabText(0)
    done = []
    r.finished.connect(done.append)
    r.finish()
    assert done == [aid]
    with ctx.db.session() as s:
        a = s.get(Attempt, aid)
        ee = a.results["EE"]
        assert ee["tasks"]["3"] == 0 and 0 < ee["note20"] < 14
        assert a.results["disclaimer"] == L.DISCLAIMER
        assert len(a.writing_submissions) == 2


def test_writing_page_training_and_report(ctx):
    from tcfmaster.ui.pages.writing_page import WritingPage
    p = WritingPage(ctx)
    p.refresh()
    assert p.exam.count() == 20
    p.task.setCurrentIndex(2)
    p.start_training()
    p.editor.edit.setPlainText("Je pense que si il faut changer, les gens est prêts. "
                               "Cependant, bien que il est difficile, on vas réussir.")
    p.submit_training()
    html = p.report.toHtml()
    assert "Note estimée" in html and "France Éducation international" in html
    assert "s'il" in html
    p.back()
    assert p.history.count() == 1
    runner = p.start_exam()
    runner.finish()
    assert "Tâche 1" in p.report.toHtml()


def test_full_exam_session_includes_writing(ctx):
    from tcfmaster.ui.exam_session import STEP_FACTORIES
    import tcfmaster.ui.pages.exam_pages  # noqa: F401  (enregistre l'épreuve EE)
    assert "EE" in STEP_FACTORIES


def test_annotation_numbers_match_detailed_list():
    from tcfmaster.ui.writing_report import annotated_text
    text = "Bien que il est tard, on vas partir."
    ev = WE.evaluate(text, 3, 40, 90).to_dict()
    html = annotated_text(text, ev["issues"])
    n = len(ev["issues"])
    for k in range(1, n + 1):
        assert str(k) in html
    assert "1,2" in html or "1,2,3" in html          # chevauchements regroupés
