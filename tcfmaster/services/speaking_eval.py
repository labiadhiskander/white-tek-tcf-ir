"""Évaluation locale de l'expression orale (TCF IRN).

Entrées : la transcription (reconnaissance vocale ou saisie manuelle), le
profil sonore de l'enregistrement (temps de parole, longues pauses) et la
tâche. Quatre critères sur 5 points :
  * réalisation de la tâche (éléments attendus selon la tâche, temps de parole) ;
  * aisance (débit, pauses, hésitations) ;
  * lexique (variété, connecteurs, phrases utiles réemployées, structures) ;
  * morphosyntaxe (erreurs fréquentes repérées dans la transcription).

La prononciation n'est pas notée : la confiance de la reconnaissance vocale
n'est affichée qu'à titre indicatif, avec la liste des mots que la
reconnaissance a eu du mal à identifier (`pronunciation_hints`). Une « réponse
améliorée » est proposée à partir de la transcription (`improved_answer`) :
hésitations retirées, corrections sûres appliquées, registre familier remplacé. Comme pour l'écrit, la note est une
ESTIMATION PÉDAGOGIQUE accompagnée de `levels.DISCLAIMER`.
"""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import asdict, dataclass, field

from tcfmaster.core import levels as L
from tcfmaster.services import writing_eval as WE
from tcfmaster.services.writing_rules import ADVICE, ERROR

ENGINE_VERSION = "oral-local-1"
AUTO_CAP = 16.0
STT_CAVEAT = ("La transcription automatique peut contenir des erreurs de reconnaissance : "
              "relisez-la et corrigez-la si nécessaire avant de vous fier à la note.")

HESITATIONS = re.compile(r"\b(euh+|heu+|hum+|hmm+|ben|bah|bon ben|beh)\b", re.I)
REPEATS = re.compile(r"\b(\w+)( \1\b)+", re.I)

# Éléments attendus propres à chaque tâche du TCF IRN.
TASK_POINTS: dict[int, list[tuple[str, re.Pattern]]] = {
    1: [
        ("se présenter", re.compile(r"\b(je m'appelle|mon nom|j'ai \d+ ans|j'ai \w+ ans|"
                                    r"je viens d|je suis (né|née|originaire)|j'habite)\b", re.I)),
        ("parler de son travail ou de ses études",
         re.compile(r"\b(travaille|travail|métier|profession|emploi|études|étudie|étudiante?|"
                    r"poste|entreprise|ingénieur|infirmière?|professeur|chômage)\b", re.I)),
        ("parler de ses loisirs ou de sa vie quotidienne",
         re.compile(r"\b(loisirs?|temps libre|week-end|j'aime|j'adore|passion|sport|lire|"
                    r"lecture|musique|cuisine|cuisiner|famille|enfants?)\b", re.I)),
        ("évoquer ses projets",
         re.compile(r"\b(je voudrais|j'aimerais|je vais|projets?|avenir|plus tard|"
                    r"dans \w+ ans|je compte|j'espère|\w+rai)\b", re.I)),
        ("justifier ses réponses",
         re.compile(r"\b(parce que|car|puisque|c'est pour ça|c'est pourquoi|comme)\b", re.I)),
    ],
    2: [
        ("s'adresser poliment à l'interlocuteur",
         re.compile(r"\b(bonjour|bonsoir|excusez-moi|madame|monsieur|s'il vous plaît|"
                    r"je vous remercie|merci)\b", re.I)),
        ("poser des questions",
         re.compile(r"\b(est-ce que|pourriez-vous|pouvez-vous|combien|quel|quelle|quels|"
                    r"quelles|comment|pourquoi|serait-il possible|avez-vous|y a-t-il|"
                    r"qu'en pensez-vous|à quelle heure|où)\b", re.I)),
        ("argumenter et répondre aux objections",
         re.compile(r"\b(je comprends|mais|cependant|pourtant|par contre|en revanche|"
                    r"je vous assure|justement|au contraire|il est vrai)\b", re.I)),
        ("proposer une solution ou négocier",
         re.compile(r"\b(je propose|je vous propose|pourquoi ne pas|on pourrait|"
                    r"nous pourrions|je m'engage|serait-il possible|je suggère|"
                    r"en échange|à condition)\b", re.I)),
        ("conclure l'échange",
         re.compile(r"\b(d'accord|entendu|parfait|merci beaucoup|au revoir|c'est noté|"
                    r"très bien|marché conclu|je vous remercie)\b", re.I)),
    ],
    3: [
        ("donner une opinion claire",
         re.compile(r"\b(je pense|je crois|à mon avis|selon moi|pour ma part|il me semble|"
                    r"je suis (convaincue?|persuadée?|pour|contre|favorable|opposée?)|"
                    r"personnellement|d'après moi|à mon sens|je trouve)\b", re.I)),
        ("développer des arguments",
         re.compile(r"\b(d'abord|tout d'abord|ensuite|de plus|en outre|d'une part|"
                    r"d'autre part|premièrement|par ailleurs|parce que|car|en effet)\b", re.I)),
        ("illustrer par des exemples",
         re.compile(r"\b(par exemple|notamment|comme|prenons|c'est le cas|dans mon pays|"
                    r"chez moi|j'ai vu|j'ai connu)\b", re.I)),
        ("nuancer", re.compile(r"\b(certes|bien que|même si|cependant|toutefois|néanmoins|"
                               r"en revanche|il faut reconnaître|il est vrai)\b", re.I)),
        ("conclure", re.compile(r"\b(en conclusion|pour conclure|en somme|finalement|bref|"
                                r"tout compte fait|en définitive|pour finir|donc)\b", re.I)),
    ],
}


