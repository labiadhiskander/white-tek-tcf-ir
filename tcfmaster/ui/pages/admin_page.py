"""Administration du contenu B2 (code PIN facultatif).

Ajouter, modifier, valider, masquer ou supprimer : vidéos, exercices CO/CE,
sujets EE et situations EO. Un contenu modifié ici n'est jamais écrasé par une
mise à jour ; un contenu préinstallé est masqué plutôt qu'effacé.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QComboBox, QDialog, QDialogButtonBox,
                               QFormLayout, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
                               QMessageBox, QPlainTextEdit, QPushButton,
                               QScrollArea, QSpinBox, QStackedWidget, QTableWidget,
                               QTableWidgetItem, QTabWidget, QVBoxLayout, QWidget)

from tcfmaster.db.models import (STATUS_VALID, Exercise, SpeakingTask, Video, WritingTask)
from tcfmaster.services import admin as AD
from tcfmaster.services import videos as VS
from tcfmaster.ui.widgets import Card, Page

TABS = [("video", "Vidéos"), ("exercise", "Exercices CO / CE"),
        ("writing", "Sujets EE"), ("speaking", "Situations EO")]
CREATABLE = {"video", "writing", "speaking"}


def _text(value: str = "", height: int = 70) -> QPlainTextEdit:
    w = QPlainTextEdit(value or "")
    w.setMinimumHeight(height)
    return w


class FormDialog(QDialog):
    """Petit formulaire générique : champs ligne, texte, liste et nombre."""

    def __init__(self, title: str, fields: list[tuple], parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(760, 640)
        self.widgets: dict[str, QWidget] = {}
        outer = QVBoxLayout(self)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        inner = QWidget()
        self.form = QFormLayout(inner)
        for key, label, kind, value in fields:
            if kind == "line":
                w = QLineEdit(str(value or ""))
            elif kind == "text":
                w = _text(value)
            elif kind == "lines":       # liste, un élément par ligne
                w = _text("\n".join(value or []))
            elif kind == "int":
                w = QSpinBox()
                w.setRange(1, 3)
                w.setValue(int(value or 1))
            else:                       # ("choice", [options])
                w = QComboBox()
                for opt in kind[1]:
                    w.addItem(opt)
                if value:
                    w.setCurrentText(value)
            self.widgets[key] = w
            self.form.addRow(label, w)
        scroll.setWidget(inner)
        outer.addWidget(scroll, 1)
        self.errors = QLabel()
        self.errors.setWordWrap(True)
        self.errors.setStyleSheet("color:#b3261e;")
        outer.addWidget(self.errors)
        bb = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        outer.addWidget(bb)

    def values(self) -> dict:
        out = {}
        for k, w in self.widgets.items():
            if isinstance(w, QLineEdit):
                out[k] = w.text().strip()
            elif isinstance(w, QSpinBox):
                out[k] = w.value()
            elif isinstance(w, QComboBox):
                out[k] = w.currentText()
            else:
                txt = w.toPlainText().strip()
                out[k] = txt
        return out


class AdminPage(Page):
    def __init__(self, ctx, parent=None):
        super().__init__(ctx, "Administration",
                         "Gérer le contenu B2 : ajouter, modifier, valider, masquer. Les "
                         "corrections restent obligatoires ; vos modifications ne sont jamais "
                         "écrasées par une mise à jour.", parent)
        self.unlocked = False
        self.stack = QStackedWidget()
        self.body.addWidget(self.stack)

        lock = Card("Accès protégé")
        lock.lay.addWidget(QLabel("Saisissez le code PIN de l'administration."))
        self.pin = QLineEdit()
        self.pin.setEchoMode(QLineEdit.Password)
        self.pin.setMaxLength(8)
        self.pin.returnPressed.connect(self.unlock)
        lock.lay.addWidget(self.pin)
        self.pin_msg = QLabel()
        lock.lay.addWidget(self.pin_msg)
        ok = QPushButton("Déverrouiller")
        ok.setObjectName("Primary")
        ok.clicked.connect(self.unlock)
        lock.lay.addWidget(ok, alignment=Qt.AlignLeft)
        self.lock_view = lock
        self.stack.addWidget(lock)

        main = QWidget()
        ml = QVBoxLayout(main)
        ml.setContentsMargins(0, 0, 0, 0)
        self.tabs = QTabWidget()
        self.tables: dict[str, QTableWidget] = {}
        self.searches: dict[str, QLineEdit] = {}
        for kind, label in TABS:
            self.tabs.addTab(self._build_tab(kind), label)
        self.tabs.addTab(self._build_pin_tab(), "Code PIN")
        ml.addWidget(self.tabs)
        self.msg = QLabel()
        self.msg.setWordWrap(True)
        ml.addWidget(self.msg)
        self.main_view = main
        self.stack.addWidget(main)

    # ------------------------------------------------------------ accès
    def refresh(self) -> None:
        with self.ctx.db.session() as s:
            protected = AD.has_pin(s)
        if protected and not self.unlocked:
            self.stack.setCurrentWidget(self.lock_view)
            return
        self.stack.setCurrentWidget(self.main_view)
        for kind in self.tables:
            self.load(kind)

    def unlock(self) -> bool:
        with self.ctx.db.session() as s:
            ok = AD.check_pin(s, self.pin.text())
        self.pin.clear()
        if not ok:
            self.pin_msg.setText("Code incorrect.")
            return False
        self.unlocked = True
        self.pin_msg.clear()
        self.refresh()
        return True

    def _build_pin_tab(self) -> QWidget:
        w = Card("Code PIN facultatif")
        w.lay.addWidget(QLabel("4 à 8 chiffres. Laissez vide puis enregistrez pour supprimer "
                               "la protection."))
        self.new_pin = QLineEdit()
        self.new_pin.setEchoMode(QLineEdit.Password)
        self.new_pin.setMaxLength(8)
        w.lay.addWidget(self.new_pin)
        b = QPushButton("Enregistrer le code")
        b.clicked.connect(self.save_pin)
        w.lay.addWidget(b, alignment=Qt.AlignLeft)
        return w

    def save_pin(self) -> None:
        try:
            with self.ctx.db.session() as s:
                AD.set_pin(s, self.new_pin.text().strip() or None)
        except ValueError as exc:
            self.msg.setText(str(exc))
            return
        self.msg.setText("Code PIN enregistré." if self.new_pin.text() else "Protection supprimée.")
        self.new_pin.clear()

    # ------------------------------------------------------------ tableaux
    def _build_tab(self, kind: str) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        search = QLineEdit()
        search.setPlaceholderText("Rechercher…")
        search.textChanged.connect(lambda _t, k=kind: self.load(k))
        lay.addWidget(search)
        t = QTableWidget(0, 6)
        t.setHorizontalHeaderLabels(["Code", "Rubrique", "Titre", "Statut", "Origine", "Modifié"])
        t.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        t.setSelectionBehavior(QTableWidget.SelectRows)
        t.setEditTriggers(QTableWidget.NoEditTriggers)
        t.doubleClicked.connect(lambda _i, k=kind: self.edit(k))
        lay.addWidget(t, 1)
        row = QHBoxLayout()
        buttons = [("Modifier", lambda k=kind: self.edit(k)),
                   ("Valider", lambda k=kind: self.set_status(k, True)),
                   ("Mettre en brouillon", lambda k=kind: self.set_status(k, False)),
                   ("Supprimer / masquer", lambda k=kind: self.delete(k)),
                   ("Rétablir l'original", lambda k=kind: self.restore(k))]
        if kind in CREATABLE:
            buttons.insert(0, ("Nouveau", lambda k=kind: self.edit(k, new=True)))
        if kind == "video":
            buttons.append(("Vérifier les liens", self.check_links))
        for label, fn in buttons:
            b = QPushButton(label)
            b.clicked.connect(fn)
            row.addWidget(b)
        row.addStretch(1)
        lay.addLayout(row)
        self.tables[kind] = t
        self.searches[kind] = search
        return w

    def load(self, kind: str) -> None:
        t = self.tables[kind]
        with self.ctx.db.session() as s:
            rows = AD.rows(s, kind, self.searches[kind].text())
        t.setRowCount(len(rows))
        for i, r in enumerate(rows):
            vals = [r.code, r.section, r.title,
                    "validé" if r.status == STATUS_VALID else r.status,
                    "administration" if r.origin == "admin" else "préinstallé",
                    "oui" if r.modified else ""]
            for j, val in enumerate(vals):
                it = QTableWidgetItem(val)
                if j == 0:
                    it.setData(256, r.id)
                t.setItem(i, j, it)

    def selected_id(self, kind: str) -> int | None:
        t = self.tables[kind]
        r = t.currentRow()
        if r < 0 or t.item(r, 0) is None:
            self.msg.setText("Sélectionnez d'abord une ligne.")
            return None
        return t.item(r, 0).data(256)

    def set_status(self, kind: str, valid: bool) -> None:
        oid = self.selected_id(kind)
        if oid is None:
            return
        with self.ctx.db.session() as s:
            AD.set_status(s, kind, oid, valid)
        self.msg.setText("Contenu validé et publié." if valid else "Contenu mis en brouillon (masqué).")
        self.load(kind)

    def delete(self, kind: str, confirm: bool = True) -> None:
        oid = self.selected_id(kind)
        if oid is None:
            return
        if confirm and QMessageBox.question(self, "Supprimer", "Supprimer ou masquer ce contenu ?") \
                != QMessageBox.Yes:
            return
        with self.ctx.db.session() as s:
            res = AD.delete(s, kind, oid)
        self.msg.setText(f"Contenu {res}.")
        self.load(kind)

    def restore(self, kind: str) -> None:
        oid = self.selected_id(kind)
        if oid is None:
            return
        with self.ctx.db.session() as s:
            AD.restore_original(s, kind, oid)
        self.msg.setText("Le contenu d'origine sera rétabli au prochain démarrage "
                         "(contenus préinstallés uniquement).")
        self.load(kind)

    def check_links(self) -> None:
        from tcfmaster.ui.speaking import run_background
        self.msg.setText("Vérification des liens en cours…")
        db = self.ctx.db

        def job():
            with db.session() as s:
                return VS.check_links(s, fetch=VS.check_url)

        def done(res):
            self.msg.setText(f"Vérification impossible : {res}" if isinstance(res, Exception)
                             else f"{res['ok']} lien(s) valide(s), {res['erreur']} en erreur.")
            self.load("video")

        run_background(self, job, done)

    # ------------------------------------------------------------ édition
    def edit(self, kind: str, new: bool = False) -> None:
        oid = None if new else self.selected_id(kind)
        if not new and oid is None:
            return
        dlg = self.make_dialog(kind, oid)
        while dlg.exec() == QDialog.Accepted:
            errs = self.save_dialog(kind, oid, dlg)
            if not errs:
                self.msg.setText("Modifications enregistrées.")
                self.load(kind)
                return
            dlg.errors.setText("\n".join(errs[:8]))

    def make_dialog(self, kind: str, oid: int | None):
        with self.ctx.db.session() as s:
            if kind == "video":
                v = s.get(Video, oid) if oid else None
                q = (v.exercise[0] if v and v.exercise else
                     {"prompt": "", "choices": ["", "", "", ""], "answer": 0,
                      "rationales": ["", "", "", ""], "explanation": ""})
                fields = [("title", "Titre", "line", v.title if v else ""),
                          ("category", "Catégorie", ("choice", list(VS.CATEGORIES)),
                           v.category if v else ""),
                          ("source", "Source", "line", v.source if v else ""),
                          ("url", "Lien (https)", "line", v.url if v else "https://"),
                          ("duration", "Durée", "line", v.duration if v else "variable"),
                          ("description", "Description", "text", v.description if v else ""),
                          ("q_prompt", "Question de l'exercice", "line", q["prompt"])]
                for j in range(4):
                    fields.append((f"q_choice{j}", f"Proposition {'ABCD'[j]}", "line",
                                   q["choices"][j]))
                    fields.append((f"q_why{j}", f"Justification {'ABCD'[j]}", "line",
                                   (q.get("rationales") or [""] * 4)[j]))
                fields.append(("q_answer", "Bonne réponse", ("choice", list("ABCD")),
                               "ABCD"[q["answer"]]))
                fields.append(("q_expl", "Correction", "text", q["explanation"]))
                return FormDialog("Fiche vidéo", fields, self)
            if kind == "writing":
                t = s.get(WritingTask, oid) if oid else None
                return FormDialog("Sujet d'expression écrite", [
                    ("task_number", "Tâche (1 à 3)", "int", t.task_number if t else 1),
                    ("task_type", "Type de tâche", "line", t.task_type if t else ""),
                    ("instructions", "Consigne", "text", t.instructions if t else ""),
                    ("model_answer", "Réponse modèle (limites de mots imposées)", "text",
                     t.model_answer if t else ""),
                    ("expected_points", "Points attendus (un par ligne)", "lines",
                     t.expected_points if t else []),
                    ("model_commentary", "Pourquoi c'est un B2", "text",
                     t.model_commentary if t else ""),
                    ("tips", "Conseils", "text", t.tips if t else "")], self)
            if kind == "speaking":
                t = s.get(SpeakingTask, oid) if oid else None
                return FormDialog("Situation d'expression orale", [
                    ("task_number", "Tâche (1 à 3)", "int", t.task_number if t else 1),
                    ("title", "Titre", "line", t.title if t else ""),
                    ("examiner_role", "Rôle de l'examinateur", "line",
                     t.examiner_role if t else "Examinateur"),
                    ("scenario", "Situation", "text", t.scenario if t else ""),
                    ("examiner_prompts", "Relances (une par ligne)", "lines",
                     t.examiner_prompts if t else []),
                    ("useful_phrases", "Phrases utiles (une par ligne)", "lines",
                     t.useful_phrases if t else []),
                    ("model_answer", "Réponse modèle", "text", t.model_answer if t else ""),
                    ("model_commentary", "Pourquoi c'est un B2", "text",
                     t.model_commentary if t else ""),
                    ("tips", "Conseils", "text", t.tips if t else "")], self)
            ex = s.get(Exercise, oid)
            fields = [("title", "Titre", "line", ex.title),
                      ("document", "Document / transcription", "text", ex.document)]
            for i, q in enumerate(ex.questions):
                fields.append((f"p{i}", f"Q{i + 1} – énoncé", "line", q.prompt))
                good = "A"
                for c in q.choices:
                    fields.append((f"c{i}{c.label}", f"Q{i + 1} – {c.label}", "line", c.text))
                    fields.append((f"r{i}{c.label}", f"Q{i + 1} – justification {c.label}",
                                   "line", c.rationale))
                    if c.is_correct:
                        good = c.label
                fields.append((f"g{i}", f"Q{i + 1} – bonne réponse", ("choice", list("ABCD")),
                               good))
                fields.append((f"e{i}", f"Q{i + 1} – correction", "text", q.explanation))
            dlg = FormDialog(f"Exercice {ex.code}", fields, self)
            dlg.n_questions = len(ex.questions)
            return dlg

    def save_dialog(self, kind: str, oid: int | None, dlg: FormDialog) -> list[str]:
        d = dlg.values()
        with self.ctx.db.session() as s:
            if kind == "video":
                ans = "ABCD".index(d["q_answer"])
                data = {k: d[k] for k in ("title", "category", "source", "url", "duration",
                                          "description")}
                data["exercise"] = [{"prompt": d["q_prompt"],
                                     "choices": [d[f"q_choice{j}"] for j in range(4)],
                                     "rationales": [d[f"q_why{j}"] for j in range(4)],
                                     "answer": ans, "explanation": d["q_expl"]}]
                _, errs = VS.save_video(s, data, oid)
                return errs
            if kind in ("writing", "speaking"):
                for k in ("expected_points", "examiner_prompts", "useful_phrases"):
                    if k in d:
                        d[k] = [x.strip() for x in d[k].splitlines() if x.strip()]
                save = AD.save_writing if kind == "writing" else AD.save_speaking
                _, errs = save(s, d, oid)
                return errs
            qs = []
            for i in range(dlg.n_questions):
                qs.append({"prompt": d[f"p{i}"], "explanation": d[f"e{i}"],
                           "choices": [{"text": d[f"c{i}{lab}"], "rationale": d[f"r{i}{lab}"],
                                        "correct": d[f"g{i}"] == lab} for lab in "ABCD"]})
            return AD.update_exercise(s, oid, {"title": d["title"], "document": d["document"],
                                               "questions": qs})

