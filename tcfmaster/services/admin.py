"""Administration du contenu B2 : code PIN, modification, validation, suppression.

Règles :
  * toute modification marque le contenu « modifié localement » : une mise à
    jour du contenu préinstallé ne l'écrase jamais ;
  * un contenu préinstallé n'est jamais effacé (l'historique du candidat en
    dépend) : « supprimer » le met en brouillon, ce qui le masque ; seuls les
    contenus créés dans l'administration sont réellement supprimés ;
  * « rétablir l'original » retire la marque locale : le contenu préinstallé est
    réimporté au prochain démarrage ;
  * les corrections restent obligatoires (validateur commun).
"""
from __future__ import annotations

import hashlib
import hmac
import os
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from tcfmaster.content import validator as V
from tcfmaster.db.models import (ORIGIN_ADMIN, STATUS_DRAFT, STATUS_VALID,
                                 WRITING_WORD_LIMITS, SPEAKING_DURATIONS_S, Exercise,
                                 SpeakingTask, Video, WritingTask)
from tcfmaster.services import settings as S

KINDS = {"exercise": Exercise, "writing": WritingTask, "speaking": SpeakingTask, "video": Video}


# ---------------------------------------------------------------- code PIN
def _digest(pin: str, salt: bytes) -> str:
    return hashlib.pbkdf2_hmac("sha256", pin.encode("utf-8"), salt, 120_000).hex()


def has_pin(s: Session) -> bool:
    return bool(S.get(s, "admin_pin_hash"))


def set_pin(s: Session, pin: str | None) -> None:
    """Définit (ou supprime si vide) le code PIN facultatif de l'administration."""
    if not pin:
        S.set_(s, "admin_pin_hash", "")
        S.set_(s, "admin_pin_salt", "")
        return
    if not pin.isdigit() or not 4 <= len(pin) <= 8:
        raise ValueError("Le code PIN doit contenir de 4 à 8 chiffres.")
    salt = os.urandom(16)
    S.set_(s, "admin_pin_salt", salt.hex())
    S.set_(s, "admin_pin_hash", _digest(pin, salt))


def check_pin(s: Session, pin: str) -> bool:
    stored = S.get(s, "admin_pin_hash")
    if not stored:
        return True
    salt = bytes.fromhex(S.get(s, "admin_pin_salt") or "")
    return hmac.compare_digest(stored, _digest(pin or "", salt))


# ------------------------------------------------------------- inventaire
@dataclass
class Row:
    kind: str
    id: int
    code: str
    section: str
    title: str
    status: str
    origin: str
    modified: bool


def rows(s: Session, kind: str, search: str = "") -> list[Row]:
    out: list[Row] = []
    if kind == "exercise":
        for e in s.execute(select(Exercise).order_by(Exercise.section, Exercise.code)).scalars():
            out.append(Row(kind, e.id, e.code, e.section, e.title, e.status, e.origin,
                           bool(e.locally_modified)))
    elif kind in ("writing", "speaking"):
        model = KINDS[kind]
        q = select(model).where(model.exam_id.is_(None), model.code.is_not(None))
        for t in s.execute(q.order_by(model.task_number, model.code)).scalars():
            title = t.instructions if kind == "writing" else t.title
            out.append(Row(kind, t.id, t.code, f"{'EE' if kind == 'writing' else 'EO'} "
                           f"T{t.task_number}", title[:120], t.status or STATUS_VALID,
                           t.origin or "", bool(t.locally_modified)))
    elif kind == "video":
        for v in s.execute(select(Video).order_by(Video.category, Video.code)).scalars():
            out.append(Row(kind, v.id, v.code, v.category, v.title, v.status, v.origin,
                           bool(v.locally_modified)))
    if search:
        needle = search.lower().strip()
        out = [r for r in out if needle in f"{r.code} {r.title} {r.section}".lower()]
    return out


def _get(s: Session, kind: str, obj_id: int):
    obj = s.get(KINDS[kind], obj_id)
    if obj is None:
        raise KeyError(f"{kind} {obj_id} introuvable")
    return obj


def set_status(s: Session, kind: str, obj_id: int, valid: bool) -> None:
    obj = _get(s, kind, obj_id)
    obj.status = STATUS_VALID if valid else STATUS_DRAFT
    obj.locally_modified = True


def delete(s: Session, kind: str, obj_id: int) -> str:
    """Supprime un contenu créé dans l'administration ; masque un contenu préinstallé."""
    obj = _get(s, kind, obj_id)
    if obj.origin == ORIGIN_ADMIN:
        s.delete(obj)
        return "supprimé"
    obj.status = STATUS_DRAFT
    obj.locally_modified = True
    return "masqué (contenu préinstallé conservé pour l'historique)"


