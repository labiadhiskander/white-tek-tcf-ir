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
