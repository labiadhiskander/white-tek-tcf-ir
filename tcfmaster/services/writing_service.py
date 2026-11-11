"""Enregistrement et évaluation des productions écrites."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from tcfmaster.core import levels as L
from tcfmaster.db.models import Attempt, WritingSubmission, WritingTask
from tcfmaster.services import writing_eval as WE


def evaluate_task(task: WritingTask, text: str) -> WE.Evaluation:
    return WE.evaluate(text, task.task_number, task.min_words, task.max_words,
                       task.expected_points, task.model_answer)


def submit(s: Session, task_id: int, text: str, duration_s: float = 0,
           attempt_id: int | None = None) -> WritingSubmission:
    """Évalue et enregistre une production (une par tâche et par tentative)."""
    task = s.get(WritingTask, task_id)
    if task is None:
        raise ValueError(f"Tâche inconnue : {task_id}")
    ev = evaluate_task(task, text)
    sub = None
    if attempt_id is not None:
        a = s.get(Attempt, attempt_id)
        if a is None or a.finished_at is not None:
            raise RuntimeError("Tentative introuvable ou déjà terminée")
        sub = s.execute(select(WritingSubmission).where(
            WritingSubmission.attempt_id == attempt_id,
            WritingSubmission.task_id == task_id)).scalar_one_or_none()
    if sub is None:
        sub = WritingSubmission(attempt_id=attempt_id, task_id=task_id)
        s.add(sub)
    sub.text = text
    sub.word_count = ev.word_count
    sub.duration_s = duration_s
    sub.evaluation = ev.to_dict()
    sub.note20 = ev.note20
    sub.level = ev.level
    s.flush()
    return sub


def attempt_result(s: Session, attempt_id: int, task_ids: list[int]) -> dict:
    """Note EE d'une tentative : moyenne des 3 tâches (une tâche non rendue vaut 0)."""
    subs = {w.task_id: w for w in s.execute(select(WritingSubmission).where(
        WritingSubmission.attempt_id == attempt_id)).scalars()}
    notes = [subs[t].note20 if t in subs and subs[t].note20 is not None else 0.0
             for t in task_ids]
    note = round(sum(notes) / len(notes) * 2) / 2 if notes else 0.0
    return {"note20": note, "level": L.expression_level(note) if note else "< A1",
            "tasks": {str(i + 1): n for i, n in enumerate(notes)},
            "disclaimer": L.DISCLAIMER}


def history(s: Session, task_id: int | None = None, limit: int = 50) -> list[WritingSubmission]:
    q = select(WritingSubmission).order_by(WritingSubmission.created_at.desc()).limit(limit)
    if task_id is not None:
        q = q.where(WritingSubmission.task_id == task_id)
    return list(s.execute(q).scalars())
