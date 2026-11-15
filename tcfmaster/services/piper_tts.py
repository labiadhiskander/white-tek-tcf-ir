"""Voix neuronales hors ligne avec Piper (facultatif, gratuit).

Piper (https://github.com/rhasspy/piper, licence MIT) est un programme de
synthèse vocale qui fonctionne entièrement sur le PC, sans connexion ni clé
API. Il produit des voix bien plus naturelles que les voix SAPI de Windows.

Rien n'est fourni avec l'application : sur demande de l'utilisateur
(Paramètres > Voix et audio), le programme Piper et une ou plusieurs voix
françaises sont téléchargés une seule fois dans le dossier de données :

    <données>/piper/      programme piper(.exe) et ses bibliothèques
    <données>/voix/       modèles  <nom>.onnx  +  <nom>.onnx.json

Chaque voix est publiée avec sa propre fiche (MODEL_CARD) qui précise le
jeu de données et la licence : elle est affichée avant le téléchargement.
Les fichiers audio générés restent sur le PC (cache) et ne sont jamais
redistribués.

Si Piper est absent ou échoue, la synthèse retombe automatiquement sur les
voix du système (SAPI) : voir `ChainBackend`.
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from tcfmaster.services.audio import TTSBackend, TTSUnavailable, VoiceInfo, choose_voice

log = logging.getLogger("tcfmaster.audio")

PIPER_RELEASE = "2023.11.14-2"
PIPER_DOWNLOADS = {
    "win32": f"https://github.com/rhasspy/piper/releases/download/{PIPER_RELEASE}/"
             "piper_windows_amd64.zip",
    "linux": f"https://github.com/rhasspy/piper/releases/download/{PIPER_RELEASE}/"
             "piper_linux_x86_64.tar.gz",
}
VOICES_BASE = "https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/fr/fr_FR"
REFERENCE_RATE = 170          # débit (mots/min) correspondant à length_scale = 1


@dataclass(frozen=True)
class CatalogVoice:
    key: str                  # ex. "fr_FR-siwis-medium"
    label: str
    gender: str | None        # genre de la voix (None : plusieurs locuteurs)
    size_mb: int

    @property
    def folder(self) -> str:
        _lang, name, quality = self.key.split("-")
        return f"{VOICES_BASE}/{name}/{quality}"

    @property
    def model_url(self) -> str:
        return f"{self.folder}/{self.key}.onnx"

    @property
    def config_url(self) -> str:
        return f"{self.folder}/{self.key}.onnx.json"

    @property
    def card_url(self) -> str:
        return f"{self.folder}/MODEL_CARD"


# Voix françaises officielles de Piper (liste VOICES.md du projet).
CATALOG: list[CatalogVoice] = [
    CatalogVoice("fr_FR-siwis-medium", "Siwis – voix féminine (France)", "F", 63),
    CatalogVoice("fr_FR-tom-medium", "Tom – voix masculine (France)", "H", 63),
    CatalogVoice("fr_FR-upmc-medium", "UPMC – voix féminine et masculine (France)", None, 77),
    CatalogVoice("fr_FR-gilles-low", "Gilles – voix masculine (France, qualité réduite)", "H", 63),
    CatalogVoice("fr_FR-mls-medium", "MLS – nombreux locuteurs (France)", None, 77),
]
CATALOG_BY_KEY = {v.key: v for v in CATALOG}

# Genre des locuteurs des voix multi-locuteurs, quand il est connu.
SPEAKER_GENDER = {"jessica": "F", "pierre": "H"}


# ------------------------------------------------------------- détection
def exe_name() -> str:
    return "piper.exe" if sys.platform == "win32" else "piper"


def find_piper(dirs: list[Path | None]) -> Path | None:
    """Cherche le programme Piper dans les dossiers donnés puis dans le PATH."""
    for d in dirs:
        if not d:
            continue
        for cand in (Path(d) / exe_name(), Path(d) / "piper" / exe_name()):
            if cand.is_file():
                return cand
    found = shutil.which("piper")
    return Path(found) if found else None


def _voice_gender(stem: str, speaker: str | None) -> str | None:
    if speaker and speaker.lower() in SPEAKER_GENDER:
        return SPEAKER_GENDER[speaker.lower()]
    entry = CATALOG_BY_KEY.get(stem)
    return entry.gender if entry else None


def installed_voices(voices_dir: Path | None) -> list[VoiceInfo]:
    """Voix Piper présentes : un VoiceInfo par modèle (et par locuteur connu).

    L'identifiant est « chemin_du_modèle#numéro_de_locuteur »."""
    out: list[VoiceInfo] = []
    if not voices_dir or not Path(voices_dir).is_dir():
        return out
    for model in sorted(Path(voices_dir).glob("*.onnx")):
        cfg = model.with_name(model.name + ".json")
        if not cfg.is_file():
            continue
        try:
            data = json.loads(cfg.read_text(encoding="utf-8"))
        except ValueError:
            log.warning("Configuration Piper illisible : %s", cfg.name)
            continue
        code = str((data.get("language") or {}).get("code") or model.stem.split("-")[0])
        locale = code.replace("_", "-")
        stem = model.stem
        speakers = data.get("speaker_id_map") or {}
        known = {n: i for n, i in speakers.items() if n.lower() in SPEAKER_GENDER}
        if known:
            for name, sid in sorted(known.items(), key=lambda kv: kv[1]):
                out.append(VoiceInfo(f"{model}#{sid}", f"Piper {stem} ({name})", locale,
                                     _voice_gender(stem, name)))
        else:
            out.append(VoiceInfo(f"{model}#", f"Piper {stem}", locale, _voice_gender(stem, None)))
    return out


