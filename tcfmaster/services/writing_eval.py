"""Moteur local de correction de l'expression écrite (TCF IRN).

Il fonctionne entièrement hors ligne et produit, pour une production :
  * la liste des erreurs repérées (position, explication, correction,
    chapitre de grammaire à revoir) et une version corrigée lorsque la
    correction est sûre ;
  * une analyse de la tâche (nombre de mots, points attendus de la consigne),
    de la cohérence (connecteurs, phrases, paragraphes) et du lexique
    (richesse, répétitions, structures complexes) ;
  * une note estimée sur 20 décomposée en quatre critères inspirés de la
    grille du TCF : réalisation de la tâche, cohérence et cohésion, lexique,
    morphosyntaxe et orthographe (5 points chacun) ;
  * des points forts, trois priorités de travail et une comparaison avec la
    réponse modèle.

La note est une ESTIMATION PÉDAGOGIQUE : elle est toujours accompagnée de
l'avertissement `levels.DISCLAIMER` et ne constitue jamais un résultat
officiel de France Éducation international. Un moteur d'IA (phase 7) peut
compléter cette analyse, jamais la présenter comme officielle.
"""
from __future__ import annotations

import re
import unicodedata
from collections import Counter
from dataclasses import asdict, dataclass, field

from tcfmaster.content.validator import count_words
from tcfmaster.core import levels as L
from tcfmaster.services.writing_rules import (ADVICE, CASE_RULES, COMPLEX_STRUCTURES,
                                              CONNECTORS, ERROR, RULES, STOPWORDS)

ENGINE_VERSION = "local-1"
AUTO_CAP = 16.0
_WORD = re.compile(r"[A-Za-zÀ-ÖØ-öø-ÿœŒæÆ]+(?:['’-][A-Za-zÀ-ÖØ-öø-ÿœŒæÆ]+)*")
_SENT_SPLIT = re.compile(r"(?<=[.!?…])\s+")


# ------------------------------------------------------------------ données
@dataclass
class Issue:
    rule: str
    category: str
    severity: str
    start: int
    end: int
    excerpt: str
    message: str
    explanation: str
    replacement: str | None = None
    suggestion: str = ""
    chapter: str = ""


@dataclass
class PointCheck:
    label: str
    status: str          # « présent », « absent », « non vérifiable »
    evidence: str = ""


@dataclass
class Evaluation:
    task_number: int | None
    word_count: int
    min_words: int
    max_words: int
    criteria: dict[str, float]          # 4 critères sur 5
    criteria_comments: dict[str, str]
    note20: float
    level: str
    issues: list[Issue]
    points: list[PointCheck]
    connectors: dict[str, list[str]]
    structures: list[str]
    repetitions: list[str]
    stats: dict[str, float]
    strengths: list[str]
    priorities: list[str]
    corrected_text: str
    model_answer: str = ""
    model_stats: dict[str, float] = field(default_factory=dict)
    syntax: list[str] = field(default_factory=list)
    disclaimer: str = L.DISCLAIMER
    engine: str = ENGINE_VERSION

    def to_dict(self) -> dict:
        return asdict(self)

    @property
    def errors(self) -> list[Issue]:
        return [i for i in self.issues if i.severity == ERROR]


# ------------------------------------------------------------------ outils
def _fold(s: str) -> str:
    s = unicodedata.normalize("NFD", s.lower().replace("’", "'"))
    return "".join(c for c in s if unicodedata.category(c) != "Mn")


def words(text: str) -> list[str]:
    return [w.lower().replace("’", "'") for w in _WORD.findall(text)]


def sentences(text: str) -> list[str]:
    return [x for x in (p.strip() for p in _SENT_SPLIT.split(text.strip())) if x]


