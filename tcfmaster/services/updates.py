"""Vérification des mises à jour (dernière version publiée sur GitHub).

Aucune donnée personnelle n'est envoyée : une simple requête anonyme vers la
page « releases » du dépôt. La mise à jour s'installe par-dessus l'ancienne
version ; les données de l'utilisateur (dans %APPDATA%) sont conservées et le
contenu pédagogique est mis à jour au démarrage sans perdre l'historique.
"""
from __future__ import annotations

import json
import logging
import re
import urllib.request
from dataclasses import dataclass

from tcfmaster import GITHUB_REPO, __version__

log = logging.getLogger("tcfmaster.updates")

DEFAULT_URL = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
TIMEOUT_S = 8


@dataclass
class UpdateInfo:
    available: bool
    current: str
    latest: str | None = None
    url: str | None = None           # page de téléchargement
    notes: str = ""
    error: str | None = None


def parse_version(v: str) -> tuple[int, ...]:
    nums = re.findall(r"\d+", (v or "").split("-")[0].split("+")[0])
    return tuple(int(n) for n in nums[:3]) + (0,) * (3 - len(nums[:3]))


def is_newer(latest: str, current: str = __version__) -> bool:
    return parse_version(latest) > parse_version(current)


def _fetch(url: str) -> dict:
    req = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json",
                                               "User-Agent": "WhiteTekTCF-updater"})
    with urllib.request.urlopen(req, timeout=TIMEOUT_S) as r:     # noqa: S310 (https fixe)
        return json.loads(r.read().decode("utf-8"))


def check(url: str | None = None, fetch=None, current: str = __version__) -> UpdateInfo:
    """Compare la version installée à la dernière version publiée."""
    url = url or DEFAULT_URL
    if not url.startswith("https://"):
        return UpdateInfo(False, current, error="Adresse de mise à jour non sécurisée.")
    try:
        data = (fetch or _fetch)(url)
    except Exception as exc:
        log.info("Vérification des mises à jour impossible : %s", exc)
        return UpdateInfo(False, current, error="Impossible de joindre le serveur de mises à "
                                                "jour (hors ligne ?).")
    tag = str(data.get("tag_name") or data.get("version") or "")
    if not tag:
        return UpdateInfo(False, current, error="Réponse du serveur inattendue.")
    page = data.get("html_url")
    for asset in data.get("assets") or []:
        if str(asset.get("name", "")).lower().endswith(".exe"):
            page = asset.get("browser_download_url") or page
            break
    return UpdateInfo(is_newer(tag, current), current, tag.lstrip("vV"), page,
                      str(data.get("body") or "")[:2000])
