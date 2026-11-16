"""Bouton « Approfondir avec l'IA » des rapports d'expression écrite et orale.

Il n'apparaît que si une IA est configurée (IA locale Ollama / LM Studio, ou
Claude). La note affichée reste l'estimation du barème local ; l'IA ajoute
des explications, jamais une note officielle.
"""
from __future__ import annotations

from html import escape

from PySide6.QtWidgets import QMessageBox, QPushButton, QTextBrowser

from tcfmaster.services.ai.base import AIUnavailable
from tcfmaster.ui.ai_settings import tutor_service

LABEL = "✨ Approfondir la correction avec l'IA"


def deepen_html(text: str, engine: str) -> str:
    paras = "".join(f"<p>{escape(p).replace(chr(10), '<br>')}</p>"
                    for p in text.split("\n\n") if p.strip())
    return (f"<hr><h3>Correction approfondie · {escape(engine)}</h3>{paras}"
            "<p style='color:#7a5d00'><i>Commentaire généré automatiquement : estimation "
            "pédagogique, à confronter au corrigé et aux règles de l'application.</i></p>")


class DeepenButton(QPushButton):
    def __init__(self, ctx, kind: str, browser: QTextBrowser, current_id, parent=None):
        """`current_id()` renvoie l'identifiant de la production affichée (ou None)."""
        super().__init__(LABEL, parent)
        self.ctx, self.kind, self.browser, self.current_id = ctx, kind, browser, current_id
        self.last_text = ""
        self.clicked.connect(self.run)
        self.setVisible(False)

    def refresh_state(self) -> None:
        tutor = tutor_service(self.ctx)
        self.setVisible(tutor.online_engine() is not None and self.current_id() is not None)
        self.setEnabled(True)
        self.setText(LABEL)

    def run(self) -> None:
        from tcfmaster.ui.speaking import run_background
        sub_id = self.current_id()
        if sub_id is None:
            return
        tutor = tutor_service(self.ctx)
        if tutor.needs_consent():
            from tcfmaster.services.ai.tutor import PRIVACY_NOTICE
            if QMessageBox.question(self, "Confidentialité", PRIVACY_NOTICE + "\n\nContinuer ?"
                                    ) != QMessageBox.Yes:
                return
            tutor.give_consent()
        self.setEnabled(False)
        self.setText("Analyse en cours… (une IA locale peut prendre une minute)")
        engine = getattr(tutor.online_engine(), "name", "IA")
        run_background(self, lambda: tutor.deepen(self.kind, sub_id),
                       lambda res: self._done(res, engine))

    def _done(self, res, engine: str) -> None:
        self.setEnabled(True)
        self.setText(LABEL)
        if isinstance(res, AIUnavailable):
            self.browser.append(f"<p style='color:#b3261e'>IA indisponible : {escape(str(res))}"
                                " La correction ci-dessus (barème local) reste valable.</p>")
            return
        if isinstance(res, Exception):
            self.browser.append(f"<p style='color:#b3261e'>Erreur : {escape(str(res))}</p>")
            return
        self.last_text = res
        self.browser.append(deepen_html(res, engine))