@dataclass
class OralEvaluation:
    task_number: int
    words: int
    duration_s: float
    target_s: int
    speech_s: float
    wpm: float
    long_pauses: int
    hesitations: int
    repetitions_immediate: int
    stt_confidence: float | None
    criteria: dict[str, float]
    criteria_comments: dict[str, str]
    note20: float
    level: str
    issues: list[WE.Issue]
    points: list[WE.PointCheck]
    connectors: dict[str, list[str]]
    structures: list[str]
    phrases_reused: list[str]
    strengths: list[str]
    priorities: list[str]
    model_answer: str = ""
    model_commentary: str = ""
    tips: str = ""
    pronunciation: dict = field(default_factory=dict)
    improved_answer: str = ""
    caveat: str = STT_CAVEAT
    disclaimer: str = L.DISCLAIMER
    engine: str = ENGINE_VERSION
    extra: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


ORAL_CRITERIA = {"tache": "Réalisation de la tâche", "aisance": "Aisance et fluidité",
                 "lexique": "Lexique", "grammaire": "Morphosyntaxe"}
_ORAL_SKIP_RULES = {"point-majuscule", "debut-majuscule", "point-final", "espace-apres",
                    "espace-avant-virgule", "accents", "elision"}


def oral_issues(text: str) -> list[WE.Issue]:
    """Erreurs pertinentes à l'oral : on ignore ponctuation et orthographe pure
    (la transcription n'en a pas), et l'omission de « ne », courante à l'oral,
    devient un simple conseil."""
    out = []
    for i in WE.find_issues(text):
        if i.rule in _ORAL_SKIP_RULES or i.category in ("ponctuation",):
            continue
        if i.rule == "negation-incomplete":
            i.severity = ADVICE
            i.message = "Négation sans « ne » : acceptée à l'oral familier, à éviter à l'examen."
        out.append(i)
    return out


# Équivalents standard des mots et tours familiers (réponse améliorée).
FAMILIAR = {
    "ouais": "oui", "bouquin": "livre", "bouquins": "livres", "boulot": "travail",
    "boulots": "emplois", "bagnole": "voiture", "bagnoles": "voitures", "truc": "chose",
    "trucs": "choses", "machin": "chose", "machins": "choses", "mec": "homme",
    "mecs": "hommes", "fringues": "vêtements", "bosser": "travailler", "bosse": "travaille",
    "kiffer": "apprécier", "kiffe": "apprécie", "marrant": "drôle", "fric": "argent",
    "bouffer": "manger", "cool": "agréable", "sympa": "sympathique",
    "sympas": "sympathiques", "du coup": "par conséquent", "ça fait que": "c'est pourquoi",
    "par contre": "en revanche", "y avait": "il y avait",
}
_FAMILIAR_RX = re.compile(r"\b(" + "|".join(sorted(map(re.escape, FAMILIAR), key=len,
                                                   reverse=True)) + r")\b", re.I)
