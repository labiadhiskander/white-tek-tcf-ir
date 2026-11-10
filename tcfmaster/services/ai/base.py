"""Structures communes aux moteurs du tuteur IA."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

MODE_TEACHER = "professeur"
MODE_CONVERSATION = "conversation"
MODE_EXAMINER = "examinateur"
MODES = (MODE_TEACHER, MODE_CONVERSATION, MODE_EXAMINER)
MODE_LABELS = {
    MODE_TEACHER: "Professeur : corrige vos phrases et explique la grammaire",
    MODE_CONVERSATION: "Conversation libre : discussion naturelle, corrections discrètes",
    MODE_EXAMINER: "Examinateur : simulation d'une tâche d'expression orale du TCF IRN",
}

LEARNER, TUTOR = "apprenant", "tuteur"


class AIUnavailable(RuntimeError):
    """Le moteur en ligne ne peut pas répondre (clé, réseau, quota…)."""


@dataclass
class Turn:
    role: str            # « apprenant » ou « tuteur »
    text: str


@dataclass
class Conversation:
    mode: str
    turns: list[Turn] = field(default_factory=list)
    state: dict = field(default_factory=dict)
    task: dict | None = None             # tâche EO (mode examinateur)
    learner_profile: list[str] = field(default_factory=list)   # difficultés récurrentes

    def learner_texts(self) -> list[str]:
        return [t.text for t in self.turns if t.role == LEARNER]


@dataclass
class TutorReply:
    text: str
    engine: str
    corrections: list[dict] = field(default_factory=list)
    evaluation: dict | None = None
    notice: str = ""


class TutorEngine(Protocol):
    name: str

    def opening(self, conv: Conversation) -> TutorReply: ...

    def reply(self, conv: Conversation, text: str) -> TutorReply: ...