# ---------------------------------------------------------------- moteur
class PiperBackend:
    """Synthèse par le programme Piper (processus séparé, hors ligne)."""
    name = "piper"

    def __init__(self, exe: Path, voices_dir: Path, timeout_s: int = 120):
        self.exe = Path(exe)
        self.voices_dir = Path(voices_dir)
        self.timeout_s = timeout_s
        if not self.exe.is_file():
            raise TTSUnavailable("Le programme Piper est introuvable.")

    def voices(self) -> list[VoiceInfo]:
        return installed_voices(self.voices_dir)

    @staticmethod
    def length_scale(rate: int) -> float:
        """Débit en mots/min → facteur de durée de Piper (plus grand = plus lent)."""
        return round(min(2.0, max(0.5, REFERENCE_RATE / max(1, int(rate)))), 3)

    def command(self, voice: VoiceInfo, rate: int, out: Path) -> list[str]:
        model, _, speaker = voice.id.partition("#")
        cmd = [str(self.exe), "--model", model, "--output_file", str(out),
               "--length_scale", str(self.length_scale(rate)), "--sentence_silence", "0.25"]
        if speaker:
            cmd += ["--speaker", speaker]
        return cmd

    def synthesize(self, text: str, voice: VoiceInfo, rate: int, out: Path) -> None:
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        try:
            proc = subprocess.run(self.command(voice, rate, out), input=text.encode("utf-8"),
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                  timeout=self.timeout_s, cwd=str(self.exe.parent),
                                  creationflags=flags)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise TTSUnavailable(f"Piper n'a pas pu démarrer ({exc}).") from exc
        if proc.returncode != 0 or not out.exists() or out.stat().st_size < 64:
            err = proc.stderr.decode("utf-8", "ignore").strip().splitlines()[-1:] or [""]
            raise TTSUnavailable(f"Piper n'a produit aucun son. {err[0]}".strip())


class ChainBackend:
    """Piper d'abord ; en cas d'échec, voix du système pour la même réplique."""

    def __init__(self, primary: TTSBackend, fallback: TTSBackend | None):
        self.primary, self.fallback = primary, fallback
        self.name = primary.name if fallback is None else f"{primary.name}+{fallback.name}"
        self.failures = 0

    def voices(self) -> list[VoiceInfo]:
        voices = [v for v in self.primary.voices() if v.is_french]
        if voices or self.fallback is None:
            return voices
        return self.fallback.voices()

    def synthesize(self, text: str, voice: VoiceInfo, rate: int, out: Path) -> None:
        if voice in self.primary.voices():
            try:
                self.primary.synthesize(text, voice, rate, out)
                return
            except TTSUnavailable as exc:
                self.failures += 1
                if self.fallback is None:
                    raise
                log.warning("Piper indisponible, repli sur les voix du système : %s", exc)
        if self.fallback is None:
            raise TTSUnavailable("Aucune voix de secours n'est disponible.")
        alt = choose_voice(self.fallback.voices(), voice.gender or "F", voice.locale)
        if alt is None:
            raise TTSUnavailable("Aucune voix française du système pour le repli.")
        self.fallback.synthesize(text, alt, rate, out)


