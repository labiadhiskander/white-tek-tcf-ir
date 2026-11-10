"""Carte « Voix et audio » des paramètres."""
from __future__ import annotations

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QMessageBox, QProgressBar, QPushButton,
                               QSpinBox)

from tcfmaster.services import settings as S
from tcfmaster.services.wiring import pregenerate_all
from tcfmaster.ui.widgets import Card

SAMPLE = ("H: Bonjour, je voudrais un renseignement sur l'examen. / "
          "F: Bien sûr, que souhaitez-vous savoir ?")


class _PregenThread(QThread):
    progressed = Signal(int, int)
    done = Signal(int, list)

    def __init__(self, ctx, generator):
        super().__init__()
        self.ctx, self.generator = ctx, generator
        self.cancelled = False

    def run(self) -> None:
        def cb(i, n):
            self.progressed.emit(i, n)
            return not self.cancelled
        ready, errors = pregenerate_all(self.ctx, self.generator, cb)
        self.done.emit(ready, errors)


class AudioSettingsCard(Card):
    def __init__(self, ctx, parent=None):
        super().__init__("Voix et audio (compréhension orale)", parent)
        self.ctx = ctx
        self._thread: _PregenThread | None = None
        self.engine_info = QLabel()
        self.engine_info.setWordWrap(True)
        self.lay.addWidget(self.engine_info)

        row = QHBoxLayout()
        row.addWidget(QLabel("Débit de la voix :"))
        self.rate = QSpinBox()
        self.rate.setRange(110, 240)
        self.rate.setSingleStep(10)
        self.rate.setSuffix(" mots/min")
        self.rate.valueChanged.connect(self._set_rate)
        row.addWidget(self.rate)
        test = QPushButton("Tester les voix")
        test.clicked.connect(self._test)
        row.addWidget(test)
        row.addStretch(1)
        self.lay.addLayout(row)

        row2 = QHBoxLayout()
        self.pregen_btn = QPushButton("Préparer tous les audios (usage hors ligne)")
        self.pregen_btn.setObjectName("Primary")
        self.pregen_btn.clicked.connect(self._pregen)
        clear = QPushButton("Vider le cache audio")
        clear.clicked.connect(self._clear)
        row2.addWidget(self.pregen_btn)
        row2.addWidget(clear)
        row2.addStretch(1)
        self.lay.addLayout(row2)
        self.bar = QProgressBar()
        self.bar.setVisible(False)
        self.lay.addWidget(self.bar)
        self.cache_info = QLabel()
        self.cache_info.setObjectName("Muted")
        self.lay.addWidget(self.cache_info)

        self.voice_info = QLabel()
        self.voice_info.setWordWrap(True)
        self.lay.addWidget(self.voice_info)
        row3 = QHBoxLayout()
        model_btn = QPushButton("Choisir le dossier du modèle de reconnaissance vocale…")
        model_btn.clicked.connect(self._choose_model)
        row3.addWidget(model_btn)
        row3.addStretch(1)
        self.lay.addLayout(row3)

    # ----------------------------------------------------------------
    @property
    def generator(self):
        audio = getattr(self.ctx, "audio", None)
        return audio.generator if audio is not None else None

    def refresh(self) -> None:
        with self.ctx.db.session() as s:
            self.rate.blockSignals(True)
            self.rate.setValue(int(S.get(s, "tts_rate") or 170))
            self.rate.blockSignals(False)
        gen = self.generator
        if gen is None or gen.backend is None:
            self.engine_info.setText(
                "⚠ Aucun moteur de synthèse vocale détecté. Les documents enregistrés "
                "restent lisibles ; sinon, la transcription est proposée en entraînement.")
        else:
            try:
                fr = [v for v in gen.backend.voices() if v.is_french]
            except Exception as exc:
                fr, err = [], str(exc)
            else:
                err = ""
            if fr:
                names = ", ".join(f"{v.name} ({v.locale}{', ' + v.gender if v.gender else ''})"
                                  for v in fr)
                self.engine_info.setText(f"Voix françaises disponibles : {names}")
            else:
                self.engine_info.setText(
                    "⚠ Aucune voix française installée. Windows : Paramètres > Heure et "
                    "langue > Voix > Ajouter des voix > Français (France, Canada…). " + err)
        self._update_cache_info()
        mic = "✔ micro détecté" if getattr(self.ctx, "recorder", None) else "⚠ aucun micro"
        stt = getattr(self.ctx, "stt", None)
        self.voice_info.setText(
            f"Expression orale : {mic} · reconnaissance vocale : "
            + ("✔ hors ligne (Vosk)" if stt else
               "⚠ modèle français absent – téléchargez « vosk-model-small-fr-0.22 » sur "
               "alphacephei.com/vosk/models et indiquez son dossier ci-dessous."))

    def _choose_model(self) -> None:
        from PySide6.QtWidgets import QFileDialog
        from tcfmaster.services.stt import default_engine, find_model
        d = QFileDialog.getExistingDirectory(self, "Dossier du modèle Vosk")
        if not d:
            return
        from pathlib import Path
        if find_model([Path(d)]) is None:
            QMessageBox.warning(self, "Reconnaissance vocale",
                                "Ce dossier ne contient pas de modèle Vosk.")
            return
        with self.ctx.db.session() as s:
            S.set_(s, "stt_model_path", d)
        self.ctx.stt = default_engine([Path(d)])
        self.refresh()

    def _update_cache_info(self) -> None:
        files = list(self.ctx.paths.audio_cache.glob("co_*.wav"))
        size = sum(p.stat().st_size for p in files) / 1e6
        self.cache_info.setText(f"Cache audio : {len(files)} document(s) · {size:.0f} Mo")

    def _set_rate(self, v: int) -> None:
        with self.ctx.db.session() as s:
            S.set_(s, "tts_rate", int(v))
        if self.generator is not None:
            self.generator.rate = int(v)
        self._update_cache_info()

    def _test(self) -> None:
        audio = getattr(self.ctx, "audio", None)
        if audio is None:
            QMessageBox.warning(self, "Audio", "Le service audio n'est pas disponible.")
            return
        audio.play_text(SAMPLE, ["H:fr-FR", "F:fr-FR"])

    def _pregen(self) -> None:
        if self._thread is not None:
            self._thread.cancelled = True
            return
        gen = self.generator
        if gen is None or gen.backend is None:
            QMessageBox.warning(self, "Audio", "Aucun moteur de synthèse vocale disponible.")
            return
        self._thread = _PregenThread(self.ctx, gen)
        self._thread.progressed.connect(self._on_progress)
        self._thread.done.connect(self._on_done)
        self.bar.setVisible(True)
        self.pregen_btn.setText("Interrompre la préparation")
        self._thread.start()

    def _on_progress(self, i: int, n: int) -> None:
        self.bar.setRange(0, max(1, n))
        self.bar.setValue(i)

    def _on_done(self, ready: int, errors: list) -> None:
        self._thread.wait()
        self._thread = None
        self.bar.setVisible(False)
        self.pregen_btn.setText("Préparer tous les audios (usage hors ligne)")
        self._update_cache_info()
        msg = f"{ready} document(s) audio prêts."
        if errors:
            msg += "\n\nProblèmes :\n" + "\n".join(errors[:5])
        QMessageBox.information(self, "Audio", msg)

    def _clear(self) -> None:
        if self.generator is not None:
            self.generator.clear_cache()
        else:
            for p in self.ctx.paths.audio_cache.glob("co_*.wav"):
                p.unlink(missing_ok=True)
        self._update_cache_info()


