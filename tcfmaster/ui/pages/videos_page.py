"""Vidéothèque B2 : 12 catégories, liens officiels, exercice corrigé par fiche."""
from __future__ import annotations

from html import escape

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QButtonGroup, QComboBox, QHBoxLayout, QLabel, QLineEdit,
                               QListWidget, QListWidgetItem, QPushButton, QRadioButton,
                               QTextBrowser, QVBoxLayout, QWidget)

from tcfmaster.db.models import Video
from tcfmaster.services import videos as VS
from tcfmaster.ui.speaking import run_background
from tcfmaster.ui.widgets import Card, Page

NOTICE = ("Les vidéos s'ouvrent sur les sites officiels, dans votre navigateur : elles ne sont "
          "ni téléchargées ni redistribuées. Utilisez « Vérifier les liens » pour tester chaque "
          "lien depuis votre ordinateur ; un lien qui ne répond plus est masqué.")


class VideosPage(Page):
    def __init__(self, ctx, parent=None):
        super().__init__(ctx, "Vidéothèque B2",
                         "Ressources gratuites et officielles pour préparer le TCF IRN, classées "
                         "en 12 catégories, chacune avec un exercice corrigé.", parent)
        self.current_id: int | None = None
        self.checking = False

        top = Card()
        row = QHBoxLayout()
        self.category = QComboBox()
        self.category.addItem("Toutes les catégories", None)
        for c in VS.CATEGORIES:
            self.category.addItem(c, c)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Rechercher (titre, source, description)…")
        self.check_btn = QPushButton("Vérifier les liens")
        self.check_btn.clicked.connect(self.check_links)
        row.addWidget(self.category, 2)
        row.addWidget(self.search, 3)
        row.addWidget(self.check_btn)
        top.lay.addLayout(row)
        self.notice = QLabel(NOTICE)
        self.notice.setObjectName("Muted")
        self.notice.setWordWrap(True)
        top.lay.addWidget(self.notice)
        self.status = QLabel()
        self.status.setObjectName("Muted")
        top.lay.addWidget(self.status)
        self.body.addWidget(top)

        main = QHBoxLayout()
        self.list = QListWidget()
        self.list.setMinimumWidth(340)
        self.list.currentItemChanged.connect(self._select)
        main.addWidget(self.list, 2)

        detail = Card()
        self.detail = QTextBrowser()
        self.detail.setOpenExternalLinks(False)
        self.detail.setMinimumHeight(220)
        detail.lay.addWidget(self.detail)
        self.open_btn = QPushButton("Ouvrir dans le navigateur")
        self.open_btn.setObjectName("Primary")
        self.open_btn.clicked.connect(self.open_current)
        detail.lay.addWidget(self.open_btn)

        self.ex_box = QWidget()
        self.ex_lay = QVBoxLayout(self.ex_box)
        self.ex_lay.setContentsMargins(0, 8, 0, 0)
        detail.lay.addWidget(self.ex_box)
        main.addWidget(detail, 3)
        self.body.addLayout(main)

        self.category.currentIndexChanged.connect(self.refresh)
        self.search.textChanged.connect(self.refresh)
        self._groups: list[QButtonGroup] = []
        self._feedback: list[QLabel] = []

    # ------------------------------------------------------------ liste
    def refresh(self) -> None:
        keep = self.current_id
        self.list.blockSignals(True)
        self.list.clear()
        with self.ctx.db.session() as s:
            vids = VS.list_videos(s, self.category.currentData(), search=self.search.text())
            for v in vids:
                it = QListWidgetItem(f"{v.title}\n{v.category} · {v.source}")
                it.setData(256, v.id)
                self.list.addItem(it)
            total = len(VS.list_videos(s))
            hidden = len(VS.list_videos(s, include_hidden=True)) - total
        self.list.blockSignals(False)
        msg = f"{total} fiche(s) disponible(s)."
        if hidden:
            msg += f" {hidden} masquée(s) (brouillon ou lien en erreur)."
        if not self.checking:
            self.status.setText(msg)
        target = 0
        for i in range(self.list.count()):
            if self.list.item(i).data(256) == keep:
                target = i
        if self.list.count():
            self.list.setCurrentRow(target)
            self._select(self.list.currentItem())
        else:
            self.current_id = None
            self.detail.setHtml("<p>Aucune fiche ne correspond à votre recherche.</p>")
            self._clear_exercise()

    def show_video(self, video_id: int):
        self.category.setCurrentIndex(0)
        self.search.clear()
        self.current_id = video_id
        self.refresh()
        return self

    # ------------------------------------------------------------ fiche
    def _select(self, item) -> None:
        if item is None:
            return
        self.current_id = item.data(256)
        with self.ctx.db.session() as s:
            v = s.get(Video, self.current_id)
            desc = "".join(f"<p>{escape(p)}</p>" for p in v.description.split("\n\n"))
            self.detail.setHtml(
                f"<h2>{escape(v.title)}</h2>"
                f"<p><b>Catégorie :</b> {escape(v.category)} &nbsp;·&nbsp; <b>Source :</b> "
                f"{escape(v.source)} &nbsp;·&nbsp; <b>Durée :</b> {escape(v.duration or 'variable')}"
                f" &nbsp;·&nbsp; <b>Niveau :</b> {escape(v.level)}</p>{desc}"
                f"<p><b>Lien :</b> {escape(v.url)}<br><i>{escape(VS.link_label(v))}</i></p>")
            exercise = list(v.exercise or [])
        self._build_exercise(exercise)

    def _clear_exercise(self) -> None:
        while self.ex_lay.count():
            w = self.ex_lay.takeAt(0).widget()
            if w is not None:
                w.deleteLater()
        self._groups, self._feedback = [], []

    def _build_exercise(self, exercise: list[dict]) -> None:
        self._clear_exercise()
        if not exercise:
            return
        head = QLabel("Exercice associé (correction immédiate)")
        head.setObjectName("H2")
        self.ex_lay.addWidget(head)
        for i, q in enumerate(exercise):
            lab = QLabel(f"{i + 1}. {q['prompt']}")
            lab.setWordWrap(True)
            self.ex_lay.addWidget(lab)
            group = QButtonGroup(self)
            for j, c in enumerate(q["choices"]):
                rb = QRadioButton(f"{'ABCD'[j]}. {c}")
                group.addButton(rb, j)
                self.ex_lay.addWidget(rb)
            fb = QLabel()
            fb.setWordWrap(True)
            fb.hide()
            self.ex_lay.addWidget(fb)
            group.idClicked.connect(lambda choice, i=i: self.answer(i, choice))
            self._groups.append(group)
            self._feedback.append(fb)

    def answer(self, index: int, choice: int) -> bool:
        with self.ctx.db.session() as s:
            ok, text = VS.check_answer(s.get(Video, self.current_id), index, choice)
        fb = self._feedback[index]
        fb.setText(("✔ " if ok else "✘ ") + text)
        fb.setObjectName("Success" if ok else "Error")
        fb.setStyleSheet("color:#1b7a3d;" if ok else "color:#b3261e;")
        fb.show()
        for b in self._groups[index].buttons():
            b.setEnabled(False)
        return ok

    def open_current(self) -> None:
        if self.current_id is None:
            return
        with self.ctx.db.session() as s:
            url = s.get(Video, self.current_id).url
        QDesktopServices.openUrl(QUrl(url))

    # ------------------------------------------------------------ liens
    def check_links(self) -> None:
        if self.checking:
            return
        self.checking = True
        self.check_btn.setEnabled(False)
        self.status.setText("Vérification des liens en cours…")
        db = self.ctx.db

        def job():
            with db.session() as s:
                return VS.check_links(s, fetch=VS.check_url)

        run_background(self, job, self._checked)

    def _checked(self, res) -> None:
        self.checking = False
        self.check_btn.setEnabled(True)
        self.refresh()
        if isinstance(res, Exception):
            self.status.setText(f"Vérification impossible : {res}")
        else:
            self.status.setText(f"Vérification terminée : {res['ok']} lien(s) valide(s), "
                                f"{res['erreur']} en erreur (masqués).")