_FILLERS = re.compile(r"\s*\b(euh+|heu+|hum+|hmm+|bon ben|ben|bah|beh|genre|en fait|"
                      r"tu vois|vous voyez|voilà quoi|quoi)\b,?", re.I)
# Négations sans « ne », fréquentes à l'oral familier.
NEGATIONS = {
    "il y a pas": "il n'y a pas", "y a pas": "il n'y a pas", "c'est pas": "ce n'est pas",
    "j'ai pas": "je n'ai pas", "je sais pas": "je ne sais pas", "je suis pas": "je ne suis pas",
    "on a pas": "on n'a pas", "je pense pas": "je ne pense pas", "je crois pas": "je ne crois pas",
    "il faut pas": "il ne faut pas", "je peux pas": "je ne peux pas",
    "c'était pas": "ce n'était pas", "j'avais pas": "je n'avais pas",
}
_NEG_RX = re.compile(r"\b(" + "|".join(sorted(map(re.escape, NEGATIONS), key=len,
                                               reverse=True)) + r")\b", re.I)
UNCLEAR_CONF = 0.6


def improved_answer(transcript: str) -> str:
    """Version améliorée de la transcription, construite sans IA : hésitations et
    tics de langage supprimés, répétitions immédiates fusionnées, mots familiers
    remplacés par un équivalent standard, corrections sûres appliquées."""
    text = re.sub(r"\s+", " ", transcript or "").strip()
    if not text:
        return ""
    text = _FILLERS.sub("", text)
    # « je je pense » → « je pense », mais « nous nous sommes » reste intact
    text = REPEATS.sub(lambda m: m.group(0) if m.group(1).lower() in ("nous", "vous")
                       else m.group(1), text)
    text = _NEG_RX.sub(lambda m: NEGATIONS[m.group(1).lower().replace("’", "'")], text)
    text = _FAMILIAR_RX.sub(lambda m: FAMILIAR[m.group(1).lower()], text)
    text = re.sub(r"\s+([,.])", r"\1", re.sub(r"\s{2,}", " ", text)).strip(" ,")
    text = WE.apply_fixes(text, [i for i in WE.find_issues(text) if i.replacement is not None])
    text = text[0].upper() + text[1:] if text else text
    return text if text.endswith((".", "!", "?", "…")) else text + "."


def pronunciation_hints(words: list | None) -> dict:
    """Indices de prononciation tirés de la confiance mot à mot de la reconnaissance
    vocale (Vosk). Indicatif : un mot mal reconnu peut aussi venir du micro ou du
    bruit ambiant. `words` : dicts {"word", "conf"} ou objets ayant ces attributs."""
    items = []
    for w in words or []:
        word = w.get("word") if isinstance(w, dict) else getattr(w, "word", "")
        conf = w.get("conf", 1.0) if isinstance(w, dict) else getattr(w, "conf", 1.0)
        if word:
            items.append((str(word), float(conf if conf is not None else 1.0)))
    if not items:
        return {}
    low = [(w, c) for w, c in items if c < UNCLEAR_CONF and len(w) > 2]
    unclear, seen = [], set()
    for w, c in sorted(low, key=lambda x: x[1]):
        if w.lower() not in seen:
            seen.add(w.lower())
            unclear.append(w)
    share = round(len(low) / len(items), 2)
    advice = []
    if share >= 0.2:
        advice.append("Beaucoup de mots ont été difficiles à reconnaître : parlez un peu plus "
                      "lentement, articulez les fins de mots et rapprochez-vous du micro.")
    elif unclear:
        advice.append("Réécoutez votre enregistrement sur les mots signalés et répétez-les "
                      "après la réponse modèle lue par la voix de synthèse.")
    else:
        advice.append("La reconnaissance a identifié presque tous les mots : votre "
                      "articulation semble claire.")
    nasal = [w for w in unclear if re.search(r"(an|en|on|in|un|ain|ein)(s|t|e)?$", w, re.I)]
    if nasal:
        advice.append("Plusieurs mots signalés contiennent une voyelle nasale (an, on, in) : "
                      "travaillez la différence entre « vent », « vont » et « vin ».")
    if any(re.search(r"(u|eu|œu)", w, re.I) for w in unclear):
        advice.append("Vérifiez les sons « u » / « ou » et « eu » (« rue » / « roue », "
                      "« deux ») dans les mots signalés.")
    return {"words": len(items), "unclear": unclear[:12], "unclear_share": share,
            "advice": advice[:3]}


