"""Branchement des services « système » (audio…) sur le contexte applicatif.

Appelé par `__main__` après `bootstrap()`. Chaque service est facultatif :
s'il ne peut pas démarrer (pas de voix, pas de carte son), l'application
reste utilisable et l'écran concerné affiche un message explicite.
"""
from __future__ import annotations

import logging
from collections.abc import Callable

from sqlalchemy import select

from tcfmaster.core.paths import resource_root
from tcfmaster.db.models import SECTION_CO, Question
from tcfmaster.services import settings as S
from tcfmaster.services.audio import AudioGenerator, TTSBackend, default_backend

log = logging.getLogger("tcfmaster.wiring")


def make_generator(ctx, backend: TTSBackend | None = None) -> AudioGenerator:
    with ctx.db.session() as s:
        rate = int(S.get(s, "tts_rate") or 170)
    return AudioGenerator(backend if backend is not None else default_backend(),
                          ctx.paths.audio_cache, rate=rate,
                          resource_dir=resource_root() / "content" / "audio")


def wire(ctx, backend: TTSBackend | None = None) -> None:
    from tcfmaster.services.audio_player import AudioService
    ctx.audio = AudioService(make_generator(ctx, backend))
    log.info("Audio : moteur %s", ctx.audio.generator.backend.name
             if ctx.audio.generator.backend else "indisponible")


def pregenerate_all(ctx, generator: AudioGenerator,
                    progress: Callable[[int, int], bool] | None = None) -> tuple[int, list[str]]:
    """Prépare l'audio de toutes les questions CO (pour un usage 100 % hors ligne).

    `progress(fait, total)` peut renvoyer False pour interrompre.
    Renvoie (nombre de fichiers prêts, erreurs)."""
    with ctx.db.session() as s:
        items = [(q.id, q.document, q.speakers, q.audio_file)
                 for q in s.execute(select(Question).where(Question.section == SECTION_CO)
                                    .order_by(Question.id)).scalars()]
    ready, errors = 0, []
    for i, (qid, doc, speakers, audio_file) in enumerate(items):
        if progress and progress(i, len(items)) is False:
            break
        try:
            generator.ensure(doc, speakers, audio_file)
            ready += 1
        except Exception as exc:
            errors.append(f"question {qid} : {exc}")
            if "Aucun" in str(exc):     # pas de moteur / pas de voix : inutile d'insister
                break
    if progress:
        progress(len(items), len(items))
    return ready, errors
