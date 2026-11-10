"""Suivi de progression : statistiques du tableau de bord et alertes pédagogiques.

Règle de préparation : le candidat n'est jamais déclaré « prêt » sur la base
d'une seule bonne note. Il faut, pour CHAQUE compétence, au moins
`MIN_RESULTS_FOR_READINESS` résultats récents, dont la moyenne glissante ET le
plus faible des derniers résultats atteignent B2.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from tcfmaster.core import levels as L
from tcfmaster.db.models import (SECTIONS, SECTION_LABELS, Attempt, ErrorLog, Profile,
                                 SpeakingSubmission, StudySession, WritingSubmission)

MIN_RESULTS_FOR_READINESS = 3
WINDOW = 5


@dataclass
class SkillStatus:
    section: str
    history: list[float] = field(default_factory=list)  # scores (CO/CE /699, EE/EO /20)
    levels: list[str] = field(default_factory=list)

    @property
    def is_comprehension(self) -> bool:
        return self.section in ("CO", "CE")

    @property
    def recent(self) -> list[float]:
        return self.history[-WINDOW:]

    @property
    def average(self) -> float | None:
        r = self.recent
        return sum(r) / len(r) if r else None

    @property
    def estimated_level(self) -> str | None:
        avg = self.average
        if avg is None:
            return None
        return L.comprehension_level(avg) if self.is_comprehension else L.expression_level(avg)

    @property
    def ready(self) -> bool:
        r = self.history[-MIN_RESULTS_FOR_READINESS:]
        if len(r) < MIN_RESULTS_FOR_READINESS:
            return False
        lvl_fn = L.comprehension_level if self.is_comprehension else L.expression_level
        return L.meets_target(lvl_fn(min(r))) and L.meets_target(self.estimated_level or "")


def skill_statuses(s: Session) -> dict[str, SkillStatus]:
    st = {sec: SkillStatus(sec) for sec in SECTIONS}
    attempts = s.execute(select(Attempt).where(Attempt.finished_at.is_not(None))
                         .order_by(Attempt.finished_at)).scalars()
    for a in attempts:
        for sec, r in (a.results or {}).items():
            if sec not in st or not isinstance(r, dict):
                continue
            val = r.get("score") if sec in ("CO", "CE") else r.get("note20")
            if val is None:
                continue
            st[sec].history.append(float(val))
            st[sec].levels.append(r.get("level", ""))
    # Productions hors examen (entraînement libre)
    for model, sec in ((WritingSubmission, "EE"), (SpeakingSubmission, "EO")):
        rows = s.execute(select(model).where(model.attempt_id.is_(None),
                                             model.note20.is_not(None))
                         .order_by(model.created_at)).scalars()
        for r in rows:
            st[sec].history.append(float(r.note20))
            st[sec].levels.append(r.level or "")
    return st


def overall_level(statuses: dict[str, SkillStatus]) -> str | None:
    lv = [x.estimated_level for x in statuses.values() if x.estimated_level in L.LEVELS]
    if not lv:
        return None
    # Le niveau global est plafonné par la compétence la plus faible + 1 au maximum,
    # et arrondi vers le bas de la médiane : prudence pédagogique.
    idx = sorted(L.level_index(x) for x in lv)
    median = idx[(len(idx) - 1) // 2]
    return L.LEVELS[min(median, idx[0] + 1)]


def alerts(statuses: dict[str, SkillStatus]) -> list[str]:
    out = []
    for sec, st in statuses.items():
        name = SECTION_LABELS[sec]
        if st.estimated_level is None:
            out.append(f"{name} : aucune évaluation pour l'instant. Faites un premier exercice.")
        elif not L.meets_target(st.estimated_level):
            out.append(f"⚠ {name} : niveau estimé {st.estimated_level}, inférieur à l'objectif B2.")
        elif not st.ready:
            out.append(f"{name} : niveau B2 atteint récemment, à confirmer sur au moins "
                       f"{MIN_RESULTS_FOR_READINESS} épreuves consécutives.")
    return out


def is_ready(statuses: dict[str, SkillStatus]) -> bool:
    return all(st.ready for st in statuses.values())


def dashboard(s: Session) -> dict:
    st = skill_statuses(s)
    profile = s.execute(select(Profile)).scalars().first()
    n_full = s.execute(select(func.count(Attempt.id)).where(
        Attempt.finished_at.is_not(None), Attempt.exam_id.is_not(None))).scalar_one()
    total_time = s.execute(select(func.coalesce(func.sum(StudySession.duration_s), 0))
                           ).scalar_one()
    err_counts = Counter(c for (c,) in s.execute(select(ErrorLog.category)).all())

    def rate(sec):
        hist = [a for a in s.execute(select(Attempt).where(Attempt.finished_at.is_not(None))
                                     ).scalars() if sec in (a.results or {})]
        tot = sum(a.results[sec].get("total", 0) for a in hist)
        ok = sum(a.results[sec].get("correct", 0) for a in hist)
        return round(100 * ok / tot, 1) if tot else None

    return {
        "initial_level": profile.initial_level if profile else None,
        "current_level": overall_level(st),
        "target": L.TARGET_LEVEL,
        "exams_done": n_full,
        "co_rate": rate("CO"),
        "ce_rate": rate("CE"),
        "ee_history": st["EE"].history,
        "eo_history": st["EO"].history,
        "grammar_errors": sum(err_counts.values()),
        "error_categories": err_counts.most_common(10),
        "training_minutes": round(total_time / 60),
        "skills": {k: {"level": v.estimated_level, "average": v.average, "ready": v.ready,
                       "history": v.history} for k, v in st.items()},
        "alerts": alerts(st),
        "ready": is_ready(st),
        "disclaimer": L.DISCLAIMER,
    }