def find_issues(text: str) -> list[Issue]:
    """Applique toutes les règles ; les chevauchements sont résolus en gardant
    la première règle (les règles d'erreur passent avant les conseils)."""
    found: list[Issue] = []
    # Deux corrections automatiques ne peuvent pas se chevaucher ; un diagnostic
    # sans correction peut en revanche recouvrir une correction (ex. « Bien que il
    # est » : élision + subjonctif).
    taken: dict[bool, list[tuple[int, int]]] = {True: [], False: []}
    ordered = sorted(RULES, key=lambda r: r.severity != ERROR)
    for rule in ordered:
        fixable = rule.fix is not None
        for m in rule.pattern.finditer(text):
            s, e = m.span()
            case_rule = rule.id in CASE_RULES       # se cumule avec les autres règles
            if s == e or (not case_rule and any(s < b and a < e for a, b in taken[fixable])):
                continue
            repl = None
            if fixable:
                repl = rule.fix(m) if callable(rule.fix) else m.expand(rule.fix)
            found.append(Issue(rule.id, rule.category, rule.severity, s, e,
                               text[s:e].strip(), rule.message, rule.explanation, repl,
                               rule.suggestion, rule.chapter))
            if not case_rule:
                taken[fixable].append((s, e))
    # majuscule en début de texte
    first = re.search(r"[A-Za-zÀ-ÿ]", text)
    if first and first.group(0).islower():
        i = first.start()
        found.append(Issue("debut-majuscule", "ponctuation", ERROR, i, i + 1, text[i],
                           "Majuscule en début de texte.",
                           "Le texte commence par une majuscule.", text[i].upper()))
    # point final
    stripped = text.rstrip()
    last = sentences(stripped)[-1] if stripped else ""
    if stripped and stripped[-1] not in ".!?…»)" and len(last.split()) >= 4:
        found.append(Issue("point-final", "ponctuation", ADVICE, len(stripped) - 1,
                           len(stripped), stripped[-1], "Ponctuation finale manquante.",
                           "Terminez la dernière phrase par un point (ou ! / ?)."))
    return sorted(found, key=lambda i: i.start)


def apply_fixes(text: str, issues: list[Issue]) -> str:
    """Applique les corrections sûres ; les majuscules sont rétablies à la fin."""
    out, pos = [], 0
    for i in sorted((i for i in issues if i.replacement is not None
                     and i.rule not in CASE_RULES), key=lambda i: i.start):
        if i.start < pos:
            continue
        out.append(text[pos:i.start])
        out.append(i.replacement)
        pos = i.end
    out.append(text[pos:])
    fixed = "".join(out)
    if any(i.rule in CASE_RULES for i in issues) or fixed != text:
        fixed = re.sub(r"(?<!etc)(?<!\.)([.!?]\s+)([a-zà-ÿ])",
                       lambda m: m.group(1) + m.group(2).upper(), fixed)
        fixed = re.sub(r"^(\W*)([a-zà-ÿ])", lambda m: m.group(1) + m.group(2).upper(), fixed)
    return fixed


def find_connectors(text: str) -> dict[str, list[str]]:
    low = " " + _fold(text) + " "
    found: dict[str, list[str]] = {}
    for kind, items in CONNECTORS.items():
        for c in items:
            if re.search(rf"(?<![\w']){re.escape(_fold(c))}(?![\w'])", low):
                found.setdefault(kind, []).append(c)
    return found


def find_structures(text: str) -> list[str]:
    return [name for name, rx in COMPLEX_STRUCTURES if rx.search(text)]


def find_repetitions(ws: list[str]) -> list[str]:
    content = [w for w in ws if len(w) >= 5 and w not in STOPWORDS]
    limit = 3 if len(ws) < 120 else 4
    return [w for w, n in Counter(content).most_common() if n >= limit][:6]


