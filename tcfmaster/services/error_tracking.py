"""Journal des erreurs de l'apprenant, pour repérer ses difficultés récurrentes.

Chaque erreur relevée dans une production (EE, EO, tuteur IA) ou dans un
exercice de grammaire est notée dans la table `error_log`. Les exercices
personnalisés s'appuient sur ce journal.

Format de la colonne `rule` pour les erreurs de production :
« [identifiant-de-règle] explication ». L'identifiant permet de retrouver la
règle de correction (et donc de fabriquer un exercice ciblé).
"""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from tcfmaster.db.models import ErrorLog, GrammarChapter
from tcfmaster.services.writing_rules import ERROR

CATEGORY_LABELS = {
    "orthographe": "Orthographe", "grammaire": "Grammaire", "conjugaison": "Conjugaison",
    "syntaxe": "Syntaxe", "registre": "Registre", "lexique": "Lexique",
    "ponctuation": "Ponctuation et typographie",
}
_RULE_TAG = re.compile(r"^\[([\w-]+)\]\s*")
MAX_PER_PRODUCTION = 12


def rule_id(row: ErrorLog) -> str | None:
    m = _RULE_TAG.match(row.rule or "")
    return m.group(1) if m else None


def _chapter_titles(s: Session) -> dict[str, str]:
    with s.no_autoflush:          # appelé au milieu d'une écriture : pas de flush prématuré
        return {slug: title for slug, title in s.execute(
            select(GrammarChapter.slug, GrammarChapter.title)).all()}


def log_issues(s: Session, source: str, issues: list, errors_only: bool = True) -> int:
    """Enregistre les erreurs d'une production. `issues` : objets Issue ou dicts."""
    titles = None
    n = 0
    for it in issues:
        d = it if isinstance(it, dict) else it.__dict__
        if errors_only and d.get("severity") != ERROR:
            continue
        if n >= MAX_PER_PRODUCTION:
            break
        chapter = d.get("chapter") or ""
        if chapter and titles is None:
            titles = _chapter_titles(s)
        category = (titles or {}).get(chapter) or CATEGORY_LABELS.get(
            d.get("category", ""), d.get("category") or "Divers")
        s.add(ErrorLog(source=source, category=category[:60],
                       excerpt=(d.get("excerpt") or "")[:500],
                       correction=d.get("replacement") or "",    # correction sûre seulement
                       rule=(f"[{d.get('rule')}] {d.get('message', '')} "
                             f"{d.get('explanation', '')}"
                             + (f" Piste : {d['suggestion']}" if d.get("suggestion") else "")
                             ).strip()[:1000]))
        n += 1
    return n


@dataclass
class Weakness:
    category: str
    count: int
    sources: list[str]
    examples: list[str] = field(default_factory=list)
    rules: list[str] = field(default_factory=list)
    last_seen: datetime | None = None


def weaknesses(s: Session, days: int = 90, limit: int = 8) -> list[Weakness]:
    """Difficultés les plus fréquentes sur la période (catégories triées par fréquence)."""
    since = datetime.now() - timedelta(days=days)
    rows = list(s.execute(select(ErrorLog).where(ErrorLog.created_at >= since)
                          .order_by(ErrorLog.created_at.desc())).scalars())
    counts = Counter(r.category for r in rows)
    out = []
    for cat, n in counts.most_common(limit):
        mine = [r for r in rows if r.category == cat]
        examples, rules = [], []
        for r in mine:
            if r.excerpt and r.excerpt not in examples and len(examples) < 3:
                examples.append(r.excerpt)
            rid = rule_id(r)
            if rid and rid not in rules:
                rules.append(rid)
        out.append(Weakness(cat, n, sorted({r.source for r in mine}), examples, rules,
                            mine[0].created_at if mine else None))
    return out


def recent_summary(s: Session, limit: int = 5) -> list[str]:
    """Phrases courtes décrivant les difficultés récurrentes (pour le tuteur)."""
    return [f"{w.category} ({w.count} erreur{'s' if w.count > 1 else ''}"
            + (f", ex. « {w.examples[0][:60]} »" if w.examples else "") + ")"
            for w in weaknesses(s, limit=limit)]
