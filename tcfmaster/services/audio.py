"""Audio des documents de compréhension orale : synthèse vocale hors ligne.

Principe :
  1. un document CO (« H: … / F: … ») est découpé en répliques ;
  2. chaque réplique est synthétisée avec une voix française adaptée
     (genre et, si possible, accent : France, Canada, Belgique, Suisse) ;
  3. les répliques sont assemblées en un seul fichier WAV, mis en cache
     dans le dossier de données : la génération n'a lieu qu'une fois et
     tout fonctionne ensuite sans connexion.

Un fichier audio enregistré (`Question.audio_file`) est toujours prioritaire
sur la synthèse. La partie « moteur » (pyttsx3 → SAPI sous Windows) est
isolée derrière `TTSBackend` pour pouvoir être remplacée et testée.
"""
from __future__ import annotations

import hashlib
import logging
import re
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

log = logging.getLogger("tcfmaster.audio")

PAUSE_S = 0.45            # silence entre deux répliques
TARGET_RATE = 22050       # format commun en cas de formats hétérogènes


# --------------------------------------------------------------- découpage
@dataclass(frozen=True)
class Segment:
    gender: str          # "H" ou "F"
    locale: str          # ex. "fr-CA"
    text: str


_TURN = re.compile(r"(?:^|\s/\s)\s*([HF])\s*:\s*")


def parse_document(document: str, speakers: list[str] | None = None) -> list[Segment]:
    """Découpe « H: … / F: … » en répliques ; l'accent vient de `speakers`
    (« H:fr-FR », « F:fr-CA »…). Un texte sans marqueur est lu par une voix
    féminine française."""
    accents: dict[str, str] = {}
    for sp in speakers or []:
        if ":" in sp:
            g, loc = sp.split(":", 1)
            accents.setdefault(g.strip().upper(), loc.strip())
    marks = list(_TURN.finditer(document))
    if not marks:
        text = document.strip()
        g = next(iter(accents), "F")
        return [Segment(g, accents.get(g, "fr-FR"), text)] if text else []
    out: list[Segment] = []
    for i, m in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(document)
        text = document[m.end():end].strip()
        if text:
            g = m.group(1)
            out.append(Segment(g, accents.get(g, "fr-FR"), text))
    return out


# ------------------------------------------------------------------ voix
@dataclass(frozen=True)
class VoiceInfo:
    id: str
    name: str
    locale: str          # "fr-FR", "fr-CA"… ou "fr" si inconnu
    gender: str | None   # "H", "F" ou None

    @property
    def is_french(self) -> bool:
        return self.locale.lower().startswith("fr")


# Voix SAPI courantes de Windows (nom → accent, genre).
KNOWN_VOICES: dict[str, tuple[str, str]] = {
    "hortense": ("fr-FR", "F"), "julie": ("fr-FR", "F"), "paul": ("fr-FR", "H"),
    "denise": ("fr-FR", "F"), "henri": ("fr-FR", "H"), "eloise": ("fr-FR", "F"),
    "caroline": ("fr-CA", "F"), "claude": ("fr-CA", "H"), "nathalie": ("fr-CA", "F"),
    "sylvie": ("fr-CA", "F"), "antoine": ("fr-CA", "H"), "jean": ("fr-CA", "H"),
    "charline": ("fr-BE", "F"), "gerard": ("fr-BE", "H"),
    "ariane": ("fr-CH", "F"), "guillaume": ("fr-CH", "H"), "fabrice": ("fr-CH", "H"),
}