def text_stats(text: str) -> dict[str, float]:
    ws = words(text)
    sents = sentences(text)
    n = len(ws)
    window = ws[:100]
    lens = [len(words(s)) for s in sents] or [0]
    return {
        "words": count_words(text),
        "sentences": len(sents),
        "paragraphs": len([p for p in re.split(r"\n\s*\n", text.strip()) if p.strip()]),
        "avg_sentence_len": round(sum(lens) / max(1, len(sents)), 1),
        "max_sentence_len": max(lens),
        "lexical_variety": round(len(set(window)) / max(1, len(window)), 2),
        "long_words_ratio": round(sum(1 for w in ws if len(w) >= 8) / max(1, n), 2),
    }


# ------------------------------------------------------- points de consigne
_POINT_DETECTORS: list[tuple[re.Pattern, re.Pattern]] = [
    (re.compile(r"salutation|formule d'appel|saluer"),
     re.compile(r"\b(bonjour|bonsoir|salut|coucou|cher|chère|chers|madame|monsieur|"
                r"mesdames|messieurs|hello)\b", re.I)),
    (re.compile(r"formule finale|prise de congé|signature|formule de politesse"),
     re.compile(r"\b(cordialement|bisous|bises|à bientôt|je t'embrasse|je vous embrasse|"
                r"amitiés|salutations|bien à (vous|toi)|à plus tard|à samedi|à dimanche|"
                r"à demain|veuillez agréer|merci d'avance|au plaisir)\b", re.I)),
    (re.compile(r"date|heure|horaire|jour|moment"),
     re.compile(r"\b(\d{1,2}\s?h(\s?\d{2})?|\d{1,2} heures?|midi|minuit|lundi|mardi|mercredi|"
                r"jeudi|vendredi|samedi|dimanche|demain|ce soir|week-end|\d{1,2}(er)? "
                r"(janvier|février|mars|avril|mai|juin|juillet|août|septembre|octobre|"
                r"novembre|décembre))\b", re.I)),
    (re.compile(r"lieu|adresse|endroit|trajet"),
     re.compile(r"\b(à|au|chez|dans|devant|place|rue|salle|gare|parc|centre|depuis|vers)\b"
                r"\s+\w+", re.I)),
    (re.compile(r"prix|tarif|coût|participation"),
     re.compile(r"(\d+\s?(€|euros?|dollars?|\$)|gratuit|offert|prix|tarif)", re.I)),
    (re.compile(r"concession"),
     re.compile(r"\b(certes|bien que|bien qu|même si|il est vrai que|malgré|quoique|"
                r"en dépit de|j'admets|je reconnais|je comprends|j'entends|sans doute|"
                r"évidemment|bien sûr)\b", re.I)),
    (re.compile(r"objection|opposition|nuance|contre-argument|position nuancée"),
     re.compile(r"\b(cependant|toutefois|néanmoins|en revanche|pourtant|mais|or|"
                r"au contraire|par contre|reste que)\b", re.I)),
    (re.compile(r"conclusion|conclure|bilan"),
     re.compile(r"\b(en conclusion|pour conclure|en somme|en définitive|finalement|bref|"
                r"tout compte fait|en bref|somme toute|pour finir|en résumé|ainsi)\b", re.I)),
    (re.compile(r"position|opinion|avis|point de vue|prise de position"),
     re.compile(r"\b(je pense|je crois|à mon avis|selon moi|pour ma part|il me semble|"
                r"je suis (convaincue?|persuadée?|plutôt|favorable|opposée?|pour|contre)|"
                r"d'après moi|personnellement|j'estime|je trouve|je considère|me semble|"
                r"me paraît|à mon sens|je (ne )?partage|je souhaite exprimer|je doute|"
                r"je soutiens|j'approuve|(pas )?d'accord|je regrette|je refuse)\b", re.I)),
    (re.compile(r"exemple|illustration"),
     re.compile(r"\b(par exemple|notamment|comme|tel que|telle que|ainsi|prenons|c'est le cas)\b",
                re.I)),
    (re.compile(r"argument"),
     re.compile(r"\b(d'abord|ensuite|de plus|en outre|d'une part|d'autre part|premièrement|"
                r"par ailleurs|parce que|car|en effet|puisque)\b", re.I)),
    (re.compile(r"proposition|solution|alternative|suggestion|conseil|recommandation"),
     re.compile(r"\b(il faudrait|il vaudrait mieux|je propose|je suggère|on pourrait|"
                r"nous pourrions|je recommande|je conseille|il serait|pourquoi ne pas|"
                r"l'idéal serait|il me semblerait|plutôt que|il vaut mieux|pourrait|"
                r"pourraient|devrait|devraient|faudrait|mon conseil|recommande|conseille|"
                r"n'hésitez pas|à ne pas manquer|allez-y|à découvrir|(?!chez\b|assez\b)"
                r"\w{3,}ez\s*!)", re.I)),
    (re.compile(r"demande|question|renseignement"),
     re.compile(r"(\?|\b(pourriez-vous|pouvez-vous|serait-il possible|je voudrais savoir|"
                r"dites-moi|dis-moi|est-ce que|je souhaiterais)\b)", re.I)),
    (re.compile(r"remerci"),
     re.compile(r"\b(merci|remercie|remercier|reconnaissante?)\b", re.I)),
    (re.compile(r"émotion|sentiment|ressenti"),
     re.compile(r"\b(heureuse?|contente?|ravie?|triste|déçue?|fière?|émue?|joie|plaisir|"
                r"adoré|aimé|peur|surprise?|génial|magnifique|inoubliable|je pense à)\b", re.I)),
    (re.compile(r"invitation|inviter"),
     re.compile(r"\b(invite|inviter|invitation|viens|venez|rejoindre|rejoins|serais-tu|"
                r"seriez-vous|je t'attends)\b", re.I)),
    (re.compile(r"contexte|circonstances|présentation"),
     re.compile(r"\b(quand|lorsque|il y a|depuis|je suis|je m'appelle|j'habite|chez moi|"
                r"en \d{4}|à l'âge de|c'était|hier|dernier|dernière|samedi|dimanche|"
                r"pendant|à l'occasion|en arrivant|un jour|cet été|cet hiver|l'an passé|"
                r"j'ai passé|j'ai participé)\b", re.I)),
    (re.compile(r"conséquence|résultat|aujourd'hui"),
     re.compile(r"\b(donc|c'est pourquoi|par conséquent|aujourd'hui|depuis|désormais|"
                r"maintenant|si bien que|de sorte que|grâce à)\b", re.I)),
    (re.compile(r"description|décrire|préparation|caractéristiques|variantes"),
     re.compile(r"\b(il y a|c'est|on trouve|se compose|est composé|grand|petit|beau|"
                r"belle|ancien|moderne|d'abord|puis)\b", re.I)),
]


