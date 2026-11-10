"""Reconnaissance vocale hors ligne (Vosk, modèle français).

Le modèle (« vosk-model-small-fr-0.22 », environ 40 Mo) est cherché :
  1. dans le dossier indiqué par le paramètre `stt_model_path` ;
  2. dans `<données>/modeles/` ;
  3. dans les ressources embarquées `tcfmaster/models/` (installateur).
`tools/fetch_vosk_model.py` le télécharge avant la création de l'installateur.
Sans modèle, l'application propose une transcription saisie à la main.
"""
from __future__ import annotations

import json
import logging
import wave
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

log = logging.getLogger("tcfmaster.stt")

MODEL_NAME = "vosk-model-small-fr-0.22"
MODEL_URL = f"https://alphacephei.com/vosk/models/{MODEL_NAME}.zip"


class STTUnavailable(RuntimeError):
    pass


@dataclass
class Word:
    word: str
    start: float
    end: float
    conf: float = 1.0


@dataclass
class Transcript:
    text: str
    words: list[Word] = field(default_factory=list)
    engine: str = ""

    @property
    def confidence(self) -> float | None:
        return round(sum(w.conf for w in self.words) / len(self.words), 2) if self.words else None


class STTEngine(Protocol):
    name: str

    def transcribe(self, wav_path: Path) -> Transcript: ...


def find_model(candidates: list[Path]) -> Path | None:
    """Premier dossier qui contient un modèle Vosk (fichier `am/final.mdl` ou `conf/`)."""
    for base in candidates:
        if not base:
            continue
        base = Path(base)
        for cand in (base, base / MODEL_NAME):
            if (cand / "am").is_dir() or (cand / "conf").is_dir():
                return cand
        if base.is_dir():
            for sub in sorted(base.glob("vosk-model*fr*")):
                if (sub / "am").is_dir() or (sub / "conf").is_dir():
                    return sub
    return None


class VoskEngine:
    name = "vosk"

    def __init__(self, model_dir: Path):
        try:
            import vosk
        except Exception as exc:  # pragma: no cover - dépend du poste
            raise STTUnavailable("Le module de reconnaissance vocale (vosk) n'est pas "
                                 "installé.") from exc
        vosk.SetLogLevel(-1)
        self._vosk = vosk
        self.model = vosk.Model(str(model_dir))

    def transcribe(self, wav_path: Path) -> Transcript:
        with wave.open(str(wav_path), "rb") as wf:
            if wf.getnchannels() != 1 or wf.getsampwidth() != 2:
                raise STTUnavailable("Format audio non pris en charge (mono 16 bits requis).")
            rec = self._vosk.KaldiRecognizer(self.model, wf.getframerate())
            rec.SetWords(True)
            parts: list[dict] = []
            while True:
                data = wf.readframes(4000)
                if not data:
                    break
                if rec.AcceptWaveform(data):
                    parts.append(json.loads(rec.Result()))
            parts.append(json.loads(rec.FinalResult()))
        words = [Word(w["word"], w.get("start", 0), w.get("end", 0), w.get("conf", 1.0))
                 for p in parts for w in p.get("result", [])]
        text = " ".join(p.get("text", "") for p in parts if p.get("text")).strip()
        return Transcript(text, words, self.name)


def default_engine(candidates: list[Path]) -> STTEngine | None:
    model = find_model(candidates)
    if model is None:
        log.info("Aucun modèle Vosk trouvé (%s)", ", ".join(map(str, candidates)))
        return None
    try:
        return VoskEngine(model)
    except Exception as exc:
        log.warning("Vosk indisponible : %s", exc)
        return None
