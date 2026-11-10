"""Lecture des documents CO dans l'interface (Qt Multimedia).

La synthèse (qui peut prendre quelques secondes la première fois) s'exécute
dans un fil d'exécution séparé : l'interface et le chronomètre ne sont
jamais bloqués. Les signaux permettent à l'écran d'épreuve d'afficher
l'état (« Préparation… », « Lecture… ») et de rendre l'écoute au candidat
si elle a échoué.
"""
from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import QObject, QThread, QUrl, Signal, Slot

from tcfmaster.services.audio import AudioGenerator, TTSUnavailable

log = logging.getLogger("tcfmaster.audio")


class _Job(QObject):
    done = Signal(int, str)      # jeton, chemin
    failed = Signal(int, str)    # jeton, message

    def __init__(self, gen: AudioGenerator, token: int, document: str,
                 speakers, audio_file):
        super().__init__()
        self.gen, self.token = gen, token
        self.args = (document, speakers, audio_file)

    @Slot()
    def run(self) -> None:
        try:
            path = self.gen.ensure(*self.args)
            self.done.emit(self.token, str(path))
        except TTSUnavailable as exc:
            self.failed.emit(self.token, str(exc))
        except Exception as exc:  # le détail va au journal, pas à l'écran
            log.exception("Échec de la génération audio")
            self.failed.emit(self.token, f"Impossible de préparer l'audio ({exc}).")


class AudioService(QObject):
    preparing = Signal()
    started = Signal()
    finished = Signal()
    failed = Signal(str)

    def __init__(self, generator: AudioGenerator, parent=None):
        super().__init__(parent)
        self.generator = generator
        self._token = 0
        self._threads: list[tuple[QThread, _Job]] = []
        self._player = None
        self._output = None

    # ----------------------------------------------------------- lecture
    def _ensure_player(self) -> bool:
        if self._player is not None:
            return True
        try:
            from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
        except Exception as exc:  # pragma: no cover - dépend du poste
            log.warning("Qt Multimedia indisponible : %s", exc)
            return False
        self._player = QMediaPlayer(self)
        self._output = QAudioOutput(self)
        self._player.setAudioOutput(self._output)
        self._player.mediaStatusChanged.connect(self._on_status)
        self._player.errorOccurred.connect(
            lambda _e, msg: self.failed.emit(f"Lecture impossible : {msg}"))
        return True

    def _on_status(self, status) -> None:
        from PySide6.QtMultimedia import QMediaPlayer
        if status == QMediaPlayer.MediaStatus.EndOfMedia:
            self.finished.emit()

    def play_file(self, path: str | Path) -> None:
        if not self._ensure_player():
            self.failed.emit("Aucune sortie audio n'est disponible.")
            return
        self._player.setSource(QUrl.fromLocalFile(str(path)))
        self._player.play()
        self.started.emit()

    def play_question(self, q) -> None:
        """Lance la lecture du document d'une question CO."""
        self.play_text(q.document, q.speakers, getattr(q, "audio_file", None))

    def play_text(self, document: str, speakers=None, audio_file=None) -> None:
        self.stop()
        self._token += 1
        if self.generator.is_ready(document, speakers, audio_file):
            try:
                self.play_file(self.generator.ensure(document, speakers, audio_file))
            except Exception as exc:
                self.failed.emit(str(exc))
            return
        self.preparing.emit()
        self._run_job(_Job(self.generator, self._token, document, speakers, audio_file))

    def _run_job(self, job: _Job) -> None:
        th = QThread(self)
        job.moveToThread(th)
        th.started.connect(job.run)
        job.done.connect(self._on_ready)
        job.failed.connect(self._on_failed)
        job.done.connect(th.quit)
        job.failed.connect(th.quit)
        th.finished.connect(lambda: self._forget(th))
        self._threads.append((th, job))
        th.start()

    def _forget(self, th: QThread) -> None:
        self._threads = [(t, j) for t, j in self._threads if t is not th]
        th.deleteLater()

    def _on_ready(self, token: int, path: str) -> None:
        if token == self._token:          # ignorer une demande périmée
            self.play_file(path)

    def _on_failed(self, token: int, message: str) -> None:
        if token == self._token:
            self.failed.emit(message)

    def stop(self) -> None:
        self._token += 1
        if self._player is not None:
            self._player.stop()

    def shutdown(self) -> None:
        self.stop()
        for th, _job in list(self._threads):
            th.quit()
            th.wait(5000)
