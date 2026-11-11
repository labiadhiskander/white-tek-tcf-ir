"""Barèmes CECRL utilisés par le TCF.

Compréhension (CO / CE) : score sur 699 points.
  A1 100–199, A2 200–299, B1 300–399, B2 400–499, C1 500–599, C2 600–699.
Expression (EE / EO) : note sur 20.
  A1 1–3, A2 4–5, B1 6–9, B2 10–13, C1 14–15, C2 16–20.

Toutes les estimations produites par l'application sont pédagogiques et ne
constituent en aucun cas un résultat officiel de France Éducation international.
"""
from __future__ import annotations

LEVELS = ["A1", "A2", "B1", "B2", "C1", "C2"]
TARGET_LEVEL = "B2"

DISCLAIMER = (
    "Estimation pédagogique fournie à titre indicatif. Ce résultat n'est pas "
    "un résultat officiel de France Éducation international."
)

# Points TCF attribués par question selon la difficulté (pondération progressive).
QUESTION_POINTS = {"A1": 3, "A2": 9, "B1": 15, "B2": 21, "C1": 26, "C2": 33}

COMPREHENSION_BANDS = [(600, "C2"), (500, "C1"), (400, "B2"), (300, "B1"),
                       (200, "A2"), (100, "A1")]
EXPRESSION_BANDS = [(16, "C2"), (14, "C1"), (10, "B2"), (6, "B1"), (4, "A2"), (1, "A1")]


def level_index(level: str) -> int:
    return LEVELS.index(level) if level in LEVELS else -1


def comprehension_level(score: float) -> str:
    for threshold, lvl in COMPREHENSION_BANDS:
        if score >= threshold:
            return lvl
    return "< A1"


def expression_level(note20: float) -> str:
    for threshold, lvl in EXPRESSION_BANDS:
        if note20 >= threshold:
            return lvl
    return "< A1"


def comprehension_score(answers: list[tuple[str, bool]]) -> int:
    """Calcule un score sur 699 à partir de (niveau_question, correct).

    Le score est ramené à l'échelle 100–699 proportionnellement au maximum
    possible pour la série de questions passée.
    """
    if not answers:
        return 0
    max_pts = sum(QUESTION_POINTS.get(lvl, 15) for lvl, _ in answers)
    got = sum(QUESTION_POINTS.get(lvl, 15) for lvl, ok in answers if ok)
    if max_pts == 0:
        return 0
    return round(100 + 599 * got / max_pts) if got else 0


def meets_target(level: str, target: str = TARGET_LEVEL) -> bool:
    return level_index(level) >= level_index(target)
