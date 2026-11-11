"""Confidentialité : effacement des données d'apprentissage et masquage des secrets.

L'effacement est précédé d'une sauvegarde automatique (restaurable depuis les
Paramètres) ; le contenu pédagogique (examens, cours, vocabulaire) est conservé.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path

from sqlalchemy import delete, select

from tcfmaster.db.models import (Attempt, ErrorLog, PlanProgress, Profile, ReviewItem,
                                 SpeakingSubmission, StudySession, WritingSubmission)

log = logging.getLogger("tcfmaster.privacy")

SECRET_PATTERNS = [
    re.compile(r"sk-ant-[A-Za-z0-9_\-]{4,}"),
    re.compile(r"\b(?:sk|pk|rk)-[A-Za-z0-9_\-]{16,}"),
    re.compile(r"(?i)\b(api[_-]?key|x-api-key|authorization|password|mot de passe)"
               r"(\s*[=:]\s*)(?:Bearer\s+)?\S+"),
]


def redact(text: str) -> str:
    """Masque tout ce qui ressemble à une clé API ou à un mot de passe."""
    out = str(text)
    for rx in SECRET_PATTERNS:
        out = rx.sub(lambda m: (m.group(1) + m.group(2) + "***") if m.re.groups >= 2
                     else "***clé masquée***", out)
    return out


class SecretFilter(logging.Filter):
    """Filtre de journal : aucune clé ne doit apparaître dans les fichiers de log."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            msg = record.getMessage()
        except Exception:
            return True
        clean = redact(msg)
        if clean != msg:
            record.msg, record.args = clean, None
        if record.exc_info and record.exc_info[1] is not None:
            exc = record.exc_info[1]
            text = str(exc)
            if redact(text) != text:
                record.exc_text = redact(
                    logging.Formatter().formatException(record.exc_info))
        return True


def purge_learning_data(db, recordings_dir: Path | None = None) -> dict[str, int]:
    """Efface résultats, productions, enregistrements, journal d'erreurs, révisions,
    temps d'étude et avancement du programme. Renvoie le nombre d'éléments effacés."""
    backup = db.backup("avant-effacement")
    counts: dict[str, int] = {}
    with db.session() as s:
        for name, model in (("productions écrites", WritingSubmission),
                            ("productions orales", SpeakingSubmission)):
            counts[name] = len(list(s.execute(select(model.id)).scalars()))
        counts["tentatives"] = 0
        for a in s.execute(select(Attempt)).scalars():
            s.delete(a)                    # réponses et productions liées en cascade
            counts["tentatives"] += 1
        s.flush()
        for name, model in (("productions écrites", WritingSubmission),
                            ("productions orales", SpeakingSubmission),
                            ("erreurs", ErrorLog), ("révisions", ReviewItem),
                            ("séances", StudySession), ("programme", PlanProgress)):
            n = s.execute(delete(model)).rowcount or 0
            if name not in counts:
                counts[name] = n
        for p in s.execute(select(Profile)).scalars():
            p.initial_level = None
    n = 0
    if recordings_dir and Path(recordings_dir).is_dir():
        for f in Path(recordings_dir).iterdir():
            if f.is_file():
                f.unlink()
                n += 1
    counts["enregistrements"] = n
    log.info("Données d'apprentissage effacées (sauvegarde préalable : %s)", backup.name)
    return counts
