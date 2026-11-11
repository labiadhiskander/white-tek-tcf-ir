"""Compile content_src/grammar/*.txt -> tcfmaster/content/data/grammar/*.json.

Format d'un chapitre :

    @slug present
    @title Le présent de l'indicatif
    @module conjugaison            (ou grammaire)
    @order 1
    @level A2
    ## COURS
    (Markdown léger : ##, ###, **gras**, listes « - »)
    ## SIMPLES
    - exemple simple
    ## B2
    - exemple de niveau B2
    ## EXERCICES
    QCM | B1 | énoncé
    * bonne option
    - option fausse
    = correction détaillée
    TROU | B1 | énoncé avec ___
    > réponse|variante acceptée
    = correction détaillée
    TRANS | B2 | énoncé (transformation)
    > réponse|variante
    = correction détaillée
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

TYPES = {"QCM": "qcm", "TROU": "trou", "TRANS": "transformation"}


def parse_chapter(path: Path) -> dict:
    ch: dict = {"exercises": []}
    section = None
    lesson: list[str] = []
    simple: list[str] = []
    b2: list[str] = []
    ex = None
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.rstrip()
        if section is None and line.startswith("@"):
            key, _, val = line[1:].partition(" ")
            ch[key] = int(val) if key == "order" else val.strip()
            continue
        if line.startswith("## ") and line[3:].strip() in ("COURS", "SIMPLES", "B2", "EXERCICES"):
            section = line[3:].strip()
            continue
        if section == "COURS":
            lesson.append(line)
        elif section == "SIMPLES" and line.startswith("- "):
            simple.append(line[2:].strip())
        elif section == "B2" and line.startswith("- "):
            b2.append(line[2:].strip())
        elif section == "EXERCICES":
            head = line.split(" | ", 2)
            if len(head) == 3 and head[0] in TYPES:
                ex = {"ex_type": TYPES[head[0]], "level": head[1].strip(),
                      "prompt": head[2].strip(), "options": None, "answer": "",
                      "explanation": ""}
                ch["exercises"].append(ex)
            elif ex is None or not line.strip():
                continue
            elif line.startswith("* "):
                ex["options"] = (ex["options"] or []) + [line[2:].strip()]
                ex["answer"] = line[2:].strip()
            elif line.startswith("- "):
                ex["options"] = (ex["options"] or []) + [line[2:].strip()]
            elif line.startswith("> "):
                ex["answer"] = line[2:].strip()
            elif line.startswith("= "):
                ex["explanation"] = (ex["explanation"] + " " + line[2:].strip()).strip()
    ch["lesson"] = "\n".join(lesson).strip()
    ch["simple_examples"] = simple
    ch["b2_examples"] = b2
    return ch


def build(src_root: Path, out_root: Path) -> list[str]:
    from tcfmaster.content import validator as V

    errors: list[str] = []
    out = out_root / "grammar"
    out.mkdir(parents=True, exist_ok=True)
    files = sorted((src_root / "grammar").glob("*.txt"))
    for f in files:
        ch = parse_chapter(f)
        errs = []
        for key in ("slug", "title", "module", "order", "level"):
            if key not in ch:
                errs.append(f"{f.name}: @{key} manquant")
        if len(ch["lesson"]) < 400:
            errs.append(f"{f.name}: cours trop court")
        if len(ch["simple_examples"]) < 3 or len(ch["b2_examples"]) < 3:
            errs.append(f"{f.name}: exemples insuffisants")
        if len(ch["exercises"]) < 10:
            errs.append(f"{f.name}: moins de 10 exercices")
        for i, ex in enumerate(ch["exercises"]):
            errs += V.validate_grammar_exercise(ex, f"{f.name}#{i + 1}")
        errors += errs
        (out / (f.stem + ".json")).write_text(
            json.dumps(ch, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"grammaire : {len(files)} chapitre(s), "
          f"{sum(len(parse_chapter(f)['exercises']) for f in files)} exercices")
    return errors


if __name__ == "__main__":
    root = Path(__file__).resolve().parent.parent
    sys.path.insert(0, str(root))
    errs = build(root / "content_src", root / "tcfmaster" / "content" / "data")
    for e in errs:
        print("ERREUR:", e)
    sys.exit(1 if errs else 0)
