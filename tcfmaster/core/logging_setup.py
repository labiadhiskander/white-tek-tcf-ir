"""Journalisation technique (fichiers tournants dans le dossier « journaux »)."""
from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

_CONFIGURED = False


def setup_logging(log_dir: Path, level: int = logging.INFO) -> logging.Logger:
    global _CONFIGURED
    logger = logging.getLogger("tcfmaster")
    if _CONFIGURED:
        return logger
    log_dir.mkdir(parents=True, exist_ok=True)
    from tcfmaster.services.privacy import SecretFilter
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    secret_filter = SecretFilter()          # aucune clé API dans les journaux
    fh = RotatingFileHandler(log_dir / "tcfmaster.log", maxBytes=1_000_000,
                             backupCount=5, encoding="utf-8")
    fh.setFormatter(fmt)
    fh.addFilter(secret_filter)
    logger.addHandler(fh)
    if sys.stderr is not None:
        sh = logging.StreamHandler()
        sh.setFormatter(fmt)
        sh.addFilter(secret_filter)
        logger.addHandler(sh)
    logger.setLevel(level)

    def _excepthook(exc_type, exc, tb):
        logger.critical("Exception non gérée", exc_info=(exc_type, exc, tb))
        sys.__excepthook__(exc_type, exc, tb)

    sys.excepthook = _excepthook
    _CONFIGURED = True
    return logger
