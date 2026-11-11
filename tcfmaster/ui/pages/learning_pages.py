"""Pages : Vocabulaire B2, Grammaire, Conjugaison."""
from __future__ import annotations

import html
import time

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QButtonGroup, QComboBox, QHBoxLayout, QHeaderView, QLabel,
                               QLineEdit, QListWidget, QListWidgetItem, QPushButton,
                               QRadioButton, QSplitter, QTableWidget, QTableWidgetItem,
                               QTabWidget, QTextBrowser, QVBoxLayout, QWidget)

from tcfmaster.db.models import Expression, GrammarChapter, ReviewItem, VocabWord
from tcfmaster.services import learning as LS
from tcfmaster.services import review as RV
from tcfmaster.ui.widgets import Card, Page

LEVEL_FILTER = [("Tous niveaux", None), ("A2", "A2"), ("B1", "B1"), ("B2", "B2"), ("C1", "C1")]
KINDS = [("Expressions et formulations", "expression"), ("Phrases complexes", "phrase_complexe"),
         ("Exemples d'argumentation", "argumentation"),
         ("Connecteurs et transitions", "connecteur")]


def _md_to_html(text: str) -> str:
    """Rendu Markdown léger pour les cours (titres, gras, listes)."""
    import re
    out, in_list = [], False
    for line in (text or "").splitlines():
        esc = html.escape(line)
        esc = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", esc)
        esc = re.sub(r"\*(.+?)\*", r"<i>\1</i>", esc)
        if line.startswith("### "):
            out.append(f"<h4>{esc[4:]}</h4>"); continue
        if line.startswith("## "):
            out.append(f"<h3>{esc[3:]}</h3>"); continue
        if line.startswith(("- ", "* ")):
            if not in_list:
                out.append("<ul>"); in_list = True
            out.append(f"<li>{esc[2:]}</li>"); continue
        if in_list:
            out.append("</ul>"); in_list = False
        out.append(f"<p>{esc}</p>" if esc.strip() else "")
    if in_list:
        out.append("</ul>")
    return "".join(out)


