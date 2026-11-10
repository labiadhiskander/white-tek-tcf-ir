"""Export PDF : résultats d'une tentative et bilan de progression.

Chaque page porte la mention « estimation pédagogique, pas un résultat officiel
de France Éducation international ».
"""
from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table,
                                TableStyle)
from sqlalchemy.orm import Session

from tcfmaster import APP_NAME
from tcfmaster.core import levels as L
from tcfmaster.db.models import SECTION_LABELS, SECTIONS, Attempt
from tcfmaster.services import progress as PR

log = logging.getLogger("tcfmaster.pdf")

FONT_CANDIDATES = [
    ("C:/Windows/Fonts/arial.ttf", "C:/Windows/Fonts/arialbd.ttf"),
    ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
     "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
]
CRITERIA = {"adequation": "Réalisation de la tâche", "coherence": "Cohérence",
            "lexique": "Lexique", "grammaire": "Grammaire", "tache": "Réalisation de la tâche",
            "aisance": "Aisance et fluidité"}
BLUE = colors.HexColor("#1F3A5F")
_FONTS: tuple[str, str] | None = None


def _fonts() -> tuple[str, str]:
    """Police TrueType du système si disponible (accents, guillemets), sinon Helvetica."""
    global _FONTS
    if _FONTS is None:
        _FONTS = ("Helvetica", "Helvetica-Bold")
        for reg, bold in FONT_CANDIDATES:
            if Path(reg).is_file() and Path(bold).is_file():
                try:
                    pdfmetrics.registerFont(TTFont("TCFSans", reg))
                    pdfmetrics.registerFont(TTFont("TCFSans-Bold", bold))
                    _FONTS = ("TCFSans", "TCFSans-Bold")
                    break
                except Exception:          # police illisible : on garde Helvetica
                    log.warning("Police %s inutilisable", reg)
    return _FONTS


def _styles():
    reg, bold = _fonts()
    ss = getSampleStyleSheet()
    return {
        "title": ParagraphStyle("t", parent=ss["Title"], fontName=bold, fontSize=18,
                                textColor=BLUE, spaceAfter=6),
        "h2": ParagraphStyle("h2", parent=ss["Heading2"], fontName=bold, fontSize=13,
                             textColor=BLUE, spaceBefore=10, spaceAfter=4),
        "h3": ParagraphStyle("h3", parent=ss["Heading3"], fontName=bold, fontSize=11,
                             spaceBefore=6, spaceAfter=2),
        "p": ParagraphStyle("p", parent=ss["BodyText"], fontName=reg, fontSize=10,
                            leading=13),
        "small": ParagraphStyle("s", parent=ss["BodyText"], fontName=reg, fontSize=8.5,
                                leading=11, textColor=colors.HexColor("#555555")),
        "cell": ParagraphStyle("c", parent=ss["BodyText"], fontName=reg, fontSize=9,
                               leading=11),
    }


def _p(text, style) -> Paragraph:
    return Paragraph(escape(str(text if text is not None else "")).replace("\n", "<br/>"), style)


def _table(rows: list[list], widths: list[float], st) -> Table:
    data = [[c if isinstance(c, Paragraph) else _p(c, st["cell"]) for c in r] for r in rows]
    t = Table(data, colWidths=widths, repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E8EEF6")),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#B8C4D6")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    return t


def _on_page(canvas, doc) -> None:
    reg, _ = _fonts()
    canvas.saveState()
    canvas.setFont(reg, 8)
    canvas.setFillColor(colors.HexColor("#555555"))
    canvas.drawString(2 * cm, 1.2 * cm, L.DISCLAIMER)
    canvas.drawRightString(A4[0] - 2 * cm, 1.2 * cm, f"{APP_NAME} · page {doc.page}")
    canvas.restoreState()


def _build(path: Path, story: list, title: str, compress: bool = True) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(str(path), pagesize=A4, title=title, author=APP_NAME,
                            leftMargin=2 * cm, rightMargin=2 * cm, topMargin=1.8 * cm,
                            bottomMargin=2 * cm, pageCompression=1 if compress else 0)
    doc.build(story, onFirstPage=_on_page, onLaterPages=_on_page)
    log.info("PDF exporté : %s", path.name)
    return path


def _evaluation_block(ev: dict, text: str, title: str, st) -> list:
    out = [_p(title, st["h3"])]
    if not ev:
        return out + [_p("Aucune évaluation.", st["p"])]
    out.append(_p(f"Note estimée : {ev.get('note20', 0):.1f} / 20 · niveau estimé "
                  f"{ev.get('level', '–')}", st["p"]))
    crit = ev.get("criteria") or {}
    if crit:
        rows = [["Critère", "Note", "Commentaire"]]
        for k, v in crit.items():
            rows.append([CRITERIA.get(k, k), f"{v:.1f} / 5",
                         (ev.get("criteria_comments") or {}).get(k, "")])
        out.append(_table(rows, [4.5 * cm, 2 * cm, 10.5 * cm], st))
    for label, key in (("Points forts", "strengths"), ("Priorités", "priorities")):
        if ev.get(key):
            out.append(_p(f"{label} : " + " ; ".join(ev[key]), st["p"]))
    errors = [i for i in (ev.get("issues") or []) if i.get("severity") == "erreur"][:12]
    if errors:
        rows = [["Passage", "Correction", "Règle"]]
        for i in errors:
            rows.append([i.get("excerpt", ""), i.get("replacement") or i.get("suggestion", ""),
                         i.get("message", "")])
        out.append(Spacer(1, 4))
        out.append(_table(rows, [4.5 * cm, 4 * cm, 8.5 * cm], st))
    if text:
        out.append(_p("Votre production :", st["small"]))
        out.append(_p(text[:3000], st["small"]))
    return out