ENGINES = {"auto": "Automatique (Piper si installé, sinon voix Windows)",
           "piper": "Piper uniquement (voix neuronales)",
           "systeme": "Voix du système (Windows SAPI)"}


def build_backend(engine: str, piper_dirs: list[Path | None], voices_dir: Path,
                  system: TTSBackend | None) -> TTSBackend | None:
    """Choisit le moteur selon le paramètre « tts_engine »."""
    if engine == "systeme":
        return system
    exe = find_piper(piper_dirs)
    if exe and any(v.is_french for v in installed_voices(voices_dir)):
        return ChainBackend(PiperBackend(exe, voices_dir), system)
    if engine == "piper":
        log.warning("Piper demandé mais absent ou sans voix française : voix du système.")
    return system


# --------------------------------------------------------- téléchargement
Progress = Callable[[int, int], bool | None]


def _download(url: str, dest: Path, progress: Progress | None = None,
              timeout: int = 60) -> Path:
    """Télécharge `url` vers `dest` (fichier .part puis renommage atomique)."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".part")
    req = urllib.request.Request(url, headers={"User-Agent": "tcfmaster"})
    with urllib.request.urlopen(req, timeout=timeout) as resp, open(tmp, "wb") as fh:
        total = int(resp.headers.get("Content-Length") or 0)
        done = 0
        while True:
            chunk = resp.read(256 * 1024)
            if not chunk:
                break
            fh.write(chunk)
            done += len(chunk)
            if progress and progress(done, total) is False:
                fh.close()
                tmp.unlink(missing_ok=True)
                raise InterruptedError("Téléchargement interrompu.")
    tmp.replace(dest)
    return dest


def download_voice(key: str, voices_dir: Path, progress: Progress | None = None) -> Path:
    entry = CATALOG_BY_KEY[key]
    voices_dir = Path(voices_dir)
    _download(entry.config_url, voices_dir / f"{key}.onnx.json")
    return _download(entry.model_url, voices_dir / f"{key}.onnx", progress)


def _safe_extract_zip(archive: Path, dest: Path) -> None:
    root = dest.resolve()
    with zipfile.ZipFile(archive) as zf:
        for m in zf.infolist():
            target = (dest / m.filename).resolve()
            if root not in target.parents and target != root:
                raise ValueError(f"Chemin suspect dans l'archive : {m.filename}")
        zf.extractall(dest)


def install_piper(dest: Path, progress: Progress | None = None) -> Path:
    """Télécharge et décompresse le programme Piper (Windows : archive zip)."""
    url = PIPER_DOWNLOADS.get("win32" if sys.platform == "win32" else "linux")
    dest = Path(dest)
    with tempfile.TemporaryDirectory() as td:
        archive = Path(td) / url.rsplit("/", 1)[-1]
        _download(url, archive, progress)
        if archive.suffix == ".zip":
            _safe_extract_zip(archive, dest.parent if dest.name == "piper" else dest)
        else:
            import tarfile
            with tarfile.open(archive) as tf:
                tf.extractall(dest.parent if dest.name == "piper" else dest, filter="data")
    exe = find_piper([dest, dest.parent])
    if exe is None:
        raise TTSUnavailable("Archive Piper téléchargée, mais programme introuvable.")
    if os.name != "nt":
        exe.chmod(exe.stat().st_mode | 0o111)
    return exe


def remove_voice(key: str, voices_dir: Path) -> None:
    for suffix in (".onnx", ".onnx.json"):
        (Path(voices_dir) / f"{key}{suffix}").unlink(missing_ok=True)
