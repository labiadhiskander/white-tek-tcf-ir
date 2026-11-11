"""Point d'assemblage : chemins, journalisation, base de données, contenu."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from sqlalchemy import func, select

from tcfmaster import __version__
from tcfmaster.content.seeder import seed_all
from tcfmaster.core.logging_setup import setup_logging
from tcfmaster.core.paths import AppPaths, get_paths
from tcfmaster.db.database import Database
from tcfmaster.db.models import Profile, SchemaInfo


@dataclass
class AppContext:
    paths: AppPaths
    db: Database
    log: logging.Logger
    audio: Any = None        # AudioService, branché par services.wiring
    recorder: Any = None     # Recorder (micro)
    stt: Any = None          # moteur de reconnaissance vocale
    tutor: Any = None        # TutorService (tuteur IA), branché par services.wiring


def bootstrap(paths: AppPaths | None = None, seed: bool = True) -> AppContext:
    paths = (paths or get_paths()).ensure()
    log = setup_logging(paths.logs)
    log.info("Démarrage version %s – données : %s", __version__, paths.data_root)
    db = Database(paths.database, paths.backups).open()
    with db.session() as s:
        if s.execute(select(func.count(Profile.id))).scalar_one() == 0:
            s.add(Profile())
        if seed:
            row = s.get(SchemaInfo, "content_version")
            if row is None or row.value != __version__:
                rep = seed_all(s)
                log.info("Contenu importé : %s", rep)
                if row is None:
                    s.add(SchemaInfo(key="content_version", value=__version__))
                else:
                    row.value = __version__
    return AppContext(paths=paths, db=db, log=log)
