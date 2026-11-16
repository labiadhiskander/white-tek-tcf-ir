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


def build_messages(conv: Conversation, extra_user: str | None = None,
                   max_turns: int = 40) -> list[dict]:
    """Historique au format « chat » (rôles user / assistant alternés, premier message
    de l'apprenant), commun aux moteurs en ligne et à l'IA locale."""
    msgs: list[dict] = []
    for t in conv.turns[-max_turns:]:
        role = "user" if t.role == LEARNER else "assistant"
        if msgs and msgs[-1]["role"] == role:        # les API attendent une alternance
            msgs[-1]["content"] += "\n\n" + t.text
        else:
            msgs.append({"role": role, "content": t.text})
    if extra_user:
        if msgs and msgs[-1]["role"] == "user":
            msgs[-1]["content"] += "\n\n" + extra_user
        else:
            msgs.append({"role": "user", "content": extra_user})
    if msgs and msgs[0]["role"] != "user":          # le premier message vient de l'apprenant
        msgs.insert(0, {"role": "user", "content": "Bonjour."})
    if not msgs:
        msgs = [{"role": "user", "content": extra_user or "Bonjour."}]
    return msgs


OPENING_CUES = {
    MODE_TEACHER: "Présente-toi en deux phrases comme professeur et demande-moi ce que je "
                  "veux travailler.",
    MODE_CONVERSATION: "Lance une conversation sur un sujet de société en me posant une "
                       "question ouverte.",
    MODE_EXAMINER: "Commence l'épreuve : salue-moi et pose la première question ou "
                   "réplique, comme à l'examen.",
}
