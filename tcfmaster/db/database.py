"""Moteur SQLite : création, protection contre la corruption, sauvegarde, restauration.

Mesures de protection :
  * Journal WAL + synchronous=FULL : une coupure de courant ne corrompt pas la base.
  * Clés étrangères activées.
  * Contrôle d'intégrité (PRAGMA integrity_check) au démarrage ; en cas d'échec,
    restauration automatique de la dernière sauvegarde saine.
  * Sauvegardes à chaud via l'API « backup » de SQLite (cohérentes même si
    l'application est ouverte), avec rotation.
"""
from __future__ import annotations

import logging
import shutil
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Iterator

from sqlalchemy import create_engine, event, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from tcfmaster import __version__
from tcfmaster.db.models import Base, SchemaInfo

log = logging.getLogger("tcfmaster.db")

SCHEMA_VERSION = "2"   # 2 = v1.1 (collections B2, vidéothèque, programme 30 jours)
MAX_BACKUPS = 15


class DatabaseCorrupted(RuntimeError):
    pass


def _set_pragmas(dbapi_conn, _record):
    cur = dbapi_conn.cursor()
    cur.execute("PRAGMA foreign_keys=ON")
    cur.execute("PRAGMA journal_mode=WAL")
    cur.execute("PRAGMA synchronous=FULL")
    cur.close()


def integrity_ok(db_path: Path) -> bool:
    if not db_path.exists():
        return True
    try:
        con = sqlite3.connect(str(db_path))
        try:
            row = con.execute("PRAGMA integrity_check").fetchone()
            return bool(row) and row[0] == "ok"
        finally:
            con.close()
    except sqlite3.DatabaseError:
        return False


def stored_schema_version(db_path: Path) -> str | None:
    """Version du schéma enregistrée dans une base existante (None si base neuve)."""
    if not db_path.exists():
        return None
    con = sqlite3.connect(str(db_path))
    try:
        row = con.execute("SELECT value FROM schema_info WHERE key='schema_version'"
                          ).fetchone()
        return row[0] if row else None
    except sqlite3.DatabaseError:
        return None
    finally:
        con.close()


def _sql_default(col) -> str | None:
    d = col.default
    if d is None or not getattr(d, "is_scalar", False):
        return None
    v = d.arg
    if isinstance(v, bool):
        return "1" if v else "0"
    if isinstance(v, (int, float)):
        return str(v)
    if isinstance(v, str):
        return "'" + v.replace("'", "''") + "'"
    return None


def add_missing_columns(engine: Engine) -> list[str]:
    """Migration additive : ajoute les colonnes du modèle absentes de la base.

    Aucune colonne n'est supprimée ni modifiée, aucune ligne n'est touchée : une
    base v1.0 garde toutes ses données. Les nouvelles colonnes sont facultatives
    ou ont une valeur par défaut.
    """
    added: list[str] = []
    with engine.begin() as con:
        for table in Base.metadata.sorted_tables:
            rows = con.exec_driver_sql(f'PRAGMA table_info("{table.name}")').fetchall()
            existing = {r[1] for r in rows}
            if not existing:
                continue
            for col in table.columns:
                if col.name in existing:
                    continue
                ddl = f'ALTER TABLE "{table.name}" ADD COLUMN "{col.name}" ' \
                      f'{col.type.compile(engine.dialect)}'
                default = _sql_default(col)
                if default is not None:
                    ddl += f" DEFAULT {default}"
                    if not col.nullable:
                        ddl += " NOT NULL"
                con.exec_driver_sql(ddl)
                added.append(f"{table.name}.{col.name}")
    return added


