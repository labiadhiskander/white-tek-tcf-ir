"""Rapport de correction d'une production écrite (HTML pour QTextBrowser)."""
from __future__ import annotations

import html

from tcfmaster.core import levels as L
from tcfmaster.services.writing_eval import CRITERIA_LABELS

RED, ORANGE, GREEN, MUTED = "#C0392B", "#C98A0B", "#2E8B57", "#5F6B7A"
CATEGORY_LABELS = {
    "orthographe": "Orthographe", "grammaire": "Grammaire", "conjugaison": "Conjugaison",
    "syntaxe": "Syntaxe", "registre": "Registre", "lexique": "Lexique",
    "ponctuation": "Ponctuation et typographie",
}


def _esc(x) -> str:
    return html.escape(str(x or ""))


def annotated_text(text: str, issues: list[dict]) -> str:
    """Texte de l'apprenant avec les passages fautifs surlignés et numérotés
    (la numérotation est celle de la correction détaillée)."""
    spans: list[dict] = []
    for n, i in enumerate(sorted(issues, key=lambda i: i["start"]), 1):
        if spans and i["start"] < spans[-1]["end"]:      # chevauchement : même repère
            spans[-1]["nums"].append(n)
            spans[-1]["end"] = max(spans[-1]["end"], i["end"])
            spans[-1]["error"] |= i["severity"] == "erreur"
            continue
        spans.append({"start": i["start"], "end": i["end"], "nums": [n],
                      "error": i["severity"] == "erreur"})
    out, pos = [], 0
    for sp in spans:
        color, bg = (RED, "#FADBD8") if sp["error"] else (ORANGE, "#FDEBD0")
        out.append(_esc(text[pos:sp["start"]]))
        out.append(f"<span style='background:{bg};color:{color};'>"
                   f"{_esc(text[sp['start']:sp['end']])}</span>"
                   f"<sup style='color:{color}'>{','.join(map(str, sp['nums']))}</sup>")
        pos = sp["end"]
    out.append(_esc(text[pos:]))
    return "".join(out).replace("\n", "<br>")


def _bar(value: float, maxi: float = 5) -> str:
    full = int(round(value * 2))                    # un bloc par demi-point
    color = GREEN if value >= 3.5 else ORANGE if value >= 2.5 else RED
    return (f"<span style='color:{color}'>{'█' * full}</span>"
            f"<span style='color:#D9DEE5'>{'█' * (int(maxi * 2) - full)}</span>")