# =========================================================================
class VocabularyPage(Page):
    def __init__(self, ctx):
        super().__init__(ctx, "Vocabulaire B2",
                         "Construire des phrases riches, fluides et naturelles : expressions, "
                         "connecteurs, phrases complexes et vocabulaire en contexte.")
        tabs = QTabWidget()
        self.body.addWidget(tabs)
        tabs.addTab(self._build_expressions(), "Expressions et phrases")
        tabs.addTab(self._build_vocab(), "Vocabulaire par thème")
        tabs.addTab(self._build_review(), "Révision du jour")
        self.tabs = tabs

    # ------------------------------------------------------ expressions
    def _build_expressions(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        row = QHBoxLayout()
        self.kind = QComboBox()
        for lab, val in KINDS:
            self.kind.addItem(lab, val)
        self.category = QComboBox()
        self.exp_level = QComboBox()
        for lab, val in LEVEL_FILTER:
            self.exp_level.addItem(lab, val)
        self.exp_search = QLineEdit()
        self.exp_search.setPlaceholderText("Rechercher…")
        for x in (self.kind, self.category, self.exp_level):
            row.addWidget(x)
        row.addWidget(self.exp_search, 1)
        lay.addLayout(row)
        split = QSplitter()
        self.exp_list = QListWidget()
        self.exp_list.setMinimumWidth(320)
        split.addWidget(self.exp_list)
        right = QWidget()
        rl = QVBoxLayout(right)
        self.exp_detail = QTextBrowser()
        rl.addWidget(self.exp_detail, 1)
        self.exp_answer = QLineEdit()
        self.exp_answer.setPlaceholderText("Votre réponse à l'exercice de réutilisation…")
        rl.addWidget(self.exp_answer)
        br = QHBoxLayout()
        self.exp_check = QPushButton("Voir la correction")
        self.exp_check.setObjectName("Primary")
        self.exp_check.clicked.connect(self._exp_correction)
        self.exp_known = QPushButton("✔ Je maîtrise")
        self.exp_known.clicked.connect(lambda: self._exp_review(5))
        self.exp_again = QPushButton("↻ À revoir")
        self.exp_again.clicked.connect(lambda: self._exp_review(2))
        for b in (self.exp_check, self.exp_known, self.exp_again):
            br.addWidget(b)
        rl.addLayout(br)
        self.exp_feedback = QLabel()
        self.exp_feedback.setWordWrap(True)
        rl.addWidget(self.exp_feedback)
        split.addWidget(right)
        split.setStretchFactor(1, 2)
        split.setMinimumHeight(480)
        lay.addWidget(split)
        self.kind.currentIndexChanged.connect(self._reload_categories)
        self.category.currentIndexChanged.connect(self._reload_expressions)
        self.exp_level.currentIndexChanged.connect(self._reload_expressions)
        self.exp_search.textChanged.connect(self._reload_expressions)
        self.exp_list.currentItemChanged.connect(self._show_expression)
        return w

    def _reload_categories(self):
        self.category.blockSignals(True)
        self.category.clear()
        self.category.addItem("Toutes catégories", None)
        with self.ctx.db.session() as s:
            for c in LS.expression_categories(s, self.kind.currentData()):
                self.category.addItem(c, c)
        self.category.blockSignals(False)
        self._reload_expressions()

    def _reload_expressions(self):
        self.exp_list.clear()
        with self.ctx.db.session() as s:
            for e in LS.search_expressions(s, self.kind.currentData(),
                                           self.category.currentData(),
                                           self.exp_level.currentData(),
                                           self.exp_search.text() or None):
                it = QListWidgetItem(f"[{e.level}] {e.text}")
                it.setData(Qt.UserRole, e.id)
                self.exp_list.addItem(it)
        if self.exp_list.count():
            self.exp_list.setCurrentRow(0)
        else:
            self.exp_detail.setHtml("<p>Aucun élément pour ce filtre.</p>")

    def _current_expression(self, s) -> Expression | None:
        it = self.exp_list.currentItem()
        return s.get(Expression, it.data(Qt.UserRole)) if it else None

    def _show_expression(self, *_):
        self.exp_answer.clear()
        self.exp_feedback.clear()
        with self.ctx.db.session() as s:
            e = self._current_expression(s)
            if not e:
                return
            self.exp_detail.setHtml(
                f"<h2>{html.escape(e.text)}</h2>"
                f"<p><b>Catégorie :</b> {html.escape(e.category)} · <b>Niveau CECRL estimé :</b> "
                f"{e.level}</p>"
                f"<p><b>1. Signification :</b> {html.escape(e.meaning)}</p>"
                f"<p><b>2. Exemple d'utilisation :</b> <i>{html.escape(e.example)}</i></p>"
                f"<p><b>3. Équivalent simple :</b> {html.escape(e.simple_equivalent)}</p>"
                f"<p><b>4. Exercice de réutilisation :</b> {html.escape(e.exercise)}</p>")

    def _exp_correction(self):
        with self.ctx.db.session() as s:
            e = self._current_expression(s)
            if not e:
                return
            given = self.exp_answer.text().strip()
            used = LS.normalize(e.text.rstrip("….").split("…")[0])[:25] in LS.normalize(given)
            msg = ""
            if given:
                msg = ("✔ Vous avez bien réemployé l'expression. " if used else
                       "✘ L'expression n'apparaît pas dans votre réponse. ")
            self.exp_feedback.setText(
                f"{msg}<br><b>Proposition de correction :</b> {html.escape(e.exercise_answer)}")

    def _exp_review(self, quality: int):
        with self.ctx.db.session() as s:
            e = self._current_expression(s)
            if e:
                RV.review(s, "expression", e.id, quality)
        row = self.exp_list.currentRow()
        if row < self.exp_list.count() - 1:
            self.exp_list.setCurrentRow(row + 1)

    # ------------------------------------------------------ vocabulaire
    def _build_vocab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        row = QHBoxLayout()
        self.theme = QComboBox()
        self.voc_level = QComboBox()
        for lab, val in LEVEL_FILTER:
            self.voc_level.addItem(lab, val)
        self.voc_search = QLineEdit()
        self.voc_search.setPlaceholderText("Rechercher un mot…")
        row.addWidget(self.theme)
        row.addWidget(self.voc_level)
        row.addWidget(self.voc_search, 1)
        lay.addLayout(row)
        self.voc_table = QTableWidget(0, 6)
        self.voc_table.setHorizontalHeaderLabels(["Mot", "Nature", "Niveau", "Définition",
                                                  "Exemple en contexte", "Synonymes"])
        self.voc_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.voc_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.Stretch)
        self.voc_table.verticalHeader().setVisible(False)
        self.voc_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.voc_table.setWordWrap(True)
        self.voc_table.setMinimumHeight(480)
        lay.addWidget(self.voc_table)
        self.voc_count = QLabel()
        self.voc_count.setObjectName("Muted")
        lay.addWidget(self.voc_count)
        self.theme.currentIndexChanged.connect(self._reload_vocab)
        self.voc_level.currentIndexChanged.connect(self._reload_vocab)
        self.voc_search.textChanged.connect(self._reload_vocab)
        return w

    def _reload_vocab(self):
        with self.ctx.db.session() as s:
            words = LS.search_vocab(s, self.theme.currentData(), self.voc_level.currentData(),
                                    self.voc_search.text() or None)
            self.voc_table.setRowCount(len(words))
            for r, wd in enumerate(words):
                nature = wd.pos + (f" ({wd.gender})" if wd.gender else "")
                for c, val in enumerate([wd.word, nature, wd.level, wd.definition,
                                         wd.example, wd.synonyms]):
                    self.voc_table.setItem(r, c, QTableWidgetItem(val))
            self.voc_count.setText(f"{len(words)} mots affichés.")
        self.voc_table.resizeRowsToContents()

    # ---------------------------------------------------------- révision
    def _build_review(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        self.rev_info = QLabel()
        self.rev_info.setObjectName("Muted")
        lay.addWidget(self.rev_info)
        self.rev_card = QTextBrowser()
        self.rev_card.setMinimumHeight(260)
        lay.addWidget(self.rev_card)
        row = QHBoxLayout()
        self.rev_show = QPushButton("Afficher la réponse")
        self.rev_show.setObjectName("Primary")
        self.rev_show.clicked.connect(self._rev_reveal)
        row.addWidget(self.rev_show)
        self.rev_btns = []
        for lab, q in (("Oublié", 1), ("Difficile", 3), ("Bien", 4), ("Facile", 5)):
            b = QPushButton(lab)
            b.clicked.connect(lambda _=False, qq=q: self._rev_grade(qq))
            b.setEnabled(False)
            row.addWidget(b)
            self.rev_btns.append(b)
        lay.addLayout(row)
        lay.addStretch(1)
        self.rev_queue: list[tuple[str, int]] = []
        return w

    def _load_review(self):
        with self.ctx.db.session() as s:
            due = RV.due_items(s, limit=40)
            self.rev_queue = [(d.item_type, d.item_id) for d in due
                              if d.item_type in ("expression", "vocab")]
            acquired = RV.acquired_count(s, "expression") + RV.acquired_count(s, "vocab")
        self.rev_info.setText(f"{len(self.rev_queue)} élément(s) à réviser aujourd'hui · "
                              f"{acquired} élément(s) acquis.")
        self._rev_next()

    def _rev_next(self):
        for b in self.rev_btns:
            b.setEnabled(False)
        if not self.rev_queue:
            self.rev_card.setHtml("<h3>Aucune révision en attente.</h3><p>Marquez des "
                                  "expressions « À revoir » ou « Je maîtrise » pour alimenter "
                                  "la répétition espacée.</p>")
            self.rev_show.setEnabled(False)
            return
        self.rev_show.setEnabled(True)
        t, i = self.rev_queue[0]
        with self.ctx.db.session() as s:
            if t == "expression":
                e = s.get(Expression, i)
                self.rev_card.setHtml(f"<h2>{html.escape(e.text)}</h2><p>Que signifie cette "
                                      f"expression ? Employez-la dans une phrase.</p>")
            else:
                v = s.get(VocabWord, i)
                self.rev_card.setHtml(f"<h2>{html.escape(v.word)}</h2><p>Définition ?</p>")

    def _rev_reveal(self):
        if not self.rev_queue:
            return
        t, i = self.rev_queue[0]
        with self.ctx.db.session() as s:
            if t == "expression":
                e = s.get(Expression, i)
                extra = (f"<p><b>Sens :</b> {html.escape(e.meaning)}</p><p><b>Exemple :</b> "
                         f"<i>{html.escape(e.example)}</i></p>")
            else:
                v = s.get(VocabWord, i)
                extra = (f"<p><b>Définition :</b> {html.escape(v.definition)}</p><p><b>Exemple :"
                         f"</b> <i>{html.escape(v.example)}</i></p>")
        self.rev_card.append(extra)
        for b in self.rev_btns:
            b.setEnabled(True)

    def _rev_grade(self, q: int):
        t, i = self.rev_queue.pop(0)
        with self.ctx.db.session() as s:
            RV.review(s, t, i, q)
        self._rev_next()

    def refresh(self):
        th = self.theme.currentData()
        self.theme.blockSignals(True)
        self.theme.clear()
        self.theme.addItem("Tous les thèmes", None)
        with self.ctx.db.session() as s:
            for t in LS.vocab_themes(s):
                self.theme.addItem(t, t)
        idx = self.theme.findData(th)
        self.theme.setCurrentIndex(max(0, idx))
        self.theme.blockSignals(False)
        self._reload_categories()
        self._reload_vocab()
        self._load_review()


# =========================================================================
class GrammarPage(Page):
    MODULE = "grammaire"

    def __init__(self, ctx, title="Grammaire",
                 subtitle="Cours, exemples simples et de niveau B2, exercices corrigés et "
                          "évaluation de la maîtrise pour chaque chapitre."):
        super().__init__(ctx, title, subtitle)
        split = QSplitter()
        self.chapter_list = QListWidget()
        self.chapter_list.setMinimumWidth(260)
        split.addWidget(self.chapter_list)
        right = QTabWidget()
        self.lesson = QTextBrowser()
        right.addTab(self.lesson, "Cours")
        right.addTab(self._build_exercises(), "Exercices")
        self.right_tabs = right
        split.addWidget(right)
        split.setStretchFactor(1, 3)
        split.setMinimumHeight(560)
        self.body.addWidget(split)
        self.chapter_list.currentItemChanged.connect(self._show_chapter)

    def _build_exercises(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        self.ex_header = QLabel()
        self.ex_header.setObjectName("Muted")
        lay.addWidget(self.ex_header)
        self.ex_prompt = QLabel()
        self.ex_prompt.setWordWrap(True)
        self.ex_prompt.setObjectName("H2")
        lay.addWidget(self.ex_prompt)
        self.ex_options_box = QVBoxLayout()
        lay.addLayout(self.ex_options_box)
        self.ex_input = QLineEdit()
        self.ex_input.setPlaceholderText("Votre réponse…")
        self.ex_input.returnPressed.connect(self.check_exercise)
        lay.addWidget(self.ex_input)
        row = QHBoxLayout()
        self.ex_check = QPushButton("Corriger")
        self.ex_check.setObjectName("Primary")
        self.ex_check.clicked.connect(self.check_exercise)
        self.ex_next = QPushButton("Exercice suivant ▶")
        self.ex_next.clicked.connect(self.next_exercise)
        row.addWidget(self.ex_check)
        row.addWidget(self.ex_next)
        row.addStretch(1)
        lay.addLayout(row)
        self.ex_feedback = QTextBrowser()
        self.ex_feedback.setMinimumHeight(140)
        lay.addWidget(self.ex_feedback)
        self.mastery = QLabel()
        self.mastery.setObjectName("H2")
        lay.addWidget(self.mastery)
        lay.addStretch(1)
        self.opt_group = QButtonGroup(self)
        return w

    def refresh(self):
        cur = self.chapter_list.currentRow()
        self.chapter_list.clear()
        with self.ctx.db.session() as s:
            for ch in LS.chapters(s, self.MODULE):
                m = LS.chapter_mastery(s, ch.slug)
                it = QListWidgetItem(f"{ch.title}  ·  {ch.level}\n{LS.mastery_label(m)}")
                it.setData(Qt.UserRole, ch.id)
                self.chapter_list.addItem(it)
        if self.chapter_list.count():
            self.chapter_list.setCurrentRow(max(0, cur))
        else:
            self.lesson.setHtml("<p>Aucun chapitre installé.</p>")

    def _show_chapter(self, *_):
        it = self.chapter_list.currentItem()
        if not it:
            return
        with self.ctx.db.session() as s:
            ch = s.get(GrammarChapter, it.data(Qt.UserRole))
            simple = "".join(f"<li>{html.escape(x)}</li>" for x in ch.simple_examples)
            b2 = "".join(f"<li>{html.escape(x)}</li>" for x in ch.b2_examples)
            self.lesson.setHtml(f"<h2>{html.escape(ch.title)}</h2>{_md_to_html(ch.lesson)}"
                                f"<h3>Exemples simples</h3><ul>{simple}</ul>"
                                f"<h3>Exemples de niveau B2</h3><ul>{b2}</ul>")
            self.ex_ids = [e.id for e in ch.exercises]
            self.ch_slug = ch.slug
        self.ex_idx = 0
        self.ex_results: list[bool] = []
        self.ex_started = time.monotonic()
        self._show_exercise()

    def _show_exercise(self):
        from tcfmaster.db.models import GrammarExercise
        while self.ex_options_box.count():
            wdg = self.ex_options_box.takeAt(0).widget()
            if wdg:
                self.opt_group.removeButton(wdg)
                wdg.deleteLater()
        self.ex_feedback.clear()
        self.ex_answered = False
        if not getattr(self, "ex_ids", None):
            self.ex_prompt.setText("Aucun exercice pour ce chapitre.")
            return
        if self.ex_idx >= len(self.ex_ids):
            self._finish_chapter()
            return
        with self.ctx.db.session() as s:
            ex = s.get(GrammarExercise, self.ex_ids[self.ex_idx])
            self.ex_header.setText(f"Exercice {self.ex_idx + 1} / {len(self.ex_ids)} · "
                                   f"{ex.level} · {ex.ex_type}")
            self.ex_prompt.setText(ex.prompt)
            is_qcm = ex.ex_type == "qcm"
            self.ex_input.setVisible(not is_qcm)
            self.ex_input.clear()
            if is_qcm:
                for o in ex.options or []:
                    rb = QRadioButton(o)
                    self.opt_group.addButton(rb)
                    self.ex_options_box.addWidget(rb)
        self.ex_check.setEnabled(True)

    def given_answer(self) -> str:
        b = self.opt_group.checkedButton()
        if self.ex_input.isVisible() or b is None:
            return self.ex_input.text() if b is None else b.text()
        return b.text()

    def check_exercise(self):
        from tcfmaster.db.models import GrammarExercise
        if self.ex_answered or not getattr(self, "ex_ids", None) \
                or self.ex_idx >= len(self.ex_ids):
            return
        given = self.given_answer().strip()
        if not given:
            return
        with self.ctx.db.session() as s:
            ex = s.get(GrammarExercise, self.ex_ids[self.ex_idx])
            ok, ok_noacc = LS.check_answer(given, ex.accepted_answers())
            LS.record_exercise(s, ex, given, ok)
            head = ("<b style='color:#2E8B57'>✔ Correct</b>" if ok else
                    "<b style='color:#C98A0B'>≈ Presque : attention aux accents</b>" if ok_noacc
                    else "<b style='color:#C0392B'>✘ Incorrect</b>")
            self.ex_feedback.setHtml(
                f"{head}<br>Réponse attendue : <b>{html.escape(ex.accepted_answers()[0])}</b>"
                f"<br><br><b>Correction détaillée :</b> {html.escape(ex.explanation)}")
        self.ex_results.append(ok)
        self.ex_answered = True
        self.ex_check.setEnabled(False)

    def next_exercise(self):
        if not self.ex_answered and getattr(self, "ex_ids", None) \
                and self.ex_idx < len(self.ex_ids):
            self.ex_results.append(False)
        self.ex_idx += 1
        self._show_exercise()

    def _finish_chapter(self):
        score = sum(self.ex_results) / len(self.ex_results) if self.ex_results else 0
        with self.ctx.db.session() as s:
            LS.record_chapter_session(s, self.ch_slug, score,
                                      time.monotonic() - self.ex_started)
            m = LS.chapter_mastery(s, self.ch_slug)
        self.ex_prompt.setText(f"Série terminée : {sum(self.ex_results)} / "
                               f"{len(self.ex_results)} bonnes réponses.")
        self.ex_input.setVisible(False)
        self.ex_check.setEnabled(False)
        self.mastery.setText(f"Évaluation de la maîtrise : {LS.mastery_label(m)} "
                             f"({round((m or 0) * 100)} %)")


# =========================================================================
class ConjugationPage(GrammarPage):
    MODULE = "conjugaison"

    def __init__(self, ctx):
        super().__init__(ctx, "Conjugaison",
                         "Cours sur les temps, tableaux de conjugaison et entraînement "
                         "intensif.")
        card = Card("Tableau de conjugaison")
        row = QHBoxLayout()
        self.verb_input = QLineEdit()
        self.verb_input.setPlaceholderText("Infinitif (ex. : prendre)")
        self.verb_input.returnPressed.connect(self.show_verb)
        b = QPushButton("Conjuguer")
        b.clicked.connect(self.show_verb)
        row.addWidget(self.verb_input, 1)
        row.addWidget(b)
        card.lay.addLayout(row)
        self.verb_table = QTextBrowser()
        self.verb_table.setMinimumHeight(300)
        card.lay.addWidget(self.verb_table)
        self.body.addWidget(card)

        quiz = Card("Entraînement rapide")
        self.quiz_label = QLabel()
        self.quiz_label.setObjectName("H2")
        quiz.lay.addWidget(self.quiz_label)
        self.quiz_input = QLineEdit()
        self.quiz_input.returnPressed.connect(self.check_quiz)
        quiz.lay.addWidget(self.quiz_input)
        r2 = QHBoxLayout()
        c = QPushButton("Corriger")
        c.setObjectName("Primary")
        c.clicked.connect(self.check_quiz)
        n = QPushButton("Autre verbe ▶")
        n.clicked.connect(self.new_quiz)
        r2.addWidget(c)
        r2.addWidget(n)
        r2.addStretch(1)
        quiz.lay.addLayout(r2)
        self.quiz_feedback = QLabel()
        self.quiz_feedback.setWordWrap(True)
        quiz.lay.addWidget(self.quiz_feedback)
        self.body.addWidget(quiz)
        self.quiz = None

    def refresh(self):
        super().refresh()
        if self.quiz is None:
            self.new_quiz()

    def show_verb(self):
        with self.ctx.db.session() as s:
            v = LS.find_verb(s, self.verb_input.text())
            if v is None:
                self.verb_table.setHtml("<p>Verbe introuvable dans la base.</p>")
                return
            cells = []
            for t, forms in v.conjugations.items():
                persons = LS.PERSONS if t != "imperatif" else ["", "", ""]
                rows = "".join(f"<tr><td style='color:#5F6B7A'>{p}</td><td>{html.escape(f)}</td>"
                               f"</tr>" for p, f in zip(persons, forms) if f)
                cells.append(f"<td valign='top' style='padding:8px'><b>"
                             f"{LS.TENSE_LABELS.get(t, t)}</b><table>{rows}</table></td>")
            grid = "".join("<tr>" + "".join(cells[i:i + 3]) + "</tr>"
                           for i in range(0, len(cells), 3))
            self.verb_table.setHtml(f"<h3>{v.infinitive} ({v.group}ᵉ groupe, auxiliaire "
                                    f"{v.auxiliary})</h3><table>{grid}</table>")

    def new_quiz(self):
        with self.ctx.db.session() as s:
            self.quiz = LS.conjugation_quiz(s)
        self.quiz_feedback.clear()
        self.quiz_input.clear()
        if not self.quiz:
            self.quiz_label.setText("Aucun verbe installé.")
            return
        q = self.quiz
        self.quiz_label.setText(f"{q['verb']} → {q['tense_label']}, {q['person']}")

    def check_quiz(self):
        if not self.quiz or not self.quiz_input.text().strip():
            return
        ok, near = LS.check_conjugation(self.quiz_input.text(), self.quiz["answer"])
        if ok:
            self.quiz_feedback.setText("✔ Correct !")
        else:
            self.quiz_feedback.setText(
                ("≈ Presque (accents). " if near else "✘ Incorrect. ")
                + f"Réponse attendue : <b>{html.escape(self.quiz['answer'])}</b>")
