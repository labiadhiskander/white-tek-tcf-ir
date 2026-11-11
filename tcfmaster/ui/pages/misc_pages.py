"""Pages : Tableau de bord, Historique, Programme, Paramètres."""
from __future__ import annotations

import shutil
from pathlib import Path

from PySide6.QtCharts import QCategoryAxis, QChart, QChartView, QLineSeries, QValueAxis
from PySide6.QtCore import Qt
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import (QCheckBox, QComboBox, QFileDialog, QGridLayout, QHBoxLayout,
                               QHeaderView, QLabel, QListWidget, QListWidgetItem,
                               QMessageBox, QProgressBar, QPushButton, QTableWidget,
                               QTableWidgetItem, QVBoxLayout, QWidget)
from sqlalchemy import select

from tcfmaster.core import levels as L
from tcfmaster.core.paths import save_data_root
from tcfmaster.db.models import (SECTION_LABELS, Attempt, PlanDay, PlanProgress)
from tcfmaster.services import progress as PR
from tcfmaster.services import review as RV
from tcfmaster.services import settings as S
from tcfmaster.ui.results_view import ResultsView
from tcfmaster.ui.widgets import Card, Kpi, Page, disclaimer_label


# =========================================================================
class DashboardPage(Page):
    def __init__(self, ctx):
        super().__init__(ctx, "Tableau de bord", "Votre progression vers le niveau B2.")
        grid = QGridLayout()
        grid.setSpacing(12)
        self.kpis = {}
        specs = [("initial", "Niveau initial"), ("current", "Niveau actuel estimé"),
                 ("target", "Objectif"), ("exams", "Examens effectués"),
                 ("co", "Réussite compréhension orale"), ("ce", "Réussite compréhension écrite"),
                 ("time", "Temps d'entraînement"), ("errors", "Erreurs grammaticales relevées"),
                 ("vocab", "Vocabulaire acquis")]
        for i, (k, lab) in enumerate(specs):
            w = Kpi(lab)
            self.kpis[k] = w
            grid.addWidget(w, i // 5, i % 5)
        self.body.addLayout(grid)

        row = QHBoxLayout()
        self.skills_card = Card("Niveau par compétence")
        self.skill_bars = {}
        for sec in ("CO", "CE", "EE", "EO"):
            lab = QLabel(SECTION_LABELS[sec])
            bar = QProgressBar()
            bar.setRange(0, 5)
            bar.setTextVisible(True)
            self.skills_card.lay.addWidget(lab)
            self.skills_card.lay.addWidget(bar)
            self.skill_bars[sec] = bar
        row.addWidget(self.skills_card, 1)
        self.chart = QChart()
        self.chart.setTitle("Historique des résultats (niveau CECRL)")
        self.chart.legend().setAlignment(Qt.AlignBottom)
        view = QChartView(self.chart)
        view.setRenderHint(QPainter.Antialiasing)
        view.setMinimumHeight(300)
        chart_card = Card()
        chart_card.lay.addWidget(view)
        row.addWidget(chart_card, 2)
        self.body.addLayout(row)

        self.alerts_card = Card("Alertes et recommandations")
        self.alerts_label = QLabel()
        self.alerts_label.setWordWrap(True)
        self.alerts_card.lay.addWidget(self.alerts_label)
        self.alerts_card.lay.addWidget(disclaimer_label(L.DISCLAIMER))
        self.body.addWidget(self.alerts_card)

    @staticmethod
    def _to_level_value(sec: str, v: float) -> float:
        """Convertit un score en position continue sur l'échelle A1(1)…C2(6)."""
        if sec in ("CO", "CE"):
            return max(0.0, min(6.0, v / 100))
        bands = [(0, 0), (1, 1), (4, 2), (6, 3), (10, 4), (14, 5), (16, 6), (20, 6.99)]
        for (a, la), (b, lb) in zip(bands, bands[1:]):
            if v <= b:
                return la + (lb - la) * (v - a) / (b - a) if b > a else la
        return 6.0

    def refresh(self):
        with self.ctx.db.session() as s:
            d = PR.dashboard(s)
            vocab = RV.acquired_count(s, "vocab") + RV.acquired_count(s, "expression")
            recs = getattr(self.ctx, "recommendations", None)
            rec_list = recs(s) if callable(recs) else []
        k = self.kpis
        k["initial"].set(d["initial_level"] or "À évaluer")
        k["current"].set(d["current_level"] or "–")
        k["target"].set(d["target"])
        k["exams"].set(d["exams_done"])
        k["co"].set(f"{d['co_rate']} %" if d["co_rate"] is not None else None)
        k["ce"].set(f"{d['ce_rate']} %" if d["ce_rate"] is not None else None)
        h, m = divmod(d["training_minutes"], 60)
        k["time"].set(f"{h} h {m:02d}")
        k["errors"].set(d["grammar_errors"])
        k["vocab"].set(vocab)
        for sec, bar in self.skill_bars.items():
            info = d["skills"][sec]
            lvl = info["level"]
            idx = L.level_index(lvl) if lvl in L.LEVELS else -1
            bar.setValue(max(0, idx))
            bar.setFormat(f"{lvl or 'non évalué'}" + ("  ✔ prêt" if info["ready"] else ""))
        self.chart.removeAllSeries()
        for ax in self.chart.axes():
            self.chart.removeAxis(ax)
        ax_y = QCategoryAxis()
        ax_y.setRange(0, 7)
        for i, lv in enumerate(L.LEVELS, 1):
            ax_y.append(lv, i)
        ax_y.setLabelsPosition(QCategoryAxis.AxisLabelsPositionOnValue)
        ax_x = QValueAxis()
        ax_x.setLabelFormat("%d")
        ax_x.setTitleText("Évaluations")
        mx = 1
        for sec in ("CO", "CE", "EE", "EO"):
            hist = d["skills"][sec]["history"]
            if not hist:
                continue
            ser = QLineSeries()
            ser.setName(SECTION_LABELS[sec])
            for i, v in enumerate(hist, 1):
                ser.append(i, self._to_level_value(sec, v))
            mx = max(mx, len(hist))
            self.chart.addSeries(ser)
        target = QLineSeries()
        target.setName("Objectif B2")
        target.append(1, 4)
        target.append(max(2, mx), 4)
        self.chart.addSeries(target)
        ax_x.setRange(1, max(2, mx))
        ax_x.setTickCount(min(max(2, mx), 11))
        self.chart.addAxis(ax_y, Qt.AlignLeft)
        self.chart.addAxis(ax_x, Qt.AlignBottom)
        for ser in self.chart.series():
            ser.attachAxis(ax_x)
            ser.attachAxis(ax_y)
        lines = list(d["alerts"])
        lines += rec_list
        if d["ready"]:
            lines.insert(0, "✔ Les quatre compétences sont stabilisées au niveau B2 sur "
                            "plusieurs épreuves.")
        self.alerts_label.setText("<br>".join(f"• {x}" for x in lines))
        self.data = d


# =========================================================================
class HistoryPage(Page):
    def __init__(self, ctx):
        super().__init__(ctx, "Historique et résultats",
                         "Tous vos passages, avec la correction détaillée.")
        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(["Date", "Examen", "Mode", "CO", "CE", "EE", "EO"])
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setMinimumHeight(260)
        self.table.itemSelectionChanged.connect(self._show)
        self.body.addWidget(self.table)
        row = QHBoxLayout()
        self.export_btn = QPushButton("Exporter en PDF")
        self.export_btn.clicked.connect(self._export)
        row.addStretch(1)
        row.addWidget(self.export_btn)
        self.body.addLayout(row)
        self.view = ResultsView(ctx)
        self.body.addWidget(self.view)

    def refresh(self):
        with self.ctx.db.session() as s:
            atts = list(s.execute(select(Attempt).where(Attempt.finished_at.is_not(None))
                                  .order_by(Attempt.finished_at.desc())).scalars())
            self.table.setRowCount(len(atts))
            for r, a in enumerate(atts):
                res = a.results or {}

                def cell(sec):
                    x = res.get(sec)
                    if not isinstance(x, dict):
                        return ""
                    if sec in ("CO", "CE"):
                        return f"{x['score']} ({x['level']})"
                    return f"{x.get('note20', 0):.1f}/20 ({x.get('level', '')})"
                vals = [f"{a.finished_at:%d/%m/%Y %H:%M}",
                        a.exam.title if a.exam else "Entraînement", a.mode,
                        cell("CO"), cell("CE"), cell("EE"), cell("EO")]
                for c, v in enumerate(vals):
                    it = QTableWidgetItem(v)
                    it.setData(Qt.UserRole, a.id)
                    self.table.setItem(r, c, it)

    def _selected(self):
        r = self.table.currentRow()
        return self.table.item(r, 0).data(Qt.UserRole) if r >= 0 else None

    def _show(self):
        aid = self._selected()
        if aid:
            self.view.show_attempt(aid)

    def _export(self):
        aid = self._selected()
        exporter = getattr(self.ctx, "export_pdf", None)
        if not aid or exporter is None:
            return
        path, _ = QFileDialog.getSaveFileName(self, "Exporter en PDF",
                                              str(self.ctx.paths.exports / f"resultat-{aid}.pdf"),
                                              "PDF (*.pdf)")
        if path:
            exporter(aid, Path(path))
            QMessageBox.information(self, "Export", f"Résultats exportés :\n{path}")


# =========================================================================
class PlanPage(Page):
    def __init__(self, ctx):
        super().__init__(ctx, "Mon programme de préparation",
                         "12 semaines · 5 × 20 minutes par jour · révisions espacées · examen "
                         "blanc partiel chaque semaine et complet toutes les deux semaines.")
        row = QHBoxLayout()
        self.weeks = QListWidget()
        self.weeks.setMaximumWidth(200)
        row.addWidget(self.weeks)
        right = QVBoxLayout()
        self.days = QListWidget()
        self.days.setMinimumHeight(200)
        right.addWidget(self.days)
        self.activities_card = Card("Activités du jour")
        self.activity_boxes: list[QCheckBox] = []
        right.addWidget(self.activities_card)
        row.addLayout(right, 1)
        holder = QWidget()
        holder.setLayout(row)
        holder.setMinimumHeight(520)
        self.body.addWidget(holder)
        self.weeks.currentRowChanged.connect(self._load_days)
        self.days.currentItemChanged.connect(self._load_activities)

    def refresh(self):
        cur = max(0, self.weeks.currentRow())
        self.weeks.clear()
        with self.ctx.db.session() as s:
            weeks = sorted({p.week for p in s.execute(select(PlanDay)).scalars()})
        for w in weeks:
            self.weeks.addItem(f"Semaine {w}")
        if weeks:
            self.weeks.setCurrentRow(min(cur, len(weeks) - 1))
        else:
            self.days.clear()
            self.days.addItem("Programme non installé.")

    def _load_days(self, row: int):
        self.days.clear()
        if row < 0:
            return
        week = row + 1
        with self.ctx.db.session() as s:
            days = list(s.execute(select(PlanDay).where(PlanDay.week == week)
                                  .order_by(PlanDay.day)).scalars())
            for d in days:
                done = len(list(s.execute(select(PlanProgress).where(
                    PlanProgress.plan_day_id == d.id)).scalars()))
                tag = " · examen blanc " + d.is_mock_exam if d.is_mock_exam else ""
                tag += " · bilan" if d.is_review else ""
                it = QListWidgetItem(f"Jour {d.day} – {d.focus}{tag}   "
                                     f"({done}/{len(d.activities)})")
                it.setData(Qt.UserRole, d.id)
                self.days.addItem(it)
        if self.days.count():
            self.days.setCurrentRow(0)

    def _load_activities(self, *_):
        for b in self.activity_boxes:
            b.deleteLater()
        self.activity_boxes = []
        it = self.days.currentItem()
        if not it or it.data(Qt.UserRole) is None:
            return
        with self.ctx.db.session() as s:
            d = s.get(PlanDay, it.data(Qt.UserRole))
            done = {p.activity_index for p in s.execute(select(PlanProgress).where(
                PlanProgress.plan_day_id == d.id)).scalars()}
            for i, a in enumerate(d.activities):
                cb = QCheckBox(f"{a['minutes']} min · {a['module']} – {a['description']}")
                cb.setChecked(i in done)
                cb.toggled.connect(lambda on, idx=i, did=d.id: self._toggle(did, idx, on))
                self.activities_card.lay.addWidget(cb)
                self.activity_boxes.append(cb)

    def _toggle(self, day_id: int, idx: int, on: bool):
        with self.ctx.db.session() as s:
            row = s.execute(select(PlanProgress).where(PlanProgress.plan_day_id == day_id,
                                                       PlanProgress.activity_index == idx)
                            ).scalar_one_or_none()
            if on and row is None:
                s.add(PlanProgress(plan_day_id=day_id, activity_index=idx))
            elif not on and row is not None:
                s.delete(row)


# =========================================================================
class SettingsPage(Page):
    def __init__(self, ctx):
        super().__init__(ctx, "Paramètres", "Préférences, données, sauvegardes et confidentialité.")
        # --- pédagogie
        c1 = Card("Correction et entraînement")
        self.correction = QComboBox()
        self.correction.addItem("Correction à la fin de l'exercice", "fin")
        self.correction.addItem("Correction immédiate après chaque question", "immediate")
        c1.lay.addWidget(QLabel("Mode de correction (entraînement) :"))
        c1.lay.addWidget(self.correction)
        self.correction.currentIndexChanged.connect(
            lambda: self._set("correction_mode", self.correction.currentData()))
        self.body.addWidget(c1)
        # --- voix et audio
        from tcfmaster.ui.audio_settings import AudioSettingsCard
        self.audio_card = AudioSettingsCard(ctx)
        self.body.addWidget(self.audio_card)
        # --- données
        c2 = Card("Stockage des données")
        self.data_dir = QLabel()
        self.data_dir.setWordWrap(True)
        c2.lay.addWidget(self.data_dir)
        b = QPushButton("Changer le répertoire de stockage…")
        b.clicked.connect(self._change_dir)
        c2.lay.addWidget(b, alignment=Qt.AlignLeft)
        self.body.addWidget(c2)
        # --- sauvegardes
        c3 = Card("Sauvegarde et restauration")
        self.auto_backup = QCheckBox("Sauvegarde automatique")
        self.auto_backup.toggled.connect(lambda v: self._set("auto_backup", v))
        c3.lay.addWidget(self.auto_backup)
        self.backups = QListWidget()
        self.backups.setMinimumHeight(140)
        c3.lay.addWidget(self.backups)
        r = QHBoxLayout()
        bb = QPushButton("Sauvegarder maintenant")
        bb.setObjectName("Primary")
        bb.clicked.connect(self._backup)
        rb = QPushButton("Restaurer la sauvegarde sélectionnée")
        rb.clicked.connect(self._restore)
        r.addWidget(bb)
        r.addWidget(rb)
        r.addStretch(1)
        c3.lay.addLayout(r)
        self.body.addWidget(c3)
        # --- confidentialité
        c4 = Card("Confidentialité")
        self.keep_rec = QCheckBox("Conserver les enregistrements vocaux après évaluation")
        self.keep_rec.toggled.connect(lambda v: self._set("keep_recordings", v))
        c4.lay.addWidget(self.keep_rec)
        self.rec_info = QLabel()
        self.rec_info.setObjectName("Muted")
        c4.lay.addWidget(self.rec_info)
        d = QPushButton("Supprimer tous les enregistrements vocaux")
        d.clicked.connect(self._delete_recordings)
        c4.lay.addWidget(d, alignment=Qt.AlignLeft)
        self.body.addWidget(c4)
        self.extra_cards_anchor = self.body.count()
        self.body.addStretch(1)

    def _set(self, key, value):
        with self.ctx.db.session() as s:
            S.set_(s, key, value)

    def refresh(self):
        with self.ctx.db.session() as s:
            st = S.all_settings(s)
        for w, key in ((self.correction, "correction_mode"),):
            w.blockSignals(True)
            w.setCurrentIndex(max(0, w.findData(st[key])))
            w.blockSignals(False)
        for w, key in ((self.auto_backup, "auto_backup"), (self.keep_rec, "keep_recordings")):
            w.blockSignals(True)
            w.setChecked(bool(st[key]))
            w.blockSignals(False)
        self.data_dir.setText(f"Dossier actuel : <b>{self.ctx.paths.data_root}</b>")
        self.backups.clear()
        for p in self.ctx.db.list_backups():
            it = QListWidgetItem(p.name)
            it.setData(Qt.UserRole, str(p))
            self.backups.addItem(it)
        recs = list(self.ctx.paths.recordings.glob("*"))
        size = sum(p.stat().st_size for p in recs if p.is_file()) / 1e6
        self.rec_info.setText(f"{len(recs)} enregistrement(s) · {size:.1f} Mo")
        self.audio_card.refresh()

    def _change_dir(self):
        d = QFileDialog.getExistingDirectory(self, "Choisir le répertoire de stockage",
                                             str(self.ctx.paths.data_root))
        if not d:
            return
        new = Path(d)
        if QMessageBox.question(
                self, "Déplacer les données",
                f"Copier vos données vers :\n{new}\n\nL'application devra redémarrer.") \
                != QMessageBox.Yes:
            return
        backup = self.ctx.db.backup("deplacement")
        new.mkdir(parents=True, exist_ok=True)
        shutil.copy2(backup, new / self.ctx.paths.database.name)
        for sub in ("enregistrements", "sauvegardes"):
            src = self.ctx.paths.data_root / sub
            if src.exists():
                shutil.copytree(src, new / sub, dirs_exist_ok=True)
        save_data_root(new)
        QMessageBox.information(self, "Redémarrage", "Données copiées. Redémarrez "
                                "l'application pour utiliser le nouveau répertoire.")

    def _backup(self):
        p = self.ctx.db.backup("manuel")
        self.refresh()
        QMessageBox.information(self, "Sauvegarde", f"Sauvegarde créée :\n{p.name}")

    def _restore(self):
        it = self.backups.currentItem()
        if not it:
            return
        if QMessageBox.question(self, "Restaurer",
                                "Remplacer les données actuelles par cette sauvegarde ?\n"
                                "(Une copie de l'état actuel est conservée.)") != QMessageBox.Yes:
            return
        self.ctx.db.restore(Path(it.data(Qt.UserRole)))
        QMessageBox.information(self, "Restauration", "Données restaurées.")
        self.refresh()

    def _delete_recordings(self):
        if QMessageBox.question(self, "Supprimer",
                                "Supprimer définitivement tous les enregistrements vocaux ?") \
                != QMessageBox.Yes:
            return
        delete_all_recordings(self.ctx)
        self.refresh()


def delete_all_recordings(ctx) -> int:
    from tcfmaster.db.models import SpeakingSubmission
    n = 0
    for p in ctx.paths.recordings.glob("*"):
        if p.is_file():
            p.unlink()
            n += 1
    with ctx.db.session() as s:
        for sub in s.execute(select(SpeakingSubmission)).scalars():
            sub.audio_path = None
    return n


class PendingPage(Page):
    """Module livré dans une phase ultérieure du développement."""

    def __init__(self, ctx, title: str, phase: int, description: str):
        super().__init__(ctx, title, description)
        c = Card()
        lbl = QLabel(f"Ce module est en cours de développement (phase {phase}).")
        lbl.setWordWrap(True)
        c.lay.addWidget(lbl)
        self.body.addWidget(c)
        self.body.addStretch(1)
