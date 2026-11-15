"""Modèle de données SQLAlchemy (SQLite local).

Trois familles de tables :
  * Contenu pédagogique (préinstallé, en lecture seule pour l'utilisateur) :
    examens, questions, tâches, vocabulaire, grammaire, plan 12 semaines.
  * Activité du candidat : tentatives, réponses, productions écrites et orales,
    évaluations, journal d'erreurs, répétition espacée, temps d'entraînement.
  * Paramètres de l'application.
"""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (JSON, Boolean, Date, DateTime, Float, ForeignKey, Integer,
                        String, Text, UniqueConstraint, func)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


# --------------------------------------------------------------------------
# Constantes de domaine
# --------------------------------------------------------------------------
SECTION_CO = "CO"   # Compréhension orale
SECTION_CE = "CE"   # Compréhension écrite
SECTION_EE = "EE"   # Expression écrite
SECTION_EO = "EO"   # Expression orale
SECTIONS = (SECTION_CO, SECTION_CE, SECTION_EE, SECTION_EO)

SECTION_LABELS = {
    SECTION_CO: "Compréhension orale",
    SECTION_CE: "Compréhension écrite",
    SECTION_EE: "Expression écrite",
    SECTION_EO: "Expression orale",
}

# Format officiel TCF IRN
SECTION_DURATIONS_S = {SECTION_CO: 20 * 60, SECTION_CE: 35 * 60,
                       SECTION_EE: 30 * 60, SECTION_EO: 10 * 60}
QUESTIONS_PER_COMPREHENSION = 25
CHOICES_PER_QUESTION = 4

WRITING_WORD_LIMITS = {1: (30, 60), 2: (40, 90), 3: (40, 90)}
SPEAKING_DURATIONS_S = {1: 180, 2: 210, 3: 210}
SPEAKING_TASK_NAMES = {1: "Entretien dirigé", 2: "Exercice en interaction",
                       3: "Exprimer ses goûts et ses opinions"}

# v1.1 : statut et origine des contenus (administration)
STATUS_VALID = "valide"
STATUS_DRAFT = "brouillon"
ORIGIN_BUILTIN = "preinstalle"
ORIGIN_ADMIN = "admin"
TARGET_LEVEL = "B2"

# Bibliothèque : familles de collections
KIND_GRAMMAR = "GRAM"
KIND_VOCAB = "VOC"
COLLECTION_KINDS = SECTIONS + (KIND_GRAMMAR, KIND_VOCAB)


# --------------------------------------------------------------------------
# Contenu : examens
# --------------------------------------------------------------------------
class Exam(Base):
    __tablename__ = "exams"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(20), unique=True)  # ex. « EXAM-01 »
    title: Mapped[str] = mapped_column(String(200))
    level: Mapped[str] = mapped_column(String(4), default="B2")  # calibrage principal
    description: Mapped[str] = mapped_column(Text, default="")
    generated: Mapped[bool] = mapped_column(Boolean, default=False)
    content_hash: Mapped[str] = mapped_column(String(64), default="")
    # v1.1 : « B2 » pour les examens blancs B2, « v1.0 » pour les examens progressifs
    series: Mapped[str | None] = mapped_column(String(20), nullable=True, default="v1.0")

    questions: Mapped[list["Question"]] = relationship(
        back_populates="exam", cascade="all, delete-orphan", order_by="Question.position")
    writing_tasks: Mapped[list["WritingTask"]] = relationship(
        back_populates="exam", cascade="all, delete-orphan", order_by="WritingTask.task_number")
    speaking_tasks: Mapped[list["SpeakingTask"]] = relationship(
        back_populates="exam", cascade="all, delete-orphan", order_by="SpeakingTask.task_number")

    def questions_for(self, section: str) -> list["Question"]:
        return [q for q in self.questions if q.section == section]


