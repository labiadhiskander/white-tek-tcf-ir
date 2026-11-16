"""Collections B2 et bibliothèque centralisée (v1.1).

  * Listes et filtres de la bibliothèque (8 familles demandées + thème + recherche).
  * Séries d'exercices CO/CE en mode entraînement ou en mode examen :
    les réponses sont enregistrées dans les tables `attempts` / `answers` de la
    v1.0 ; le résultat est marqué `kind = "collection"` afin de ne pas fausser
    l'estimation « prêt pour le B2 », qui repose sur les examens complets.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from tcfmaster.core import levels as L
from tcfmaster.db.models import (KIND_GRAMMAR, KIND_VOCAB, SECTION_CE, SECTION_CO,
                                 SECTION_DURATIONS_S, SECTION_EE, SECTION_EO, STATUS_VALID,
                                 QUESTIONS_PER_COMPREHENSION, Answer, Attempt, Collection,
                                 Exam, Exercise, Expression, GrammarChapter, Question,
                                 SpeakingSubmission, SpeakingTask, Video, WritingSubmission,
                                 WritingTask)
from tcfmaster.services import correction as C
from tcfmaster.services import error_tracking as ET
from tcfmaster.services import exam_service as ES

KIND_COLLECTION = "collection"

# Filtres de la bibliothèque, dans l'ordre du cahier des charges
FILTER_CO = SECTION_CO
FILTER_CE = SECTION_CE
FILTER_EO = SECTION_EO
FILTER_EE = SECTION_EE
FILTER_EXAMS = "EXAM"
FILTER_VIDEOS = "VID"
FILTER_GRAMMAR = KIND_GRAMMAR
FILTER_VOCAB = KIND_VOCAB
FILTERS = {
    FILTER_CO: "Compréhension orale B2",
    FILTER_CE: "Compréhension écrite B2",
    FILTER_EO: "Expression orale B2",
    FILTER_EE: "Expression écrite B2",
    FILTER_EXAMS: "Examens blancs",
    FILTER_VIDEOS: "Vidéos et formations",
    FILTER_GRAMMAR: "Grammaire",
    FILTER_VOCAB: "Vocabulaire",
}


@dataclass
class LibraryItem:
    kind: str            # exercise | writing | speaking | exam | video | grammar | vocab
    ref: int | str       # identifiant (ou catégorie pour le vocabulaire)
    family: str          # clé de FILTERS
    title: str
    collection: str
    detail: str
    status: str = STATUS_VALID
    done: int = 0        # nombre de passages / productions
    last: str = ""       # dernier résultat lisible


# ------------------------------------------------------------------ requêtes
def list_collections(s: Session, section: str | None = None) -> list[Collection]:
    q = select(Collection).order_by(Collection.section, Collection.order, Collection.title)
    if section:
        q = q.where(Collection.section == section)
    return list(s.execute(q).scalars())


def published_exercises(s: Session, collection_id: int | None = None,
                        section: str | None = None) -> list[Exercise]:
    q = select(Exercise).where(Exercise.status == STATUS_VALID)
    if collection_id is not None:
        q = q.where(Exercise.collection_id == collection_id)
    if section:
        q = q.where(Exercise.section == section)
    return list(s.execute(q.order_by(Exercise.collection_id, Exercise.position)).scalars())


def bank_subjects(s: Session, section: str, task_number: int | None = None,
                  collection_id: int | None = None) -> list:
    """Sujets EE / situations EO de la banque B2 (hors examens)."""
    model = WritingTask if section == SECTION_EE else SpeakingTask
    q = select(model).where(model.exam_id.is_(None), model.code.is_not(None),
                            model.status == STATUS_VALID)
    if task_number:
        q = q.where(model.task_number == task_number)
    if collection_id is not None:
        q = q.where(model.collection_id == collection_id)
    return list(s.execute(q.order_by(model.task_number, model.code)).scalars())


def _exercise_stats(s: Session) -> dict[int, tuple[int, str]]:
    """{exercise_id: (passages, dernier résultat)} à partir des tentatives de collection."""
    out: dict[int, tuple[int, str]] = {}
    rows = s.execute(select(Attempt).where(Attempt.finished_at.is_not(None))
                     .order_by(Attempt.finished_at)).scalars()
    for a in rows:
        res = a.results or {}
        if res.get("kind") != KIND_COLLECTION:
            continue
        per = res.get("per_exercise", {})
        for ex_id in res.get("exercise_ids", []):
            n, _ = out.get(ex_id, (0, ""))
            score = per.get(str(ex_id))
            out[ex_id] = (n + 1, f"{score[0]}/{score[1]}" if score else "")
    return out


def library(s: Session, family: str | None = None, search: str = "",
            collection_id: int | None = None, include_drafts: bool = False) -> list[LibraryItem]:
    items: list[LibraryItem] = []
    fams = [family] if family else list(FILTERS)
    stats = _exercise_stats(s) if any(f in (FILTER_CO, FILTER_CE) for f in fams) else {}
    for fam in fams:
        if fam in (FILTER_CO, FILTER_CE):
            q = select(Exercise).where(Exercise.section == fam)
            if not include_drafts:
                q = q.where(Exercise.status == STATUS_VALID)
            if collection_id is not None:
                q = q.where(Exercise.collection_id == collection_id)
            for ex in s.execute(q.order_by(Exercise.collection_id, Exercise.position)).scalars():
                n, last = stats.get(ex.id, (0, ""))
                items.append(LibraryItem(
                    "exercise", ex.id, fam, ex.title,
                    ex.collection.title if ex.collection else "",
                    f"{ex.doc_type} · {len(ex.questions)} question(s)", ex.status, n, last))
        elif fam in (FILTER_EE, FILTER_EO):
            model, sub = ((WritingTask, WritingSubmission) if fam == FILTER_EE
                          else (SpeakingTask, SpeakingSubmission))
            q = select(model).where(model.exam_id.is_(None), model.code.is_not(None))
            if not include_drafts:
                q = q.where(model.status == STATUS_VALID)
            if collection_id is not None:
                q = q.where(model.collection_id == collection_id)
            counts = dict(s.execute(select(sub.task_id, func.count(sub.id))
                                    .group_by(sub.task_id)).all())
            for t in s.execute(q.order_by(model.task_number, model.code)).scalars():
                title = (t.task_type if fam == FILTER_EE else t.title) or t.code
                items.append(LibraryItem(
                    "writing" if fam == FILTER_EE else "speaking", t.id, fam,
                    f"Tâche {t.task_number} – {title}",
                    t.collection.title if t.collection else "", t.theme or "",
                    t.status or STATUS_VALID, counts.get(t.id, 0)))
        elif fam == FILTER_EXAMS:
            for e in ES.list_exams(s):
                serie = "Examen blanc B2" if e.series == "B2" else "Examen v1.0"
                items.append(LibraryItem("exam", e.id, fam, f"{e.code} – {e.title}", serie,
                                         "CO 25 · CE 25 · EE 3 · EO 3"))
        elif fam == FILTER_VIDEOS:
            q = select(Video)
            if not include_drafts:   # brouillons et liens en erreur masqués
                q = q.where(Video.status == STATUS_VALID,
                            or_(Video.link_status.is_(None), Video.link_status != "erreur"))
            for v in s.execute(q.order_by(Video.category, Video.title)).scalars():
                items.append(LibraryItem("video", v.id, fam, v.title, v.category,
                                         f"{v.source} · {v.duration}", v.status))
        elif fam == FILTER_GRAMMAR:
            for ch in s.execute(select(GrammarChapter).order_by(GrammarChapter.order)).scalars():
                items.append(LibraryItem("grammar", ch.id, fam, ch.title, ch.module.capitalize(),
                                         f"{len(ch.exercises)} exercice(s) corrigé(s)"))
        elif fam == FILTER_VOCAB:
            rows = s.execute(select(Expression.category, func.count(Expression.id))
                             .group_by(Expression.category).order_by(Expression.category)).all()
            for cat, n in rows:
                items.append(LibraryItem("vocab", cat, fam, cat, "Expressions et formulations",
                                         f"{n} exercice(s) de réemploi corrigé(s)"))
    if search:
        needle = search.lower().strip()
        items = [i for i in items if needle in f"{i.title} {i.collection} {i.detail}".lower()]
    return items


def counts(s: Session) -> dict[str, int]:
    """Volumes publiés par famille (tableau de bord, documentation)."""
    return {
        FILTER_CO: s.execute(select(func.count(Exercise.id)).where(
            Exercise.section == SECTION_CO, Exercise.status == STATUS_VALID)).scalar_one(),
        FILTER_CE: s.execute(select(func.count(Exercise.id)).where(
            Exercise.section == SECTION_CE, Exercise.status == STATUS_VALID)).scalar_one(),
        FILTER_EE: len(bank_subjects(s, SECTION_EE)),
        FILTER_EO: len(bank_subjects(s, SECTION_EO)),
        FILTER_EXAMS: s.execute(select(func.count(Exam.id))).scalar_one(),
        FILTER_VIDEOS: s.execute(select(func.count(Video.id)).where(
            Video.status == STATUS_VALID,
            or_(Video.link_status.is_(None), Video.link_status != "erreur"))).scalar_one(),
    }


# --------------------------------------------------------- séries d'exercices
def time_limit(section: str, n_questions: int) -> int:
    """Temps proportionnel au format officiel (CO 20 min / 25 q, CE 35 min / 25 q)."""
    per_q = SECTION_DURATIONS_S[section] / QUESTIONS_PER_COMPREHENSION
    return max(60, round(per_q * n_questions))


def question_ids(s: Session, exercise_ids: list[int]) -> list[int]:
    out: list[int] = []
    for i in exercise_ids:
        ex = s.get(Exercise, i)
        if ex is not None:
            out += [q.id for q in ex.questions]
    return out


def start_series(s: Session, exercise_ids: list[int], mode: str) -> Attempt:
    exs = [s.get(Exercise, i) for i in exercise_ids]
    exs = [e for e in exs if e is not None]
    if not exs:
        raise ValueError("Aucun exercice")
    sections = sorted({e.section for e in exs})
    if len(sections) != 1:
        raise ValueError("Une série ne mélange pas compréhension orale et écrite")
    a = ES.start_attempt(s, None, sections, mode)
    a.results = {"kind": KIND_COLLECTION, "exercise_ids": [e.id for e in exs]}
    s.flush()
    return a


def record(s: Session, attempt: Attempt, question: Question, label: str | None,
           time_spent_s: float = 0) -> C.McqCorrection:
    """Enregistre une réponse et renvoie sa correction (affichée ou non selon le mode)."""
    ES.record_answer(s, attempt, question, label, time_spent_s)
    return C.correct_question(question, label)


def finish_series(s: Session, attempt: Attempt) -> C.SessionCorrection:
    if attempt.finished_at is None:
        corr = C.session_correction(s, attempt.id)
        res = dict(attempt.results or {})
        res.update({
            "kind": KIND_COLLECTION,
            "section": corr.section,
            "correct": corr.correct, "total": corr.total, "rate": round(corr.rate, 3),
            "per_exercise": {str(e.exercise_id): [e.correct, e.total] for e in corr.exercises},
            "disclaimer": L.DISCLAIMER,
        })
        attempt.results = res
        attempt.finished_at = datetime.now()
        # Les questions manquées alimentent le journal des difficultés et le
        # vocabulaire à revoir (répétition espacée).
        from tcfmaster.services import review as RV
        for e in corr.exercises:
            if any(not q.is_correct for q in e.questions):
                ex = s.get(Exercise, e.exercise_id)
                if ex is not None:
                    RV.enqueue_lexicon(s, ex)
            for q in e.questions:
                if not q.is_correct:
                    right = next(c.text for c in q.choices if c.is_correct)
                    ET.log_issues(s, corr.section, [{
                        "severity": "erreur", "rule": "comprehension",
                        "category": f"Compréhension : {q.skill or 'globale'}",
                        "excerpt": q.prompt, "replacement": right,
                        "message": e.code, "explanation": q.explanation}])
        s.flush()
        return corr
    return C.session_correction(s, attempt.id)


def answered(s: Session, attempt_id: int) -> dict[int, str | None]:
    return {a.question_id: a.choice_label for a in s.execute(
        select(Answer).where(Answer.attempt_id == attempt_id)).scalars()}


def success_rate(s: Session, section: str) -> tuple[int, int]:
    """(bonnes réponses, questions) cumulées sur les séries de collection terminées."""
    ok = tot = 0
    for a in s.execute(select(Attempt).where(Attempt.finished_at.is_not(None))).scalars():
        r = a.results or {}
        if r.get("kind") == KIND_COLLECTION and r.get("section") == section:
            ok += int(r.get("correct", 0))
            tot += int(r.get("total", 0))
    return ok, tot
