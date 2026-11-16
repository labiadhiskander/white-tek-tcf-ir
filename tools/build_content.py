"""Compile les sources rédactionnelles (format texte) en JSON importable.

Format d'un examen (content_src/exams/exam_XX.txt) :

    @code EXAM-01
    @title Examen blanc n° 1
    @level B2
    @description ...

    ## CO 1 | A2 | message téléphonique | information précise | F:fr-FR
    DOC: texte du document (CO : transcription ; « / » sépare les répliques,
         « H: », « F: » indiquent le locuteur)
    Q: énoncé
    + bonne réponse | justification
    - distracteur | pourquoi c'est faux
    - distracteur | pourquoi c'est faux
    - distracteur | pourquoi c'est faux
    EXP: correction détaillée

    ## EE 1 | B1 | décrire un lieu
    CONSIGNE: ...
    MODELE: ...
    POINTS: point attendu ; point attendu
    CONSEILS: ...

    ## EO 2 | B2 | Titre | Rôle de l'examinateur
    SCENARIO: ...
    RELANCES: question / question / question
    PHRASES: phrase utile / phrase utile
    MODELE: ...

Les lignes qui commencent par un espace prolongent le champ précédent.
La position de la bonne réponse est mélangée de façon déterministe.

v1.1 – examens blancs B2 (content_src/exams/exam_b2_XX.txt) : l'en-tête
`@series B2` les distingue des examens v1.0. Pour cette série, la bonne
réponse est répartie de façon équilibrée sur A–D, toutes les questions doivent
être de niveau B2, un champ COMMENTAIRE est accepté pour EE et EO, et aucun
document ni sujet ne peut reprendre un autre examen ou une collection.
"""
from __future__ import annotations

import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "content_src"
OUT = ROOT / "tcfmaster" / "content" / "data"

sys.path.insert(0, str(ROOT))
from tcfmaster.content import validator as V  # noqa: E402

WRITING_LIMITS = {1: (30, 60), 2: (40, 90), 3: (40, 90)}
SPEAKING_DUR = {1: 180, 2: 210, 3: 210}


def _blocks(text: str):
    header, blocks, cur = {}, [], None
    for raw in text.splitlines():
        line = raw.rstrip()
        if not line.strip() or line.lstrip().startswith("#!"):
            continue
        if line.startswith("@") and cur is None:
            k, _, v = line[1:].partition(" ")
            header[k] = v.strip()
        elif line.startswith("## "):
            cur = {"head": line[3:].strip(), "lines": []}
            blocks.append(cur)
        elif cur is not None:
            if raw.startswith((" ", "\t")) and cur["lines"]:
                cur["lines"][-1] += " " + line.strip()
            else:
                cur["lines"].append(line.strip())
    return header, blocks


def _fields(lines):
    f, choices = {}, []
    for ln in lines:
        if ln.startswith(("+ ", "- ")):
            text, _, why = ln[2:].partition(" | ")
            choices.append((ln[0] == "+", text.strip(), why.strip()))
        else:
            k, _, v = ln.partition(":")
            f[k.strip().upper()] = v.strip()
    return f, choices


def parse_exam(path: Path) -> dict:
    header, blocks = _blocks(path.read_text(encoding="utf-8"))
    code = header["code"]
    exam = {"code": code, "title": header["title"], "level": header.get("level", "B2"),
            "description": header.get("description", ""), "CO": [], "CE": [], "EE": [], "EO": []}
    series = header.get("series")
    if series:
        exam["series"] = series
    slots = None
    if series == "B2":                  # v1.0 inchangé : positions d'origine conservées
        sys.path.insert(0, str(ROOT / "tools"))
        from build_collections import AnswerSlots
        slots = {k: AnswerSlots(f"{code}-{k}") for k in ("CO", "CE")}
    for b in blocks:
        parts = [p.strip() for p in b["head"].split("|")]
        kind, num = parts[0].split()
        num = int(num)
        f, choices = _fields(b["lines"])
        if kind in ("CO", "CE"):
            rng = random.Random(f"{code}-{kind}-{num}")
            order = list(range(4))
            rng.shuffle(order)
            labels = "ABCD"
            if slots is not None:       # bonne réponse placée selon un tirage équilibré
                good = next(i for i in order if i < len(choices) and choices[i][0])
                order.remove(good)
                order.insert(slots[kind].next(), good)
            ch = []
            for i, idx in enumerate(order):
                ok, text, why = choices[idx] if idx < len(choices) else (False, "", "")
                ch.append({"label": labels[i], "text": text, "correct": ok, "rationale": why})
            q = {"position": num, "level": parts[1], "doc_type": parts[2],
                 "skill": parts[3] if len(parts) > 3 else "",
                 "document": f.get("DOC", ""), "prompt": f.get("Q", ""),
                 "choices": ch, "explanation": f.get("EXP", "")}
            if kind == "CO":
                q["speakers"] = [s.strip() for s in parts[4].split(",")] if len(parts) > 4 else []
                # enregistrement facultatif (tcfmaster/content/audio/) ; à défaut,
                # le document est lu par la synthèse vocale
                q["audio_file"] = f"{code.lower()}_co{num:02d}.wav"
            exam[kind].append(q)
        elif kind == "EE":
            lo, hi = WRITING_LIMITS[num]
            exam["EE"].append({
                "task_number": num, "level": parts[1], "task_type": parts[2],
                "instructions": f.get("CONSIGNE", ""), "min_words": lo, "max_words": hi,
                "model_answer": f.get("MODELE", ""), "tips": f.get("CONSEILS", ""),
                "expected_points": [x.strip() for x in f.get("POINTS", "").split(";")
                                    if x.strip()]})
            if f.get("COMMENTAIRE"):
                exam["EE"][-1]["model_commentary"] = f["COMMENTAIRE"]
        elif kind == "EO":
            exam["EO"].append({
                "task_number": num, "level": parts[1], "title": parts[2],
                "examiner_role": parts[3] if len(parts) > 3 else "Examinateur",
                "scenario": f.get("SCENARIO", ""), "duration_s": SPEAKING_DUR[num],
                "examiner_prompts": [x.strip() for x in f.get("RELANCES", "").split(" / ")
                                     if x.strip()],
                "useful_phrases": [x.strip() for x in f.get("PHRASES", "").split(" / ")
                                   if x.strip()],
                "model_answer": f.get("MODELE", "")})
            if f.get("COMMENTAIRE"):
                exam["EO"][-1]["model_commentary"] = f["COMMENTAIRE"]
            if f.get("CONSEILS"):
                exam["EO"][-1]["tips"] = f["CONSEILS"]
    for k in ("CO", "CE"):
        exam[k].sort(key=lambda q: q["position"])
    return exam


