"""Carte « Tuteur IA » des paramètres : fournisseur, modèle et clé API.

La clé est confiée au coffre d'identifiants du système (Gestionnaire
d'identification Windows) : elle n'est jamais écrite dans la base, dans un
fichier de configuration ni dans le journal.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QComboBox, QHBoxLayout, QLabel, QLineEdit, QMessageBox,
                               QPushButton, QVBoxLayout, QWidget)

from tcfmaster.services import settings as S
from tcfmaster.services.ai.anthropic_engine import DEFAULT_MODEL
from tcfmaster.services.ai.base import AIUnavailable
from tcfmaster.services.ai.local_llm import DEFAULT_URL, PRESETS, is_local
from tcfmaster.services.ai.tutor import (PRIVACY_NOTICE, PROVIDER_ANTHROPIC, PROVIDER_LOCAL_LLM,
                                         PROVIDERS)
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

        # --- IA locale (Ollama / LM Studio)
        self.llm_box = QWidget()
        ll = QVBoxLayout(self.llm_box)
        ll.setContentsMargins(0, 4, 0, 4)
        lrow = QHBoxLayout()
        lrow.addWidget(QLabel("Logiciel :"))
        self.llm_preset = QComboBox()
        for k, (label, _url) in PRESETS.items():
            self.llm_preset.addItem(label, k)
        self.llm_preset.addItem("Autre serveur compatible OpenAI", "autre")
        self.llm_preset.activated.connect(self._preset_chosen)
        lrow.addWidget(self.llm_preset, 1)
        lrow.addWidget(QLabel("Adresse :"))
        self.llm_url = QLineEdit()
        self.llm_url.setPlaceholderText(DEFAULT_URL)
        self.llm_url.editingFinished.connect(self._url_changed)
        lrow.addWidget(self.llm_url, 2)
        ll.addLayout(lrow)
        mrow = QHBoxLayout()
        mrow.addWidget(QLabel("Modèle :"))
        self.llm_model = QComboBox()
        self.llm_model.setEditable(True)
        self.llm_model.lineEdit().setPlaceholderText("premier modèle installé (ex. mistral)")
        self.llm_model.lineEdit().editingFinished.connect(self._llm_model_changed)
        self.llm_model.activated.connect(lambda *_: self._llm_model_changed())
        mrow.addWidget(self.llm_model, 2)
        self.llm_list_btn = QPushButton("Lister les modèles")
        self.llm_list_btn.clicked.connect(self._list_models)
        self.llm_test_btn = QPushButton("Tester l'IA locale")
        self.llm_test_btn.clicked.connect(self._test)
        mrow.addWidget(self.llm_list_btn)
        mrow.addWidget(self.llm_test_btn)
        ll.addLayout(mrow)
        self._llm_help = (
            "Gratuit et sans clé : installez Ollama (ollama.com) puis, dans un terminal, "
            "« ollama pull mistral » ; ou LM Studio (lmstudio.ai), téléchargez un modèle et "
            "démarrez le serveur local. Un modèle de 7 à 8 milliards de paramètres demande "
            "environ 8 Go de mémoire. L'IA locale approfondit les corrections d'expression "
            "écrite et orale ; le barème et la note estimée restent ceux de l'application.")
        self.llm_info = QLabel(self._llm_help)
        self.llm_info.setWordWrap(True)
        self.llm_info.setObjectName("Muted")
        ll.addWidget(self.llm_info)
        self.lay.addWidget(self.llm_box)

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
        url = st.get("local_ai_url") or DEFAULT_URL
        self.llm_url.setText(url)
        preset = next((k for k, (_l, u) in PRESETS.items() if u == url), "autre")
        self.llm_preset.setCurrentIndex(self.llm_preset.findData(preset))
        self.llm_model.setEditText(st.get("local_ai_model") or "")
        self._update_state()

    # ------------------------------------------------------------ IA locale
    def _preset_chosen(self, *_):
        key = self.llm_preset.currentData()
        if key in PRESETS:
            self.llm_url.setText(PRESETS[key][1])
            self._url_changed()

    def _url_changed(self) -> None:
        from tcfmaster.services.ai.base import AIUnavailable as _AU
        from tcfmaster.services.ai.local_llm import normalize_url
        try:
            url = normalize_url(self.llm_url.text())
        except _AU as exc:
            self.llm_url.setText(DEFAULT_URL)
            QMessageBox.warning(self, "IA locale", str(exc))
            url = DEFAULT_URL
        self.llm_url.setText(url)
        self._set("local_ai_url", url)
        self._update_state()

    def _llm_model_changed(self) -> None:
        self._set("local_ai_model", self.llm_model.currentText().strip())

    def _list_models(self) -> None:
        from tcfmaster.ui.speaking import run_background
        self.llm_list_btn.setEnabled(False)
        url = self.llm_url.text().strip() or DEFAULT_URL
        run_background(self, lambda: tutor_service(self.ctx).list_local_models(url),
                       self._models_listed)

    def _models_listed(self, res) -> None:
        self.llm_list_btn.setEnabled(True)
        if isinstance(res, Exception):
            QMessageBox.warning(self, "IA locale", str(res))
            return
        current = self.llm_model.currentText().strip()
        self.llm_model.blockSignals(True)
        self.llm_model.clear()
        self.llm_model.addItems(res)
        self.llm_model.blockSignals(False)
        if current:
            self.llm_model.setEditText(current)
        elif res:
            self.llm_model.setCurrentIndex(0)
            self._llm_model_changed()
        if not res:
            QMessageBox.information(self, "IA locale", "Aucun modèle installé sur ce serveur.")

    def _update_state(self) -> None:
        online = self.provider.currentData() == PROVIDER_ANTHROPIC
        llm = self.provider.currentData() == PROVIDER_LOCAL_LLM
        self.llm_box.setVisible(llm)
        for w in (self.llm_preset, self.llm_url, self.llm_model, self.llm_list_btn,
                  self.llm_test_btn):
            w.setEnabled(llm)
        if llm and not is_local(self.llm_url.text() or DEFAULT_URL):
            self.llm_info.setText("⚠ Cette adresse n'est pas sur votre ordinateur ni sur votre "
                                  "réseau local : vos textes y seront envoyés.")
        else:
            self.llm_info.setText(self._llm_help)
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
        self.llm_test_btn.setEnabled(False)
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
