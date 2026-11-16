"""Vidéothèque B2 : consultation, vérification des liens, administration.

Les vidéos ne sont jamais téléchargées ni redistribuées : l'application ouvre
le lien officiel dans le navigateur. Les liens sont testés depuis le PC de
l'utilisateur ; un lien en erreur est masqué de la vidéothèque (il reste
visible et modifiable dans l'administration).
"""
from __future__ import annotations

import urllib.error
import urllib.request
from collections.abc import Callable
from datetime import datetime

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from tcfmaster import APP_NAME, __version__
from tcfmaster.content import validator as V
from tcfmaster.db.models import ORIGIN_ADMIN, STATUS_DRAFT, STATUS_VALID, Video

CATEGORIES = V.VIDEO_CATEGORIES
LINK_OK, LINK_ERROR = "ok", "erreur"
TIMEOUT_S = 10


def list_videos(s: Session, category: str | None = None, include_hidden: bool = False,
                search: str = "") -> list[Video]:
    q = select(Video)
    if category:
        q = q.where(Video.category == category)
    if not include_hidden:
        q = q.where(Video.status == STATUS_VALID,
                    or_(Video.link_status.is_(None), Video.link_status != LINK_ERROR))
    order = {c: i for i, c in enumerate(CATEGORIES)}
    vids = list(s.execute(q).scalars())
    vids.sort(key=lambda v: (order.get(v.category, 99), v.code))
    if search:
        needle = search.lower().strip()
        vids = [v for v in vids if needle in f"{v.title} {v.description} {v.source}".lower()]
    return vids


def link_label(v: Video) -> str:
    if v.link_status == LINK_OK:
        return f"Lien vérifié le {v.link_checked_at:%d/%m/%Y}" if v.link_checked_at else "Lien vérifié"
    if v.link_status == LINK_ERROR:
        return "Lien en erreur (masqué)"
    return "Lien non encore vérifié"


# ------------------------------------------------------------ vérification
def check_url(url: str, timeout: float = TIMEOUT_S) -> tuple[bool, str]:
    """Teste un lien (HEAD puis GET si le serveur refuse HEAD)."""
    headers = {"User-Agent": f"{APP_NAME}/{__version__} (verification de lien)"}
    for method in ("HEAD", "GET"):
        req = urllib.request.Request(url, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310 (https imposé)
                code = getattr(r, "status", 200)
                if code < 400:
                    return True, f"HTTP {code}"
        except urllib.error.HTTPError as exc:
            if method == "HEAD" and exc.code in (403, 405, 501):
                continue          # certains sites refusent HEAD : on réessaie en GET
            return False, f"HTTP {exc.code}"
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            return False, f"inaccessible ({getattr(exc, 'reason', exc)})"
    return False, "réponse inattendue"


def check_links(s: Session, fetch: Callable[[str], tuple[bool, str]] = check_url,
                only: list[int] | None = None) -> dict[str, int]:
    """Vérifie les liens ; met à jour l'état (ok / erreur) et la date."""
    q = select(Video)
    if only:
        q = q.where(Video.id.in_(only))
    cache: dict[str, tuple[bool, str]] = {}
    res = {"ok": 0, "erreur": 0}
    for v in s.execute(q).scalars():
        if v.url not in cache:
            cache[v.url] = fetch(v.url)
        ok, _ = cache[v.url]
        v.link_status = LINK_OK if ok else LINK_ERROR
        v.link_checked_at = datetime.now()
        res["ok" if ok else "erreur"] += 1
    s.flush()
    return res


def check_answer(v: Video, index: int, choice: int) -> tuple[bool, str]:
    """Correction immédiate de l'exercice associé à une fiche."""
    q = v.exercise[index]
    if choice == q["answer"]:
        return True, f"Bonne réponse. {q['explanation']}"
    why = (q.get("rationales") or [""] * len(q["choices"]))[choice]
    return False, (f"Réponse incorrecte : {why}\n"
                   f"La bonne réponse est « {q['choices'][q['answer']]} ». {q['explanation']}")


# --------------------------------------------------------- administration
def save_video(s: Session, data: dict, video_id: int | None = None) -> tuple[Video | None, list[str]]:
    """Crée ou modifie une fiche ; elle ne sera plus écrasée par une mise à jour."""
    v = s.get(Video, video_id) if video_id else None
    code = data.get("code") or (v.code if v else _next_code(s))
    full = {"code": code, "exercise": data.get("exercise", v.exercise if v else []), **data}
    full["code"] = code
    errs = V.validate_video(full, admin=True)
    dup = s.execute(select(Video).where(Video.code == code)).scalar_one_or_none()
    if dup is not None and dup is not v:
        errs.append(f"{code}: code déjà utilisé")
    if errs:
        return None, errs
    if v is None:
        v = Video(code=code, origin=ORIGIN_ADMIN)
        s.add(v)
    if v.url and v.url != full["url"]:
        v.link_status, v.link_checked_at = None, None
    for k in ("title", "description", "category", "source", "url", "duration", "exercise"):
        if k in full:
            setattr(v, k, full[k])
    v.level = "B2"
    v.status = full.get("status", v.status or STATUS_DRAFT)
    v.locally_modified = True
    s.flush()
    return v, []


def set_status(s: Session, video_id: int, valid: bool) -> None:
    v = s.get(Video, video_id)
    v.status = STATUS_VALID if valid else STATUS_DRAFT
    v.locally_modified = True


def delete_video(s: Session, video_id: int) -> None:
    v = s.get(Video, video_id)
    if v is not None:
        s.delete(v)


def _next_code(s: Session) -> str:
    n = len(list(s.execute(select(Video.id).where(Video.origin == ORIGIN_ADMIN)).scalars())) + 1
    while s.execute(select(Video).where(Video.code == f"VID-PERSO-{n:03d}")).scalar_one_or_none():
        n += 1
    return f"VID-PERSO-{n:03d}"
