"""Suivi de progression : statistiques du tableau de bord et alertes pédagogiques.

Règle de préparation : le candidat n'est jamais déclaré « prêt » sur la base
d'une seule bonne note. Il faut, pour CHAQUE compétence, au moins
`MIN_RESULTS_FOR_READINESS` résultats récents, dont la moyenne glissante ET le
plus faible des derniers résultats atteignent B2, et au moins
`MIN_FULL_EXAMS` examens blancs complets (4 épreuves) doivent avoir été passés.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from tcfmaster.core import levels as L
from tcfmaster.db.models import (SECTIONS, SECTION_LABELS, Attempt, ErrorLog, PlanDay,
                                 PlanProgress, Profile, ReviewItem, SpeakingSubmission,
                                 StudySession, WritingSubmission)

MIN_RESULTS_FOR_READINESS = 3
MIN_FULL_EXAMS = 2
WINDOW = 5
MAX_ATTEMPT_S = 3 * 3600          # une tentative laissée ouverte ne compte pas des jours entiers
SKILL_PAGES = {"CO": "co", "CE": "ce", "EE": "ee", "EO": "eo"}


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


def is_ready(statuses: dict[str, SkillStatus], full_exams: int | None = None) -> bool:
    """Prêt = chaque compétence stabilisée au niveau B2 ET assez d'examens blancs complets."""
    if full_exams is not None and full_exams < MIN_FULL_EXAMS:
        return False
    return all(st.ready for st in statuses.values())


def full_exam_count(s: Session) -> int:
    """Examens blancs complets : tentatives terminées couvrant les 4 épreuves."""
    rows = s.execute(select(Attempt.results).where(Attempt.finished_at.is_not(None),
                                                   Attempt.exam_id.is_not(None))).all()
    return sum(1 for (r,) in rows if r and all(sec in r for sec in SECTIONS))


# ------------------------------------------------------------ préparation détaillée
@dataclass
class SkillReadiness:
    section: str
    label: str
    results: int
    average_level: str | None
    weakest_recent_level: str | None
    status: str                    # « stabilisé », « à confirmer », « insuffisant », « non évalué »
    advice: str


def readiness(statuses: dict[str, SkillStatus]) -> list[SkillReadiness]:
    out = []
    for sec, st in statuses.items():
        fn = L.comprehension_level if st.is_comprehension else L.expression_level
        last = st.history[-MIN_RESULTS_FOR_READINESS:]
        weakest = fn(min(last)) if last else None
        label = SECTION_LABELS[sec]
        if not st.history:
            status, adv = "non évalué", "Faites une première épreuve."
        elif st.ready:
            status, adv = "stabilisé", "Niveau B2 confirmé sur les dernières épreuves."
        elif L.meets_target(st.estimated_level or ""):
            missing = MIN_RESULTS_FOR_READINESS - len(last)
            status = "à confirmer"
            adv = (f"Encore {missing} épreuve(s) au niveau B2 pour confirmer." if missing > 0
                   else f"Un résultat récent ({weakest}) est sous B2 : à consolider.")
        else:
            status = "insuffisant"
            adv = f"Niveau estimé {st.estimated_level} : priorité d'entraînement."
        out.append(SkillReadiness(sec, label, len(st.history), st.estimated_level, weakest,
                                  status, adv))
    return out


def verdict(statuses: dict[str, SkillStatus], full_exams: int) -> tuple[bool, str]:
    """Avis global prudent : jamais « prêt » sur un seul résultat."""
    if is_ready(statuses, full_exams):
        return True, ("Les quatre compétences sont stabilisées au niveau B2 sur plusieurs "
                      "épreuves et vous avez passé au moins "
                      f"{MIN_FULL_EXAMS} examens blancs complets. Continuez à vous entraîner "
                      "régulièrement jusqu'au jour de l'examen.")
    reasons = []
    not_ok = [SECTION_LABELS[k] for k, v in statuses.items() if not v.ready]
    if not_ok:
        reasons.append("compétences pas encore stabilisées au niveau B2 : " + ", ".join(not_ok))
    if full_exams < MIN_FULL_EXAMS:
        reasons.append(f"examens blancs complets passés : {full_exams} sur "
                       f"{MIN_FULL_EXAMS} minimum")
    return False, "Pas encore prêt : " + " ; ".join(reasons) + "."


