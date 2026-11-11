"""Logique des modules Grammaire, Conjugaison et Vocabulaire."""
from __future__ import annotations

import random
import re
import unicodedata
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from tcfmaster.db.models import (ErrorLog, Expression, GrammarChapter, GrammarExercise,
                                 StudySession, Verb, VocabWord)

PERSONS = ["je", "tu", "il/elle/on", "nous", "vous", "ils/elles"]
TENSE_LABELS = {
    "present": "Présent", "passe_compose": "Passé composé", "imparfait": "Imparfait",
    "plus_que_parfait": "Plus-que-parfait", "futur_simple": "Futur simple",
    "futur_anterieur": "Futur antérieur", "conditionnel_present": "Conditionnel présent",
    "conditionnel_passe": "Conditionnel passé", "subjonctif_present": "Subjonctif présent",
    "subjonctif_passe": "Subjonctif passé", "imperatif": "Impératif",
    "passe_simple": "Passé simple",
}


def normalize(s: str, strict_accents: bool = True) -> str:
    s = (s or "").strip().lower().replace("’", "'").replace("œ", "oe")
    s = re.sub(r"\s+", " ", s)
    s = re.sub(r"\s*'\s*", "'", s)
    s = s.strip(" .!?")
    # Ponctuation interne tolérante : « ; », « : » et « . » valent une virgule.
    s = re.sub(r"\s*[,;:.]\s*", ", ", s)
    s = re.sub(r"\s*([!?])", r"\1", s)
    if not strict_accents:
        s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    return s


def check_answer(given: str, accepted: list[str]) -> tuple[bool, bool]:
    """Renvoie (correct, correct_sauf_accents)."""
    g = normalize(given)
    if any(g == normalize(a) for a in accepted):
        return True, True
    g2 = normalize(given, strict_accents=False)
    return False, any(g2 == normalize(a, strict_accents=False) for a in accepted)


# ----------------------------------------------------------------- grammaire
def chapters(s: Session, module: str | None = None) -> list[GrammarChapter]:
    q = select(GrammarChapter).order_by(GrammarChapter.order, GrammarChapter.title)
    if module:
        q = q.where(GrammarChapter.module == module)
    return list(s.execute(q).scalars())


def record_exercise(s: Session, ex: GrammarExercise, given: str, correct: bool) -> None:
    if not correct:
        s.add(ErrorLog(source="grammaire", category=ex.chapter.title, excerpt=given,
                       correction=ex.accepted_answers()[0] if ex.accepted_answers() else "",
                       rule=ex.explanation[:500]))


def record_chapter_session(s: Session, slug: str, score: float, duration_s: float) -> None:
    s.add(StudySession(module=f"grammaire:{slug}", started_at=datetime.now(),
                       duration_s=duration_s, score=score))


def chapter_mastery(s: Session, slug: str) -> float | None:
    """Maîtrise = moyenne des 3 dernières séries d'exercices du chapitre (0–1)."""
    rows = list(s.execute(select(StudySession.score).where(
        StudySession.module == f"grammaire:{slug}", StudySession.score.is_not(None))
        .order_by(StudySession.started_at.desc()).limit(3)).scalars())
    return sum(rows) / len(rows) if rows else None


def mastery_label(m: float | None) -> str:
    if m is None:
        return "Non évalué"
    if m >= 0.85:
        return "Maîtrisé"
    if m >= 0.65:
        return "En bonne voie"
    if m >= 0.4:
        return "Fragile"
    return "À retravailler"


# ---------------------------------------------------------------- conjugaison
def find_verb(s: Session, infinitive: str) -> Verb | None:
    return s.execute(select(Verb).where(Verb.infinitive == infinitive.strip().lower())
                     ).scalar_one_or_none()


def conjugation_quiz(s: Session, tenses: list[str] | None = None,
                     rng: random.Random | None = None) -> dict | None:
    rng = rng or random.Random()
    verbs = list(s.execute(select(Verb)).scalars())
    if not verbs:
        return None
    v = rng.choice(verbs)
    available = [t for t in v.conjugations if not tenses or t in tenses]
    if not available:
        return None
    t = rng.choice(available)
    forms = v.conjugations[t]
    idxs = [i for i, f in enumerate(forms) if f]
    i = rng.choice(idxs)
    person = PERSONS[i] if t != "imperatif" else ["(tu)", "(nous)", "(vous)"][min(i, 2)]
    return {"verb": v.infinitive, "tense": t, "tense_label": TENSE_LABELS.get(t, t),
            "person": person, "answer": forms[i]}


def check_conjugation(given: str, expected: str) -> tuple[bool, bool]:
    """Accepte la forme avec ou sans pronom (« je parle » ou « parle ») et,
    pour les accords notés « allé(e)s », le masculin comme le féminin."""
    alts = [expected]
    if "(e)" in expected:
        alts = [expected.replace("(e)", ""), expected.replace("(e)", "e")]
    pron = r"^(j'|je |tu |il |elle |on |nous |vous |ils |elles |que |qu')+"
    for a in list(alts):
        m = re.match(pron, a)
        if m:
            alts.append(a[m.end():])
    return check_answer(given, alts)


# --------------------------------------------------------------- vocabulaire
def expression_categories(s: Session, kind: str | None = None) -> list[str]:
    q = select(Expression.category).distinct().order_by(Expression.category)
    if kind:
        q = q.where(Expression.kind == kind)
    return list(s.execute(q).scalars())


def search_expressions(s: Session, kind=None, category=None, level=None, text=None,
                       limit: int = 500) -> list[Expression]:
    q = select(Expression)
    if kind:
        q = q.where(Expression.kind == kind)
    if category:
        q = q.where(Expression.category == category)
    if level:
        q = q.where(Expression.level == level)
    if text:
        q = q.where(Expression.text.ilike(f"%{text}%"))
    return list(s.execute(q.order_by(Expression.id).limit(limit)).scalars())


def vocab_themes(s: Session) -> list[str]:
    return list(s.execute(select(VocabWord.theme).distinct().order_by(VocabWord.theme)
                          ).scalars())


def search_vocab(s: Session, theme=None, level=None, text=None, limit=1000) -> list[VocabWord]:
    q = select(VocabWord)
    if theme:
        q = q.where(VocabWord.theme == theme)
    if level:
        q = q.where(VocabWord.level == level)
    if text:
        q = q.where(VocabWord.word.ilike(f"%{text}%"))
    return list(s.execute(q.order_by(VocabWord.word).limit(limit)).scalars())
