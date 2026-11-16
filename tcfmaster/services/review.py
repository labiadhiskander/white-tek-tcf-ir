"""Répétition espacée (SM-2 simplifié) pour vocabulaire, expressions et grammaire."""
from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from tcfmaster.db.models import ReviewItem


def schedule(item: ReviewItem, quality: int, today: date | None = None) -> ReviewItem:
    """quality : 0 (oubli total) … 5 (réponse parfaite)."""
    today = today or date.today()
    q = max(0, min(5, quality))
    if q < 3:
        item.repetitions = 0
        item.interval_days = 1
    else:
        item.repetitions += 1
        if item.repetitions == 1:
            item.interval_days = 1
        elif item.repetitions == 2:
            item.interval_days = 6
        else:
            item.interval_days = round(item.interval_days * item.easiness)
    item.easiness = max(1.3, item.easiness + 0.1 - (5 - q) * (0.08 + (5 - q) * 0.02))
    item.last_reviewed = today
    item.due = today + timedelta(days=item.interval_days)
    return item


def review(s: Session, item_type: str, item_id: int, quality: int,
           today: date | None = None) -> ReviewItem:
    it = s.execute(select(ReviewItem).where(ReviewItem.item_type == item_type,
                                            ReviewItem.item_id == item_id)
                   ).scalar_one_or_none()
    if it is None:
        it = ReviewItem(item_type=item_type, item_id=item_id, easiness=2.5,
                        interval_days=0, repetitions=0, due=today or date.today())
        s.add(it)
    schedule(it, quality, today)
    s.flush()
    return it


def due_items(s: Session, item_type: str | None = None, today: date | None = None,
              limit: int = 50) -> list[ReviewItem]:
    today = today or date.today()
    q = select(ReviewItem).where(ReviewItem.due <= today)
    if item_type:
        q = q.where(ReviewItem.item_type == item_type)
    return list(s.execute(q.order_by(ReviewItem.due).limit(limit)).scalars())


def acquired_count(s: Session, item_type: str) -> int:
    """Éléments considérés comme acquis : au moins 3 révisions réussies d'affilée."""
    return len(list(s.execute(select(ReviewItem.id).where(
        ReviewItem.item_type == item_type, ReviewItem.repetitions >= 3)).scalars()))


# ------------------------------------------------------------------------
# v1.1 : lexique des documents manqués (vocabulaire à revoir)
# ------------------------------------------------------------------------
LEXICON = "lexique"
_LEX_FACTOR = 1000      # item_id = id de l'exercice × 1000 + rang du terme


def lexicon_id(exercise_id: int, index: int) -> int:
    return exercise_id * _LEX_FACTOR + index


def enqueue_lexicon(s: Session, exercise, today: date | None = None) -> int:
    """Une question manquée sur un document met son vocabulaire en révision dès
    aujourd'hui (répétition espacée). Renvoie le nombre de termes concernés."""
    today = today or date.today()
    n = 0
    for i, v in enumerate(exercise.vocabulary or []):
        if not isinstance(v, dict) or not v.get("terme"):
            continue
        iid = lexicon_id(exercise.id, i)
        it = s.execute(select(ReviewItem).where(ReviewItem.item_type == LEXICON,
                                                ReviewItem.item_id == iid)).scalar_one_or_none()
        if it is None:
            s.add(ReviewItem(item_type=LEXICON, item_id=iid, easiness=2.5, interval_days=0,
                             repetitions=0, due=today))
        elif it.due > today:
            it.due = today               # de nouveau manqué : revu dès aujourd'hui
        n += 1
    s.flush()
    return n


def lexicon_entry(s: Session, item: ReviewItem) -> dict | None:
    from tcfmaster.db.models import Exercise
    ex = s.get(Exercise, item.item_id // _LEX_FACTOR)
    voc = list(ex.vocabulary or []) if ex else []
    i = item.item_id % _LEX_FACTOR
    if i >= len(voc) or not isinstance(voc[i], dict):
        return None
    v = voc[i]
    return {"item_id": item.item_id, "term": v.get("terme", ""),
            "definition": v.get("definition", ""), "example": v.get("exemple", ""),
            "source": f"{ex.code} – {ex.title}", "section": ex.section, "due": item.due,
            "repetitions": item.repetitions}


def lexicon_due(s: Session, today: date | None = None, limit: int = 20) -> list[dict]:
    out = []
    for it in due_items(s, LEXICON, today, limit=limit * 2):
        e = lexicon_entry(s, it)
        if e:
            out.append(e)
        if len(out) >= limit:
            break
    return out


def lexicon_counts(s: Session, today: date | None = None) -> dict[str, int]:
    from sqlalchemy import func
    today = today or date.today()
    base = select(func.count(ReviewItem.id)).where(ReviewItem.item_type == LEXICON)
    return {"total": s.execute(base).scalar_one(),
            "due": s.execute(base.where(ReviewItem.due <= today)).scalar_one(),
            "acquired": acquired_count(s, LEXICON)}
