"""Enregistrement, évaluation et suppression des productions orales."""
from __future__ import annotations

import logging
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from tcfmaster.core import levels as L
from tcfmaster.db.models import Attempt, SpeakingSubmission, SpeakingTask
from tcfmaster.services import error_tracking as ET
from tcfmaster.services import settings as S
from tcfmaster.services import speaking_eval as SE

log = logging.getLogger("tcfmaster.speaking")


def evaluate_task(task: SpeakingTask, transcript: str, profile: dict | None = None,
                  stt_confidence: float | None = None,
                  duration_s: float | None = None) -> SE.OralEvaluation:
    return SE.evaluate_oral(transcript, task.task_number, task.duration_s, profile,
                            stt_confidence, task.useful_phrases, task.model_answer, duration_s)


def submit(s: Session, task_id: int, transcript: str, *, profile: dict | None = None,
           audio_path: str | Path | None = None, stt_confidence: float | None = None,
           duration_s: float | None = None, dialogue: list | None = None,
           attempt_id: int | None = None, submission_id: int | None = None
           ) -> SpeakingSubmission:
    """Évalue et enregistre (ou réévalue, si `submission_id`) une production orale.

    Si l'utilisateur a choisi de ne pas conserver ses enregistrements, le
    fichier audio est supprimé dès que la transcription est faite."""
    task = s.get(SpeakingTask, task_id)
    if task is None:
        raise ValueError(f"Tâche inconnue : {task_id}")
    sub = s.get(SpeakingSubmission, submission_id) if submission_id else None
    if sub is None and attempt_id is not None:
        a = s.get(Attempt, attempt_id)
        if a is None or a.finished_at is not None:
            raise RuntimeError("Tentative introuvable ou déjà terminée")
        sub = s.execute(select(SpeakingSubmission).where(
            SpeakingSubmission.attempt_id == attempt_id,
            SpeakingSubmission.task_id == task_id)).scalar_one_or_none()
    is_new = sub is None
    if sub is None:
        sub = SpeakingSubmission(attempt_id=attempt_id, task_id=task_id)
        s.add(sub)
    if profile is None and sub.evaluation:
        profile = (sub.evaluation.get("extra") or {}).get("profile")
    if duration_s is None:
        duration_s = sub.duration_s or None
    ev = evaluate_task(task, transcript, profile, stt_confidence, duration_s)
    ev.extra["profile"] = profile or {}
    sub.transcript = transcript
    sub.duration_s = float(duration_s or (profile or {}).get("duration_s", 0) or 0)
    if dialogue is not None:
        sub.dialogue = dialogue
    if audio_path is not None:
        sub.audio_path = str(audio_path)
    if sub.audio_path and not S.get(s, "keep_recordings"):
        delete_audio_file(sub)
    sub.evaluation = ev.to_dict()
    sub.note20 = ev.note20
    sub.level = ev.level
    if is_new:                      # une réévaluation ne compte pas les erreurs deux fois
        ET.log_issues(s, "EO", ev.issues)
    s.flush()
    return sub


def delete_audio_file(sub: SpeakingSubmission) -> bool:
    """Supprime le fichier audio d'une production (la transcription est gardée)."""
    if not sub.audio_path:
        return False
    try:
        Path(sub.audio_path).unlink(missing_ok=True)
    except OSError:
        log.exception("Suppression impossible : %s", sub.audio_path)
        return False
    sub.audio_path = None
    return True


def delete_submission(s: Session, submission_id: int) -> None:
    """Supprime une production orale et son enregistrement."""
    sub = s.get(SpeakingSubmission, submission_id)
    if sub is not None:
        delete_audio_file(sub)
        s.delete(sub)
        s.flush()


def attempt_result(s: Session, attempt_id: int, task_ids: list[int]) -> dict:
    subs = {w.task_id: w for w in s.execute(select(SpeakingSubmission).where(
        SpeakingSubmission.attempt_id == attempt_id)).scalars()}
    notes = [subs[t].note20 if t in subs and subs[t].note20 is not None else 0.0
             for t in task_ids]
    note = round(sum(notes) / len(notes) * 2) / 2 if notes else 0.0
    return {"note20": note, "level": L.expression_level(note) if note else "< A1",
            "tasks": {str(i + 1): n for i, n in enumerate(notes)},
            "disclaimer": L.DISCLAIMER}


def history(s: Session, limit: int = 50) -> list[SpeakingSubmission]:
    return list(s.execute(select(SpeakingSubmission)
                          .order_by(SpeakingSubmission.created_at.desc()).limit(limit)).scalars())
