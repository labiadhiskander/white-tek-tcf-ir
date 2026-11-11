"""Import du contenu pédagogique (JSON) dans la base SQLite.

L'import est idempotent et conserve les identifiants existants : une mise à
jour de contenu modifie les questions en place (même examen, même section,
même position) afin de ne jamais casser l'historique du candidat.
"""
from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from tcfmaster.content import validator as V
from tcfmaster.core.paths import resource_root
from tcfmaster.db.models import (Choice, Exam, Expression, GrammarChapter, GrammarExercise,
                                 PlanDay, Question, SpeakingTask, Verb, VocabWord,
                                 WritingTask)

log = logging.getLogger("tcfmaster.seed")


def content_dir() -> Path:
    return resource_root() / "content" / "data"


@dataclass
class SeedReport:
    exams: int = 0
    expressions: int = 0
    vocab: int = 0
    grammar_chapters: int = 0
    verbs: int = 0
    plan_days: int = 0
    errors: list[str] = field(default_factory=list)


def _load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _hash(obj) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, ensure_ascii=False)
                          .encode("utf-8")).hexdigest()


# ------------------------------------------------------------------ exams
def import_exam(s: Session, data: dict, generated: bool = False) -> Exam:
    h = _hash(data)
    exam = s.execute(select(Exam).where(Exam.code == data["code"])).scalar_one_or_none()
    if exam is not None and exam.content_hash == h:
        return exam
    if exam is None:
        exam = Exam(code=data["code"])
        s.add(exam)
    exam.title = data["title"]
    exam.level = data.get("level", "B2")
    exam.description = data.get("description", "")
    exam.generated = generated
    exam.content_hash = h

    existing_q = {(q.section, q.position): q for q in exam.questions}
    for section in ("CO", "CE"):
        for qd in data.get(section, []):
            q = existing_q.get((section, qd["position"]))
            if q is None:
                q = Question(section=section, position=qd["position"])
                exam.questions.append(q)
            q.level = qd["level"]
            q.doc_type = qd["doc_type"]
            q.skill = qd.get("skill", "")
            q.document = qd["document"]
            q.speakers = qd.get("speakers")
            q.audio_file = qd.get("audio_file")
            q.prompt = qd["prompt"]
            q.explanation = qd["explanation"]
            by_label = {c.label: c for c in q.choices}
            for cd in qd["choices"]:
                c = by_label.get(cd["label"])
                if c is None:
                    c = Choice(label=cd["label"])
                    q.choices.append(c)
                c.text = cd["text"]
                c.is_correct = bool(cd.get("correct"))
                c.rationale = cd.get("rationale", "")

    existing_w = {t.task_number: t for t in exam.writing_tasks}
    for td in data.get("EE", []):
        t = existing_w.get(td["task_number"]) or WritingTask(task_number=td["task_number"])
        if t.id is None and t not in exam.writing_tasks:
            exam.writing_tasks.append(t)
        for k in ("level", "task_type", "instructions", "min_words", "max_words",
                  "model_answer", "tips", "expected_points"):
            if k in td:
                setattr(t, k, td[k])

    existing_s = {t.task_number: t for t in exam.speaking_tasks}
    for td in data.get("EO", []):
        t = existing_s.get(td["task_number"]) or SpeakingTask(task_number=td["task_number"])
        if t.id is None and t not in exam.speaking_tasks:
            exam.speaking_tasks.append(t)
        for k in ("level", "title", "scenario", "examiner_role", "duration_s",
                  "examiner_prompts", "useful_phrases", "model_answer"):
            if k in td:
                setattr(t, k, td[k])
    return exam


# ------------------------------------------------------------ expressions
def import_expressions(s: Session, items: list[dict]) -> int:
    existing = {(e.kind, e.text): e for e in s.execute(select(Expression)).scalars()}
    n = 0
    for d in items:
        e = existing.get((d["kind"], d["text"]))
        if e is None:
            e = Expression(kind=d["kind"], text=d["text"])
            s.add(e)
            existing[(d["kind"], d["text"])] = e
        for k in ("category", "meaning", "level", "example", "simple_equivalent",
                  "exercise", "exercise_answer"):
            setattr(e, k, d.get(k, ""))
        n += 1
    return n


