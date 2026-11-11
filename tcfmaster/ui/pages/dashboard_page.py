"""Tableau de bord : progression vers le B2, préparation, régularité, recommandations.

Règle affichée : le candidat n'est jamais déclaré prêt sur un seul résultat
(voir `services.progress`).
"""
from __future__ import annotations

from datetime import date

from PySide6.QtCharts import (QBarCategoryAxis, QBarSeries, QBarSet, QCategoryAxis, QChart,
                              QChartView, QLineSeries, QValueAxis)
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (QGridLayout, QHBoxLayout, QHeaderView, QLabel, QProgressBar,
                               QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout,
                               QWidget)

from tcfmaster.core import levels as L
from tcfmaster.services import progress as PR
from tcfmaster.services import review as RV
from tcfmaster.ui.widgets import Card, Kpi, Page, disclaimer_label

STATUS_COLORS = {"stabilisé": "#1E8449", "à confirmer": "#B9770E", "insuffisant": "#C0392B",
                 "non évalué": "#7F8C8D"}
SERIES_COLORS = {"CO": "#2E86C1", "CE": "#8E44AD", "EE": "#D35400", "EO": "#16A085"}


def level_value(sec: str, v: float) -> float:
    """Position continue d'un score sur l'échelle A1(1)…C2(6)."""
    if sec in ("CO", "CE"):
        return max(0.0, min(6.0, v / 100))
    bands = [(0, 0), (1, 1), (4, 2), (6, 3), (10, 4), (14, 5), (16, 6), (20, 6.99)]
    for (a, la), (b, lb) in zip(bands, bands[1:]):
        if v <= b:
            return la + (lb - la) * (v - a) / (b - a) if b > a else la
    return 6.0


