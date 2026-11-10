"""Rapport d'évaluation d'une production orale (HTML)."""
from __future__ import annotations

from tcfmaster.core import levels as L
from tcfmaster.services.speaking_eval import ORAL_CRITERIA, STT_CAVEAT
from tcfmaster.ui.writing_report import (CATEGORY_LABELS, GREEN, MUTED, ORANGE, RED, _bar,
                                         _esc, annotated_text)


def oral_html(ev: dict, transcript: str, title: str = "", dialogue: list | None = None,
              has_audio: bool = False) -> str:
    if not ev:
        return "<p>Aucune évaluation.</p>"
    out = []
    if title:
        out.append(f"<h2>{_esc(title)}</h2>")
    conf = ev.get("stt_confidence")
    out.append(
        f"<p style='font-size:15pt'><b>Note estimée : {ev['note20']:.1f} / 20</b> · niveau "
        f"estimé <b>{_esc(ev['level'])}</b></p>"
        f"<p style='color:{MUTED}'><i>{_esc(ev.get('disclaimer') or L.DISCLAIMER)} "
        f"{_esc(ev.get('caveat') or STT_CAVEAT)} La prononciation n'est pas notée.</i></p>")
    dur, target = ev.get("duration_s", 0), ev.get("target_s", 0)
    out.append("<table cellpadding=4>"
               f"<tr><td>Durée</td><td><b>{int(dur // 60)} min {int(dur % 60):02d} s</b> "
               f"sur {int(target // 60)} min {int(target % 60):02d} s prévues</td></tr>"
               f"<tr><td>Temps de parole</td><td>{ev.get('speech_s', 0):.0f} s</td></tr>"
               f"<tr><td>Débit</td><td>{int(ev.get('wpm', 0))} mots/min "
               f"<span style='color:{MUTED}'>(repère : 100 à 160)</span></td></tr>"
               f"<tr><td>Longues pauses</td><td>{ev.get('long_pauses', 0)}</td></tr>"
               f"<tr><td>Hésitations (euh, ben…)</td><td>{ev.get('hesitations', 0)}</td></tr>"
               + (f"<tr><td>Intelligibilité (indicatif)</td><td>{round(conf * 100)} % de "
                  f"confiance de la reconnaissance</td></tr>" if conf is not None else "")
               + "</table>")
    out.append("<h3>Grille d'évaluation</h3><table cellpadding=4>")
    for key, label in ORAL_CRITERIA.items():
        v = ev["criteria"].get(key, 0)
        out.append(f"<tr><td><b>{label}</b></td><td>{_bar(v)}</td><td>{v:.1f} / 5</td>"
                   f"<td style='color:{MUTED}'>{_esc(ev['criteria_comments'].get(key))}"
                   f"</td></tr>")
    out.append("</table>")
    if ev.get("strengths"):
        out.append("<h3>Points forts</h3><ul>" + "".join(
            f"<li style='color:{GREEN}'>{_esc(x)}</li>" for x in ev["strengths"]) + "</ul>")
    if ev.get("priorities"):
        out.append("<h3>Vos priorités</h3><ol>" + "".join(
            f"<li>{_esc(x)}</li>" for x in ev["priorities"]) + "</ol>")
    if ev.get("points"):
        out.append("<h3>Ce que l'examinateur attend</h3><ul>" + "".join(
            (f"<li><span style='color:{GREEN}'>✔</span> {_esc(p['label'])} "
             f"<span style='color:{MUTED}'>(« {_esc(p['evidence'])} »)</span></li>"
             if p["status"] == "présent" else
             f"<li><span style='color:{RED}'>✘</span> {_esc(p['label'])}</li>")
            for p in ev["points"]) + "</ul>")
    if dialogue:
        out.append("<h3>Déroulement</h3><ul>")
        for turn in dialogue:
            who = "Examinateur" if turn.get("who") == "examinateur" else "Vous"
            t = turn.get("t")
            stamp = f"[{int(t // 60)}:{int(t % 60):02d}] " if isinstance(t, (int, float)) else ""
            out.append(f"<li><b>{stamp}{who} :</b> {_esc(turn.get('text'))}</li>")
        out.append("</ul>")
    issues = ev.get("issues") or []
    out.append("<h3>Votre transcription annotée</h3>"
               f"<p style='line-height:150%'>{annotated_text(transcript, issues) or '—'}</p>")
    if issues:
        out.append("<h3>Remarques</h3><ol>")
        for i in sorted(issues, key=lambda i: i["start"]):
            color = RED if i["severity"] == "erreur" else ORANGE
            fix = (f" → <b style='color:{GREEN}'>{_esc(i['replacement'])}</b>"
                   if i.get("replacement") else
                   f" → <i>{_esc(i['suggestion'])}</i>" if i.get("suggestion") else "")
            out.append(f"<li><span style='color:{color}'>[{CATEGORY_LABELS.get(i['category'], i['category'])}]"
                       f"</span> « {_esc(i['excerpt'])} »{fix}<br><b>{_esc(i['message'])}</b> "
                       f"{_esc(i['explanation'])}</li>")
        out.append("</ol>")
    conns = ev.get("connectors") or {}
    out.append("<h3>Richesse du discours</h3><ul>"
               "<li>Connecteurs : " + ("; ".join(f"<i>{_esc(k)}</i> : {_esc(', '.join(v))}"
                                                 for k, v in conns.items()) or "aucun") + "</li>"
               "<li>Structures complexes : " + (_esc(", ".join(ev.get("structures") or []))
                                                or "aucune repérée") + "</li>"
               "<li>Phrases utiles réemployées : " + (_esc(" ; ".join(ev.get("phrases_reused")
                                                                     or [])) or "aucune")
               + "</li></ul>")
    if ev.get("model_answer"):
        out.append("<h3>Exemple de production attendue (extrait)</h3>"
                   f"<p style='background:#F3F5F8;padding:6px'>{_esc(ev['model_answer'])}</p>")
    out.append(f"<p style='color:{MUTED}'>Enregistrement audio : "
               + ("conservé (vous pouvez le réécouter ou le supprimer)." if has_audio else
                  "non conservé.") + "</p>")
    return "".join(out)