def describe_voice(vid: str, name: str, languages=(), gender: str | None = None) -> VoiceInfo:
    """Normalise les informations très variables renvoyées par les moteurs."""
    low = f"{name} {vid}".lower()
    locale, g = "", None
    for key, (loc, gen) in KNOWN_VOICES.items():
        if re.search(rf"\b{key}\b", low):
            locale, g = loc, gen
            break
    if not locale:
        for lang in languages or ():
            if isinstance(lang, bytes):
                lang = lang.decode("ascii", "ignore")
            lang = str(lang).strip("\x05 ").replace("_", "-")
            if lang.lower().startswith("fr"):
                locale = lang if "-" in lang else "fr"
                break
    if not locale and re.search(r"french|fran[cç]ais|fr-fr|\bfr\b", low):
        locale = "fr-CA" if "canad" in low else "fr"
    if g is None and gender:
        gl = str(gender).lower()
        g = "F" if gl.startswith(("f", "w")) else "H" if gl.startswith("m") else None
    if g is None:
        g = "F" if re.search(r"female|femme|woman", low) else (
            "H" if re.search(r"\bmale\b|homme", low) else None)
    return VoiceInfo(vid, name, locale or "?", g)


def choose_voice(voices: list[VoiceInfo], gender: str, locale: str) -> VoiceInfo | None:
    """Meilleure voix française pour une réplique (genre, puis accent)."""
    french = [v for v in voices if v.is_french]
    if not french:
        return None

    def score(v: VoiceInfo) -> tuple:
        return (v.gender == gender, v.locale.lower() == locale.lower(),
                v.locale.lower().startswith("fr-fr"), v.name)
    return max(french, key=score)


# ---------------------------------------------------------------- moteurs
class TTSBackend(Protocol):
    name: str

    def voices(self) -> list[VoiceInfo]: ...

    def synthesize(self, text: str, voice: VoiceInfo, rate: int, out: Path) -> None: ...


class TTSUnavailable(RuntimeError):
    """Aucun moteur ou aucune voix française n'est disponible."""


class Pyttsx3Backend:
    """Synthèse hors ligne : SAPI 5 sous Windows (voix « Microsoft … »)."""
    name = "systeme"

    def __init__(self) -> None:
        try:
            import pyttsx3  # noqa: F401
        except Exception as exc:  # pragma: no cover - dépend du poste
            raise TTSUnavailable("Le module pyttsx3 n'est pas installé.") from exc
        self._voices: list[VoiceInfo] | None = None

    @staticmethod
    def _engine():
        import pyttsx3
        try:  # SAPI exige l'initialisation COM dans chaque fil d'exécution
            import pythoncom  # type: ignore
            pythoncom.CoInitialize()
        except Exception:
            pass
        return pyttsx3.init()

    def voices(self) -> list[VoiceInfo]:
        if self._voices is None:
            eng = self._engine()
            self._voices = [describe_voice(v.id, v.name or v.id,
                                           getattr(v, "languages", ()),
                                           getattr(v, "gender", None))
                            for v in eng.getProperty("voices")]
            eng.stop()
        return self._voices

    def synthesize(self, text: str, voice: VoiceInfo, rate: int, out: Path) -> None:
        eng = self._engine()
        eng.setProperty("voice", voice.id)
        eng.setProperty("rate", int(rate))
        eng.save_to_file(text, str(out))
        eng.runAndWait()
        eng.stop()
        if not out.exists() or out.stat().st_size < 64:
            raise TTSUnavailable("La synthèse vocale n'a produit aucun son.")


def default_backend() -> TTSBackend | None:
    try:
        return Pyttsx3Backend()
    except TTSUnavailable as exc:
        log.warning("Synthèse vocale indisponible : %s", exc)
        return None


# ------------------------------------------------------------- fichiers WAV
def _read_pcm16(path: Path):
    """Lit un WAV et le convertit en mono 16 bits à TARGET_RATE (numpy)."""
    import numpy as np
    with wave.open(str(path), "rb") as w:
        ch, width, rate, n = w.getnchannels(), w.getsampwidth(), w.getframerate(), w.getnframes()
        raw = w.readframes(n)
    if width == 1:
        data = (np.frombuffer(raw, np.uint8).astype(np.float32) - 128) / 128
    elif width == 2:
        data = np.frombuffer(raw, "<i2").astype(np.float32) / 32768
    elif width == 4:
        data = np.frombuffer(raw, "<i4").astype(np.float32) / 2147483648
    else:
        raise ValueError(f"format WAV non géré ({width} octets)")
    if ch > 1:
        data = data.reshape(-1, ch).mean(axis=1)
    if rate != TARGET_RATE and len(data):
        x_new = np.linspace(0, len(data) - 1, int(len(data) * TARGET_RATE / rate))
        data = np.interp(x_new, np.arange(len(data)), data)
    return (np.clip(data, -1, 1) * 32767).astype("<i2")


