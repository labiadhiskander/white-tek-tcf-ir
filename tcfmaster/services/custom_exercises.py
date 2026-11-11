"""Exercices personnalisés, construits à partir du journal des erreurs.

Une série mélange :
1. des corrections d'erreurs tirées de VOS productions (EE, EO, tuteur) ;
2. des exercices de grammaire des chapitres liés à vos difficultés récurrentes ;
3. si le journal est vide, un diagnostic couvrant plusieurs chapitres.
Chaque exercice a une correction détaillée et la raison pour laquelle il est proposé.
"""
from __future__ import annotations

import random
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from tcfmaster.db.models import ErrorLog, GrammarChapter, GrammarExercise, StudySession
from tcfmaster.services import error_tracking as ET
from tcfmaster.services import learning as LS
from tcfmaster.services.writing_rules import RULES

RULE_CHAPTER = {r.id: r.chapter for r in RULES if getattr(r, "chapter", "")}
SOURCE_LABELS = {"EE": "expression écrite", "EO": "expression orale", "IA": "tuteur IA",
                 "grammaire": "exercice de grammaire", "perso": "exercice personnalisé"}
_LETTERS = re.compile(r"[A-Za-zÀ-ÿ]{2,}")


@dataclass
class CustomExercise:
    kind: str                  # correction | trou | qcm | transformation
    prompt: str
    accepted: list[str]
    explanation: str
    origin: str                # pourquoi cet exercice est proposé
    options: list[str] | None = None
    chapter: str = ""          # slug du chapitre lié
    exercise_id: int | None = None
    rule: str | None = None
    meta: dict = field(default_factory=dict)


def _rule_text(row: ErrorLog) -> str:
    return re.sub(r"^\[[\w-]+\]\s*", "", row.rule or "").strip()


def _correction_items(s: Session, limit: int) -> list[CustomExercise]:
    rows = list(s.execute(select(ErrorLog).where(ErrorLog.source.in_(("EE", "EO", "IA", "perso")))
                          .order_by(ErrorLog.created_at.desc()).limit(300)).scalars())
    freq = Counter(ET.rule_id(r) for r in rows)
    seen, out = set(), []
    for r in sorted(rows, key=lambda r: -freq[ET.rule_id(r)]):
        exc, fix = (r.excerpt or "").strip(), (r.correction or "").strip()
        key = (exc.lower(), fix.lower())
        if (not exc or not fix or key in seen or exc.lower() == fix.lower()
                or not _LETTERS.search(exc) or len(exc) > 120):
            continue
        seen.add(key)
        rid = ET.rule_id(r)
        n = freq[rid]
        out.append(CustomExercise(
            "correction",
            f"Corrigez ce passage tiré de votre {SOURCE_LABELS.get(r.source, r.source)} "
            f"du {r.created_at:%d/%m} : « {exc} »",
            [fix], _rule_text(r) or "Voir la règle associée.",
            f"Erreur de type « {r.category} » relevée {n} fois dans vos productions.",
            chapter=RULE_CHAPTER.get(rid or "", ""), rule=rid, meta={"category": r.category}))
        if len(out) >= limit:
            break
    return out


def _weak_chapters(s: Session) -> list[tuple[str, int]]:
    titles = {t: slug for slug, t in s.execute(select(GrammarChapter.slug,
                                                       GrammarChapter.title)).all()}
    score: Counter = Counter()
    for w in ET.weaknesses(s, limit=20):
        if w.category in titles:
            score[titles[w.category]] += w.count
            continue
        for slug in {RULE_CHAPTER[r] for r in w.rules if RULE_CHAPTER.get(r)}:
            score[slug] += w.count
    return score.most_common()


def _grammar_items(s: Session, slug: str, k: int, rng: random.Random,
                   avoid: set[int], origin: str) -> list[CustomExercise]:
    ch = s.execute(select(GrammarChapter).where(GrammarChapter.slug == slug)).scalar_one_or_none()
    if ch is None:
        return []
    # On privilégie les exercices déjà manqués, puis les niveaux B2.
    missed = {r.excerpt for r in s.execute(select(ErrorLog).where(
        ErrorLog.source == "grammaire", ErrorLog.category == ch.title)).scalars()}
    pool = [e for e in ch.exercises if e.id not in avoid]
    rng.shuffle(pool)
    pool.sort(key=lambda e: (e.level != "B2",))
    out = []
    for e in pool[:k]:
        avoid.add(e.id)
        out.append(CustomExercise(e.ex_type, e.prompt, e.accepted_answers(), e.explanation,
                                  origin, list(e.options) if e.options else None, slug, e.id,
                                  meta={"chapter_title": ch.title, "missed_before": bool(missed)}))
    return out


def build_session(s: Session, n: int = 10, rng: random.Random | None = None
                  ) -> list[CustomExercise]:
    rng = rng or random.Random()
    items = _correction_items(s, limit=max(2, n * 4 // 10))
    weak = _weak_chapters(s)
    avoid: set[int] = set()
    if weak:
        total = sum(c for _, c in weak[:3])
        for slug, c in weak[:3]:
            k = max(1, round((n - len(items)) * c / total))
            ch_title = s.execute(select(GrammarChapter.title).where(
                GrammarChapter.slug == slug)).scalar_one_or_none() or slug
            items += _grammar_items(s, slug, k, rng, avoid,
                                    f"Chapitre « {ch_title} » : difficulté récurrente "
                                    f"({c} erreur{'s' if c > 1 else ''}).")
    if len(items) < n:
        # Diagnostic : on complète avec des chapitres variés.
        slugs = [x for (x,) in s.execute(select(GrammarChapter.slug)).all()]
        rng.shuffle(slugs)
        label = ("Diagnostic : aucune erreur enregistrée pour l'instant, cet exercice aide à "
                 "repérer vos points faibles." if not weak and not items else
                 "Révision générale pour compléter la série.")
        for slug in slugs:
            if len(items) >= n:
                break
            items += _grammar_items(s, slug, 1, rng, avoid, label)
    return items[:n]


def check(ex: CustomExercise, given: str) -> tuple[bool, bool]:
    """(correct, correct_sauf_accents). Accepte la lettre d'une option de QCM."""
    g = (given or "").strip()
    if ex.options and re.fullmatch(r"[a-dA-D]\)?", g):
        idx = ord(g[0].lower()) - 97
        if idx < len(ex.options):
            g = ex.options[idx]
    return LS.check_answer(g, ex.accepted)


def record(s: Session, ex: CustomExercise, given: str, ok: bool) -> None:
    if ok:
        return
    if ex.exercise_id:
        e = s.get(GrammarExercise, ex.exercise_id)
        if e is not None:
            LS.record_exercise(s, e, given, False)
            return
    s.add(ErrorLog(source="perso", category=ex.meta.get("category") or "Correction",
                   excerpt=given[:500], correction=ex.accepted[0] if ex.accepted else "",
                   rule=f"[{ex.rule or 'perso'}] {ex.explanation}"[:1000]))


def record_session(s: Session, score: float, duration_s: float) -> None:
    s.add(StudySession(module="perso", started_at=datetime.now(), duration_s=duration_s,
                       score=score))