def check_points(text: str, points: list[str] | None) -> list[PointCheck]:
    out = []
    folded = _fold(text)
    for label in points or []:
        lab = _fold(label)
        detector = next((rx for key, rx in _POINT_DETECTORS
                         if key.search(label.lower()) or key.search(lab)), None)
        if detector is not None:
            m = detector.search(text)
            if not m and re.search(r"conclu|bilan", lab) and len(sentences(text)) >= 4:
                # une conclusion sans connecteur ne se repère pas automatiquement
                out.append(PointCheck(label, "non vérifiable"))
                continue
            out.append(PointCheck(label, "présent" if m else "absent",
                                  m.group(0).strip() if m else ""))
            continue
        # repli : mots de l'intitulé (racines) présents dans le texte
        keys = [w[:5] for w in re.findall(r"[a-z]{4,}", lab) if w not in STOPWORDS]
        hits = [k for k in keys if k in folded]
        if keys and hits:
            out.append(PointCheck(label, "présent", ", ".join(hits)))
        else:
            out.append(PointCheck(label, "non vérifiable"))
    return out


# ------------------------------------------------------------------ notation
def _clamp(x: float, lo: float = 0, hi: float = 5) -> float:
    return round(max(lo, min(hi, x)) * 2) / 2      # demi-points


