"""Rendu HTML du système de correction unifié (QCM et productions)."""
from __future__ import annotations

import html

from tcfmaster.db.models import SECTION_LABELS
from tcfmaster.services import correction as C

GREEN, RED, GREY = "#2E8B57", "#C0392B", "#5F6B7A"


def _e(x) -> str:
    return html.escape(str(x or ""))


def question_html(q: C.McqCorrection, number: int | None = None) -> str:
    color = GREEN if q.is_correct else RED
    mark = "✔" if q.is_correct else "✘"
    n = number if number is not None else q.position
    out = [f"<p><b style='color:{color}'>{mark} Question {n} – {_e(q.result)}</b>"
           f"<br><b>{_e(q.prompt)}</b></p>",
           "<table cellpadding='3'>",
           f"<tr><td>Votre réponse :</td><td><b>{_e(q.user_answer or '—')}</b></td></tr>",
           f"<tr><td>Bonne réponse :</td><td><b style='color:{GREEN}'>"
           f"{_e(q.correct_answer)}</b></td></tr>",
           f"<tr><td>Résultat :</td><td><b style='color:{color}'>{_e(q.result)}</b></td></tr>",
           "</table>",
           f"<p><b>Justification :</b> {_e(q.justification)}</p>",
           f"<p><b>Explication :</b> {_e(q.explanation)}</p>",
           "<p><b>Pourquoi les autres propositions sont fausses :</b></p><ul>"]
    for c in q.wrong_choices:
        tag = " <i>(votre choix)</i>" if c.label == q.user_answer else ""
        out.append(f"<li><b>{c.label}.</b> {_e(c.text)}{tag}<br>"
                   f"<span style='color:{GREY}'>{_e(c.rationale)}</span></li>")
    out.append("</ul>")
    return "".join(out)


def exercise_extras_html(ex: C.ExerciseCorrection, show_document: bool = True) -> str:
    out = []
    if show_document:
        label = "Transcription" if ex.section == "CO" else "Texte"
        doc = _e(ex.document).replace("\n", "<br>")
        out.append(f"<h4>{label}</h4><p style='color:{GREY}'>{doc}</p>")
    if ex.vocabulary:
        out.append("<h4>Vocabulaire avancé</h4><ul>")
        for v in ex.vocabulary:
            ex_ = f"<br><i>{_e(v.get('exemple'))}</i>" if v.get("exemple") else ""
            out.append(f"<li><b>{_e(v.get('terme'))}</b> : {_e(v.get('definition'))}{ex_}</li>")
        out.append("</ul>")
    if ex.expressions:
        title = "Expressions idiomatiques" if ex.section == "CE" else "Expressions importantes"
        out.append(f"<h4>{title}</h4><ul>")
        for e in ex.expressions:
            ex_ = f"<br><i>{_e(e.get('exemple'))}</i>" if e.get("exemple") else ""
            out.append(f"<li><b>{_e(e.get('expression'))}</b> : {_e(e.get('sens'))}{ex_}</li>")
        out.append("</ul>")
    if ex.traps:
        out.append("<h4>Pièges de compréhension</h4><ul>")
        out += [f"<li>{_e(t)}</li>" for t in ex.traps]
        out.append("</ul>")
    return "".join(out)


def exercise_html(ex: C.ExerciseCorrection, show_document: bool = True) -> str:
    out = [f"<h3>{_e(ex.code)} – {_e(ex.title)} "
           f"<span style='color:{GREY}'>({ex.correct}/{ex.total})</span></h3>"]
    for q in ex.questions:
        out.append(question_html(q))
    out.append(exercise_extras_html(ex, show_document))
    return "".join(out)


def session_html(corr: C.SessionCorrection) -> str:
    pct = round(corr.rate * 100)
    color = GREEN if corr.rate >= 0.7 else RED
    mode = "Mode examen" if corr.mode == "examen" else "Mode entraînement"
    out = [f"<h2>Résultats – {SECTION_LABELS.get(corr.section, corr.section)} B2</h2>",
           f"<p>{mode} · <b style='color:{color}'>{corr.correct} / {corr.total} bonnes "
           f"réponses ({pct} %)</b></p>",
           "<h3>Conseils d'amélioration</h3><ul>"]
    out += [f"<li>{_e(a)}</li>" for a in corr.advice]
    out.append("</ul>")
    out.append(f"<p><i>{_e(corr.disclaimer)}</i></p><hr>")
    for ex in corr.exercises:
        out.append(exercise_html(ex))
        out.append("<hr>")
    return "".join(out)


def production_html(p: dict, title: str = "") -> str:
    """Vue commune d'une production EE/EO corrigée (voir correction.production_correction)."""
    out = [f"<h3>{_e(title)}</h3>" if title else "",
           f"<h4>Votre {'texte' if p.get('type') == 'EE' else 'réponse (transcription)'}</h4>",
           f"<p>{_e(p.get('original')).replace(chr(10), '<br>')}</p>"]
    errs = p.get("errors") or []
    out.append(f"<h4>Erreurs identifiées ({len(errs)})</h4>")
    if errs:
        out.append("<ul>")
        for e in errs:
            fix = f" → <b style='color:{GREEN}'>{_e(e['correction'])}</b>" if e.get("correction") else ""
            out.append(f"<li><b style='color:{RED}'>{_e(e['extrait'])}</b>{fix}"
                       f"<br><span style='color:{GREY}'>{_e(e['explication'])}</span></li>")
        out.append("</ul>")
    else:
        out.append("<p>Aucune erreur fréquente repérée automatiquement.</p>")
    out.append(f"<h4>Version corrigée</h4><p>{_e(p.get('corrected')).replace(chr(10), '<br>')}</p>")
    if p.get("model_answer"):
        out.append(f"<h4>Réponse modèle B2</h4><p>"
                   f"{_e(p['model_answer']).replace(chr(10), '<br>')}</p>")
    if p.get("explanations"):
        out.append("<h4>Explications</h4><ul>")
        out += [f"<li>{_e(v)}</li>" for v in p["explanations"].values() if v]
        out.append("</ul>")
    out.append(f"<h4>Appréciation pédagogique</h4><p>{_e(p.get('appreciation'))}</p>")
    if p.get("advice"):
        out.append("<ul>" + "".join(f"<li>{_e(a)}</li>" for a in p["advice"]) + "</ul>")
    out.append(f"<p><i>{_e(p.get('disclaimer'))}</i></p>")
    return "".join(out)
