"""Gestion des répertoires de l'application.

Le répertoire de données (base SQLite, enregistrements, sauvegardes, journaux)
est choisi par l'utilisateur. Son emplacement est mémorisé dans un petit
fichier « bootstrap » placé dans le dossier de configuration standard de
l'utilisateur (%APPDATA% sous Windows).
"""
from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path

from tcfmaster import APP_SLUG


def _config_root() -> Path:
    override = os.environ.get("TCFMASTER_CONFIG_DIR")
    if override:
        return Path(override)
    if sys.platform.startswith("win"):
        base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
        return Path(base) / APP_SLUG
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / APP_SLUG


def _default_data_root() -> Path:
    if sys.platform.startswith("win"):
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(base) / APP_SLUG / "data"
    base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(base) / APP_SLUG


def resource_root() -> Path:
    """Dossier des ressources embarquées (fonctionne aussi après PyInstaller)."""
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS) / "tcfmaster"  # type: ignore[attr-defined]
    return Path(__file__).resolve().parent.parent


BOOTSTRAP_FILE = "bootstrap.json"


@dataclass(frozen=True)
class AppPaths:
    data_root: Path

    @property
    def database(self) -> Path:
        return self.data_root / "tcfmaster.sqlite3"

    @property
    def recordings(self) -> Path:
        return self.data_root / "enregistrements"

    @property
    def audio_cache(self) -> Path:
        return self.data_root / "audio"

    @property
    def backups(self) -> Path:
        return self.data_root / "sauvegardes"

    @property
    def logs(self) -> Path:
        return self.data_root / "journaux"

    @property
    def exports(self) -> Path:
        return self.data_root / "exports"

    def ensure(self) -> "AppPaths":
        for p in (self.data_root, self.recordings, self.audio_cache, self.backups,
                  self.logs, self.exports):
            p.mkdir(parents=True, exist_ok=True)
        return self


def load_data_root() -> Path:
    override = os.environ.get("TCFMASTER_DATA_DIR")
    if override:
        return Path(override)
    f = _config_root() / BOOTSTRAP_FILE
    if f.exists():
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            if data.get("data_root"):
                return Path(data["data_root"])
        except (OSError, ValueError):
            pass
    return _default_data_root()


def save_data_root(path: Path) -> None:
    root = _config_root()
    root.mkdir(parents=True, exist_ok=True)
    (root / BOOTSTRAP_FILE).write_text(
        json.dumps({"data_root": str(Path(path).resolve())}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def get_paths() -> AppPaths:
    return AppPaths(load_data_root()).ensure()