def _task_score(n: int, lo: int, hi: int, points: list[PointCheck]) -> tuple[float, str]:
    if n == 0:
        return 0, "Aucune production."
    verifiable = [p for p in points if p.status != "non vérifiable"]
    coverage = (sum(p.status == "présent" for p in verifiable) / len(verifiable)
                if verifiable else 0.75)
    score = 1.5 + 3.5 * coverage
    comment = [f"{round(coverage * 100)} % des éléments attendus repérés."]
    if n < lo:
        ratio = n / lo
        score *= ratio if ratio >= 0.5 else ratio * 0.6
        comment.append(f"Texte trop court ({n} mots pour {lo} minimum) : la tâche ne peut "
                       f"pas être entièrement réalisée.")
    elif n > hi:
        over = (n - hi) / hi
        score -= 1 if over > 0.25 else 0.5
        comment.append(f"Texte trop long ({n} mots pour {hi} maximum) : respectez la "
                       f"limite, les correcteurs peuvent ignorer la fin.")
    return _clamp(score), " ".join(comment)


_GREETING = re.compile(r"^(bonjour|bonsoir|salut|coucou|cher|chère|chers|madame|monsieur|"
                       r"cordialement|bien cordialement|bien à (toi|vous)|à bientôt|amitiés|"
                       r"amicalement|bises|respectueusement)\b", re.I)
_SUBORD = re.compile(r"\b(que|qu'|qui|dont|où|lorsque|lorsqu'|quand|puisque|puisqu'|bien que|"
                     r"bien qu'|si|s'il|s'ils|afin que|pour que|alors que|tandis que|même si|"
                     r"parce que|parce qu'|en \w+ant|ayant|étant)", re.I)


def syntax_notes(text: str) -> list[str]:
    """Analyse de la syntaxe : construction et longueur des phrases.

    Mesure la part de phrases complexes (avec subordonnée), repère les phrases
    trop longues à découper, les débuts de phrase répétitifs et l'absence de
    ponctuation finale (une formule de congé « …, Prénom » est admise). Les formules d'appel et de congé et une signature
    finale sont ignorées."""
    text = (text or "").strip()
    if not text:
        return []
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if len(lines) > 1 and len(words(lines[-1])) <= 4:      # signature
        lines = lines[:-1]
    body = "\n".join(lines)
    sents = []
    for x in sentences(body):
        if _GREETING.match(x):          # « Bonjour Madame, je… » : on garde la suite
            x = x.split(",", 1)[1].strip() if "," in x else ""
        if len(words(x)) >= 3:
            sents.append(x)
    if not sents:
        return []
    notes: list[str] = []
    complex_n = sum(1 for x in sents if _SUBORD.search(x))
    notes.append(f"{complex_n} phrase(s) complexe(s) sur {len(sents)} (avec une subordonnée : "
                 f"que, qui, dont, où, si, parce que, bien que, gérondif…).")
    if complex_n == 0 and len(sents) >= 4:
        notes.append("Aucune subordonnée : au niveau B2, reliez vos idées avec des relatives "
                     "(qui, que, dont) et des circonstancielles (bien que, si, afin que).")
    for x in sents:
        n = len(words(x))
        if n > 35:
            notes.append(f"Phrase de {n} mots (« {x[:40]}… ») : découpez-la ou "
                         f"allégez-la avec un point-virgule.")
    starts = Counter(words(x)[0] for x in sents if words(x))
    for w, cnt in starts.most_common(1):
        if cnt >= 4 and cnt * 2 >= len(sents):
            notes.append(f"{cnt} phrases commencent par « {w} » : variez les débuts "
                         f"(connecteur, complément circonstanciel, inversion).")
    tail = re.split(r"[.!?…]", body)[-1]           # après la dernière ponctuation forte
    if len(words(tail)) >= 6 and "," not in tail:    # une formule de congé a une virgule
        notes.append("La dernière phrase ne se termine pas par une ponctuation finale.")
    return notes[:6]