def evaluation_html(ev: dict, text: str, title: str = "") -> str:
    if not ev:
        return "<p>Aucune évaluation.</p>"
    n, lo, hi = ev["word_count"], ev["min_words"], ev["max_words"]
    wc_color = GREEN if lo <= n <= hi else RED
    out = []
    if title:
        out.append(f"<h2>{_esc(title)}</h2>")
    out.append(
        f"<p style='font-size:15pt'><b>Note estimée : {ev['note20']:.1f} / 20</b> · "
        f"niveau estimé <b>{_esc(ev['level'])}</b></p>"
        f"<p style='color:{MUTED}'><i>{_esc(ev.get('disclaimer') or L.DISCLAIMER)} "
        f"Correction automatique hors ligne : elle repère les erreurs fréquentes mais ne "
        f"remplace pas la relecture d'un enseignant.</i></p>"
        f"<p>Nombre de mots : <b style='color:{wc_color}'>{n}</b> (attendu : {lo} à {hi})</p>")
    # critères
    out.append("<h3>Grille d'évaluation</h3><table cellpadding=4>")
    for key, label in CRITERIA_LABELS.items():
        v = ev["criteria"].get(key, 0)
        out.append(f"<tr><td><b>{label}</b></td><td>{_bar(v)}</td><td>{v:.1f} / 5</td>"
                   f"<td style='color:{MUTED}'>{_esc(ev['criteria_comments'].get(key))}"
                   f"</td></tr>")
    out.append("</table>")
    if ev.get("strengths"):
        out.append("<h3>Points forts</h3><ul>" + "".join(
            f"<li style='color:{GREEN}'>{_esc(x)}</li>" for x in ev["strengths"]) + "</ul>")
    if ev.get("priorities"):
        out.append("<h3>Vos trois priorités</h3><ol>" + "".join(
            f"<li>{_esc(x)}</li>" for x in ev["priorities"]) + "</ol>")
    if ev.get("points"):
        icon = {"présent": f"<span style='color:{GREEN}'>✔</span>",
                "absent": f"<span style='color:{RED}'>✘</span>",
                "non vérifiable": f"<span style='color:{MUTED}'>?</span>"}
        out.append("<h3>Éléments attendus par la consigne</h3><ul>" + "".join(
            f"<li>{icon.get(p['status'], '')} {_esc(p['label'])}"
            + (f" <span style='color:{MUTED}'>(« {_esc(p['evidence'])} »)</span>"
               if p.get("evidence") else
               f" <span style='color:{MUTED}'>— à vérifier vous-même</span>"
               if p["status"] == "non vérifiable" else "")
            + "</li>" for p in ev["points"]) + "</ul>")
    # texte annoté et détail
    issues = ev.get("issues") or []
    out.append("<h3>Votre texte annoté</h3>"
               f"<p style='line-height:150%'>{annotated_text(text, issues)}</p>")
    if issues:
        out.append(f"<p style='color:{MUTED}'>Souligné rouge : erreur · orange : conseil "
                   f"de style ou de registre.</p><h3>Correction détaillée</h3><ol>")
        for i in sorted(issues, key=lambda i: i["start"]):
            color = RED if i["severity"] == "erreur" else ORANGE
            fix = (f" → <b style='color:{GREEN}'>{_esc(i['replacement'].strip())}</b>"
                   if i.get("replacement") else
                   f" → <i>{_esc(i['suggestion'])}</i>" if i.get("suggestion") else "")
            chap = (f"<br><span style='color:{MUTED}'>À revoir : chapitre de grammaire "
                    f"« {_esc(i['chapter'])} »</span>" if i.get("chapter") else "")
            out.append(f"<li><span style='color:{color}'>[{CATEGORY_LABELS.get(i['category'], i['category'])}]"
                       f"</span> « {_esc(i['excerpt'])} »{fix}<br><b>{_esc(i['message'])}</b> "
                       f"{_esc(i['explanation'])}{chap}</li>")
        out.append("</ol>")
    else:
        out.append("<p>Aucune erreur fréquente repérée automatiquement. Relisez tout de même "
                   "les accords et la conjugaison.</p>")
    if ev.get("corrected_text") and ev["corrected_text"] != text:
        out.append("<h3>Version corrigée (corrections sûres appliquées)</h3>"
                   f"<p style='background:#F3F8F4;padding:6px'>{_esc(ev['corrected_text'])}"
                   "</p>")
    # cohérence et lexique
    conns = ev.get("connectors") or {}
    out.append("<h3>Cohérence et richesse de la langue</h3><ul>")
    out.append("<li>Connecteurs utilisés : " + ("; ".join(
        f"<i>{_esc(k)}</i> : {_esc(', '.join(v))}" for k, v in conns.items()) or "aucun")
        + "</li>")
    out.append("<li>Structures complexes : " + (_esc(", ".join(ev.get("structures") or []))
                                              or "aucune repérée") + "</li>")
    if ev.get("repetitions"):
        out.append("<li>Mots répétés : " + _esc(", ".join(ev["repetitions"])) + "</li>")
    st = ev.get("stats") or {}
    if st:
        out.append(f"<li>{st.get('sentences', 0)} phrase(s), {st.get('avg_sentence_len', 0)} "
                   f"mots par phrase en moyenne, variété lexicale "
                   f"{round(100 * st.get('lexical_variety', 0))} %</li>")
    out.append("</ul>")
    if ev.get("syntax"):
        out.append("<h3>Syntaxe</h3><ul>" + "".join(
            f"<li>{_esc(x)}</li>" for x in ev["syntax"]) + "</ul>")
    if ev.get("model_answer"):
        ms = ev.get("model_stats") or {}
        out.append("<h3>Réponse modèle (niveau B2)</h3>"
                   f"<p style='background:#F3F5F8;padding:6px'>{_esc(ev['model_answer'])}</p>"
                   f"<p style='color:{MUTED}'>Comparez : modèle {ms.get('words', '?')} mots, "
                   f"{ms.get('sentences', '?')} phrases, variété "
                   f"{round(100 * ms.get('lexical_variety', 0))} %. Repérez ses connecteurs "
                   f"et ses structures, puis réécrivez votre texte.</p>")
    return "".join(out)
