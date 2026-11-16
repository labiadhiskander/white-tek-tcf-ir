"""Page « Programme intensif 30 jours » : les quatre compétences chaque jour,
examens blancs B2 aux jours 10, 20 et 29."""
from __future__ import annotations

from html import escape

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
                               QMessageBox, QProgressBar, QPushButton, QVBoxLayout, QWidget)

from tcfmaster.core import levels as L
from tcfmaster.db.models import IntensiveDay
from tcfmaster.services import intensive as IS
from tcfmaster.ui.widgets import Card, Page, disclaimer_label


class IntensivePage(Page):
    def __init__(self, ctx):
        super().__init__(ctx, "Programme intensif 30 jours",
                         "Environ 2 heures par jour, les quatre compétences chaque jour, un "
                         "examen blanc B2 complet aux jours 10, 20 et 29. Il complète le "
                         "programme de 12 semaines.")
        top = Card()
        row = QHBoxLayout()
        self.bar = QProgressBar()
        row.addWidget(self.bar, 3)
        self.start_btn = QPushButton("Démarrer aujourd'hui")
        self.start_btn.setObjectName("Primary")
        self.start_btn.clicked.connect(self.start_today)
        self.reset_btn = QPushButton("Recommencer le programme")
        self.reset_btn.clicked.connect(self.reset)
        row.addWidget(self.start_btn)
        row.addWidget(self.reset_btn)
        top.lay.addLayout(row)
        self.info = QLabel()
        self.info.setWordWrap(True)
        self.info.setObjectName("Muted")
        top.lay.addWidget(self.info)
        self.body.addWidget(top)

        main = QHBoxLayout()
        self.days = QListWidget()
        self.days.setMinimumWidth(320)
        self.days.currentItemChanged.connect(self._load_day)
        main.addWidget(self.days, 2)
        right = QVBoxLayout()
        self.day_card = Card("Activités du jour")
        self.day_title = QLabel()
        self.day_title.setObjectName("H2")
        self.day_title.setWordWrap(True)
        self.day_advice = QLabel()
        self.day_advice.setWordWrap(True)
        self.day_advice.setObjectName("Muted")
        self.day_card.lay.addWidget(self.day_title)
        self.day_card.lay.addWidget(self.day_advice)
        self.acts_box = QWidget()
        self.acts_lay = QVBoxLayout(self.acts_box)
        self.acts_lay.setContentsMargins(0, 4, 0, 0)
        self.day_card.lay.addWidget(self.acts_box)
        self.mock_info = QLabel()
        self.mock_info.setWordWrap(True)
        self.day_card.lay.addWidget(self.mock_info)
        self.day_card.lay.addWidget(disclaimer_label(L.DISCLAIMER))
        right.addWidget(self.day_card)
        right.addStretch(1)
        main.addLayout(right, 3)
        holder = QWidget()
        holder.setLayout(main)
        holder.setMinimumHeight(520)
        self.body.addWidget(holder)
        self.boxes: list[QCheckBox] = []

    # ------------------------------------------------------------ état
    def refresh(self) -> None:
        keep = self.days.currentItem().data(Qt.UserRole) if self.days.currentItem() else None
        with self.ctx.db.session() as s:
            IS.sync_mock_days(s)
            p = IS.progress(s)
            done = IS.done_map(s)
            rows = [(d.id, d.day, d.focus, d.is_mock_exam, len(done.get(d.id, set())),
                     len(d.activities or [])) for d in IS.days(s)]
        self.bar.setValue(p["percent"])
        self.bar.setFormat(f"{p['percent']} % · {p['days_complete']} jour(s) terminé(s) sur "
                           f"{p['days']}")
        if p["started"]:
            cal = p["calendar_day"]
            msg = (f"Commencé le {p['started']:%d/%m/%Y} · jour {cal} du calendrier · prochain "
                   f"jour à faire : {p['current_day']}.")
            if cal and p["current_day"] < cal:
                msg += f" Vous avez {cal - p['current_day']} jour(s) de retard : rattrapez " \
                       "les activités des quatre compétences en priorité, pas le travail de la langue."
            h, m = divmod(p["minutes_left"], 60)
            msg += f" Reste environ {h} h {m:02d} de travail."
        else:
            msg = ("Programme non commencé. Cliquez sur « Démarrer aujourd'hui », ou cochez "
                   "simplement une première activité.")
        self.info.setText(msg)
        self.start_btn.setVisible(p["started"] is None)
        self.days.blockSignals(True)
        self.days.clear()
        target = 0
        for i, (did, day, focus, mock, n, tot) in enumerate(rows):
            mark = "✔" if tot and n >= tot else ("◐" if n else "○")
            tag = "  ★ examen blanc" if mock else ""
            it = QListWidgetItem(f"{mark}  Jour {day} – {focus}{tag}   ({n}/{tot})")
            it.setData(Qt.UserRole, did)
            self.days.addItem(it)
            if (keep is not None and did == keep) or (keep is None and day == p["current_day"]):
                target = i
        self.days.blockSignals(False)
        if self.days.count():
            self.days.setCurrentRow(target)
            self._load_day(self.days.currentItem())
        else:
            self.day_title.setText("Programme non installé.")

    def _load_day(self, item, _prev=None) -> None:
        while self.acts_lay.count():
            w = self.acts_lay.takeAt(0).widget()
            if w is not None:
                w.deleteLater()
        self.boxes = []
        if item is None:
            return
        with self.ctx.db.session() as s:
            d = s.get(IntensiveDay, item.data(Qt.UserRole))
            done = IS.done_map(s).get(d.id, set())
            self.day_title.setText(f"Jour {d.day} – {d.focus}")
            self.day_advice.setText(f"Consigne : {d.advice}." if d.advice else "")
            for i, a in enumerate(d.activities or []):
                line = QWidget()
                hl = QHBoxLayout(line)
                hl.setContentsMargins(0, 0, 0, 0)
                cb = QCheckBox(f"{a['minutes']} min · {a['module']} – {a['description']}")
                cb.setChecked(i in done)
                cb.toggled.connect(lambda on, idx=i, did=d.id: self.toggle(did, idx, on))
                hl.addWidget(cb, 1)
                if a.get("ref"):
                    go = QPushButton("Y aller ▶")
                    go.clicked.connect(lambda _=False, k=a["ref"]: self._go(k))
                    hl.addWidget(go)
                self.acts_lay.addWidget(line)
                self.boxes.append(cb)
            mock = ""
            if d.is_mock_exam:
                a = IS.mock_result(s, d)
                if a is None:
                    mock = (f"Examen du jour : {d.exam_code} (page « Examens blancs »). Les "
                            "épreuves passées seront cochées automatiquement.")
                else:
                    res = a.results or {}
                    parts = []
                    for sec in ("CO", "CE", "EE", "EO"):
                        r = res.get(sec) or {}
                        if r.get("level"):
                            score = (f"{r['correct']}/{r['total']}" if "total" in r
                                     else f"{r.get('note20', 0):.1f}/20")
                            parts.append(f"{sec} {score} ({r['level']})")
                    mock = (f"<b>{escape(d.exam_code)} passé le {a.finished_at:%d/%m/%Y}</b> · "
                            + escape(" · ".join(parts) or "résultats disponibles dans "
                                     "l'historique"))
            self.mock_info.setText(mock)

    # ------------------------------------------------------------ actions
    def toggle(self, day_id: int, index: int, on: bool) -> None:
        with self.ctx.db.session() as s:
            IS.toggle(s, day_id, index, on)
        it = self.days.currentItem()
        if it is not None:
            with self.ctx.db.session() as s:
                d = s.get(IntensiveDay, day_id)
                n = len(IS.done_map(s).get(day_id, set()))
                tot = len(d.activities or [])
                mark = "✔" if tot and n >= tot else ("◐" if n else "○")
                tag = "  ★ examen blanc" if d.is_mock_exam else ""
                it.setText(f"{mark}  Jour {d.day} – {d.focus}{tag}   ({n}/{tot})")
                p = IS.progress(s)
            self.bar.setValue(p["percent"])
            self.bar.setFormat(f"{p['percent']} % · {p['days_complete']} jour(s) terminé(s) "
                               f"sur {p['days']}")
            self.start_btn.setVisible(p["started"] is None)

    def start_today(self) -> None:
        with self.ctx.db.session() as s:
            IS.start(s)
        self.refresh()

    def reset(self, confirm: bool = True) -> None:
        if confirm and QMessageBox.question(
                self, "Recommencer", "Effacer la progression du programme intensif ? Vos "
                "résultats, examens et productions sont conservés.") != QMessageBox.Yes:
            return
        with self.ctx.db.session() as s:
            IS.reset(s)
        self.refresh()

    def _go(self, key: str) -> None:
        win = self.window()
        if hasattr(win, "open_page") and key in getattr(win, "pages", {}):
            win.open_page(key)