class Database:
    def __init__(self, db_path: Path, backup_dir: Path | None = None):
        self.path = Path(db_path)
        self.backup_dir = Path(backup_dir) if backup_dir else self.path.parent / "sauvegardes"
        self.engine: Engine | None = None
        self._factory: sessionmaker[Session] | None = None

    # ------------------------------------------------------------------ init
    def open(self) -> "Database":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not integrity_ok(self.path):
            log.error("Base corrompue détectée : %s", self.path)
            if not self.restore_latest_backup():
                raise DatabaseCorrupted(
                    "La base de données est corrompue et aucune sauvegarde saine n'a été trouvée.")
        previous = stored_schema_version(self.path)
        if previous is not None and previous != SCHEMA_VERSION:
            # Sauvegarde complète avant toute migration : rien ne doit être perdu.
            self.backup(f"avant-migration-v{previous}")
        self.engine = create_engine(f"sqlite:///{self.path}", future=True)
        event.listen(self.engine, "connect", _set_pragmas)
        Base.metadata.create_all(self.engine)
        added = add_missing_columns(self.engine)
        if added:
            log.info("Migration du schéma : colonnes ajoutées %s", added)
        self._factory = sessionmaker(self.engine, expire_on_commit=False)
        with self.session() as s:
            row = s.get(SchemaInfo, "schema_version")
            if row is None:
                s.add(SchemaInfo(key="schema_version", value=SCHEMA_VERSION))
                s.add(SchemaInfo(key="created_with", value=__version__))
            elif row.value != SCHEMA_VERSION:
                log.info("Schéma migré de v%s à v%s", row.value, SCHEMA_VERSION)
                s.add(SchemaInfo(key=f"migrated_from_v{row.value}", value=__version__))
                row.value = SCHEMA_VERSION
        return self

    def close(self) -> None:
        if self.engine is not None:
            self.engine.dispose()
            self.engine = None

    @contextmanager
    def session(self) -> Iterator[Session]:
        if self._factory is None:
            raise RuntimeError("Base non ouverte")
        s = self._factory()
        try:
            yield s
            s.commit()
        except Exception:
            s.rollback()
            raise
        finally:
            s.close()

    def new_session(self) -> Session:
        if self._factory is None:
            raise RuntimeError("Base non ouverte")
        return self._factory()

    # ---------------------------------------------------------------- backup
    def backup(self, label: str = "auto") -> Path:
        """Sauvegarde à chaud cohérente ; renvoie le chemin du fichier créé."""
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        dest = self.backup_dir / f"tcfmaster-{label}-{stamp}.sqlite3"
        src = sqlite3.connect(str(self.path))
        dst = sqlite3.connect(str(dest))
        try:
            src.backup(dst)
        finally:
            dst.close()
            src.close()
        log.info("Sauvegarde créée : %s", dest)
        self._rotate()
        return dest

    def _rotate(self) -> None:
        autos = sorted(self.backup_dir.glob("tcfmaster-auto-*.sqlite3"))
        for old in autos[:-MAX_BACKUPS]:
            try:
                old.unlink()
            except OSError:
                pass

    def list_backups(self) -> list[Path]:
        if not self.backup_dir.exists():
            return []
        return sorted(self.backup_dir.glob("tcfmaster-*.sqlite3"),
                      key=lambda p: p.stat().st_mtime, reverse=True)

    def restore(self, backup_file: Path) -> None:
        backup_file = Path(backup_file)
        if not integrity_ok(backup_file):
            raise DatabaseCorrupted(f"Sauvegarde invalide : {backup_file}")
        was_open = self.engine is not None
        self.close()
        if self.path.exists():
            # On garde une copie de sécurité de l'état avant restauration.
            shutil.copy2(self.path, self.path.with_suffix(".avant-restauration.sqlite3"))
        for suffix in ("-wal", "-shm"):
            p = Path(str(self.path) + suffix)
            if p.exists():
                p.unlink()
        shutil.copy2(backup_file, self.path)
        log.info("Base restaurée depuis %s", backup_file)
        if was_open:
            self.open()

    def restore_latest_backup(self) -> bool:
        for b in self.list_backups():
            if integrity_ok(b):
                if self.path.exists():
                    corrupt = self.path.with_suffix(
                        f".corrompue-{datetime.now():%Y%m%d%H%M%S}.sqlite3")
                    shutil.move(str(self.path), corrupt)
                for suffix in ("-wal", "-shm"):
                    p = Path(str(self.path) + suffix)
                    if p.exists():
                        p.unlink()
                shutil.copy2(b, self.path)
                log.warning("Restauration automatique depuis %s", b)
                return True
        return False

    def schema_version(self) -> str | None:
        with self.session() as s:
            row = s.execute(select(SchemaInfo).where(SchemaInfo.key == "schema_version")
                            ).scalar_one_or_none()
            return row.value if row else None
