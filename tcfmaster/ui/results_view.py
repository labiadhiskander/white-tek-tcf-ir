"""Affichage des résultats d'une tentative avec la correction détaillée."""
from __future__ import annotations

import html

from PySide6.QtWidgets import QTextBrowser

from tcfmaster.core import levels as L
from tcfmaster.db.models import SECTION_LABELS, Attempt, Question


def attempt_report_html(s, attempt_id: int, with_correction: bool = True) -> str:
    a = s.get(Attempt, attempt_id)
    res = a.results or {}
    out = [f"<h2>Résultats – {html.escape(a.exam.title) if a.exam else 'Entraînement'}</h2>",
           f"<p>Mode : {a.mode} · {a.started_at:%d/%m/%Y %H:%M}</p><table cellpadding='6'>"]
    for sec in ("CO", "CE", "EE", "EO"):
        r = res.get(sec)
        if not isinstance(r, dict):
            continue
        if sec in ("CO", "CE"):
            val = f"{r['score']} / 699 · {r['correct']}/{r['total']} bonnes réponses"
        else:
            val = f"{r.get('note20', 0):.1f} / 20"
        lvl = r.get("level", "")
        color = "#2E8B57" if L.meets_target(lvl) else "#C0392B"
        out.append(f"<tr><td><b>{SECTION_LABELS[sec]}</b></td><td>{val}</td>"
                   f"<td><b style='color:{color}'>{lvl}</b></td></tr>")
    out.append("</table>")
    out.append(f"<p><i>{L.DISCLAIMER}</i></p>")
    if with_correction:
        answers = {x.question_id: x for x in a.answers}
        for sec in ("CO", "CE"):
            if sec not in a.sections:
                continue
            if a.exam is not None:
                qs = a.exam.questions_for(sec)
            else:
                qs = [s.get(Question, qid) for qid in answers
                      if s.get(Question, qid).section == sec]
            if not qs:
                continue
            out.append(f"<h3>Correction – {SECTION_LABELS[sec]}</h3>")
            for q in qs:
                ans = answers.get(q.id)
                chosen = ans.choice_label if ans else None
                right = q.correct_choice.label if q.correct_choice else "?"
                mark = "✔" if chosen == right else "✘"
                color = "#2E8B57" if chosen == right else "#C0392B"
                out.append(
                    f"<p><b style='color:{color}'>{mark} Q{q.position}</b> "
                    f"({q.level}, {html.escape(q.doc_type)}) – {html.escape(q.prompt)}<br>"
                    f"Votre réponse : <b>{chosen or '—'}</b> · Bonne réponse : <b>{right}</b>"
                    f"<br>{html.escape(q.explanation)}</p>")
                if sec == "CO":
                    out.append(f"<p style='color:#5F6B7A'><i>Transcription : "
                               f"{html.escape(q.document)}</i></p>")
                out.append("<ul>")
                for c in q.choices:
                    out.append(f"<li><b>{c.label}.</b> {html.escape(c.text)}"
                               + (f" — <i>{html.escape(c.rationale)}</i>" if c.rationale else "")
                               + "</li>")
                out.append("</ul>")
        for ws in sorted(a.writing_submissions,
                         key=lambda w: w.task.task_number if w.task else 0):
            from tcfmaster.ui.writing_report import evaluation_html
            out.append(evaluation_html(ws.evaluation or {}, ws.text,
                                       f"Expression écrite – tâche "
                                       f"{ws.task.task_number if ws.task else ''}"))
        for sp in a.speaking_submissions:
            out.append(f"<h3>Expression orale – tâche {sp.task.task_number if sp.task else ''}"
                       f"</h3><p>Note {sp.note20 or 0:.1f}/20 · {sp.level or ''}</p>"
                       f"<p>{html.escape(sp.transcript)}</p>")
    return "".join(out)


class ResultsView(QTextBrowser):
    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.setOpenExternalLinks(False)
        self.setMinimumHeight(420)

    def show_attempt(self, attempt_id: int) -> None:
        with self.ctx.db.session() as s:
            self.setHtml(attempt_report_html(s, attempt_id))
