"""Compile content_src/videos/videos.txt → tcfmaster/content/data/videos.json.

    python3 tools/build_videos.py

Voir content_src/videos/README.md pour le format. Les bonnes réponses sont
réparties équilibrément entre A et D ; toute fiche invalide bloque la compilation.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

from build_collections import AnswerSlots  # noqa: E402

from tcfmaster.content import validator as V  # noqa: E402

SRC = ROOT / "content_src" / "videos" / "videos.txt"
OUT = ROOT / "tcfmaster" / "content" / "data" / "videos.json"


def _blocks(text: str):
    cur = None
    for line in text.splitlines():
        line = line.rstrip()
        if line.startswith("## "):
            if cur:
                yield cur
            cur = [line[3:], []]
        elif cur is not None and line:
            cur[1].append(line)
    if cur:
        yield cur


def build_video(head: str, lines: list[str], slots: AnswerSlots) -> dict:
    code, category, source, duration = [p.strip() for p in head.split("|")]
    v = {"code": code, "category": category, "source": source, "duration": duration,
         "level": "B2", "exercise": [], "related": []}
    fields, q = {}, None
    for ln in lines:
        if ln.startswith(("+ ", "- ")):
            text, _, why = ln[2:].partition("|")
            q["opts"].append((ln[0] == "+", text.strip(), why.strip()))
            continue
        key, _, val = ln.partition(":")
        key, val = key.strip(), val.strip()
        if key == "Q":
            q = {"prompt": val, "opts": []}
            v["exercise"].append(q)
        else:
            fields[key] = val
    v["title"] = fields.get("TITRE", "")
    v["url"] = fields.get("URL", "")
    desc = fields.get("DESCRIPTION", "")
    if fields.get("CONSEIL"):
        desc += "\n\nConseil d'utilisation : " + fields["CONSEIL"]
    v["description"] = desc
    out = []
    for q in v["exercise"]:
        good = [o for o in q["opts"] if o[0]]
        bad = [o for o in q["opts"] if not o[0]]
        if len(good) != 1:
            raise SystemExit(f"{code}: une seule bonne réponse attendue")
        pos = slots.next()
        opts = bad[:pos] + good + bad[pos:]
        explanation = good[0][2]
        out.append({"prompt": q["prompt"], "choices": [o[1] for o in opts],
                    "rationales": [o[2] for o in opts], "answer": pos,
                    "explanation": explanation})
    v["exercise"] = out
    return v


def main() -> int:
    slots = AnswerSlots("videos")
    videos = [build_video(h, ls, slots) for h, ls in _blocks(SRC.read_text(encoding="utf-8"))]
    errs = [e for v in videos for e in V.validate_video(v)]
    codes = [v["code"] for v in videos]
    if len(set(codes)) != len(codes):
        errs.append("codes en double")
    missing = set(V.VIDEO_CATEGORIES) - {v["category"] for v in videos}
    if missing:
        errs.append(f"catégories sans fiche : {sorted(missing)}")
    for e in errs:
        print("ERREUR", e)
    if errs:
        return 1
    OUT.write_text(json.dumps(videos, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"videos.json : {len(videos)} fiches, {len({v['category'] for v in videos})} catégories")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
