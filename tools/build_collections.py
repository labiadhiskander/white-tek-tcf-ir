"""Compile les collections B2 (format texte) en JSON importable (v1.1).

Fichiers sources : content_src/collections/<co|ce|ee|eo>/<slug>.txt

En-tête de collection :

    @slug co-environnement
    @section CO
    @title Environnement et climat
    @order 2
    @description Débats, reportages et interviews sur la transition écologique.

Exercice de compréhension (CO ou CE) :

    ## CO-ENV-01 | interview radio | H:fr-FR, F:fr-CA
    TITRE: Titre de l'exercice
    CONTEXTE: mise en situation (facultatif)
    DOC: transcription (CO, « / » sépare les répliques, « H: » / « F: » le locuteur)
         ou texte (CE, « ¶ » sépare les paragraphes)
    Q: énoncé | compétence (implicite, point de vue, argumentation, synthèse…)
    + bonne réponse | justification fondée sur le document
    - distracteur | pourquoi c'est faux
    - distracteur | pourquoi c'est faux
    - distracteur | pourquoi c'est faux
    EXP: explication pédagogique
    (… autres questions …)
    VOCAB: terme = définition = exemple ; terme = définition = exemple
    EXPR: expression = sens = exemple ; …
    PIEGES: piège ; piège            (obligatoire en CE)

Sujet d'expression écrite :

    ## EE-B2-001 | 1 | type de tâche | thème
    CONSIGNE: énoncé et consignes
    MODELE: réponse modèle B2 (dans les limites officielles)
    COMMENTAIRE: pourquoi ce modèle est de niveau B2
    POINTS: point attendu ; point attendu
    CONSEILS: conseils de rédaction

Situation d'expression orale :

    ## EO-B2-001 | 2 | Titre | Rôle de l'examinateur | thème
    SCENARIO: consigne
    RELANCES: relance / relance
    PHRASES: phrase utile / phrase utile
    MODELE: réponse modèle B2
    COMMENTAIRE: pourquoi ce modèle est de niveau B2
    CONSEILS: conseils

Les lignes qui commencent par un espace prolongent le champ précédent. La
position de la bonne réponse est mélangée de façon déterministe (graine = code).
"""
from __future__ import annotations

import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "content_src" / "collections"
OUT = ROOT / "tcfmaster" / "content" / "data" / "collections"
sys.path.insert(0, str(ROOT))

from tcfmaster.content import validator as V  # noqa: E402
from tcfmaster.db.models import SPEAKING_DURATIONS_S, WRITING_WORD_LIMITS  # noqa: E402

LABELS = "ABCD"


def _split_list(value: str, sep: str = ";") -> list[str]:
    return [x.strip() for x in value.split(sep) if x.strip()]


def _triples(value: str, keys: tuple[str, str, str]) -> list[dict]:
    out = []
    for part in _split_list(value):
        bits = [b.strip() for b in part.split("=")]
        d = {keys[0]: bits[0], keys[1]: bits[1] if len(bits) > 1 else ""}
        if len(bits) > 2 and bits[2]:
            d[keys[2]] = "=".join(bits[2:]).strip()
        out.append(d)
    return out


def _speakers(spec: str) -> list[str] | None:
    sp = [x.strip() for x in spec.split(",") if x.strip()]
    return sp or None


def _blocks(text: str):
    """Découpe le fichier en (en-tête, [(titre, [lignes])])."""
    header: dict[str, str] = {}
    blocks: list[tuple[str, list[str]]] = []
    for raw in text.splitlines():
        if not raw.strip() or (raw.startswith("#") and not raw.startswith("## ")):
            continue                                  # ligne vide ou commentaire
        if raw.startswith("@") and not blocks:
            k, _, v = raw[1:].partition(" ")
            header[k.strip()] = v.strip()
        elif raw.startswith("## "):
            blocks.append((raw[3:].strip(), []))
        elif blocks:
            blocks[-1][1].append(raw)
    return header, blocks


def _fields(lines: list[str]) -> list[tuple[str, str]]:
    """Lignes → [(clé, valeur)] en conservant l'ordre (les questions se répètent)."""
    out: list[tuple[str, str]] = []
    for ln in lines:
        if ln.startswith((" ", "\t")) and out:
            k, v = out[-1]
            out[-1] = (k, (v + " " + ln.strip()).strip())
            continue
        s = ln.strip()
        if s.startswith(("+ ", "- ")):
            out.append((s[0], s[2:].strip()))
            continue
        key, sep, val = s.partition(":")
        if sep and key.isupper():
            out.append((key, val.strip()))
        elif out:
            k, v = out[-1]
            out[-1] = (k, (v + " " + s).strip())
    return out


def _document(text: str) -> str:
    return text.replace(" ¶ ", "\n\n").replace("¶", "\n\n").strip()


