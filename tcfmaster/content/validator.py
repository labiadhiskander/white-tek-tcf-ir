"""Validation du contenu pédagogique avant import.

Garantit le respect du format TCF IRN :
  * 25 questions CO + 25 questions CE par examen complet ;
  * exactement 4 propositions par question, étiquetées A–D ;
  * une et une seule bonne réponse (aucune double bonne réponse involontaire) ;
  * propositions toutes différentes ;
  * 3 tâches EE dans les limites de mots officielles ;
  * 3 tâches EO avec les durées officielles ;
  * réponses modèles EE elles-mêmes conformes aux limites de mots.
"""
from __future__ import annotations

import re
import unicodedata

from tcfmaster.db.models import (CHOICES_PER_QUESTION, QUESTIONS_PER_COMPREHENSION,
                                 SPEAKING_DURATIONS_S, WRITING_WORD_LIMITS)

VALID_LEVELS = {"A1", "A2", "B1", "B2", "C1", "C2"}
_WORD_RE = re.compile(r"[A-Za-zÀ-ÖØ-öø-ÿœŒæÆ0-9]+(?:['’\-][A-Za-zÀ-ÖØ-öø-ÿœŒæÆ0-9]+)*")


def count_words(text: str) -> int:
    """Compte les mots comme le TCF : « l'école » = 1 mot, « porte-monnaie » = 1 mot."""
    return len(_WORD_RE.findall(text or ""))


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode()
    return re.sub(r"\W+", " ", s.lower()).strip()


def validate_question(q: dict, where: str) -> list[str]:
    errs: list[str] = []
    for key in ("level", "doc_type", "document", "prompt", "choices", "explanation"):
        if not q.get(key):
            errs.append(f"{where}: champ « {key} » manquant ou vide")
    if q.get("level") and q["level"] not in VALID_LEVELS:
        errs.append(f"{where}: niveau invalide {q['level']}")
    choices = q.get("choices") or []
    if len(choices) != CHOICES_PER_QUESTION:
        errs.append(f"{where}: {len(choices)} propositions au lieu de 4")
    labels = [c.get("label") for c in choices]
    if labels and labels != ["A", "B", "C", "D"][:len(labels)]:
        errs.append(f"{where}: étiquettes incorrectes {labels}")
    n_ok = sum(1 for c in choices if c.get("correct"))
    if n_ok != 1:
        errs.append(f"{where}: {n_ok} bonne(s) réponse(s) au lieu d'une seule")
    texts = [_norm(c.get("text", "")) for c in choices]
    if len(set(texts)) != len(texts):
        errs.append(f"{where}: propositions en double")
    if any(not t for t in texts):
        errs.append(f"{where}: proposition vide")
    return errs


def validate_writing_task(t: dict, where: str) -> list[str]:
    errs: list[str] = []
    n = t.get("task_number")
    if n not in WRITING_WORD_LIMITS:
        return [f"{where}: numéro de tâche invalide {n}"]
    lo, hi = WRITING_WORD_LIMITS[n]
    if (t.get("min_words"), t.get("max_words")) != (lo, hi):
        errs.append(f"{where}: limites {t.get('min_words')}–{t.get('max_words')} "
                    f"au lieu de {lo}–{hi}")
    for key in ("task_type", "instructions", "model_answer"):
        if not t.get(key):
            errs.append(f"{where}: champ « {key} » manquant")
    if t.get("model_answer"):
        wc = count_words(t["model_answer"])
        if not lo <= wc <= hi:
            errs.append(f"{where}: réponse modèle de {wc} mots (attendu {lo}–{hi})")
    return errs


def validate_speaking_task(t: dict, where: str) -> list[str]:
    errs: list[str] = []
    n = t.get("task_number")
    if n not in SPEAKING_DURATIONS_S:
        return [f"{where}: numéro de tâche invalide {n}"]
    if t.get("duration_s") != SPEAKING_DURATIONS_S[n]:
        errs.append(f"{where}: durée {t.get('duration_s')} s au lieu de {SPEAKING_DURATIONS_S[n]} s")
    for key in ("title", "scenario", "examiner_prompts"):
        if not t.get(key):
            errs.append(f"{where}: champ « {key} » manquant")
    return errs


def validate_exam(exam: dict) -> list[str]:
    code = exam.get("code", "?")
    errs: list[str] = []
    for section in ("CO", "CE"):
        qs = exam.get(section) or []
        if len(qs) != QUESTIONS_PER_COMPREHENSION:
            errs.append(f"{code} {section}: {len(qs)} questions au lieu de 25")
        positions = [q.get("position") for q in qs]
        if sorted(positions) != list(range(1, len(qs) + 1)):
            errs.append(f"{code} {section}: positions non continues")
        for q in qs:
            errs += validate_question(q, f"{code} {section} Q{q.get('position')}")
    ee = exam.get("EE") or []
    if sorted(t.get("task_number") for t in ee) != [1, 2, 3]:
        errs.append(f"{code} EE: il faut exactement les tâches 1, 2 et 3")
    for t in ee:
        errs += validate_writing_task(t, f"{code} EE T{t.get('task_number')}")
    eo = exam.get("EO") or []
    if sorted(t.get("task_number") for t in eo) != [1, 2, 3]:
        errs.append(f"{code} EO: il faut exactement les tâches 1, 2 et 3")
    for t in eo:
        errs += validate_speaking_task(t, f"{code} EO T{t.get('task_number')}")
    return errs


def validate_expression(e: dict, where: str) -> list[str]:
    errs = []
    for key in ("kind", "category", "text", "meaning", "level", "example",
                "simple_equivalent", "exercise", "exercise_answer"):
        if not e.get(key):
            errs.append(f"{where}: champ « {key} » manquant")
    if e.get("level") and e["level"] not in VALID_LEVELS:
        errs.append(f"{where}: niveau invalide")
    return errs


def validate_grammar_exercise(ex: dict, where: str) -> list[str]:
    errs = []
    for key in ("ex_type", "prompt", "answer", "explanation"):
        if not ex.get(key):
            errs.append(f"{where}: champ « {key} » manquant")
    if ex.get("ex_type") == "qcm":
        opts = ex.get("options") or []
        answers = [a.strip() for a in ex.get("answer", "").split("|")]
        if len(opts) < 2:
            errs.append(f"{where}: QCM sans options")
        matches = [o for o in opts if o in answers]
        if len(matches) != 1:
            errs.append(f"{where}: QCM avec {len(matches)} bonne(s) réponse(s)")
    return errs