def import_vocab(s: Session, items: list[dict]) -> int:
    existing = {(w.word, w.theme): w for w in s.execute(select(VocabWord)).scalars()}
    n = 0
    for d in items:
        w = existing.get((d["word"], d["theme"]))
        if w is None:
            w = VocabWord(word=d["word"], theme=d["theme"])
            s.add(w)
            existing[(d["word"], d["theme"])] = w
        for k in ("pos", "gender", "level", "definition", "example", "synonyms",
                  "collocations"):
            setattr(w, k, d.get(k, "" if k != "gender" else None))
        n += 1
    return n


def import_grammar(s: Session, chapter: dict) -> GrammarChapter:
    ch = s.execute(select(GrammarChapter).where(GrammarChapter.slug == chapter["slug"])
                   ).scalar_one_or_none()
    if ch is None:
        ch = GrammarChapter(slug=chapter["slug"])
        s.add(ch)
    for k in ("title", "module", "order", "level", "lesson", "simple_examples",
              "b2_examples"):
        if k in chapter:
            setattr(ch, k, chapter[k])
    ch.exercises.clear()
    for ex in chapter.get("exercises", []):
        ch.exercises.append(GrammarExercise(
            ex_type=ex["ex_type"], level=ex.get("level", ch.level), prompt=ex["prompt"],
            options=ex.get("options"), answer=ex["answer"], explanation=ex["explanation"]))
    return ch


def import_verbs(s: Session, verbs: list[dict]) -> int:
    existing = {v.infinitive: v for v in s.execute(select(Verb)).scalars()}
    for d in verbs:
        v = existing.get(d["infinitive"]) or Verb(infinitive=d["infinitive"])
        v.group = d["group"]
        v.auxiliary = d.get("auxiliary", "avoir")
        v.conjugations = d["conjugations"]
        if v.id is None:
            s.add(v)
    return len(verbs)


def import_plan(s: Session, days: list[dict]) -> int:
    existing = {(p.week, p.day): p for p in s.execute(select(PlanDay)).scalars()}
    for d in days:
        p = existing.get((d["week"], d["day"])) or PlanDay(week=d["week"], day=d["day"])
        p.focus = d["focus"]
        p.activities = d["activities"]
        p.is_mock_exam = d.get("is_mock_exam")
        p.is_review = d.get("is_review", False)
        if p.id is None:
            s.add(p)
    return len(days)


# ------------------------------------------------------------------- main
def seed_all(s: Session, root: Path | None = None, strict: bool = True) -> SeedReport:
    root = root or content_dir()
    rep = SeedReport()

    for f in sorted((root / "exams").glob("*.json")):
        data = _load_json(f)
        errs = V.validate_exam(data)
        if errs:
            rep.errors += errs
            if strict:
                continue
        import_exam(s, data)
        rep.exams += 1

    for f in sorted((root / "expressions").glob("*.json")):
        items = _load_json(f)
        good = []
        for i, e in enumerate(items):
            errs = V.validate_expression(e, f"{f.name}#{i}")
            rep.errors += errs
            if not errs or not strict:
                good.append(e)
        rep.expressions += import_expressions(s, good)

    for f in sorted((root / "vocab").glob("*.json")):
        rep.vocab += import_vocab(s, _load_json(f))

    for f in sorted((root / "grammar").glob("*.json")):
        ch = _load_json(f)
        for i, ex in enumerate(ch.get("exercises", [])):
            rep.errors += V.validate_grammar_exercise(ex, f"{f.name}#{i}")
        import_grammar(s, ch)
        rep.grammar_chapters += 1

    if (root / "verbs.json").exists():
        rep.verbs = import_verbs(s, _load_json(root / "verbs.json"))
    if (root / "plan.json").exists():
        rep.plan_days = import_plan(s, _load_json(root / "plan.json"))

    for e in rep.errors:
        log.warning("Contenu invalide : %s", e)
    s.flush()
    return rep
