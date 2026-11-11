"""Compile la bibliothèque de vocabulaire B2.

Sources (content_src/vocab/) — une entrée par ligne, champs séparés par « | »,
les lignes « # Catégorie » ouvrent une catégorie :

expressions/*.txt et connecteurs/*.txt
    texte | niveau | signification | exemple | équivalent simple [| consigne | modèle]
    Sans consigne, l'exercice de réutilisation est un texte à trous construit à
    partir de l'exemple (la correction est l'expression elle-même).

phrases/*.txt (phrases complexes) et argumentation/*.txt
    phrase B2 | niveau | structure ou stratégie | version simple | autre exemple
    L'exercice demande de transformer la version simple ; la correction est la
    phrase B2.

mots/*.txt (vocabulaire contextualisé, la catégorie est le thème)
    mot | nature | genre (m/f/-) | niveau | définition | exemple | synonymes | collocations
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

LEVELS = {"A1", "A2", "B1", "B2", "C1", "C2"}
KIND_DIRS = {"expressions": "expression", "connecteurs": "connecteur",
             "phrases": "phrase_complexe", "argumentation": "argumentation"}


def _lines(path: Path):
    cat = None
    for n, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("//"):
            continue
        if line.startswith("# "):
            cat = line[2:].strip()
            continue
        yield n, cat, [f.strip() for f in line.split(" | ")]


def _cloze(example: str, text: str) -> str | None:
    key = text.strip(" ….").rstrip(",")
    m = re.search(re.escape(key), example, flags=re.IGNORECASE)
    if not m:
        return None
    return example[:m.start()] + "……" + example[m.end():]


def parse_expressions(path: Path, kind: str, errors: list[str]) -> list[dict]:
    out = []
    for n, cat, f in _lines(path):
        where = f"{path.name}:{n}"
        if len(f) not in (5, 7) or not cat:
            errors.append(f"{where}: 5 ou 7 champs attendus ({len(f)})")
            continue
        text, level, meaning, example, simple = f[:5]
        if level not in LEVELS:
            errors.append(f"{where}: niveau {level!r}")
        if len(f) == 7:
            exercise, answer = f[5], f[6]
        else:
            hole = _cloze(example, text)
            if hole is None:  # verbe conjugué dans l'exemple : exercice de production
                exercise = (f"Réutilisez « {text} » ({meaning.rstrip('.')}) dans une phrase "
                            f"personnelle sur un autre sujet que l'exemple.")
                answer = (f"Exemple de réponse : {example} Vérifiez que votre phrase garde "
                          f"le sens « {meaning.rstrip('.')} » et la construction correcte.")
            else:
                exercise = (f"Complétez avec l'expression qui convient (sens : {meaning.rstrip('.')}) :"
                        f"\n{hole}")
                answer = (f"{text.strip(' …')} — phrase complète : {example} "
                      f"Équivalent plus simple : {simple}")
        out.append({"kind": kind, "category": cat, "text": text, "meaning": meaning,
                    "level": level, "example": example, "simple_equivalent": simple,
                    "exercise": exercise, "exercise_answer": answer})
    return out


def parse_transformations(path: Path, kind: str, errors: list[str]) -> list[dict]:
    out = []
    for n, cat, f in _lines(path):
        where = f"{path.name}:{n}"
        if len(f) != 5 or not cat:
            errors.append(f"{where}: 5 champs attendus ({len(f)})")
            continue
        text, level, meaning, simple, example = f
        if level not in LEVELS:
            errors.append(f"{where}: niveau {level!r}")
        if kind == "phrase_complexe":
            exercise = (f"Transformez ces phrases simples en une phrase complexe "
                        f"({meaning.rstrip('.')}) :\n{simple}")
        else:
            exercise = (f"Développez cet argument simple en un argument de niveau B2 "
                        f"(stratégie : {meaning.rstrip('.')}) :\n{simple}")
        out.append({"kind": kind, "category": cat, "text": text, "meaning": meaning,
                    "level": level, "example": example, "simple_equivalent": simple,
                    "exercise": exercise,
                    "exercise_answer": f"Proposition de correction : {text}"})
    return out


def parse_words(path: Path, errors: list[str]) -> list[dict]:
    out = []
    for n, theme, f in _lines(path):
        where = f"{path.name}:{n}"
        if len(f) != 8 or not theme:
            errors.append(f"{where}: 8 champs attendus ({len(f)})")
            continue
        word, pos, gender, level, definition, example, syn, coll = f
        if level not in LEVELS:
            errors.append(f"{where}: niveau {level!r}")
        out.append({"word": word, "pos": pos, "gender": gender if gender in ("m", "f") else None,
                    "theme": theme, "level": level, "definition": definition,
                    "example": example, "synonyms": syn if syn != "-" else "",
                    "collocations": coll if coll != "-" else ""})
    return out


def build(src_root: Path, out_root: Path) -> list[str]:
    errors: list[str] = []
    src = src_root / "vocab"
    if not src.is_dir():
        return errors
    (out_root / "expressions").mkdir(parents=True, exist_ok=True)
    (out_root / "vocab").mkdir(parents=True, exist_ok=True)
    counts: dict[str, int] = {}
    seen: set[tuple[str, str]] = set()
    for d, kind in KIND_DIRS.items():
        for f in sorted((src / d).glob("*.txt")):
            items = (parse_expressions(f, kind, errors)
                     if kind in ("expression", "connecteur")
                     else parse_transformations(f, kind, errors))
            for it in items:
                key = (kind, it["text"].lower(), it["category"])
                if key in seen:
                    errors.append(f"{f.name}: doublon « {it['text']} »")
                seen.add(key)
            counts[kind] = counts.get(kind, 0) + len(items)
            (out_root / "expressions" / f"{d}_{f.stem}.json").write_text(
                json.dumps(items, ensure_ascii=False, indent=1), encoding="utf-8")
    words_seen: set[tuple[str, str]] = set()
    nwords = 0
    for f in sorted((src / "mots").glob("*.txt")):
        items = parse_words(f, errors)
        for it in items:
            key = (it["word"].lower(), it["theme"])
            if key in words_seen:
                errors.append(f"{f.name}: mot en double « {it['word']} »")
            words_seen.add(key)
        nwords += len(items)
        (out_root / "vocab" / f"{f.stem}.json").write_text(
            json.dumps(items, ensure_ascii=False, indent=1), encoding="utf-8")
    print("vocabulaire : " + ", ".join(f"{v} {k}" for k, v in counts.items())
          + f", {nwords} mots")
    return errors


if __name__ == "__main__":
    root = Path(__file__).resolve().parent.parent
    sys.path.insert(0, str(root))
    errs = build(root / "content_src", root / "tcfmaster" / "content" / "data")
    for e in errs:
        print("ERREUR:", e)
    sys.exit(1 if errs else 0)