class Question(Base):
    """Question à choix multiple (CO ou CE) : 4 propositions, 1 seule correcte."""
    __tablename__ = "questions"
    __table_args__ = (UniqueConstraint("exam_id", "section", "position"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    exam_id: Mapped[int | None] = mapped_column(ForeignKey("exams.id", ondelete="CASCADE"),
                                                index=True)
    section: Mapped[str] = mapped_column(String(2), index=True)  # CO / CE
    position: Mapped[int] = mapped_column(Integer)  # 1..25
    level: Mapped[str] = mapped_column(String(4), index=True)
    doc_type: Mapped[str] = mapped_column(String(60))  # « annonce publique », « courriel »…
    skill: Mapped[str] = mapped_column(String(60), default="")  # compréhension globale…
    document: Mapped[str] = mapped_column(Text)  # texte (CE) ou transcription audio (CO)
    speakers: Mapped[list | None] = mapped_column(JSON, nullable=True)  # voix / accents CO
    audio_file: Mapped[str | None] = mapped_column(String(255), nullable=True)
    prompt: Mapped[str] = mapped_column(Text)  # l'énoncé de la question
    explanation: Mapped[str] = mapped_column(Text, default="")  # correction détaillée
    # v1.1 : question rattachée à un exercice de collection (exam_id est alors nul)
    exercise_id: Mapped[int | None] = mapped_column(
        ForeignKey("exercises.id", ondelete="CASCADE"), nullable=True, index=True)

    exam: Mapped[Exam | None] = relationship(back_populates="questions")
    exercise: Mapped["Exercise | None"] = relationship(back_populates="questions")
    choices: Mapped[list["Choice"]] = relationship(
        back_populates="question", cascade="all, delete-orphan", order_by="Choice.label")

    @property
    def correct_choice(self) -> "Choice | None":
        c = [x for x in self.choices if x.is_correct]
        return c[0] if len(c) == 1 else None


class Choice(Base):
    __tablename__ = "choices"
    __table_args__ = (UniqueConstraint("question_id", "label"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    question_id: Mapped[int] = mapped_column(ForeignKey("questions.id", ondelete="CASCADE"),
                                             index=True)
    label: Mapped[str] = mapped_column(String(1))  # A, B, C, D
    text: Mapped[str] = mapped_column(Text)
    is_correct: Mapped[bool] = mapped_column(Boolean, default=False)
    rationale: Mapped[str] = mapped_column(Text, default="")  # pourquoi juste / faux

    question: Mapped[Question] = relationship(back_populates="choices")


class WritingTask(Base):
    __tablename__ = "writing_tasks"

    id: Mapped[int] = mapped_column(primary_key=True)
    exam_id: Mapped[int | None] = mapped_column(ForeignKey("exams.id", ondelete="CASCADE"),
                                                index=True)
    task_number: Mapped[int] = mapped_column(Integer)  # 1, 2, 3
    level: Mapped[str] = mapped_column(String(4), default="B2")
    task_type: Mapped[str] = mapped_column(String(80))  # « décrire un lieu »…
    instructions: Mapped[str] = mapped_column(Text)
    min_words: Mapped[int] = mapped_column(Integer)
    max_words: Mapped[int] = mapped_column(Integer)
    model_answer: Mapped[str] = mapped_column(Text, default="")  # réponse modèle B2
    tips: Mapped[str] = mapped_column(Text, default="")
    expected_points: Mapped[list | None] = mapped_column(JSON, nullable=True)
    # v1.1 : sujet indépendant d'une collection (exam_id nul)
    code: Mapped[str | None] = mapped_column(String(30), nullable=True, index=True)
    collection_id: Mapped[int | None] = mapped_column(
        ForeignKey("collections.id", ondelete="SET NULL"), nullable=True, index=True)
    theme: Mapped[str | None] = mapped_column(String(80), nullable=True)
    model_commentary: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str | None] = mapped_column(String(12), nullable=True, default=STATUS_VALID)
    origin: Mapped[str | None] = mapped_column(String(12), nullable=True,
                                               default=ORIGIN_BUILTIN)
    locally_modified: Mapped[bool | None] = mapped_column(Boolean, nullable=True,
                                                          default=False)

    exam: Mapped[Exam | None] = relationship(back_populates="writing_tasks")
    collection: Mapped["Collection | None"] = relationship()


class SpeakingTask(Base):
    __tablename__ = "speaking_tasks"

    id: Mapped[int] = mapped_column(primary_key=True)
    exam_id: Mapped[int | None] = mapped_column(ForeignKey("exams.id", ondelete="CASCADE"),
                                                index=True)
    task_number: Mapped[int] = mapped_column(Integer)  # 1, 2, 3
    level: Mapped[str] = mapped_column(String(4), default="B2")
    title: Mapped[str] = mapped_column(String(200))
    scenario: Mapped[str] = mapped_column(Text)  # consigne / rôle de l'examinateur
    examiner_role: Mapped[str] = mapped_column(String(120), default="Examinateur")
    duration_s: Mapped[int] = mapped_column(Integer)
    examiner_prompts: Mapped[list | None] = mapped_column(JSON, nullable=True)
    useful_phrases: Mapped[list | None] = mapped_column(JSON, nullable=True)
    model_answer: Mapped[str] = mapped_column(Text, default="")
    tips: Mapped[str | None] = mapped_column(Text, nullable=True)
    # v1.1 : sujet indépendant d'une collection (exam_id nul)
    code: Mapped[str | None] = mapped_column(String(30), nullable=True, index=True)
    collection_id: Mapped[int | None] = mapped_column(
        ForeignKey("collections.id", ondelete="SET NULL"), nullable=True, index=True)
    theme: Mapped[str | None] = mapped_column(String(80), nullable=True)
    model_commentary: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str | None] = mapped_column(String(12), nullable=True, default=STATUS_VALID)
    origin: Mapped[str | None] = mapped_column(String(12), nullable=True,
                                               default=ORIGIN_BUILTIN)
    locally_modified: Mapped[bool | None] = mapped_column(Boolean, nullable=True,
                                                          default=False)

    exam: Mapped[Exam | None] = relationship(back_populates="speaking_tasks")
    collection: Mapped["Collection | None"] = relationship()


# --------------------------------------------------------------------------
# Contenu : vocabulaire et expressions
# --------------------------------------------------------------------------
class Expression(Base):
    """Expression / formulation / phrase complexe / connecteur."""
    __tablename__ = "expressions"

    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(20), index=True)
    # kind : expression | phrase_complexe | argumentation | connecteur
    category: Mapped[str] = mapped_column(String(60), index=True)  # « Donner son opinion »…
    text: Mapped[str] = mapped_column(Text)
    meaning: Mapped[str] = mapped_column(Text)
    level: Mapped[str] = mapped_column(String(4), index=True)
    example: Mapped[str] = mapped_column(Text)
    simple_equivalent: Mapped[str] = mapped_column(Text)
    exercise: Mapped[str] = mapped_column(Text)  # exercice de réutilisation
    exercise_answer: Mapped[str] = mapped_column(Text, default="")  # correction


class VocabWord(Base):
    __tablename__ = "vocab_words"
    __table_args__ = (UniqueConstraint("word", "theme"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    word: Mapped[str] = mapped_column(String(120), index=True)
    pos: Mapped[str] = mapped_column(String(30), default="")  # nom, verbe…
    gender: Mapped[str | None] = mapped_column(String(3), nullable=True)  # m / f
    theme: Mapped[str] = mapped_column(String(60), index=True)
    level: Mapped[str] = mapped_column(String(4), index=True)
    definition: Mapped[str] = mapped_column(Text)
    example: Mapped[str] = mapped_column(Text)
    synonyms: Mapped[str] = mapped_column(Text, default="")
    collocations: Mapped[str] = mapped_column(Text, default="")


# --------------------------------------------------------------------------
# Contenu : grammaire et conjugaison
# --------------------------------------------------------------------------
class GrammarChapter(Base):
    __tablename__ = "grammar_chapters"

    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(String(60), unique=True)
    title: Mapped[str] = mapped_column(String(160))
    module: Mapped[str] = mapped_column(String(20), default="grammaire")  # ou conjugaison
    order: Mapped[int] = mapped_column(Integer, default=0)
    level: Mapped[str] = mapped_column(String(4), default="B1")
    lesson: Mapped[str] = mapped_column(Text)  # cours (Markdown léger)
    simple_examples: Mapped[list] = mapped_column(JSON, default=list)
    b2_examples: Mapped[list] = mapped_column(JSON, default=list)

    exercises: Mapped[list["GrammarExercise"]] = relationship(
        back_populates="chapter", cascade="all, delete-orphan", order_by="GrammarExercise.id")


class GrammarExercise(Base):
    __tablename__ = "grammar_exercises"

    id: Mapped[int] = mapped_column(primary_key=True)
    chapter_id: Mapped[int] = mapped_column(ForeignKey("grammar_chapters.id",
                                                       ondelete="CASCADE"), index=True)
    ex_type: Mapped[str] = mapped_column(String(20))  # qcm | trou | transformation
    level: Mapped[str] = mapped_column(String(4), default="B1")
    prompt: Mapped[str] = mapped_column(Text)
    options: Mapped[list | None] = mapped_column(JSON, nullable=True)
    answer: Mapped[str] = mapped_column(Text)  # réponse attendue (alternatives séparées par |)
    explanation: Mapped[str] = mapped_column(Text)  # correction détaillée

    chapter: Mapped[GrammarChapter] = relationship(back_populates="exercises")

    def accepted_answers(self) -> list[str]:
        return [a.strip() for a in self.answer.split("|") if a.strip()]


class Verb(Base):
    """Table de conjugaison (pour le module Conjugaison)."""
    __tablename__ = "verbs"

    id: Mapped[int] = mapped_column(primary_key=True)
    infinitive: Mapped[str] = mapped_column(String(60), unique=True)
    group: Mapped[int] = mapped_column(Integer)
    auxiliary: Mapped[str] = mapped_column(String(10), default="avoir")
    conjugations: Mapped[dict] = mapped_column(JSON)  # {temps: [6 formes]}


# --------------------------------------------------------------------------
# Contenu : plan d'apprentissage
# --------------------------------------------------------------------------
class PlanDay(Base):
    __tablename__ = "plan_days"
    __table_args__ = (UniqueConstraint("week", "day"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    week: Mapped[int] = mapped_column(Integer)  # 1..12
    day: Mapped[int] = mapped_column(Integer)  # 1..7
    focus: Mapped[str] = mapped_column(String(200))
    activities: Mapped[list] = mapped_column(JSON)  # [{module, minutes, description, ref}]
    is_mock_exam: Mapped[str | None] = mapped_column(String(20), nullable=True)  # partiel/complet
    is_review: Mapped[bool] = mapped_column(Boolean, default=False)


# --------------------------------------------------------------------------
# Contenu v1.1 : collections B2, exercices corrigés, vidéothèque, programme 30 jours
# --------------------------------------------------------------------------
class Collection(Base):
    """Collection thématique (« Environnement et climat », « Éditoriaux »…)."""
    __tablename__ = "collections"

    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(String(60), unique=True)
    section: Mapped[str] = mapped_column(String(4), index=True)  # CO, CE, EE, EO, GRAM, VOC
    title: Mapped[str] = mapped_column(String(160))
    description: Mapped[str] = mapped_column(Text, default="")
    order: Mapped[int] = mapped_column(Integer, default=0)
    level: Mapped[str] = mapped_column(String(4), default=TARGET_LEVEL)

    exercises: Mapped[list["Exercise"]] = relationship(
        back_populates="collection", order_by="Exercise.position")


class Exercise(Base):
    """Exercice de compréhension : un document (audio ou texte) et ses questions."""
    __tablename__ = "exercises"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(30), unique=True)  # ex. « CO-ENV-03 »
    section: Mapped[str] = mapped_column(String(2), index=True)  # CO / CE
    collection_id: Mapped[int | None] = mapped_column(
        ForeignKey("collections.id", ondelete="SET NULL"), nullable=True, index=True)
    position: Mapped[int] = mapped_column(Integer, default=0)
    title: Mapped[str] = mapped_column(String(200))
    level: Mapped[str] = mapped_column(String(4), default=TARGET_LEVEL)
    doc_type: Mapped[str] = mapped_column(String(80))  # « interview radio », « éditorial »…
    context: Mapped[str] = mapped_column(Text, default="")  # mise en situation
    document: Mapped[str] = mapped_column(Text)  # texte (CE) ou transcription (CO)
    speakers: Mapped[list | None] = mapped_column(JSON, nullable=True)
    audio_file: Mapped[str | None] = mapped_column(String(255), nullable=True)
    source_note: Mapped[str] = mapped_column(Text, default="")  # « document original »…
    vocabulary: Mapped[list] = mapped_column(JSON, default=list)  # [{terme, definition, exemple}]
    expressions: Mapped[list] = mapped_column(JSON, default=list)  # [{expression, sens, exemple}]
    traps: Mapped[list] = mapped_column(JSON, default=list)  # pièges de compréhension
    skills: Mapped[list] = mapped_column(JSON, default=list)  # implicite, point de vue…
    status: Mapped[str] = mapped_column(String(12), default=STATUS_VALID, index=True)
    origin: Mapped[str] = mapped_column(String(12), default=ORIGIN_BUILTIN)
    locally_modified: Mapped[bool] = mapped_column(Boolean, default=False)
    content_hash: Mapped[str] = mapped_column(String(64), default="")

    collection: Mapped[Collection | None] = relationship(back_populates="exercises")
    questions: Mapped[list[Question]] = relationship(
        back_populates="exercise", cascade="all, delete-orphan", order_by="Question.position")


class Video(Base):
    """Ressource vidéo gratuite (lien externe uniquement, jamais téléchargée)."""
    __tablename__ = "videos"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(30), unique=True)
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    category: Mapped[str] = mapped_column(String(60), index=True)
    source: Mapped[str] = mapped_column(String(80), default="")  # TV5MONDE, RFI, FEI…
    url: Mapped[str] = mapped_column(String(500))
    duration: Mapped[str] = mapped_column(String(60), default="")  # « 12 min », « série »
    level: Mapped[str] = mapped_column(String(10), default=TARGET_LEVEL)
    exercise: Mapped[list] = mapped_column(JSON, default=list)  # [{prompt, choices, answer, explanation}]
    related: Mapped[list] = mapped_column(JSON, default=list)  # codes d'exercices liés
    status: Mapped[str] = mapped_column(String(12), default=STATUS_VALID)
    origin: Mapped[str] = mapped_column(String(12), default=ORIGIN_BUILTIN)
    locally_modified: Mapped[bool] = mapped_column(Boolean, default=False)
    link_status: Mapped[str | None] = mapped_column(String(20), nullable=True)  # ok / erreur
    link_checked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class IntensiveDay(Base):
    """Programme intensif de 30 jours (les quatre compétences chaque jour)."""
    __tablename__ = "intensive_days"

    id: Mapped[int] = mapped_column(primary_key=True)
    day: Mapped[int] = mapped_column(Integer, unique=True)  # 1..30
    focus: Mapped[str] = mapped_column(String(200))
    activities: Mapped[list] = mapped_column(JSON)  # [{module, minutes, description, ref}]
    is_mock_exam: Mapped[bool] = mapped_column(Boolean, default=False)


class IntensiveProgress(Base):
    __tablename__ = "intensive_progress"
    __table_args__ = (UniqueConstraint("day_id", "activity_index"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    day_id: Mapped[int] = mapped_column(ForeignKey("intensive_days.id", ondelete="CASCADE"))
    activity_index: Mapped[int] = mapped_column(Integer)
    done_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


# --------------------------------------------------------------------------
# Activité du candidat
# --------------------------------------------------------------------------
class Profile(Base):
    __tablename__ = "profile"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), default="Candidat")
    initial_level: Mapped[str | None] = mapped_column(String(4), nullable=True)
    target_level: Mapped[str] = mapped_column(String(4), default="B2")
    exam_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    plan_start: Mapped[date | None] = mapped_column(Date, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class Attempt(Base):
    """Passage d'un examen complet, d'une épreuve isolée ou d'un entraînement."""
    __tablename__ = "attempts"

    id: Mapped[int] = mapped_column(primary_key=True)
    exam_id: Mapped[int | None] = mapped_column(ForeignKey("exams.id", ondelete="SET NULL"),
                                                index=True)
    mode: Mapped[str] = mapped_column(String(20))  # examen | entrainement
    sections: Mapped[list] = mapped_column(JSON)  # sections passées
    started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    results: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # results : {CO: {score, level, correct, total}, CE: …, EE: {note20, level}, EO: …}

    exam: Mapped[Exam | None] = relationship()
    answers: Mapped[list["Answer"]] = relationship(back_populates="attempt",
                                                   cascade="all, delete-orphan")
    writing_submissions: Mapped[list["WritingSubmission"]] = relationship(
        back_populates="attempt", cascade="all, delete-orphan")
    speaking_submissions: Mapped[list["SpeakingSubmission"]] = relationship(
        back_populates="attempt", cascade="all, delete-orphan")


class Answer(Base):
    __tablename__ = "answers"
    __table_args__ = (UniqueConstraint("attempt_id", "question_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    attempt_id: Mapped[int] = mapped_column(ForeignKey("attempts.id", ondelete="CASCADE"),
                                            index=True)
    question_id: Mapped[int] = mapped_column(ForeignKey("questions.id", ondelete="CASCADE"))
    choice_label: Mapped[str | None] = mapped_column(String(1), nullable=True)
    is_correct: Mapped[bool] = mapped_column(Boolean, default=False)
    time_spent_s: Mapped[float] = mapped_column(Float, default=0)

    attempt: Mapped[Attempt] = relationship(back_populates="answers")
    question: Mapped[Question] = relationship()


class WritingSubmission(Base):
    __tablename__ = "writing_submissions"

    id: Mapped[int] = mapped_column(primary_key=True)
    attempt_id: Mapped[int | None] = mapped_column(ForeignKey("attempts.id",
                                                              ondelete="CASCADE"), index=True)
    task_id: Mapped[int | None] = mapped_column(ForeignKey("writing_tasks.id",
                                                           ondelete="SET NULL"))
    text: Mapped[str] = mapped_column(Text)
    word_count: Mapped[int] = mapped_column(Integer)
    duration_s: Mapped[float] = mapped_column(Float, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    evaluation: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    note20: Mapped[float | None] = mapped_column(Float, nullable=True)
    level: Mapped[str | None] = mapped_column(String(4), nullable=True)

    attempt: Mapped[Attempt | None] = relationship(back_populates="writing_submissions")
    task: Mapped[WritingTask | None] = relationship()


class SpeakingSubmission(Base):
    __tablename__ = "speaking_submissions"

    id: Mapped[int] = mapped_column(primary_key=True)
    attempt_id: Mapped[int | None] = mapped_column(ForeignKey("attempts.id",
                                                              ondelete="CASCADE"), index=True)
    task_id: Mapped[int | None] = mapped_column(ForeignKey("speaking_tasks.id",
                                                           ondelete="SET NULL"))
    audio_path: Mapped[str | None] = mapped_column(String(255), nullable=True)
    transcript: Mapped[str] = mapped_column(Text, default="")
    dialogue: Mapped[list | None] = mapped_column(JSON, nullable=True)  # tours de parole
    duration_s: Mapped[float] = mapped_column(Float, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    evaluation: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    note20: Mapped[float | None] = mapped_column(Float, nullable=True)
    level: Mapped[str | None] = mapped_column(String(4), nullable=True)

    attempt: Mapped[Attempt | None] = relationship(back_populates="speaking_submissions")
    task: Mapped[SpeakingTask | None] = relationship()


class ErrorLog(Base):
    """Erreurs détectées, pour identifier les difficultés récurrentes."""
    __tablename__ = "error_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, index=True)
    source: Mapped[str] = mapped_column(String(20))  # EE | EO | grammaire | CO | CE
    category: Mapped[str] = mapped_column(String(60), index=True)  # accord, conjugaison…
    excerpt: Mapped[str] = mapped_column(Text, default="")
    correction: Mapped[str] = mapped_column(Text, default="")
    rule: Mapped[str] = mapped_column(Text, default="")


class ReviewItem(Base):
    """Répétition espacée (algorithme SM-2 simplifié)."""
    __tablename__ = "review_items"
    __table_args__ = (UniqueConstraint("item_type", "item_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    item_type: Mapped[str] = mapped_column(String(20))  # expression | vocab | grammaire
    item_id: Mapped[int] = mapped_column(Integer)
    easiness: Mapped[float] = mapped_column(Float, default=2.5)
    interval_days: Mapped[int] = mapped_column(Integer, default=0)
    repetitions: Mapped[int] = mapped_column(Integer, default=0)
    due: Mapped[date] = mapped_column(Date, default=date.today, index=True)
    last_reviewed: Mapped[date | None] = mapped_column(Date, nullable=True)


class StudySession(Base):
    """Temps d'entraînement par module."""
    __tablename__ = "study_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    module: Mapped[str] = mapped_column(String(30), index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, index=True)
    duration_s: Mapped[float] = mapped_column(Float, default=0)
    plan_day_id: Mapped[int | None] = mapped_column(ForeignKey("plan_days.id"), nullable=True)
    score: Mapped[float | None] = mapped_column(Float, nullable=True)  # 0..1 si exercices


class PlanProgress(Base):
    __tablename__ = "plan_progress"
    __table_args__ = (UniqueConstraint("plan_day_id", "activity_index"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    plan_day_id: Mapped[int] = mapped_column(ForeignKey("plan_days.id", ondelete="CASCADE"))
    activity_index: Mapped[int] = mapped_column(Integer)
    done_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


class Setting(Base):
    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    value: Mapped[str | None] = mapped_column(Text, nullable=True)


class SchemaInfo(Base):
    __tablename__ = "schema_info"

    key: Mapped[str] = mapped_column(String(40), primary_key=True)
    value: Mapped[str] = mapped_column(String(200))
