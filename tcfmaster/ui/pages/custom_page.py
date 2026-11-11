"""Page « Exercices personnalisés » : séries ciblées sur les erreurs récurrentes."""
from __future__ import annotations

import html
import time

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QButtonGroup, QHBoxLayout, QLabel, QLineEdit, QPushButton,
                               QRadioButton, QSizePolicy, QSpinBox, QStackedWidget, QTableWidget,
                               QTableWidgetItem, QTextBrowser, QVBoxLayout, QWidget)

from tcfmaster.services import custom_exercises as CX
from tcfmaster.services import error_tracking as ET
from tcfmaster.services.error_tracking import Weakness
from tcfmaster.ui.widgets import Card, Page

GREEN, RED, ORANGE = "#1E8449", "#C0392B", "#B9770E"
SRC = {"EE": "Écrit", "EO": "Oral", "IA": "Tuteur", "grammaire": "Grammaire",
       "perso": "Exercices perso"}


class CustomExercisesPage(Page):
    def __init__(self, ctx):
        super().__init__(ctx, "Exercices personnalisés",
                         "Des séries construites à partir de VOS erreurs : productions écrites "
                         "et orales, tuteur IA et exercices de grammaire.")
        self.stack = QStackedWidget()
        self.body.addWidget(self.stack, 1)
        self.items: list[CX.CustomExercise] = []
        self.idx = 0
        self.score = 0
        self.answered = False
        self.t0 = 0.0
        self.results: list[tuple[CX.CustomExercise, str, bool]] = []

        # --- accueil
        home = QWidget()
        hl = QVBoxLayout(home)
        hl.setContentsMargins(0, 0, 0, 0)
        card = Card("Vos difficultés récurrentes (90 derniers jours)")
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Difficulté", "Erreurs", "Repérée dans",
                                              "Exemples"])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setMinimumHeight(220)
        card.lay.addWidget(self.table)
        self.empty = QLabel("Aucune erreur enregistrée pour l'instant. Faites des exercices, "
                            "des productions écrites ou orales, ou discutez avec le tuteur : "
                            "vos difficultés apparaîtront ici. En attendant, une série de "
                            "diagnostic vous est proposée.")
        self.empty.setWordWrap(True)
        self.empty.setObjectName("Muted")
        card.lay.addWidget(self.empty)
        row = QHBoxLayout()
        row.addWidget(QLabel("Nombre d'exercices :"))
        self.count = QSpinBox()
        self.count.setRange(5, 30)
        self.count.setValue(10)
        row.addWidget(self.count)
        self.start_btn = QPushButton("Générer une série personnalisée")
        self.start_btn.setObjectName("Primary")
        self.start_btn.clicked.connect(self.start)
        row.addWidget(self.start_btn)
        row.addStretch(1)
        card.lay.addLayout(row)
        hl.addWidget(card)
        hl.addStretch(1)
        self.stack.addWidget(home)
        self.home = home

        # --- exercice
        run = QWidget()
        rl = QVBoxLayout(run)
        rl.setContentsMargins(0, 0, 0, 0)
        self.ex_card = Card()
        self.progress = QLabel()
        self.progress.setObjectName("Muted")
        self.ex_card.lay.addWidget(self.progress)
        self.origin = QLabel()
        self.origin.setWordWrap(True)
        self.origin.setStyleSheet(f"color:{ORANGE}")
        self.ex_card.lay.addWidget(self.origin)
        self.prompt = QLabel()
        self.prompt.setWordWrap(True)
        self.prompt.setStyleSheet("font-size:14pt")
        self.ex_card.lay.addWidget(self.prompt)
        self.opts_box = QVBoxLayout()
        self.ex_card.lay.addLayout(self.opts_box)
        self.opt_group = QButtonGroup(self)
        self.answer = QLineEdit()
        self.answer.setPlaceholderText("Votre réponse")
        self.answer.returnPressed.connect(self.validate)
        self.ex_card.lay.addWidget(self.answer)
        self.feedback = QLabel()
        self.feedback.setWordWrap(True)
        self.feedback.setTextFormat(Qt.RichText)
        self.feedback.setMinimumHeight(90)
        self.feedback.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self.feedback.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.MinimumExpanding)
        self.ex_card.lay.addWidget(self.feedback)
        b = QHBoxLayout()
        self.validate_btn = QPushButton("Valider")
        self.validate_btn.setObjectName("Primary")
        self.validate_btn.clicked.connect(self.validate)
        self.next_btn = QPushButton("Suivant ▶")
        self.next_btn.clicked.connect(self.next)
        quit_btn = QPushButton("Abandonner la série")
        quit_btn.clicked.connect(self.back)
        for w in (self.validate_btn, self.next_btn, quit_btn):
            b.addWidget(w)
        b.addStretch(1)
        self.ex_card.lay.addLayout(b)
        rl.addWidget(self.ex_card)
        rl.addStretch(1)
        self.stack.addWidget(run)
        self.run_view = run

        # --- bilan
        rep = QWidget()
        pl = QVBoxLayout(rep)
        pl.setContentsMargins(0, 0, 0, 0)
        self.report = QTextBrowser()
        self.report.setMinimumHeight(420)
        pl.addWidget(self.report, 1)
        bb = QHBoxLayout()
        again = QPushButton("Nouvelle série")
        again.setObjectName("Primary")
        again.clicked.connect(self.start)
        back = QPushButton("◀ Retour")
        back.clicked.connect(self.back)
        bb.addWidget(again)
        bb.addWidget(back)
        bb.addStretch(1)
        pl.addLayout(bb)
        self.stack.addWidget(rep)
        self.report_view = rep

    # ---------------------------------------------------------------- accueil
    def refresh(self) -> None:
        if self.stack.currentWidget() is not self.home:
            return
        with self.ctx.db.session() as s:
            ws: list[Weakness] = ET.weaknesses(s, limit=12)
        self.table.setRowCount(len(ws))
        for r, w in enumerate(ws):
            for c, v in enumerate((w.category, str(w.count),
                                   ", ".join(SRC.get(x, x) for x in w.sources),
                                   " · ".join(f"« {e[:40]} »" for e in w.examples))):
                self.table.setItem(r, c, QTableWidgetItem(v))
        self.table.resizeColumnsToContents()
        self.table.setVisible(bool(ws))
        self.empty.setVisible(not ws)
        self.start_btn.setText("Générer une série personnalisée" if ws else
                               "Commencer une série de diagnostic")

    def back(self) -> None:
        self.stack.setCurrentWidget(self.home)
        self.refresh()

    # ---------------------------------------------------------------- série
    def start(self) -> None:
        with self.ctx.db.session() as s:
            self.items = CX.build_session(s, self.count.value())
        self.idx, self.score, self.results = 0, 0, []
        self.t0 = time.monotonic()
        if not self.items:
            self.back()
            return
        self.stack.setCurrentWidget(self.run_view)
        self._show()

    def _show(self) -> None:
        ex = self.items[self.idx]
        self.answered = False
        self.progress.setText(f"Exercice {self.idx + 1} / {len(self.items)} · score "
                              f"{self.score}")
        self.origin.setText("Pourquoi cet exercice : " + ex.origin)
        self.prompt.setText(ex.prompt)
        for btn in self.opt_group.buttons():
            self.opt_group.removeButton(btn)
            btn.deleteLater()
        if ex.options:
            for o in ex.options:
                rb = QRadioButton(o)
                self.opt_group.addButton(rb)
                self.opts_box.addWidget(rb)
        self.answer.setVisible(not ex.options)
        self.answer.clear()
        self.answer.setEnabled(True)
        self.feedback.clear()
        self.validate_btn.setEnabled(True)
        self.next_btn.setEnabled(False)
        if not ex.options:
            self.answer.setFocus()

    def given(self) -> str:
        ex = self.items[self.idx]
        if ex.options:
            b = self.opt_group.checkedButton()
            return b.text() if b else ""
        return self.answer.text()

    def validate(self) -> None:
        if self.answered or not self.items:
            return
        ex = self.items[self.idx]
        given = self.given().strip()
        if not given:
            return
        ok, accents = CX.check(ex, given)
        self.answered = True
        self.score += int(ok)
        self.results.append((ex, given, ok))
        with self.ctx.db.session() as s:
            CX.record(s, ex, given, ok)
        if ok:
            head = f"<b style='color:{GREEN}'>✔ Correct !</b>"
        elif accents:
            head = (f"<b style='color:{ORANGE}'>≈ Presque : attention aux accents.</b> "
                    f"Réponse attendue : <b>{html.escape(ex.accepted[0])}</b>")
        else:
            head = (f"<b style='color:{RED}'>✘ Incorrect.</b> Réponse attendue : "
                    f"<b>{html.escape(ex.accepted[0])}</b>")
        self.feedback.setText(f"{head}<br><i>Correction :</i> {html.escape(ex.explanation)}")
        self.answer.setEnabled(False)
        self.validate_btn.setEnabled(False)
        self.next_btn.setEnabled(True)
        self.next_btn.setFocus()
        self.progress.setText(f"Exercice {self.idx + 1} / {len(self.items)} · score "
                              f"{self.score}")

    def next(self) -> None:
        if self.idx + 1 < len(self.items):
            self.idx += 1
            self._show()
        else:
            self._finish()

    def _finish(self) -> None:
        n = len(self.results)
        rate = self.score / n if n else 0.0
        with self.ctx.db.session() as s:
            CX.record_session(s, rate, time.monotonic() - self.t0)
        rows = "".join(
            f"<tr><td style='color:{GREEN if ok else RED}'>{'✔' if ok else '✘'}</td>"
            f"<td>{html.escape(ex.prompt)}</td><td>{html.escape(given)}</td>"
            f"<td><b>{html.escape(ex.accepted[0])}</b><br>"
            f"<span style='color:#666'>{html.escape(ex.explanation)}</span></td></tr>"
            for ex, given, ok in self.results)
        chapters = sorted({ex.meta.get("chapter_title") for ex, _, ok in self.results
                           if not ok and ex.meta.get("chapter_title")})
        advice = (("<p>À revoir dans le module Grammaire : " + ", ".join(
            f"<b>{html.escape(c)}</b>" for c in chapters) + ".</p>") if chapters else "")
        self.report.setHtml(
            f"<h2>Bilan de la série : {self.score} / {n} ({round(rate * 100)} %)</h2>"
            + advice + "<table cellpadding=5 border=0><tr><th></th><th>Exercice</th>"
            "<th>Votre réponse</th><th>Correction</th></tr>" + rows + "</table>")
        self.stack.setCurrentWidget(self.report_view)
