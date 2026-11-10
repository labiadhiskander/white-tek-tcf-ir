"""Logique métier des examens blancs et des entraînements CO/CE.

Modes :
  * « examen »       : conditions réelles (chronomètre imposé, pas de réécoute,
                        correction affichée seulement à la fin) ;
  * « entrainement » : réécoute autorisée, correction possible après chaque question.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from tcfmaster.core import levels as L
from tcfmaster.db.models import (SECTION_CE, SECTION_CO, SECTION_DURATIONS_S, SECTION_EE,
                                 SECTION_EO, SECTIONS, Answer, Attempt, Exam, Question)

MODE_EXAM = "examen"
MODE_TRAINING = "entrainement"


@dataclass
class QuestionFeedback:
    question_id: int
    chosen: str | None
    correct: str
    is_correct: bool
    explanation: str
    rationales: dict[str, str]


def list_exams(s: Session) -> list[Exam]:
    return list(s.execute(select(Exam).order_by(Exam.code)).scalars())


def start_attempt(s: Session, exam_id: int | None, sections: list[str],
                  mode: str = MODE_EXAM) -> Attempt:
    bad = [x for x in sections if x not in SECTIONS]
    if bad:
        raise ValueError(f"Épreuves inconnues : {bad}")
    if mode not in (MODE_EXAM, MODE_TRAINING):
        raise ValueError(f"Mode inconnu : {mode}")
    a = Attempt(exam_id=exam_id, mode=mode, sections=list(sections), started_at=datetime.now())
    s.add(a)
    s.flush()
    return a


def time_limit(section: str) -> int:
    return SECTION_DURATIONS_S[section]


def can_replay(mode: str) -> bool:
    """Réécoute autorisée uniquement en mode entraînement."""
    return mode == MODE_TRAINING


def record_answer(s: Session, attempt: Attempt, question: Question, label: str | None,
                  time_spent_s: float = 0) -> QuestionFeedback:
    if attempt.finished_at is not None:
        raise RuntimeError("Tentative déjà terminée")
    correct = question.correct_choice
    if correct is None:
        raise ValueError(f"Question {question.id} invalide (pas exactement une bonne réponse)")
    if label is not None and label not in {c.label for c in question.choices}:
        raise ValueError(f"Proposition inconnue : {label}")
    ans = s.execute(select(Answer).where(Answer.attempt_id == attempt.id,
                                         Answer.question_id == question.id)
                    ).scalar_one_or_none()
    if ans is None:
        ans = Answer(attempt_id=attempt.id, question_id=question.id)
        s.add(ans)
    ans.choice_label = label
    ans.is_correct = label == correct.label
    ans.time_spent_s = time_spent_s
    s.flush()
    return QuestionFeedback(question.id, label, correct.label, ans.is_correct,
                            question.explanation,
                            {c.label: c.rationale for c in question.choices})


def score_comprehension(s: Session, attempt: Attempt, section: str) -> dict:
    """Score TCF (sur 699) et niveau estimé pour une épreuve CO ou CE.

    Les questions non répondues comptent comme fausses.
    """
    if attempt.exam_id is None:
        qs = [a.question for a in attempt.answers if a.question.section == section]
    else:
        qs = list(s.execute(select(Question).where(Question.exam_id == attempt.exam_id,
                                                   Question.section == section)
                            .order_by(Question.position)).scalars())
    answered = {a.question_id: a for a in attempt.answers}
    pairs = [(q.level, bool(answered.get(q.id) and answered[q.id].is_correct)) for q in qs]
    score = L.comprehension_score(pairs)
    correct = sum(1 for _, ok in pairs if ok)
    return {"score": score, "level": L.comprehension_level(score) if score else "< A1",
            "correct": correct, "total": len(pairs)}


def finish_attempt(s: Session, attempt: Attempt, extra_results: dict | None = None) -> dict:
    """Clôture la tentative et calcule les résultats.

    `extra_results` porte les notes EE / EO calculées par le moteur de correction
    sous la forme {"EE": {"note20": x, "level": "B2"}, "EO": {...}}.
    """
    results: dict = dict(attempt.results or {})
    for sec in (SECTION_CO, SECTION_CE):
        if sec in attempt.sections:
            results[sec] = score_comprehension(s, attempt, sec)
    for sec in (SECTION_EE, SECTION_EO):
        if extra_results and sec in extra_results:
            r = dict(extra_results[sec])
            r.setdefault("level", L.expression_level(r.get("note20", 0)))
            results[sec] = r
    results["disclaimer"] = L.DISCLAIMER
    attempt.results = results
    attempt.finished_at = datetime.now()
    s.flush()
    return results