def build_exercise(title: str, lines: list[str], section: str) -> dict:
    parts = [p.strip() for p in title.split("|")]
    code, doc_type = parts[0], parts[1]
    ex: dict = {"code": code, "level": "B2", "doc_type": doc_type, "questions": []}
    if section == "CO":
        ex["speakers"] = _speakers(parts[2] if len(parts) > 2 else "")
    q: dict | None = None
    for key, val in _fields(lines):
        if key == "TITRE":
            ex["title"] = val
        elif key == "CONTEXTE":
            ex["context"] = val
        elif key == "DOC":
            ex["document"] = _document(val)
        elif key == "Q":
            prompt, _, skill = val.partition("|")
            q = {"prompt": prompt.strip(), "skill": skill.strip(), "choices": []}
            ex["questions"].append(q)
        elif key in "+-" and q is not None:
            text, _, why = val.partition("|")
            q["choices"].append({"text": text.strip(), "correct": key == "+",
                                 "rationale": why.strip()})
        elif key == "EXP" and q is not None:
            q["explanation"] = val
        elif key == "VOCAB":
            ex["vocabulary"] = _triples(val, ("terme", "definition", "exemple"))
        elif key == "EXPR":
            ex["expressions"] = _triples(val, ("expression", "sens", "exemple"))
        elif key == "PIEGES":
            ex["traps"] = _split_list(val)
        elif key == "SOURCE":
            ex["source_note"] = val
    for i, qd in enumerate(ex["questions"], 1):
        rng = random.Random(f"{code}-{i}")
        rng.shuffle(qd["choices"])
        for lab, c in zip(LABELS, qd["choices"]):
            c["label"] = lab
    return ex


def build_writing(title: str, lines: list[str]) -> dict:
    parts = [p.strip() for p in title.split("|")]
    n = int(parts[1])
    lo, hi = WRITING_WORD_LIMITS[n]
    t = {"code": parts[0], "task_number": n, "level": "B2", "task_type": parts[2],
         "theme": parts[3] if len(parts) > 3 else "", "min_words": lo, "max_words": hi}
    for key, val in _fields(lines):
        if key == "CONSIGNE":
            t["instructions"] = val
        elif key == "MODELE":
            t["model_answer"] = _document(val)
        elif key == "COMMENTAIRE":
            t["model_commentary"] = val
        elif key == "POINTS":
            t["expected_points"] = _split_list(val)
        elif key == "CONSEILS":
            t["tips"] = val
    return t


def build_speaking(title: str, lines: list[str]) -> dict:
    parts = [p.strip() for p in title.split("|")]
    n = int(parts[1])
    t = {"code": parts[0], "task_number": n, "level": "B2", "title": parts[2],
         "examiner_role": parts[3] if len(parts) > 3 else "Examinateur",
         "theme": parts[4] if len(parts) > 4 else "", "duration_s": SPEAKING_DURATIONS_S[n]}
    for key, val in _fields(lines):
        if key == "SCENARIO":
            t["scenario"] = val
        elif key == "RELANCES":
            t["examiner_prompts"] = _split_list(val, "/")
        elif key == "PHRASES":
            t["useful_phrases"] = _split_list(val, "/")
        elif key == "MODELE":
            t["model_answer"] = _document(val)
        elif key == "COMMENTAIRE":
            t["model_commentary"] = val
        elif key == "CONSEILS":
            t["tips"] = val
    return t


def build_file(path: Path) -> dict:
    header, blocks = _blocks(path.read_text(encoding="utf-8"))
    sec = header["section"]
    col = {"slug": header["slug"], "section": sec, "title": header["title"],
           "description": header.get("description", ""), "order": int(header.get("order", 0)),
           "level": "B2", "items": []}
    for title, lines in blocks:
        if sec in ("CO", "CE"):
            col["items"].append(build_exercise(title, lines, sec))
        elif sec == "EE":
            col["items"].append(build_writing(title, lines))
        else:
            col["items"].append(build_speaking(title, lines))
    return col


def main() -> int:
    errors: list[str] = []
    docs: list[tuple[str, str]] = []
    n = 0
    for src in sorted(SRC.glob("*/*.txt")):
        col = build_file(src)
        errs = V.validate_collection(col)
        errors += [f"{src.name}: {e}" for e in errs]
        docs += [(it["code"], it.get("document") or it.get("instructions")
                  or it.get("scenario") or "") for it in col["items"]]
        dest = OUT / src.parent.name / (src.stem + ".json")
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(json.dumps(col, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        n += len(col["items"])
    errors += V.find_duplicates(docs)
    for e in errors:
        print("ERREUR", e)
    print(f"{n} élément(s) compilé(s), {len(errors)} erreur(s)")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