# ------------------------------------------------------------ temps et régularité
def activity_by_day(s: Session, days: int = 28, today: date | None = None) -> dict[date, float]:
    """Minutes d'entraînement par jour (toutes activités confondues)."""
    today = today or date.today()
    start = today - timedelta(days=days - 1)
    since = datetime.combine(start, datetime.min.time())
    out = {start + timedelta(days=i): 0.0 for i in range(days)}

    def add(when: datetime | None, seconds: float | None) -> None:
        if when and seconds and when.date() in out:
            out[when.date()] += float(seconds) / 60

    for st in s.execute(select(StudySession).where(StudySession.started_at >= since)).scalars():
        add(st.started_at, st.duration_s)
    for a in s.execute(select(Attempt).where(Attempt.started_at >= since,
                                             Attempt.finished_at.is_not(None))).scalars():
        add(a.started_at, min(MAX_ATTEMPT_S, (a.finished_at - a.started_at).total_seconds()))
    for model in (WritingSubmission, SpeakingSubmission):
        for w in s.execute(select(model).where(model.attempt_id.is_(None),
                                               model.created_at >= since)).scalars():
            add(w.created_at, w.duration_s)
    return {d: round(m, 1) for d, m in out.items()}


def total_training_minutes(s: Session) -> int:
    total = s.execute(select(func.coalesce(func.sum(StudySession.duration_s), 0))).scalar_one()
    for a in s.execute(select(Attempt).where(Attempt.finished_at.is_not(None))).scalars():
        total += min(MAX_ATTEMPT_S, (a.finished_at - a.started_at).total_seconds())
    for model in (WritingSubmission, SpeakingSubmission):
        total += s.execute(select(func.coalesce(func.sum(model.duration_s), 0)).where(
            model.attempt_id.is_(None))).scalar_one()
    return round(total / 60)


def last_activity(s: Session) -> datetime | None:
    cands = [s.execute(select(func.max(StudySession.started_at))).scalar_one(),
             s.execute(select(func.max(Attempt.started_at))).scalar_one(),
             s.execute(select(func.max(WritingSubmission.created_at))).scalar_one(),
             s.execute(select(func.max(SpeakingSubmission.created_at))).scalar_one()]
    cands = [c for c in cands if c]
    return max(cands) if cands else None


def plan_progress(s: Session) -> dict:
    days = list(s.execute(select(PlanDay).order_by(PlanDay.week, PlanDay.day)).scalars())
    total = sum(len(d.activities or []) for d in days)
    done = s.execute(select(func.count(PlanProgress.id))).scalar_one()
    # Semaine en cours : première semaine contenant une activité non faite.
    done_keys = {(p.plan_day_id, p.activity_index)
                 for p in s.execute(select(PlanProgress)).scalars()}
    week = next((d.week for d in days for i, _ in enumerate(d.activities or [])
                 if (d.id, i) not in done_keys), days[-1].week if days else 0)
    return {"total": total, "done": done, "percent": round(100 * done / total) if total else 0,
            "current_week": week, "weeks": max((d.week for d in days), default=0)}


# ------------------------------------------------------------ recommandations
@dataclass
class Recommendation:
    text: str
    page: str | None = None        # clé de page du menu, pour un bouton « Y aller »
    priority: int = 2              # 1 = urgent