def _coherence_score(n: int, conns: dict[str, list[str]], st: dict) -> tuple[float, str]:
    if n == 0:
        return 0, ""
    kinds = len(conns)
    total = sum(len(v) for v in conns.values())
    expected = max(1, n / 35)                   # environ un connecteur pour 35 mots
    score = 1.0 + min(2.0, 2.0 * total / expected) + min(1.5, 0.5 * kinds)
    notes = [f"{total} connecteur(s) de {kinds} type(s)."]
    if st["sentences"] <= 1 and n > 30:
        score -= 1
        notes.append("Une seule phrase : découpez votre texte.")
    if st["max_sentence_len"] > 45:
        score -= 0.5
        notes.append("Certaines phrases sont très longues : allégez-les.")
    if st["avg_sentence_len"] < 7 and st["sentences"] >= 3:
        score -= 0.5
        notes.append("Phrases très courtes : reliez-les avec des connecteurs.")
    return _clamp(score), " ".join(notes)


def _lexicon_score(n: int, st: dict, reps: list[str], structures: list[str],
                   advice_count: int) -> tuple[float, str]:
    if n == 0:
        return 0, ""
    variety = st["lexical_variety"]
    score = 0.5 + min(2.0, max(0.0, (variety - 0.5) * 7)) + min(1.0, st["long_words_ratio"] * 5)
    score += min(1.5, 0.5 * len(structures))
    score -= 0.5 * len(reps) + 0.25 * advice_count
    if n < 25:
        score = min(score, 2.5)
    notes = [f"Variété lexicale {round(variety * 100)} %."]
    if structures:
        notes.append("Structures valorisées : " + ", ".join(structures) + ".")
    if reps:
        notes.append("Répétitions : " + ", ".join(reps) + ".")
    return _clamp(score), " ".join(notes)


def _grammar_score(n: int, errors: int) -> tuple[float, str]:
    if n == 0:
        return 0, ""
    density = errors * 100 / max(n, 20)
    score = 5 - density * 0.6
    if n < 20:
        score = min(score, 3)
    return _clamp(score, 0.5), (f"{errors} erreur(s) repérée(s), soit {density:.1f} pour 100 "
                                f"mots. (Le repérage automatique n'est pas exhaustif.)")


CRITERIA_LABELS = {
    "tache": "Réalisation de la tâche",
    "coherence": "Cohérence et cohésion",
    "lexique": "Lexique",
    "grammaire": "Morphosyntaxe et orthographe",
}