class DashboardPage(Page):
    def __init__(self, ctx):
        super().__init__(ctx, "Tableau de bord", "Votre progression vers le niveau B2.")
        # --- verdict
        self.verdict = QLabel()
        self.verdict.setWordWrap(True)
        self.verdict.setObjectName("Verdict")
        self.body.addWidget(self.verdict)

        # --- indicateurs
        grid = QGridLayout()
        grid.setSpacing(12)
        self.kpis: dict[str, Kpi] = {}
        specs = [("initial", "Niveau initial"), ("current", "Niveau actuel estimé"),
                 ("target", "Objectif"), ("exams", "Examens effectués"),
                 ("full", "Examens blancs complets"),
                 ("co", "Réussite compréhension orale"), ("ce", "Réussite compréhension écrite"),
                 ("ee", "Note moyenne expression écrite"),
                 ("eo", "Note moyenne expression orale"), ("time", "Temps d'entraînement"),
                 ("errors", "Erreurs relevées"), ("vocab", "Vocabulaire acquis")]
        for i, (k, lab) in enumerate(specs):
            w = Kpi(lab)
            self.kpis[k] = w
            grid.addWidget(w, i // 6, i % 6)
        self.body.addLayout(grid)

        # --- préparation par compétence
        rc = Card("Préparation par compétence")
        self.table = QTableWidget(4, 5)
        self.table.setHorizontalHeaderLabels(["Compétence", "Niveau estimé", "Résultats",
                                              "Statut", "Conseil"])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionMode(QTableWidget.NoSelection)
        self.table.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        hh = self.table.horizontalHeader()
        for c in range(4):
            hh.setSectionResizeMode(c, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(4, QHeaderView.Stretch)
        rc.lay.addWidget(self.table)
        rule = QLabel(f"Une compétence est « stabilisée » quand les {PR.MIN_RESULTS_FOR_READINESS} "
                      "derniers résultats ET la moyenne récente atteignent B2. Vous êtes "
                      "considéré prêt seulement si les 4 compétences sont stabilisées et après "
                      f"au moins {PR.MIN_FULL_EXAMS} examens blancs complets.")
        rule.setWordWrap(True)
        rule.setObjectName("Muted")
        rc.lay.addWidget(rule)
        self.body.addWidget(rc)

        # --- historique et régularité
        row = QHBoxLayout()
        self.chart = QChart()
        self.chart.setTitle("Historique des résultats (niveau CECRL) · CO/CE compréhension, "
                            "EE/EO expression")
        self.chart.legend().setAlignment(Qt.AlignBottom)
        view = QChartView(self.chart)
        view.setRenderHint(QPainter.Antialiasing)
        view.setMinimumHeight(320)
        cc = Card()
        cc.lay.addWidget(view)
        row.addWidget(cc, 3)
        self.activity = QChart()
        self.activity.setTitle("Minutes d'entraînement par semaine (semaine du…)")
        self.activity.legend().hide()
        av = QChartView(self.activity)
        av.setRenderHint(QPainter.Antialiasing)
        av.setMinimumHeight(320)
        ac = Card()
        ac.lay.addWidget(av)
        row.addWidget(ac, 2)
        self.body.addLayout(row)

        # --- programme et erreurs
        row2 = QHBoxLayout()
        pc = Card("Programme de 12 semaines")
        self.plan_bar = QProgressBar()
        self.plan_info = QLabel()
        self.plan_info.setObjectName("Muted")
        pc.lay.addWidget(self.plan_bar)
        pc.lay.addWidget(self.plan_info)
        pc.lay.addStretch(1)
        row2.addWidget(pc, 1)
        ec = Card("Erreurs les plus fréquentes")
        self.errors = QLabel()
        self.errors.setWordWrap(True)
        ec.lay.addWidget(self.errors)
        go = QPushButton("Exercices personnalisés ▶")
        go.clicked.connect(lambda: self._go("custom"))
        ec.lay.addWidget(go, alignment=Qt.AlignLeft)
        ec.lay.addStretch(1)
        row2.addWidget(ec, 1)
        self.body.addLayout(row2)

        # --- recommandations
        self.rec_card = Card("Recommandations")
        self.rec_box = QVBoxLayout()
        self.rec_card.lay.addLayout(self.rec_box)
        self.rec_card.lay.addWidget(disclaimer_label(L.DISCLAIMER))
        self.pdf_btn = QPushButton("Exporter mon bilan en PDF")
        self.pdf_btn.clicked.connect(self.export_pdf)
        self.rec_card.lay.addWidget(self.pdf_btn, alignment=Qt.AlignLeft)
        self.body.addWidget(self.rec_card)
        self.rec_holder: QWidget | None = None
        self.data: dict = {}
        self.recs: list[PR.Recommendation] = []

    # ------------------------------------------------------------------
    def export_pdf(self, path: str | None = None) -> str | None:
        from datetime import datetime

        from PySide6.QtWidgets import QFileDialog, QMessageBox

        from tcfmaster.services.pdf_export import export_progress
        if path is None:
            default = self.ctx.paths.exports / f"bilan-{datetime.now():%Y%m%d}.pdf"
            path, _ = QFileDialog.getSaveFileName(self, "Exporter le bilan", str(default),
                                                  "PDF (*.pdf)")
            if not path:
                return None
            with self.ctx.db.session() as s:
                export_progress(s, path)
            QMessageBox.information(self, "Export", f"Bilan exporté :\n{path}")
            return path
        with self.ctx.db.session() as s:
            export_progress(s, path)
        return path

    def _go(self, key: str) -> None:
        win = self.window()
        if hasattr(win, "open_page"):
            win.open_page(key)

    def refresh(self) -> None:
        with self.ctx.db.session() as s:
            d = PR.dashboard(s)
            vocab = RV.acquired_count(s, "vocab") + RV.acquired_count(s, "expression")
            self.recs = PR.recommendations(s)
            act = PR.activity_by_day(s, 28)
            plan = PR.plan_progress(s)
        self.data = d
        self._kpis(d, vocab)
        self._verdict(d)
        self._readiness(d["readiness"])
        self._history_chart(d)
        self._activity_chart(act)
        self.plan_bar.setValue(plan["percent"])
        self.plan_bar.setFormat(f"{plan['percent']} %")
        self.plan_info.setText(f"{plan['done']} activité(s) sur {plan['total']} · semaine "
                               f"{plan['current_week']} / {plan['weeks']}")
        cats = d["error_categories"][:5]
        self.errors.setText("<br>".join(f"• {c} : <b>{n}</b>" for c, n in cats) if cats else
                            "Aucune erreur relevée pour l'instant.")
        self._recommendations()

    def _kpis(self, d: dict, vocab: int) -> None:
        k = self.kpis
        k["initial"].set(d["initial_level"] or "À évaluer")
        k["current"].set(d["current_level"] or "–")
        k["target"].set(d["target"])
        k["exams"].set(d["exams_done"])
        k["full"].set(f"{d['full_exams']} (min. {PR.MIN_FULL_EXAMS})")
        k["co"].set(f"{d['co_rate']} %" if d["co_rate"] is not None else None)
        k["ce"].set(f"{d['ce_rate']} %" if d["ce_rate"] is not None else None)
        for key in ("ee", "eo"):
            avg = d[f"{key}_average"]
            k[key].set(f"{avg:.1f} / 20" if avg is not None else None)
        h, m = divmod(d["training_minutes"], 60)
        k["time"].set(f"{h} h {m:02d}")
        k["errors"].set(d["grammar_errors"])
        k["vocab"].set(vocab)

    def _verdict(self, d: dict) -> None:
        color, bg = ("#1E8449", "#E9F7EF") if d["ready"] else ("#9A5B00", "#FEF5E7")
        self.verdict.setText(("✔ " if d["ready"] else "⏳ ") + d["verdict"])
        self.verdict.setStyleSheet(f"color:{color}; background:{bg}; padding:10px 14px; "
                                   "border-radius:8px; font-size:12pt;")

    def _readiness(self, rows: list[PR.SkillReadiness]) -> None:
        self.table.setRowCount(len(rows))
        for r, x in enumerate(rows):
            vals = [x.label, x.average_level or "–", str(x.results), x.status, x.advice]
            for c, v in enumerate(vals):
                it = QTableWidgetItem(v)
                if c == 3:
                    it.setForeground(QColor(STATUS_COLORS.get(x.status, "#333")))
                self.table.setItem(r, c, it)
        self.table.resizeRowsToContents()
        h = self.table.horizontalHeader().height() + sum(
            self.table.rowHeight(i) for i in range(len(rows))) + 4
        self.table.setFixedHeight(h)

    def _history_chart(self, d: dict) -> None:
        ch = self.chart
        ch.removeAllSeries()
        for ax in ch.axes():
            ch.removeAxis(ax)
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
            ser.setName(sec)
            ser.setColor(QColor(SERIES_COLORS[sec]))
            for i, v in enumerate(hist, 1):
                ser.append(i, level_value(sec, v))
            mx = max(mx, len(hist))
            ch.addSeries(ser)
        target = QLineSeries()
        target.setName("Objectif B2")
        pen = target.pen()
        pen.setStyle(Qt.DashLine)
        pen.setColor(QColor("#7F8C8D"))
        target.setPen(pen)
        target.append(1, 4)
        target.append(max(2, mx), 4)
        ch.addSeries(target)
        ax_x.setRange(1, max(2, mx))
        ax_x.setTickCount(min(max(2, mx), 11))
        ch.addAxis(ax_y, Qt.AlignLeft)
        ch.addAxis(ax_x, Qt.AlignBottom)
        for ser in ch.series():
            ser.attachAxis(ax_x)
            ser.attachAxis(ax_y)

    def _activity_chart(self, act: dict[date, float]) -> None:
        ch = self.activity
        ch.removeAllSeries()
        for ax in ch.axes():
            ch.removeAxis(ax)
        days = sorted(act)
        weeks = [days[i:i + 7] for i in range(0, len(days), 7)]
        bars = QBarSet("Minutes")
        bars.setColor(QColor("#2E86C1"))
        cats = []
        for wk in weeks:
            bars.append(round(sum(act[d] for d in wk)))
            cats.append(f"{wk[0]:%d/%m}")
        series = QBarSeries()
        series.append(bars)
        series.setLabelsVisible(True)
        ch.addSeries(series)
        ax_x = QBarCategoryAxis()
        ax_x.append(cats)
        ax_y = QValueAxis()
        top = max([bars.at(i) for i in range(bars.count())] + [60])
        ax_y.setRange(0, top * 1.2)
        ax_y.setLabelFormat("%d")
        ch.addAxis(ax_x, Qt.AlignBottom)
        ch.addAxis(ax_y, Qt.AlignLeft)
        series.attachAxis(ax_x)
        series.attachAxis(ax_y)

    def _recommendations(self) -> None:
        if self.rec_holder is not None:
            self.rec_box.removeWidget(self.rec_holder)
            self.rec_holder.deleteLater()
        self.rec_holder = QWidget()
        lay = QVBoxLayout(self.rec_holder)
        lay.setContentsMargins(0, 0, 0, 0)
        for r in self.recs:
            row = QHBoxLayout()
            mark = {1: "🔴", 2: "🟠", 3: "🟢"}.get(r.priority, "•")
            lab = QLabel(f"{mark} {r.text}")
            lab.setWordWrap(True)
            row.addWidget(lab, 1)
            if r.page:
                b = QPushButton("Y aller")
                b.clicked.connect(lambda _=False, p=r.page: self._go(p))
                row.addWidget(b)
            lay.addLayout(row)
        self.rec_box.addWidget(self.rec_holder)