def concat_wavs(parts: list[Path], out: Path, pause_s: float = PAUSE_S) -> Path:
    """Assemble les répliques avec un court silence entre elles."""
    import numpy as np
    silence = np.zeros(int(TARGET_RATE * pause_s), "<i2")
    chunks = []
    for i, p in enumerate(parts):
        if i:
            chunks.append(silence)
        chunks.append(_read_pcm16(p))
    tmp = out.with_suffix(".part")
    with wave.open(str(tmp), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(TARGET_RATE)
        w.writeframes(np.concatenate(chunks).tobytes() if chunks else b"")
    tmp.replace(out)
    return out


# ------------------------------------------------------------- générateur
class AudioGenerator:
    """Produit (ou retrouve en cache) le fichier audio d'un document."""

    def __init__(self, backend: TTSBackend | None, cache_dir: Path, rate: int = 170,
                 resource_dir: Path | None = None):
        self.backend = backend
        self.cache_dir = Path(cache_dir)
        self.rate = rate
        self.resource_dir = resource_dir

    def recorded_file(self, audio_file: str | None) -> Path | None:
        if not audio_file:
            return None
        p = Path(audio_file)
        for cand in ([p] if p.is_absolute() else
                     [d / p for d in (self.resource_dir, self.cache_dir) if d]):
            if cand.is_file():
                return cand
        return None

    def cache_key(self, document: str, speakers: list[str] | None) -> str:
        h = hashlib.sha256()
        h.update(f"{self.backend.name if self.backend else '-'}|{self.rate}|".encode())
        h.update("|".join(speakers or []).encode())
        h.update(document.encode("utf-8"))
        return h.hexdigest()[:24]

    def cached_path(self, document: str, speakers: list[str] | None) -> Path:
        return self.cache_dir / f"co_{self.cache_key(document, speakers)}.wav"

    def is_ready(self, document: str, speakers: list[str] | None,
                 audio_file: str | None = None) -> bool:
        return bool(self.recorded_file(audio_file)) or self.cached_path(document,
                                                                       speakers).is_file()

    def ensure(self, document: str, speakers: list[str] | None = None,
               audio_file: str | None = None) -> Path:
        rec = self.recorded_file(audio_file)
        if rec:
            return rec
        out = self.cached_path(document, speakers)
        if out.is_file():
            return out
        if self.backend is None:
            raise TTSUnavailable(
                "Aucun moteur de synthèse vocale n'est disponible sur cet ordinateur.")
        voices = self.backend.voices()
        if not any(v.is_french for v in voices):
            raise TTSUnavailable(
                "Aucune voix française n'est installée. Sous Windows : Paramètres > "
                "Heure et langue > Voix > Ajouter des voix > Français.")
        segments = parse_document(document, speakers)
        if not segments:
            raise ValueError("document vide")
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        parts: list[Path] = []
        try:
            for i, seg in enumerate(segments):
                voice = choose_voice(voices, seg.gender, seg.locale)
                part = out.with_name(f"{out.stem}_{i:02d}.tmp.wav")
                self.backend.synthesize(seg.text, voice, self.rate, part)
                parts.append(part)
            concat_wavs(parts, out)
        finally:
            for p in parts:
                p.unlink(missing_ok=True)
        log.info("Audio généré : %s (%d réplique(s))", out.name, len(segments))
        return out

    def ensure_question(self, q) -> Path:
        return self.ensure(q.document, q.speakers, getattr(q, "audio_file", None))

    def clear_cache(self) -> int:
        n = 0
        for p in self.cache_dir.glob("co_*.wav"):
            p.unlink(missing_ok=True)
            n += 1
        return n