def evaluate(text: str, task_number: int | None = None, min_words: int = 40,
             max_words: int = 90, expected_points: list[str] | None = None,
             model_answer: str = "") -> Evaluation:
    text = (text or "").replace("\r\n", "\n")
    n = count_words(text)
    ws = words(text)
    issues = find_issues(text) if n else []
    errors = [i for i in issues if i.severity == ERROR]
    advice = [i for i in issues if i.severity == ADVICE]
    points = check_points(text, expected_points) if n else [
        PointCheck(p, "absent") for p in expected_points or []]
    conns = find_connectors(text) if n else {}
    structures = find_structures(text) if n else []
    reps = find_repetitions(ws)
    st = text_stats(text)

    c_task, m_task = _task_score(n, min_words, max_words, points)
    c_coh, m_coh = _coherence_score(n, conns, st)
    c_lex, m_lex = _lexicon_score(n, st, reps, structures,
                                  sum(1 for i in advice if i.category in ("registre", "lexique")))
    c_gram, m_gram = _grammar_score(n, len(errors))
    criteria = {"tache": c_task, "coherence": c_coh, "lexique": c_lex, "grammaire": c_gram}
    # Au-delà de 16/20 (C2), seule une évaluation humaine peut juger la finesse
    # du propos : le moteur automatique plafonne son estimation.
    note = min(AUTO_CAP, round(sum(criteria.values()) * 2) / 2)
    if n and n < min_words * 0.5:           # production très incomplète : plafond
        note = min(note, 5.0)
    # Un texte truffé d'erreurs ne peut pas atteindre B2, quelles que soient ses idées.
    density = len(errors) * 100 / max(n, 20) if n else 0
    if density >= 12:
        note = min(note, 7.5)
    elif density >= 7:
        note = min(note, 9.5)
    level = L.expression_level(note) if note > 0 else "< A1"

    strengths, priorities = _advice(n, min_words, max_words, criteria, errors, advice, conns,
                                    structures, reps, points)
    return Evaluation(
        task_number=task_number, word_count=n, min_words=min_words, max_words=max_words,
        criteria=criteria,
        criteria_comments={"tache": m_task, "coherence": m_coh, "lexique": m_lex,
                           "grammaire": m_gram},
        note20=note, level=level, issues=issues, points=points, connectors=conns,
        structures=structures, repetitions=reps, stats=st, strengths=strengths,
        priorities=priorities, corrected_text=apply_fixes(text, issues),
        model_answer=model_answer,
        model_stats=text_stats(model_answer) if model_answer else {},
        syntax=syntax_notes(text) if n else [])


def _advice(n, lo, hi, criteria, errors, advice, conns, structures, reps, points):
    strengths, prio = [], []
    if lo <= n <= hi:
        strengths.append("Le nombre de mots respecte la consigne.")
    if criteria["tache"] >= 4:
        strengths.append("Les éléments attendus par la consigne sont bien présents.")
    if len(conns) >= 4:
        strengths.append("Bonne variété de connecteurs logiques.")
    if len(structures) >= 2:
        strengths.append("Vous utilisez des structures complexes de niveau B2.")
    if n and not errors:
        strengths.append("Aucune erreur fréquente repérée automatiquement.")

    if n == 0:
        return [], ["Rédigez un texte : une page blanche vaut 0."]
    if n < lo:
        prio.append(f"Développez votre texte jusqu'à au moins {lo} mots.")
    elif n > hi:
        prio.append(f"Réduisez votre texte à {hi} mots maximum.")
    missing = [p.label for p in points if p.status == "absent"]
    if missing:
        prio.append("Traitez tous les éléments de la consigne : " + ", ".join(missing[:4]) + ".")
    cats = Counter(i.chapter or i.category for i in errors)
    for key, cnt in cats.most_common(2):
        prio.append(f"Revoyez « {key} » ({cnt} erreur(s)).")
    if len(conns) < 3:
        prio.append("Articulez vos idées avec des connecteurs variés (cependant, de plus, "
                    "par conséquent, en somme…).")
    if not structures:
        prio.append("Ajoutez une ou deux structures complexes : relative avec « dont », "
                    "subjonctif après « bien que », hypothèse avec « si ».")
    if reps:
        prio.append("Évitez les répétitions (" + ", ".join(reps[:3]) + ") : utilisez des "
                    "synonymes ou des pronoms.")
    if any(i.category == "registre" for i in advice):
        prio.append("Surveillez le registre : évitez les tournures familières à l'écrit.")
    return strengths, prio[:3]


def overall_note(evals: list[Evaluation]) -> dict:
    """Note EE globale (moyenne des tâches traitées ; une tâche vide compte 0)."""
    if not evals:
        return {"note20": 0.0, "level": "< A1", "disclaimer": L.DISCLAIMER}
    note = round(sum(e.note20 for e in evals) / len(evals) * 2) / 2
    return {"note20": note, "level": L.expression_level(note) if note else "< A1",
            "tasks": {str(e.task_number): e.note20 for e in evals},
            "disclaimer": L.DISCLAIMER}
