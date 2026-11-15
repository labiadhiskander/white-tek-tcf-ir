"""Paramètres de l'application (stockés en base) et clés API (coffre sécurisé).

Les clés API ne sont JAMAIS écrites dans la base ni dans le code source :
elles sont confiées au gestionnaire d'identifiants du système
(Gestionnaire d'identification Windows via la bibliothèque « keyring »).
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any

from sqlalchemy.orm import Session

from tcfmaster import APP_SLUG
from tcfmaster.db.models import Setting

log = logging.getLogger("tcfmaster.settings")

DEFAULTS: dict[str, Any] = {
    "correction_mode": "fin",          # « immediate » ou « fin » d'exercice
    "ai_provider": "local",            # local (hors ligne) | anthropic (Claude, en ligne)
    "ai_model": "claude-opus-5-5",
    "ai_effort": "medium",             # low | medium | high
    "ai_consent": False,               # avertissement de confidentialité accepté
    "tts_engine": "auto",              # auto (Piper si installé) | piper | systeme (SAPI)
    "tts_rate": 170,
    "stt_engine": "local",             # moteur de reconnaissance vocale
    "stt_model_path": "",              # dossier d'un modèle Vosk personnalisé
    "keep_recordings": True,
    "auto_backup": True,
    "backup_interval_min": 30,
    "co_replay_in_training": True,
    "theme": "clair",
    "check_updates": True,
    "update_url": "",
}


def get(s: Session, key: str, default: Any = None) -> Any:
    row = s.get(Setting, key)
    if row is None or row.value is None:
        return DEFAULTS.get(key, default)
    try:
        return json.loads(row.value)
    except ValueError:
        return row.value


_SECRET_KEY = re.compile(r"(api_?key|secret|token|password|mot_de_passe)", re.I)


def set_(s: Session, key: str, value: Any) -> None:
    if _SECRET_KEY.search(key):
        raise ValueError("Les secrets ne sont jamais stockés en base : utilisez "
                         "store_api_key() (coffre d'identifiants du système).")
    row = s.get(Setting, key)
    payload = json.dumps(value, ensure_ascii=False)
    if row is None:
        s.add(Setting(key=key, value=payload))
    else:
        row.value = payload


def all_settings(s: Session) -> dict[str, Any]:
    out = dict(DEFAULTS)
    for row in s.query(Setting).all():
        try:
            out[row.key] = json.loads(row.value) if row.value is not None else None
        except ValueError:
            out[row.key] = row.value
    return out


# ------------------------------------------------------------ clés API
_SERVICE = f"{APP_SLUG}-api"


def _keyring():
    try:
        import keyring  # type: ignore
        return keyring
    except Exception:  # pragma: no cover - dépend de l'OS
        return None


def store_api_key(provider: str, secret: str) -> bool:
    kr = _keyring()
    if kr is None:
        log.error("Coffre d'identifiants indisponible : clé non enregistrée.")
        return False
    kr.set_password(_SERVICE, provider, secret)
    return True


def load_api_key(provider: str) -> str | None:
    kr = _keyring()
    if kr is None:
        return None
    try:
        return kr.get_password(_SERVICE, provider)
    except Exception:  # pragma: no cover
        return None


def delete_api_key(provider: str) -> None:
    kr = _keyring()
    if kr is None:
        return
    try:
        kr.delete_password(_SERVICE, provider)
    except Exception:  # pragma: no cover
        pass
