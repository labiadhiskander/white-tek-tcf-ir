"""Carte « Tuteur IA » des paramètres : fournisseur, modèle et clé API.

La clé est confiée au coffre d'identifiants du système (Gestionnaire
d'identification Windows) : elle n'est jamais écrite dans la base, dans un
fichier de configuration ni dans le journal.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QComboBox, QHBoxLayout, QLabel, QLineEdit, QMessageBox,
                               QPushButton)

from tcfmaster.services import settings as S
from tcfmaster.services.ai.anthropic_engine import DEFAULT_MODEL
from tcfmaster.services.ai.base import AIUnavailable
from tcfmaster.services.ai.tutor import PRIVACY_NOTICE, PROVIDER_ANTHROPIC, PROVIDERS
from tcfmaster.ui.widgets import Card, disclaimer_label

EFFORT_LABELS = {"low": "Rapide", "medium": "Équilibré (recommandé)", "high": "Approfondi"}


def tutor_service(ctx):
    from tcfmaster.services.ai.tutor import TutorService
    if getattr(ctx, "tutor", None) is None:
        ctx.tutor = TutorService(ctx.db)
    return ctx.tutor


class AISettingsCard(Card):
    def __init__(self, ctx, parent=None):
        super().__init__("Tuteur IA", parent)
        self.ctx = ctx
        self.provider = QComboBox()
        for k, label in PROVIDERS.items():
            self.provider.addItem(label, k)
        self.provider.currentIndexChanged.connect(self._provider_changed)
        self.lay.addWidget(QLabel("Moteur du tuteur :"))
        self.lay.addWidget(self.provider)

        row = QHBoxLayout()
        row.addWidget(QLabel("Modèle :"))
        self.model = QLineEdit()
        self.model.setPlaceholderText(DEFAULT_MODEL)
        self.model.editingFinished.connect(
            lambda: self._set("ai_model", self.model.text().strip() or DEFAULT_MODEL))
        row.addWidget(self.model, 2)
        row.addWidget(QLabel("Réflexion :"))
        self.effort = QComboBox()
        for k, label in EFFORT_LABELS.items():
            self.effort.addItem(label, k)
        self.effort.currentIndexChanged.connect(
            lambda: self._set("ai_effort", self.effort.currentData()))
        row.addWidget(self.effort, 1)
        self.lay.addLayout(row)

        krow = QHBoxLayout()
        self.key = QLineEdit()
        self.key.setEchoMode(QLineEdit.Password)
        self.key.setPlaceholderText("Clé API Anthropic (sk-ant-…)")
        krow.addWidget(self.key, 2)
        self.save_key = QPushButton("Enregistrer la clé")
        self.save_key.clicked.connect(self._save_key)
        self.del_key = QPushButton("Supprimer la clé")
        self.del_key.clicked.connect(self._delete_key)
        self.test_btn = QPushButton("Tester la connexion")
        self.test_btn.clicked.connect(self._test)
        for b in (self.save_key, self.del_key, self.test_btn):
            krow.addWidget(b)
        self.lay.addLayout(krow)
        self.key_info = QLabel()
        self.key_info.setWordWrap(True)
        self.key_info.setObjectName("Muted")
        self.lay.addWidget(self.key_info)
        privacy = QLabel(PRIVACY_NOTICE + " Les replis côté serveur sont activés : si le "
                         "modèle choisi décline une demande, un modèle de substitution répond.")
        privacy.setWordWrap(True)
        privacy.setObjectName("Muted")
        privacy.setTextFormat(Qt.PlainText)
        self.lay.addWidget(privacy)
        self.lay.addWidget(disclaimer_label(
            "Les évaluations du tuteur sont des estimations pédagogiques, jamais des résultats "
            "officiels de France Éducation international."))

    # ------------------------------------------------------------------
    def _set(self, key, value) -> None:
        with self.ctx.db.session() as s:
            S.set_(s, key, value)

    def _provider_changed(self) -> None:
        self._set("ai_provider", self.provider.currentData())
        self._update_state()

    def refresh(self) -> None:
        with self.ctx.db.session() as s:
            st = S.all_settings(s)
        for w, key in ((self.provider, "ai_provider"), (self.effort, "ai_effort")):
            w.blockSignals(True)
            w.setCurrentIndex(max(0, w.findData(st.get(key))))
            w.blockSignals(False)
        self.model.setText(st.get("ai_model") or DEFAULT_MODEL)
        self._update_state()

    def _update_state(self) -> None:
        online = self.provider.currentData() == PROVIDER_ANTHROPIC
        for w in (self.model, self.effort, self.key, self.save_key, self.del_key,
                  self.test_btn):
            w.setEnabled(online)
        if S._keyring() is None:
            self.key_info.setText("⚠ Coffre d'identifiants du système indisponible : la clé ne "
                                  "peut pas être enregistrée (elle n'est jamais stockée en "
                                  "clair). Le tuteur hors ligne reste utilisable.")
            self.save_key.setEnabled(False)
        elif S.load_api_key(PROVIDER_ANTHROPIC):
            self.key_info.setText("✔ Clé enregistrée dans le coffre sécurisé du système.")
        else:
            self.key_info.setText("Aucune clé enregistrée." + ("" if online else
                                  " (Inutile pour le tuteur hors ligne.)"))

    def _save_key(self) -> None:
        secret = self.key.text().strip()
        if not secret:
            return
        ok = S.store_api_key(PROVIDER_ANTHROPIC, secret)
        self.key.clear()
        if not ok:
            QMessageBox.warning(self, "Clé API", "Impossible d'enregistrer la clé : coffre "
                                "d'identifiants indisponible.")
        self._update_state()

    def _delete_key(self) -> None:
        S.delete_api_key(PROVIDER_ANTHROPIC)
        self._update_state()

    def _test(self) -> None:
        from tcfmaster.ui.speaking import run_background
        self.test_btn.setEnabled(False)
        self.test_btn.setText("Test en cours…")
        run_background(self, tutor_service(self.ctx).test_connection, self._tested)

    def _tested(self, res) -> None:
        self.test_btn.setText("Tester la connexion")
        self._update_state()
        if isinstance(res, AIUnavailable):
            QMessageBox.warning(self, "Tuteur IA", str(res))
        elif isinstance(res, Exception):
            QMessageBox.warning(self, "Tuteur IA", f"Erreur inattendue : {res}")
        else:
            QMessageBox.information(self, "Tuteur IA", str(res))