def export_attempt(s: Session, attempt_id: int, path: Path, compress: bool = True) -> Path:
    a = s.get(Attempt, attempt_id)
    if a is None:
        raise ValueError(f"Tentative introuvable : {attempt_id}")
    st = _styles()
    res = a.results or {}
    exam = f"{a.exam.code} – {a.exam.title}" if a.exam else "Entraînement"
    story = [_p("Résultats – TCF IRN (simulation)", st["title"]),
             _p(f"{exam} · {a.mode} · {a.started_at:%d/%m/%Y %H:%M}", st["p"]),
             _p(L.DISCLAIMER, st["small"]), _p("Synthèse", st["h2"])]
    rows = [["Épreuve", "Résultat", "Niveau estimé", "Détail"]]
    for sec in SECTIONS:
        r = res.get(sec)
        if not isinstance(r, dict):
            continue
        if sec in ("CO", "CE"):
            val = f"{r.get('score', 0)} / 699"
            det = (f"{r.get('correct', 0)} bonne(s) réponse(s) sur {r.get('total', 0)}"
                   if r.get("total") else "")
        else:
            val = f"{r.get('note20', 0):.1f} / 20"
            det = ", ".join(f"T{k} : {v:.1f}" for k, v in (r.get("tasks") or {}).items())
        rows.append([SECTION_LABELS[sec], val, r.get("level", "–"), det])
    if len(rows) == 1:
        rows.append(["–", "Aucun résultat enregistré", "", ""])
    story.append(_table(rows, [4.5 * cm, 3 * cm, 3 * cm, 6.5 * cm], st))
    subs_w = sorted(a.writing_submissions, key=lambda w: w.task.task_number if w.task else 0)
    subs_o = sorted(a.speaking_submissions, key=lambda w: w.task.task_number if w.task else 0)
    if subs_w:
        story += [PageBreak(), _p("Expression écrite – détail", st["h2"])]
        for w in subs_w:
            story += _evaluation_block(w.evaluation or {}, w.text,
                                       f"Tâche {w.task.task_number if w.task else '?'}", st)
    if subs_o:
        story += [PageBreak(), _p("Expression orale – détail", st["h2"])]
        for w in subs_o:
            story += _evaluation_block(w.evaluation or {}, w.transcript,
                                       f"Tâche {w.task.task_number if w.task else '?'}", st)
    return _build(path, story, f"Résultats {exam}", compress)


def export_progress(s: Session, path: Path, compress: bool = True) -> Path:
    st = _styles()
    d = PR.dashboard(s)
    story = [_p("Bilan de progression – objectif B2", st["title"]),
             _p(f"Édité le {datetime.now():%d/%m/%Y à %H:%M}", st["p"]),
             _p(L.DISCLAIMER, st["small"]), Spacer(1, 6),
             _p("Avis : " + d["verdict"], st["p"]),
             _p("Indicateurs", st["h2"])]
    h, m = divmod(d["training_minutes"], 60)
    kpis = [["Indicateur", "Valeur"],
            ["Niveau initial", d["initial_level"] or "À évaluer"],
            ["Niveau actuel estimé", d["current_level"] or "–"],
            ["Objectif", d["target"]],
            ["Examens effectués", d["exams_done"]],
            ["Examens blancs complets", f"{d['full_exams']} (minimum {PR.MIN_FULL_EXAMS})"],
            ["Réussite compréhension orale", f"{d['co_rate']} %" if d["co_rate"] is not None
             else "–"],
            ["Réussite compréhension écrite", f"{d['ce_rate']} %" if d["ce_rate"] is not None
             else "–"],
            ["Note moyenne expression écrite", f"{d['ee_average']:.1f} / 20"
             if d["ee_average"] is not None else "–"],
            ["Note moyenne expression orale", f"{d['eo_average']:.1f} / 20"
             if d["eo_average"] is not None else "–"],
            ["Temps d'entraînement", f"{h} h {m:02d}"],
            ["Erreurs relevées", d["grammar_errors"]]]
    story.append(_table(kpis, [8 * cm, 9 * cm], st))
    story.append(_p("Préparation par compétence", st["h2"]))
    rows = [["Compétence", "Niveau estimé", "Résultats", "Statut", "Conseil"]]
    for r in d["readiness"]:
        rows.append([r.label, r.average_level or "–", r.results, r.status, r.advice])
    story.append(_table(rows, [3.8 * cm, 2.4 * cm, 2 * cm, 2.4 * cm, 6.4 * cm], st))
    if d["error_categories"]:
        story.append(_p("Erreurs les plus fréquentes", st["h2"]))
        story.append(_table([["Difficulté", "Nombre"]]
                            + [[c, n] for c, n in d["error_categories"][:8]],
                            [13 * cm, 4 * cm], st))
    story.append(_p("Recommandations", st["h2"]))
    for r in PR.recommendations(s):
        story.append(_p(f"• {r.text}", st["p"]))
    return _build(path, story, "Bilan de progression", compress)
