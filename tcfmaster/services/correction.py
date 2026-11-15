"""Système de correction unifié (v1.1).

Toutes les activités produisent une correction de même structure, affichée
immédiatement en mode entraînement et à la fin de l'épreuve en mode examen :

  * QCM (CO/CE) : réponse de l'utilisateur, bonne réponse, résultat,
    justification (fondée sur le document), explication pédagogique et
    explication de chaque proposition incorrecte ; pour l'exercice entier :
    transcription (CO), vocabulaire avancé, expressions, pièges ;
  * productions (EE/EO) : texte ou transcription d'origine, erreurs repérées,
    correction, réponse modèle B2, explications, appréciation pédagogique.

Chaque correction porte l'avertissement `levels.DISCLAIMER` : une estimation
automatique n'est jamais présentée comme une note officielle du TCF.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field

from sqlalchemy.orm import Session

from tcfmaster.core import levels as L
from tcfmaster.db.models import Answer, Attempt, Exercise, Question

SKILL_ADVICE = {
    "implicite": "Entraînez-vous à repérer ce que le locuteur sous-entend : ton, sous-entendus, "
                 "ironie, ce qui n'est pas dit explicitement.",
    "point de vue": "Repérez qui parle et sa position : verbes d'opinion, modalisateurs "
                    "(certes, sans doute, il semblerait), adjectifs évaluatifs.",
    "argumentation": "Identifiez la thèse, les arguments et les concessions : soulignez les "
                     "connecteurs (or, pourtant, en revanche, dès lors).",
    "synthèse": "Reformulez le document en une phrase avant de répondre : la bonne réponse "
                "résume souvent l'idée générale sans reprendre les mêmes mots.",
    "information détaillée": "Lisez les questions avant le document et notez les chiffres, "
                             "dates et conditions précises.",
    "vocabulaire": "Révisez le vocabulaire avancé de l'exercice : les distracteurs jouent "
                   "souvent sur un faux ami ou un mot proche.",
    "compréhension globale": "Identifiez d'abord le type de document, l'intention et le "
                             "destinataire avant d'entrer dans le détail.",
    "intention": "Demandez-vous pourquoi le document a été produit : informer, convaincre, "
                 "dénoncer, conseiller, prévenir.",
}


@dataclass
class ChoiceNote:
    label: str
    text: str
    is_correct: bool
    rationale: str


@dataclass
class McqCorrection:
    question_id: int
    position: int
    prompt: str
    skill: str
    user_answer: str | None
    correct_answer: str
    is_correct: bool
    result: str                 # « Bonne réponse » / « Réponse incorrecte » / « Sans réponse »
    justification: str          # pourquoi la bonne réponse est juste (fondée sur le document)
    explanation: str            # explication pédagogique
    choices: list[ChoiceNote] = field(default_factory=list)

    @property
    def wrong_choices(self) -> list[ChoiceNote]:
        return [c for c in self.choices if not c.is_correct]


@dataclass
class ExerciseCorrection:
    exercise_id: int
    code: str
    title: str
    section: str
    doc_type: str
    document: str               # texte (CE) ou transcription (CO)
    questions: list[McqCorrection]
    vocabulary: list[dict]
    expressions: list[dict]
    traps: list[str]

    @property
    def correct(self) -> int:
        return sum(1 for q in self.questions if q.is_correct)

    @property
    def total(self) -> int:
        return len(self.questions)


@dataclass
class SessionCorrection:
    """Correction d'une série d'exercices (une tentative)."""
    attempt_id: int
    mode: str
    section: str
    exercises: list[ExerciseCorrection]
    advice: list[str]
    disclaimer: str = L.DISCLAIMER

    @property
    def correct(self) -> int:
        return sum(e.correct for e in self.exercises)

    @property
    def total(self) -> int:
        return sum(e.total for e in self.exercises)

    @property
    def rate(self) -> float:
        return self.correct / self.total if self.total else 0.0

    def to_dict(self) -> dict:
        d = asdict(self)
        d.update(correct=self.correct, total=self.total, rate=self.rate)
        return d


def correct_question(q: Question, chosen: str | None) -> McqCorrection:
    right = q.correct_choice
    if right is None:
        raise ValueError(f"Question {q.id} sans correction valide")
    ok = chosen == right.label
    result = ("Bonne réponse" if ok else "Sans réponse" if chosen is None
              else "Réponse incorrecte")
    return McqCorrection(
        question_id=q.id, position=q.position, prompt=q.prompt, skill=q.skill or "",
        user_answer=chosen, correct_answer=right.label, is_correct=ok, result=result,
        justification=right.rationale, explanation=q.explanation,
        choices=[ChoiceNote(c.label, c.text, c.is_correct, c.rationale) for c in q.choices])


def correct_exercise(ex: Exercise, answers: dict[int, str | None]) -> ExerciseCorrection:
    return ExerciseCorrection(
        exercise_id=ex.id, code=ex.code, title=ex.title, section=ex.section,
        doc_type=ex.doc_type, document=ex.document,
        questions=[correct_question(q, answers.get(q.id)) for q in ex.questions],
        vocabulary=list(ex.vocabulary or []), expressions=list(ex.expressions or []),
        traps=list(ex.traps or []))


def advice_for(corrections: list[McqCorrection]) -> list[str]:
    """Conseils d'amélioration selon les compétences des questions manquées."""
    missed: dict[str, int] = {}
    for c in corrections:
        if not c.is_correct:
            key = (c.skill or "compréhension globale").lower()
            missed[key] = missed.get(key, 0) + 1
    out = []
    for skill, n in sorted(missed.items(), key=lambda kv: -kv[1]):
        tip = next((v for k, v in SKILL_ADVICE.items() if k in skill), None)
        if tip:
            out.append(f"{skill.capitalize()} ({n} erreur(s)) : {tip}")
    if not corrections:
        return out
    rate = sum(c.is_correct for c in corrections) / len(corrections)
    if rate >= 0.85:
        out.append("Très bon résultat : passez au mode examen pour travailler la gestion "
                   "du temps.")
    elif rate < 0.5:
        out.append("Relisez la correction et le vocabulaire, puis refaites l'exercice en "
                   "mode entraînement avant de passer au suivant.")
    return out or ["Continuez : relisez les justifications même pour les bonnes réponses."]


