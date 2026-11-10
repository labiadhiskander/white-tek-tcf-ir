"""Télécharge le modèle français de Vosk dans tcfmaster/models/ (avant l'installateur).

    python tools/fetch_vosk_model.py
"""
from __future__ import annotations

import io
import sys
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tcfmaster.services.stt import MODEL_NAME, MODEL_URL  # noqa: E402

DEST = ROOT / "tcfmaster" / "models"


def main() -> int:
    target = DEST / MODEL_NAME
    if target.is_dir():
        print(f"Déjà présent : {target}")
        return 0
    DEST.mkdir(parents=True, exist_ok=True)
    print(f"Téléchargement de {MODEL_URL} …")
    with urllib.request.urlopen(MODEL_URL, timeout=120) as r:
        data = r.read()
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        for member in z.namelist():           # protection contre les chemins hors dossier
            p = (DEST / member).resolve()
            if not str(p).startswith(str(DEST.resolve())):
                raise RuntimeError(f"Chemin suspect dans l'archive : {member}")
        z.extractall(DEST)
    print(f"Modèle installé : {target}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
