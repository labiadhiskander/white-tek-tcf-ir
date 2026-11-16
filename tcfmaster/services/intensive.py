"""Programme intensif B2 de 30 jours : suivi, jour en cours, examens blancs.

Il complète le programme de 12 semaines (les deux progressions sont
indépendantes). Les jours 10, 20 et 29 sont des examens blancs B2 : un
examen terminé après le début du programme coche automatiquement ses quatre
épreuves.
"""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from tcfmaster.db.models import Attempt, Exam, IntensiveDay, IntensiveProgress
from tcfmaster.services import settings as S

START_KEY = "intensive_start"
DAYS = 30


def days(s: Session) -> list[IntensiveDay]:
    return list(s.execute(select(IntensiveDay).order_by(IntensiveDay.day)).scalars())


def done_map(s: Session) -> dict[int, set[int]]:
    out: dict[int, set[int]] = {}
    for p in s.execute(select(IntensiveProgress)).scalars():
        out.setdefault(p.day_id, set()).add(p.activity_index)
    return out


def toggle(s: Session, day_id: int, index: int, on: bool) -> None:
    row = s.execute(select(IntensiveProgress).where(
        IntensiveProgress.day_id == day_id, IntensiveProgress.activity_index == index)
    ).scalar_one_or_none()
    if on and row is None:
        s.add(IntensiveProgress(day_id=day_id, activity_index=index))
    elif not on and row is not None:
        s.delete(row)
    s.flush()
    if on and start_date(s) is None:
        start(s)


# ------------------------------------------------------------- calendrier
def start_date(s: Session) -> date | None:
    v = S.get(s, START_KEY)
    try:
        return date.fromisoformat(v) if v else None
    except (TypeError, ValueError):
        return None


def start(s: Session, today: date | None = None) -> date:
    d = today or date.today()
    S.set_(s, START_KEY, d.isoformat())
    return d


def reset(s: Session) -> None:
    """Recommence le programme : efface la progression intensive (rien d'autre)."""
    for p in s.execute(select(IntensiveProgress)).scalars():
        s.delete(p)
    S.set_(s, START_KEY, "")
    s.flush()


def calendar_day(s: Session, today: date | None = None) -> int | None:
    """Jour du programme selon le calendrier (1 le jour du démarrage), borné à 30."""
    d0 = start_date(s)
    if d0 is None:
        return None
    return max(1, min(DAYS, ((today or date.today()) - d0).days + 1))


# ------------------------------------------------------------- examens blancs
def mock_result(s: Session, day: IntensiveDay) -> Attempt | None:
    """Dernier passage terminé de l'examen blanc du jour (depuis le début du programme)."""
    if not day.exam_code:
        return None
    exam = s.execute(select(Exam).where(Exam.code == day.exam_code)).scalar_one_or_none()
    if exam is None:
        return None
    q = select(Attempt).where(Attempt.exam_id == exam.id, Attempt.finished_at.is_not(None))
    d0 = start_date(s)
    if d0 is not None:
        q = q.where(Attempt.finished_at >= datetime.combine(d0, datetime.min.time()))
    return s.execute(q.order_by(Attempt.finished_at.desc())).scalars().first()


def sync_mock_days(s: Session) -> int:
    """Coche les épreuves d'un examen blanc du programme déjà passé ; renvoie le nombre
    d'activités cochées."""
    n = 0
    done = done_map(s)
    for d in days(s):
        if not d.is_mock_exam:
            continue
        a = mock_result(s, d)
        if a is None:
            continue
        passed = set(a.sections or []) | set((a.results or {}).keys())
        for i, act in enumerate(d.activities or []):
            if act.get("ref") == "mock" and i not in done.get(d.id, set()) \
                    and _section_of(act) in passed:
                s.add(IntensiveProgress(day_id=d.id, activity_index=i))
                n += 1
    s.flush()
    return n


def _section_of(act: dict) -> str:
    return {"Compréhension orale": "CO", "Compréhension écrite": "CE",
            "Expression écrite": "EE", "Expression orale": "EO"}.get(act.get("module"), "")


# ------------------------------------------------------------- progression
def progress(s: Session, today: date | None = None) -> dict:
    ds = days(s)
    done = done_map(s)
    total = sum(len(d.activities or []) for d in ds)
    n_done = sum(len(v) for v in done.values())
    complete = [d.day for d in ds if d.activities and
                len(done.get(d.id, set())) >= len(d.activities)]
    current = next((d.day for d in ds if len(done.get(d.id, set())) < len(d.activities or [])),
                   ds[-1].day if ds else 0)
    mocks = []
    for d in ds:
        if d.is_mock_exam:
            a = mock_result(s, d)
            mocks.append({"day": d.day, "code": d.exam_code, "done": a is not None,
                          "results": dict(a.results or {}) if a else {}})
    minutes_left = sum(a.get("minutes", 0) for d in ds for i, a in enumerate(d.activities or [])
                       if i not in done.get(d.id, set()))
    return {"total": total, "done": n_done,
            "percent": round(100 * n_done / total) if total else 0,
            "days_complete": len(complete), "current_day": current,
            "calendar_day": calendar_day(s, today), "started": start_date(s),
            "mocks": mocks, "minutes_left": minutes_left, "days": len(ds)}


def completed_count(s: Session) -> int:
    return s.execute(select(func.count(IntensiveProgress.id))).scalar_one()