def restore_original(s: Session, kind: str, obj_id: int) -> None:
    """Le contenu préinstallé sera réimporté au prochain démarrage."""
    obj = _get(s, kind, obj_id)
    obj.locally_modified = False
    if hasattr(obj, "content_hash"):
        obj.content_hash = ""


# ------------------------------------------------- exercices CO / CE
def update_exercise(s: Session, ex_id: int, data: dict) -> list[str]:
    """data = {title?, document?, questions?: [{prompt, explanation, choices:[{text,
    correct, rationale}]}]} ; les questions gardent leur position (historique)."""
    ex = _get(s, "exercise", ex_id)
    errs = []
    qs = data.get("questions")
    if qs is not None:
        if len(qs) != len(ex.questions):
            errs.append("Le nombre de questions ne peut pas changer (historique du candidat).")
        for i, qd in enumerate(qs, 1):
            errs += V.validate_exercise_question(
                {"prompt": qd.get("prompt", ""), "explanation": qd.get("explanation", ""),
                 "choices": [dict(c, label="ABCD"[j]) for j, c in
                             enumerate(qd.get("choices", [])[:4])] + qd.get("choices", [])[4:],
                 "skill": "admin"}, f"Q{i}")
    if not str(data.get("title", ex.title)).strip():
        errs.append("Titre manquant.")
    if errs:
        return errs
    if "title" in data:
        ex.title = data["title"]
    if "document" in data:
        ex.document = data["document"]
    for q, qd in zip(ex.questions, qs or []):
        q.prompt = qd["prompt"]
        q.explanation = qd["explanation"]
        q.document = ex.document
        for c, cd in zip(q.choices, qd["choices"]):
            c.text = cd["text"]
            c.is_correct = bool(cd["correct"])
            c.rationale = cd.get("rationale", "")
    ex.locally_modified = True
    s.flush()
    return []


# ------------------------------------------------- sujets EE / situations EO
def save_writing(s: Session, data: dict, task_id: int | None = None) -> tuple[WritingTask | None, list[str]]:
    n = int(data.get("task_number") or 1)
    lo, hi = WRITING_WORD_LIMITS.get(n, (0, 0))
    full = {"task_number": n, "level": "B2", "task_type": data.get("task_type", "sujet"),
            "instructions": data.get("instructions", ""), "min_words": lo, "max_words": hi,
            "model_answer": data.get("model_answer", ""), "tips": data.get("tips", ""),
            "model_commentary": data.get("model_commentary", ""),
            "expected_points": data.get("expected_points") or [],
            "code": data.get("code") or "admin"}
    errs = V.validate_writing_subject(full, full["code"])
    if errs:
        return None, errs
    t = s.get(WritingTask, task_id) if task_id else None
    if t is None:
        t = WritingTask(code=_next_code(s, WritingTask, "EE-PERSO"), origin=ORIGIN_ADMIN,
                        status=STATUS_DRAFT, task_number=n)
        s.add(t)
    for k in ("task_number", "task_type", "instructions", "min_words", "max_words",
              "model_answer", "tips", "model_commentary", "expected_points"):
        setattr(t, k, full[k])
    t.level = "B2"
    t.locally_modified = True
    s.flush()
    return t, []


def save_speaking(s: Session, data: dict, task_id: int | None = None) -> tuple[SpeakingTask | None, list[str]]:
    n = int(data.get("task_number") or 1)
    full = {"task_number": n, "level": "B2", "title": data.get("title", ""),
            "scenario": data.get("scenario", ""), "model_answer": data.get("model_answer", ""),
            "duration_s": SPEAKING_DURATIONS_S.get(n, 0),
            "examiner_role": data.get("examiner_role") or "Examinateur",
            "examiner_prompts": data.get("examiner_prompts") or [],
            "useful_phrases": data.get("useful_phrases") or [],
            "tips": data.get("tips", ""), "model_commentary": data.get("model_commentary", ""),
            "code": data.get("code") or "admin"}
    errs = V.validate_speaking_subject(full, full["code"])
    if errs:
        return None, errs
    t = s.get(SpeakingTask, task_id) if task_id else None
    if t is None:
        t = SpeakingTask(code=_next_code(s, SpeakingTask, "EO-PERSO"), origin=ORIGIN_ADMIN,
                         status=STATUS_DRAFT, task_number=n)
        s.add(t)
    for k in ("task_number", "title", "scenario", "model_answer", "duration_s",
              "examiner_role", "examiner_prompts", "useful_phrases", "tips", "model_commentary"):
        setattr(t, k, full[k])
    t.level = "B2"
    t.locally_modified = True
    s.flush()
    return t, []


def _next_code(s: Session, model, prefix: str) -> str:
    n = 1
    while s.execute(select(model).where(model.code == f"{prefix}-{n:03d}")).first():
        n += 1
    return f"{prefix}-{n:03d}"
