"""Enregistrement du microphone (WAV mono 16 kHz, format attendu par Vosk).

`SoundDeviceRecorder` écrit le son au fil de l'eau dans un fichier WAV depuis
le fil audio de PortAudio ; l'interface interroge `level()` pour afficher un
vumètre. Aucune donnée ne quitte l'ordinateur.
"""
from __future__ import annotations

import logging
import threading
import time
import wave
from pathlib import Path
from typing import Protocol

log = logging.getLogger("tcfmaster.recorder")

SAMPLE_RATE = 16000


class RecorderUnavailable(RuntimeError):
    """Pas de micro, pas de pilote audio ou module sounddevice absent."""


class Recorder(Protocol):
    def start(self, path: Path) -> None: ...

    def stop(self) -> float: ...                # durée enregistrée (s)

    def level(self) -> float: ...               # 0..1, pour le vumètre

    def pause(self, on: bool) -> None: ...      # ne pas enregistrer la voix de l'examinateur

    @property
    def recording(self) -> bool: ...


class SoundDeviceRecorder:
    def __init__(self, samplerate: int = SAMPLE_RATE, device=None):
        try:
            import sounddevice  # noqa: F401
        except Exception as exc:  # pragma: no cover - dépend du poste
            raise RecorderUnavailable(
                "Le module d'enregistrement audio (sounddevice) n'est pas disponible.") from exc
        self.samplerate, self.device = samplerate, device
        self._stream = None
        self._wav: wave.Wave_write | None = None
        self._lock = threading.Lock()
        self._level = 0.0
        self._frames = 0
        self._paused = False

    def pause(self, on: bool) -> None:
        self._paused = bool(on)

    @property
    def recording(self) -> bool:
        return self._stream is not None

    def _callback(self, indata, frames, _time, status) -> None:  # fil PortAudio
        import numpy as np
        if status:
            log.debug("Statut audio : %s", status)
        with self._lock:
            if self._wav is not None and not self._paused:
                self._wav.writeframes(indata.tobytes())
                self._frames += frames
        peak = float(np.abs(indata).max()) / 32768 if frames else 0.0
        self._level = 0.7 * self._level + 0.3 * peak

    def start(self, path: Path) -> None:
        import sounddevice as sd
        if self.recording:
            self.stop()
        path.parent.mkdir(parents=True, exist_ok=True)
        wav = wave.open(str(path), "wb")
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(self.samplerate)
        self._wav, self._frames, self._paused = wav, 0, False
        try:
            self._stream = sd.InputStream(samplerate=self.samplerate, channels=1,
                                          dtype="int16", device=self.device,
                                          callback=self._callback)
            self._stream.start()
        except Exception as exc:
            with self._lock:
                self._wav = None
            wav.close()
            path.unlink(missing_ok=True)
            self._stream = None
            raise RecorderUnavailable(f"Impossible d'ouvrir le microphone : {exc}") from exc

    def stop(self) -> float:
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            finally:
                self._stream = None
        with self._lock:
            if self._wav is not None:
                self._wav.close()
                self._wav = None
        self._level = 0.0
        return self._frames / self.samplerate

    def level(self) -> float:
        return min(1.0, self._level * 3)


def default_recorder() -> Recorder | None:
    try:
        return SoundDeviceRecorder()
    except RecorderUnavailable as exc:
        log.warning("Enregistrement indisponible : %s", exc)
        return None


def recording_path(recordings_dir: Path, task_number: int) -> Path:
    return Path(recordings_dir) / f"eo_{time.strftime('%Y%m%d_%H%M%S')}_t{task_number}.wav"


# ------------------------------------------------------------ analyse du son
def speech_profile(path: Path, frame_ms: int = 50, pause_s: float = 1.2) -> dict:
    """Temps de parole, silences et longues pauses à partir de l'énergie du signal."""
    import numpy as np
    with wave.open(str(path), "rb") as w:
        rate, n, width, ch = w.getframerate(), w.getnframes(), w.getsampwidth(), w.getnchannels()
        raw = w.readframes(n)
    if width != 2 or n == 0:
        return {"duration_s": n / rate if rate else 0, "speech_s": 0.0, "speech_ratio": 0.0,
                "long_pauses": 0}
    data = np.frombuffer(raw, "<i2").astype(np.float32)
    if ch > 1:
        data = data.reshape(-1, ch).mean(axis=1)
    hop = max(1, int(rate * frame_ms / 1000))
    frames = len(data) // hop
    if frames == 0:
        return {"duration_s": n / rate, "speech_s": 0.0, "speech_ratio": 0.0, "long_pauses": 0}
    rms = np.sqrt((data[: frames * hop].reshape(frames, hop) ** 2).mean(axis=1))
    noise = np.percentile(rms, 20)
    threshold = max(300.0, noise * 3)
    voiced = rms > threshold
    speech_s = float(voiced.sum()) * frame_ms / 1000
    # longues pauses : silences de plus de `pause_s` entre deux segments parlés
    long_pauses, run, seen_speech = 0, 0, False
    for v in voiced:
        if v:
            if seen_speech and run * frame_ms / 1000 >= pause_s:
                long_pauses += 1
            run, seen_speech = 0, True
        else:
            run += 1
    duration = n / rate
    return {"duration_s": round(duration, 1), "speech_s": round(speech_s, 1),
            "speech_ratio": round(speech_s / duration, 2) if duration else 0.0,
            "long_pauses": long_pauses}