def _clamp(x: float) -> float:
    return round(max(0.0, min(5.0, x)) * 2) / 2


def _reused_phrases(text: str, phrases: list[str] | None) -> list[str]:
    folded = WE._fold(text)
    out = []
    for p in phrases or []:
        key = WE._fold(p).split("…")[0].split("...")[0].strip(" .?!")
        if len(key) >= 6 and key in folded:
            out.append(p)
    return out


def evaluate_oral(transcript: str, task_number: int, target_s: int,
                  profile: dict | None = None, stt_confidence: float | None = None,
                  useful_phrases: list[str] | None = None, model_answer: str = "",
                  duration_s: float | None = None, stt_words: list | None = None,
                  model_commentary: str = "", tips: str = "") -> OralEvaluation:
    text = re.sub(r"\s+", " ", transcript or "").strip()
    ws = WE.words(text)
    n = len(ws)
    profile = profile or {}
    duration = float(duration_s if duration_s is not None else profile.get("duration_s", 0))
    speech = float(profile.get("speech_s") or (duration * 0.8 if duration else 0))
    minutes = speech / 60 if speech > 0 else (duration / 60 if duration else 0)
    wpm = round(n / minutes, 0) if minutes else 0.0
    long_pauses = int(profile.get("long_pauses", 0))
    hes = len(HESITATIONS.findall(text))
    reps = len(REPEATS.findall(text))

    issues = oral_issues(text) if n else []
    errors = [i for i in issues if i.severity == ERROR]
    advice = [i for i in issues if i.severity == ADVICE]
    points = []
    for label, rx in TASK_POINTS.get(task_number, []):
        m = rx.search(text)
        points.append(WE.PointCheck(label, "présent" if m else "absent",
                                    m.group(0) if m else ""))
    conns = WE.find_connectors(text) if n else {}
    structures = WE.find_structures(text) if n else []
    reused = _reused_phrases(text, useful_phrases)

    # --- réalisation de la tâche
    if n == 0:
        c_task, m_task = 0.0, "Aucune parole transcrite."
    else:
        cov = sum(p.status == "présent" for p in points) / max(1, len(points))
        time_ratio = min(1.0, (duration or speech) / target_s) if target_s else 1.0
        c_task = 1 + 3 * cov + (1 if time_ratio >= 0.7 else 0.5 if time_ratio >= 0.4 else 0)
        if time_ratio < 0.3:
            c_task -= 1.5
        m_task = (f"{round(cov * 100)} % des éléments attendus ; temps utilisé "
                  f"{round(time_ratio * 100)} % de la durée prévue.")
        c_task = _clamp(c_task)
    # --- aisance
    if n == 0:
        c_flu, m_flu = 0.0, ""
    else:
        if wpm > 230:          # débit impossible : transcription et durée incohérentes
            c_flu = 2.5
        elif wpm >= 100:
            c_flu = 4.5 if wpm <= 170 else 4.0
        elif wpm >= 80:
            c_flu = 3.5
        elif wpm >= 60:
            c_flu = 2.5
        else:
            c_flu = 1.5
        per_min = minutes or 1
        c_flu -= min(1.5, 0.5 * long_pauses / per_min)
        c_flu -= min(1.5, hes * 100 / max(n, 30) * 0.15)
        c_flu -= min(0.5, reps * 0.25)
        c_flu = _clamp(c_flu + (0.5 if len(conns) >= 4 else 0))
        m_flu = (f"Débit {int(wpm)} mots/min ; {long_pauses} longue(s) pause(s) ; "
                 f"{hes} hésitation(s).")
        if wpm > 230:
            m_flu += " Débit incohérent avec la durée : vérifiez la transcription."
    # --- lexique
    if n == 0:
        c_lex, m_lex = 0.0, ""
    else:
        st = WE.text_stats(text)
        c_lex = (0.5 + min(2.0, max(0.0, (st["lexical_variety"] - 0.45) * 7))
                 + min(1.0, 0.25 * len(conns)) + min(1.0, 0.5 * len(structures))
                 + min(1.0, 0.5 * len(reused))
                 - 0.25 * sum(1 for i in advice if i.category in ("registre", "lexique")))
        if n < 40:
            c_lex = min(c_lex, 2.5)
        c_lex = _clamp(c_lex)
        m_lex = (f"Variété {round(st['lexical_variety'] * 100)} % ; "
                 f"{sum(len(v) for v in conns.values())} connecteur(s) ; "
                 f"{len(reused)} phrase(s) utile(s) réemployée(s).")
    # --- morphosyntaxe
    if n == 0:
        c_gram, m_gram = 0.0, ""
    else:
        density = len(errors) * 100 / max(n, 40)
        c_gram = _clamp(5 - density * 0.8)
        if n < 40:
            c_gram = min(c_gram, 3.0)
        m_gram = f"{len(errors)} erreur(s) repérée(s) dans la transcription."

    criteria = {"tache": c_task, "aisance": c_flu, "lexique": c_lex, "grammaire": c_gram}
    note = min(AUTO_CAP, round(sum(criteria.values()) * 2) / 2)
    # Plafonds de prudence : une production trop courte ne peut pas montrer un niveau B2.
    if n and (duration or speech) < 30:
        note = min(note, 5.0)
    if n and n < 40:
        note = min(note, 6.0)
    elif n and n < 80:
        note = min(note, 9.0)
    if n and target_s and (duration or speech) < 0.5 * target_s:
        note = min(note, 9.0)
    level = L.expression_level(note) if note > 0 else "< A1"

    strengths, prio = [], []
    if n and 90 <= wpm <= 230 and long_pauses <= 2:
        strengths.append("Discours fluide, avec un débit naturel.")
    if points and all(p.status == "présent" for p in points):
        strengths.append("Tous les éléments attendus de la tâche sont abordés.")
    if len(conns) >= 4:
        strengths.append("Vous enchaînez vos idées avec des connecteurs variés.")
    if reused:
        strengths.append("Vous réemployez des formules utiles de la leçon.")
    if n == 0:
        prio.append("Parlez pendant toute la durée de la tâche : un silence vaut 0.")
    else:
        if target_s and (duration or speech) < 0.7 * target_s:
            prio.append("Utilisez tout le temps disponible : développez vos réponses avec "
                        "des exemples personnels.")
        missing = [p.label for p in points if p.status == "absent"]
        if missing:
            prio.append("Pensez à : " + ", ".join(missing[:3]) + ".")
        if hes * 100 / max(n, 30) > 4 or long_pauses >= 4:
            prio.append("Réduisez les hésitations : préparez des formules d'attaque "
                        "(« Pour ma part… », « Ce que je veux dire, c'est que… »).")
        cats = Counter(i.chapter or i.category for i in errors)
        for key, cnt in cats.most_common(1):
            prio.append(f"Revoyez « {key} » ({cnt} erreur(s)).")
        if len(conns) < 3:
            prio.append("Structurez votre discours : d'abord, ensuite, de plus, en revanche, "
                        "pour conclure.")
    return OralEvaluation(
        task_number=task_number, words=n, duration_s=round(duration, 1), target_s=target_s,
        speech_s=round(speech, 1), wpm=wpm, long_pauses=long_pauses, hesitations=hes,
        repetitions_immediate=reps, stt_confidence=stt_confidence, criteria=criteria,
        criteria_comments={"tache": m_task, "aisance": m_flu, "lexique": m_lex,
                           "grammaire": m_gram},
        note20=note, level=level, issues=issues, points=points, connectors=conns,
        structures=structures, phrases_reused=reused, strengths=strengths,
        priorities=prio[:3], model_answer=model_answer,
        model_commentary=model_commentary or "", tips=tips or "",
        pronunciation=pronunciation_hints(stt_words) if n else {},
        improved_answer=improved_answer(text) if n else "")