def recommendations(s: Session, statuses: dict[str, SkillStatus] | None = None,
                    now: datetime | None = None) -> list[Recommendation]:
    now = now or datetime.now()
    st = statuses or skill_statuses(s)
    recs: list[Recommendation] = []
    # 1. compétence la plus faible
    evaluated = {k: v for k, v in st.items() if v.estimated_level}
    missing = [k for k, v in st.items() if not v.estimated_level]
    for k in missing:
        recs.append(Recommendation(f"Évaluez votre niveau en {SECTION_LABELS[k].lower()} : "
                                   "aucun résultat pour l'instant.", SKILL_PAGES[k], 1))
    if evaluated:
        weakest = min(evaluated, key=lambda k: L.level_index(evaluated[k].estimated_level))
        lvl = evaluated[weakest].estimated_level
        if not L.meets_target(lvl):
            recs.append(Recommendation(
                f"Priorité : {SECTION_LABELS[weakest].lower()} (niveau estimé {lvl}). "
                "Faites au moins deux séances par semaine sur cette compétence.",
                SKILL_PAGES[weakest], 1))
    # 2. erreurs récurrentes
    since = now - timedelta(days=30)
    errs = Counter(c for (c,) in s.execute(select(ErrorLog.category).where(
        ErrorLog.created_at >= since)).all())
    if errs:
        cat, n = errs.most_common(1)[0]
        if n >= 3:
            recs.append(Recommendation(
                f"Erreur récurrente : « {cat} » ({n} fois ce mois-ci). Lancez une série "
                "d'exercices personnalisés.", "custom", 1 if n >= 6 else 2))
    # 3. révisions dues
    due = s.execute(select(func.count(ReviewItem.id)).where(
        ReviewItem.due <= now.date())).scalar_one()
    if due:
        recs.append(Recommendation(f"{due} élément(s) de vocabulaire à réviser aujourd'hui.",
                                   "vocab", 2))
    # 4. régularité
    last = last_activity(s)
    if last is not None and (now - last).days >= 3:
        recs.append(Recommendation(f"Aucune activité depuis {(now - last).days} jours : "
                                   "15 minutes par jour valent mieux qu'une longue séance "
                                   "par semaine.", "plan", 1))
    # 5. examens blancs
    last_full = s.execute(select(func.max(Attempt.finished_at)).where(
        Attempt.exam_id.is_not(None), Attempt.finished_at.is_not(None))).scalar_one()
    if full_exam_count(s) < MIN_FULL_EXAMS:
        recs.append(Recommendation(
            f"Passez un examen blanc complet en conditions réelles (au moins {MIN_FULL_EXAMS} "
            "avant de vous estimer prêt).", "mock", 2))
    elif last_full and (now - last_full).days > 14:
        recs.append(Recommendation("Votre dernier examen blanc date de plus de deux semaines : "
                                   "refaites-en un pour vérifier vos acquis.", "mock", 2))
    # 6. programme
    pp = plan_progress(s)
    if pp["total"] and pp["done"] == 0:
        recs.append(Recommendation("Commencez votre programme de préparation sur 12 semaines.",
                                   "plan", 3))
    if not recs:
        recs.append(Recommendation("Continuez ainsi : alternez examens blancs, productions "
                                   "écrites et orales, et révisions.", None, 3))
    return sorted(recs, key=lambda r: r.priority)


def dashboard(s: Session) -> dict:
    st = skill_statuses(s)
    profile = s.execute(select(Profile)).scalars().first()
    n_full = s.execute(select(func.count(Attempt.id)).where(
        Attempt.finished_at.is_not(None), Attempt.exam_id.is_not(None))).scalar_one()
    complete = full_exam_count(s)
    ready, verdict_text = verdict(st, complete)
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
        "training_minutes": total_training_minutes(s),
        "full_exams": complete,
        "readiness": readiness(st),
        "verdict": verdict_text,
        "ee_average": st["EE"].average,
        "eo_average": st["EO"].average,
        "skills": {k: {"level": v.estimated_level, "average": v.average, "ready": v.ready,
                       "history": v.history} for k, v in st.items()},
        "alerts": alerts(st),
        "ready": ready,
        "disclaimer": L.DISCLAIMER,
    }