def session_correction(s: Session, attempt_id: int) -> SessionCorrection:
    a = s.get(Attempt, attempt_id)
    if a is None:
        raise ValueError(f"Tentative inconnue : {attempt_id}")
    ex_ids = list((a.results or {}).get("exercise_ids", []))
    answers = {x.question_id: x.choice_label for x in
               s.query(Answer).filter(Answer.attempt_id == attempt_id)}
    exercises = [correct_exercise(s.get(Exercise, i), answers) for i in ex_ids
                 if s.get(Exercise, i) is not None]
    allq = [q for e in exercises for q in e.questions]
    section = exercises[0].section if exercises else (a.sections or ["CO"])[0]
    return SessionCorrection(attempt_id, a.mode, section, exercises, advice_for(allq))


# ------------------------------------------------------------ productions
def production_correction(evaluation: dict, original: str, model_answer: str = "",
                          kind: str = "EE") -> dict:
    """Vue commune d'une production corrigée (EE ou EO) à partir de l'évaluation locale."""
    ev = evaluation or {}
    issues = ev.get("issues") or []
    errors = [{"extrait": i.get("excerpt", ""), "correction": i.get("replacement") or
               i.get("suggestion", ""), "explication": i.get("explanation") or i.get("message", ""),
               "categorie": i.get("category", "")} for i in issues]
    note = ev.get("note20")
    level = ev.get("level", "")
    if note is None:
        appreciation = "Production non évaluée."
    elif L.meets_target(level):
        appreciation = (f"Production de niveau {level} estimé : les attentes B2 sont "
                        "globalement atteintes. Visez la précision et la variété.")
    else:
        appreciation = (f"Production de niveau {level} estimé, en dessous de l'objectif B2 : "
                        "concentrez-vous sur les priorités ci-dessous.")
    return {
        "type": kind,
        "original": original,
        "errors": errors,
        "corrected": ev.get("corrected_text") or original,
        "model_answer": model_answer or ev.get("model_answer", ""),
        "explanations": ev.get("criteria_comments", {}),
        "strengths": ev.get("strengths", []),
        "advice": ev.get("priorities", []),
        "appreciation": appreciation,
        "note20": note,
        "level": level,
        "disclaimer": L.DISCLAIMER,
    }
