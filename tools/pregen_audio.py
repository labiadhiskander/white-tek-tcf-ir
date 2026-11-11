"""Pré-génère les fichiers audio des 500 documents CO (à lancer sous Windows).

    python tools/pregen_audio.py [--rate 170] [--force] [--exam EXAM-03]

Les fichiers sont écrits dans tcfmaster/content/audio/ sous le nom
`exam-NN_coMM.wav` (attendu par `Question.audio_file`) et sont ensuite
embarqués dans l'installateur : l'application lit alors les CO sans
dépendre des voix installées sur le poste de l'utilisateur.
Un enregistrement humain déposé sous le même nom remplace la synthèse.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tcfmaster.services.audio import AudioGenerator, default_backend  # noqa: E402

DATA = ROOT / "tcfmaster" / "content" / "data" / "exams"
AUDIO = ROOT / "tcfmaster" / "content" / "audio"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--rate", type=int, default=170)
    ap.add_argument("--force", action="store_true", help="régénérer les fichiers existants")
    ap.add_argument("--exam", help="limiter à un examen (ex. EXAM-03)")
    args = ap.parse_args(argv)

    backend = default_backend()
    if backend is None:
        print("Aucun moteur de synthèse vocale (pip install pyttsx3).")
        return 1
    fr = [v for v in backend.voices() if v.is_french]
    print("Voix françaises :", ", ".join(f"{v.name} [{v.locale}/{v.gender}]" for v in fr)
          or "aucune")
    if not fr:
        return 1
    tmp = AUDIO / ".tmp"
    gen = AudioGenerator(backend, tmp, rate=args.rate)
    AUDIO.mkdir(parents=True, exist_ok=True)
    done = 0
    for path in sorted(DATA.glob("*.json")):
        exam = json.loads(path.read_text(encoding="utf-8"))
        if args.exam and exam["code"] != args.exam:
            continue
        for q in exam["CO"]:
            target = AUDIO / q["audio_file"]
            if target.exists() and not args.force:
                continue
            out = gen.ensure(q["document"], q.get("speakers"))
            out.replace(target)
            done += 1
            print(f"  {target.name}")
    for p in tmp.glob("*"):
        p.unlink()
    if tmp.exists():
        tmp.rmdir()
    print(f"{done} fichier(s) généré(s) dans {AUDIO}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