def _collection_texts() -> list[tuple[str, str]]:
    """Documents et sujets des collections v1.1, pour interdire les reprises."""
    out = []
    for f in sorted((OUT / "collections").glob("*/*.json")):
        for it in json.loads(f.read_text(encoding="utf-8"))["items"]:
            for key in ("document", "instructions", "scenario"):
                if it.get(key):
                    out.append((f"collection {it['code']}", it[key]))
    return out


def _exam_texts(exam: dict) -> list[tuple[str, str]]:
    code = exam["code"]
    out = [(f"{code} {k} Q{q['position']}", q["document"]) for k in ("CO", "CE")
           for q in exam[k]]
    out += [(f"{code} EE T{t['task_number']}", t["instructions"]) for t in exam["EE"]]
    out += [(f"{code} EO T{t['task_number']}", t["scenario"]) for t in exam["EO"]]
    return out


def validate_b2_series(exam: dict) -> list[str]:
    """Règles propres aux examens blancs B2 de la v1.1."""
    code, errs = exam["code"], []
    for k in ("CO", "CE"):
        for q in exam[k]:
            if q["level"] != "B2":
                errs.append(f"{code} {k} Q{q['position']}: niveau {q['level']} (100 % B2)")
            if not q["explanation"] or not all(c["rationale"] for c in q["choices"]):
                errs.append(f"{code} {k} Q{q['position']}: correction incomplète")
    for t in exam["EE"] + exam["EO"]:
        if t["level"] != "B2":
            errs.append(f"{code} tâche {t['task_number']}: niveau {t['level']} (100 % B2)")
        if not t.get("model_answer"):
            errs.append(f"{code} tâche {t['task_number']}: réponse modèle manquante")
    return errs


def build_exams() -> list[str]:
    errors = []
    (OUT / "exams").mkdir(parents=True, exist_ok=True)
    seen = _collection_texts()
    for src in sorted((SRC / "exams").glob("exam_*.txt")):
        exam = parse_exam(src)
        errs = V.validate_exam(exam)
        if exam.get("series") == "B2":
            errs += validate_b2_series(exam)
            mine = _exam_texts(exam)
            errs += [e for e in V.find_duplicates(seen + mine) if e.split(" reprend ")[0]
                     .removeprefix("doublon : ") in {w for w, _ in mine}]
            seen += mine
        errors += errs
        (OUT / "exams" / (src.stem + ".json")).write_text(
            json.dumps(exam, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"{src.name}: {len(exam['CO'])} CO, {len(exam['CE'])} CE, "
              f"{len(exam['EE'])} EE, {len(exam['EO'])} EO, {len(errs)} erreur(s)")
    return errors


def main() -> int:
    errors = build_exams()
    for mod in ("build_vocab", "build_grammar", "build_plan", "build_verbs"):
        p = ROOT / "tools" / f"{mod}.py"
        if p.exists():
            ns: dict = {"__name__": "builder", "__file__": str(p)}
            exec(compile(p.read_text(encoding="utf-8"), str(p), "exec"), ns)
            errors += ns["build"](SRC, OUT) or []
    for e in errors:
        print("ERREUR:", e)
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
