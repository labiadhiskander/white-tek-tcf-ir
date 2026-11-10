"""Règles de détection des erreurs fréquentes des apprenants (niveau B1–B2).

Chaque règle est une expression régulière accompagnée :
  * d'une catégorie (orthographe, grammaire, conjugaison, syntaxe, registre,
    lexique, ponctuation) ;
  * d'une gravité : « erreur » (compte dans la note) ou « conseil » (style,
    registre, typographie : ne pénalise que légèrement) ;
  * d'une correction automatique quand elle est sûre (`fix`), sinon d'une
    suggestion en texte ;
  * d'une explication et du chapitre de grammaire à revoir.

Les règles privilégient la précision : mieux vaut laisser passer une erreur
que signaler à tort une phrase correcte. Elles ne remplacent pas une
relecture humaine.
"""
from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass

ERROR, ADVICE = "erreur", "conseil"

PRON = r"(?:je|j['’]|tu|il|elle|on|nous|vous|ils|elles)"
_SUBJ_PRON = r"(?:il|elle|on|ils|elles|je|tu|nous|vous|ce|cela|ça)"
_IND_FORMS = (r"(?:est|sont|a|ont|va|vont|peut|peuvent|fait|font|doit|doivent|sait|"
              r"savent|veut|veulent|vient|viennent|prend|prennent|suis|es|ai|as|vais|"
              r"peux|fais|dois|sais|veux|vas|viens|prends|sommes|êtes|avons|avez|allons|"
              r"allez|pouvons|pouvez|faisons|faites|devons|devez)")
COND = (r"(?:\w+er|ser|aur|pourr|voudr|fer|ir|devr|saur|viendr|reviendr|verr|tiendr|prendr|"
        r"apprendr|comprendr|mettr|faudr|vaudr|dir|lir|écrir|finir|choisir|partir|sortir|"
        r"dormir|vivr|boir|recevr|connaîtr|croir|attendr|répondr|vendr|perdr|rendr|"
        r"entendr|courr|mourr|envoir|enverr)(?:ais|ait|ions|iez|aient)")
_ETRE_PP = (r"(?:allée?s?|venue?s?|partie?s?|arrivée?s?|née?s?|morte?s?|restée?s?|"
            r"tombée?s?|devenue?s?|revenue?s?|décédée?s?)")
_AVOIR = r"(?:j['’]ai|je ai|tu as|il a|elle a|on a|nous avons|vous avez|ils ont|elles ont)"


@dataclass(frozen=True)
class Rule:
    id: str
    category: str
    pattern: re.Pattern
    message: str
    explanation: str
    severity: str = ERROR
    fix: str | Callable[[re.Match], str] | None = None
    suggestion: str = ""
    chapter: str = ""            # slug du chapitre de grammaire


def _r(rx: str, flags=re.IGNORECASE) -> re.Pattern:
    return re.compile(rx, flags)


def _keep_case(src: str, repl: str) -> str:
    return repl[:1].upper() + repl[1:] if src[:1].isupper() else repl


_ACCENTS = {
    "tres": "très", "deja": "déjà", "déja": "déjà", "apres": "après", "probleme": "problème",
    "problemes": "problèmes", "different": "différent", "differente": "différente",
    "differents": "différents", "differentes": "différentes", "ecole": "école",
    "ecoles": "écoles", "etudiant": "étudiant", "etudiante": "étudiante",
    "etudiants": "étudiants", "etudiantes": "étudiantes", "societe": "société",
    "societes": "sociétés", "eleve": "élève", "eleves": "élèves", "etait": "était",
    "etaient": "étaient", "evenement": "événement", "evenements": "événements",
    "interet": "intérêt", "interets": "intérêts", "economique": "économique",
    "economiques": "économiques", "periode": "période", "periodes": "périodes",
    "general": "général", "generale": "générale", "reponse": "réponse",
    "reponses": "réponses", "telephone": "téléphone", "frere": "frère", "pere": "père",
    "bientot": "bientôt", "meme": "même", "peut-etre": "peut-être", "ca": "ça",
}


_ELISIONS = {
    "je": "ai aime habite étais étudie arrive espère attends appelle écris entends apprends "
          "adore avais en y",
    "que": "il ils elle elles on un une",
    "ne": "ai as a avons avez ont est était étais en y aime habite arrive attends entends",
    "de": "un une elle elles en y",
    "me": "appelle aime étais était est en y attends entends",
    "te": "appelle aime étais était est en y attends entends",
    "se": "appelle aime était est en y entend entendent amuse amusent intéresse",
}
_ELISION_RX = r"\b(?:" + "|".join(
    rf"({k}) ({'|'.join(v.split())})" for k, v in _ELISIONS.items()) + r")\b"


def _sub(repl: str) -> Callable[[re.Match], str]:
    """Remplacement simple qui conserve la majuscule initiale."""
    return lambda m: _keep_case(m.group(0), m.expand(repl))


RULES: list[Rule] = [
    # ---------------------------------------------------------- orthographe
    Rule("si-il", "orthographe", _r(r"\bsi (ils?)\b"), "« si il » s'élide en « s'il ».",
         "Devant « il » et « ils », « si » s'élide : s'il, s'ils (mais : si elle, si on).",
         fix=_sub(r"s'\1")),
    Rule("entrain", "orthographe", _r(r"\bentrain de\b"), "« entrain de » → « en train de ».",
         "« Être en train de » (deux mots) exprime une action en cours ; « l'entrain » "
         "signifie l'énergie, la bonne humeur.", fix=_sub("en train de")),
    Rule("malgre", "orthographe", _r(r"\bmalgrè\b"), "Accent : « malgré ».",
         "« Malgré » prend un accent aigu.", fix=_sub("malgré")),
    Rule("quelque-soit", "orthographe", _r(r"\bquelques? soi(en)?t\b"),
         "« quelque soit » → « quel(le)(s) que soit ».",
         "Devant le verbe être, on écrit « quel que soit » en deux mots, accordé avec le "
         "sujet : quelle que soit la raison, quels que soient les obstacles.",
         suggestion="quel que soit / quelle que soit / quels que soient"),
    Rule("comme-meme", "orthographe", _r(r"\bcomme même\b"), "« comme même » → « quand même ».",
         "L'expression correcte est « quand même ».", fix=_sub("quand même")),
    Rule("parmis", "orthographe", _r(r"\bparmis\b"), "« parmis » → « parmi ».",
         "« Parmi » ne prend jamais de « s ».", fix=_sub("parmi")),
    Rule("language", "orthographe", _r(r"\blanguage\b"), "« language » → « langage ».",
         "En français : « le langage » (sans u) ; « language » est anglais.", fix=_sub("langage")),
    Rule("developpement", "orthographe", _r(r"\b(?:dévelopement|dévellop+ement|devel+op+ement|developement|développemment)\b"),
         "Orthographe : « développement ».", "Un seul « l » et deux « p » : développement.",
         fix=_sub("développement")),
    Rule("apeller", "orthographe", _r(r"\b(?:apel+|ap{2}el{2})(?:er|é\w*)\b"), "Orthographe du verbe « appeler ».",
         "« Appeler » : deux « p », un seul « l » à l'infinitif (j'appelle, nous appelons).",
         suggestion="appeler / appelé"),
    Rule("a-cause", "orthographe", _r(r"\ba (cause d|partir d|côté d|travers\b|propos d)"),
         "Préposition : « à » avec accent.",
         "« À cause de », « à partir de », « à côté de », « à travers », « à propos de » : "
         "« à » est ici une préposition (accent grave), pas le verbe avoir.",
         fix=_sub(r"à \1"), chapter="prepositions"),
    Rule("a-preposition", "orthographe",
         _r(r"\b(favorable|favorables|opposée?s?|grâce|face|quant|pense|penser|parle|parler|"
            r"répondre|réponds|répond|commence|continue|aide|réussir|jusqu['’]) a (ce|cet|"
            r"cette|ces|la|mon|ma|mes|son|sa|ses|notre|nos|votre|vos|leur|leurs|un|une|tout|"
            r"tous|toute|toutes|moi|toi|lui|eux|elle|elles|l['’]\w+)\b"),
         "Préposition : « à » avec accent.",
         "Ici « a » introduit un complément : c'est la préposition « à » (favorable à, "
         "grâce à, penser à, répondre à…), pas le verbe avoir.",
         fix=lambda m: f"{m.group(1)} à {m.group(2)}", chapter="prepositions"),
    Rule("il-a", "orthographe", _r(r"\b(il|elle|on) à\b"), "Verbe avoir : « a » sans accent.",
         "Après un sujet, « a » est le verbe avoir (il a, elle a). On peut le remplacer "
         "par « avait ».", fix=_sub(r"\1 a")),
    Rule("ses-cest", "orthographe", _r(r"\bses (un|une|vrai|important|pourquoi|dommage|difficile|possible)\b"),
         "« ses » / « s'est » → « c'est » ?",
         "« C'est » = cela est. « Ses » est un déterminant possessif pluriel, « s'est » "
         "l'auxiliaire d'un verbe pronominal (il s'est levé).", fix=_sub(r"c'est \1")),
    Rule("davantage", "orthographe", _r(r"(?<!plus )(?<!moins )(?<!autant )(?<!beaucoup )\bd'avantage (que|de)\b"),
         "« d'avantage » → « davantage » (= plus).",
         "« Davantage » (en un mot) signifie « plus ». « Un avantage » est un bénéfice.",
         fix=_sub(r"davantage \1")),
    Rule("plutot", "orthographe", _r(r"\bplutot\b"), "Accent : « plutôt ».",
         "« Plutôt » prend un accent circonflexe.", fix=_sub("plutôt")),
    Rule("etre-accent", "orthographe", _r(r"\b(peut-)?etre\b"), "Accent : « être ».",
         "« Être » prend un accent circonflexe (peut-être).",
         fix=lambda m: _keep_case(m.group(0), (m.group(1) or "") + "être")),
    Rule("ca-accent", "orthographe", _r(r"\bca (va|fait|dépend|me|te|nous|vous|ne)\b"),
         "« ca » → « ça ».", "Le pronom démonstratif « ça » prend une cédille.",
         fix=_sub(r"ça \1")),
    Rule("tous-les-jours", "orthographe", _r(r"\btout les (jours|ans|mois|soirs|matins|samedis|dimanches|gens|"
                                       r"enfants|élèves|étudiants|hommes|pays|deux|trois)\b"), "« tout les » → « tous les ».",
         "Devant un nom masculin pluriel, « tout » s'accorde : tous les jours, toutes les "
         "semaines.", fix=_sub(r"tous les \1"), chapter="accords"),
    Rule("toute-les", "orthographe", _r(r"\btoute les (semaines|personnes|femmes|années|nuits|fois|"
                                        r"choses|filles)\b"), "« toute les » → « toutes les ».",
         "Devant un nom féminin pluriel : toutes les personnes.", fix=_sub(r"toutes les \1"),
         chapter="accords"),

    Rule("accents", "orthographe", _r(r"\b(tres|deja|déja|apres|problemes?|differente?s?|ecoles?|"
                                       r"etudiante?s?|societes?|eleves?|etait|etaient|"
                                       r"evenements?|interets?|economiques?|periodes?|"
                                       r"generale?|reponses?|telephone|frere|pere|bientot|"
                                       r"meme)\b(?!['’-])"),
         "Accent manquant.", "En français, les accents font partie de l'orthographe : "
         "très, déjà, après, problème, différent, école, étudiant, société, même…",
         fix=lambda m: _keep_case(m.group(0), _ACCENTS.get(m.group(1).lower(), m.group(1)))),
    Rule("elision", "orthographe", _r(_ELISION_RX),
         "Élision obligatoire devant une voyelle.",
         "Devant une voyelle ou un h muet, je, me, te, se, ne, de et que perdent leur "
         "voyelle : j'ai, qu'il, n'est, d'un, s'appelle.",
         fix=lambda m: (lambda g: g[0][:-1] + "'" + g[1])([x for x in m.groups() if x])),
    Rule("aller-present", "conjugaison", _r(r"\b(je vas|tu va|il vas|elle vas|on vas)\b"),
         "Conjugaison du verbe aller.", "Aller au présent : je vais, tu vas, il/elle/on va.",
         fix=lambda m: _keep_case(m.group(0), {"je vas": "je vais", "tu va": "tu vas",
                                               "il vas": "il va", "elle vas": "elle va",
                                               "on vas": "on va"}[m.group(1).lower()]),
         chapter="present"),

    # ------------------------------------------------------------ grammaire
    Rule("gens-singulier", "grammaire", _r(r"\bles gens (est|a|fait|va|peut|veut|doit)\b"),
         "Accord : « les gens » est pluriel.",
         "« Les gens » se construit avec un verbe au pluriel : les gens sont, ont, font…",
         fix=lambda m: "les gens " + {"est": "sont", "a": "ont", "fait": "font", "va": "vont",
                                      "peut": "peuvent", "veut": "veulent",
                                      "doit": "doivent"}[m.group(1).lower()],
         chapter="accords"),
    Rule("subj-apres-conj", "grammaire",
         _r(rf"(?<!si )\b(bien|pour|afin|avant|sans|à moins|en attendant|il faut|faut) "
            rf"qu(?:e\s+|['’])\s*{_SUBJ_PRON}\s+{_IND_FORMS}\b"),
         "Subjonctif attendu.",
         "Après « bien que, pour que, afin que, avant que, sans que, à moins que, il faut "
         "que », le verbe se met au subjonctif : bien qu'il soit, pour qu'elle puisse, "
         "il faut que nous fassions.",
         suggestion="soit / aient / puisse / fasse / aille…", chapter="subjonctif"),
    Rule("apres-que-subj", "grammaire",
         _r(rf"\baprès qu(?:e\s+|['’])\s*{_SUBJ_PRON}\s+(soit|soient|ait|aient|fasse|"
            rf"fassent|puisse|puissent)\b"),
         "« après que » se construit avec l'indicatif.",
         "« Après que » exprime un fait accompli : il est suivi de l'indicatif "
         "(après qu'il est parti, après qu'elle a fini).", chapter="subjonctif"),
    Rule("si-conditionnel", "grammaire",
         _r(rf"(?:^|[.!?;]\s+|,\s*|\bet\s+|\bmême\s+)si\s+(?:{PRON}\s*|j['’])"
            rf"(?:n['’]|ne\s+)?(?:\w+['’])?{COND}\b"),
         "Hypothèse : pas de conditionnel après « si ».",
         "Dans une hypothèse, « si » est suivi de l'imparfait (ou du plus-que-parfait), "
         "jamais du conditionnel : si j'avais le temps, je viendrais.",
         suggestion="si + imparfait, … conditionnel", chapter="hypotheses"),
    Rule("auxiliaire-etre", "grammaire", _r(rf"\b{_AVOIR}\s+{_ETRE_PP}\b"),
         "Auxiliaire « être » attendu.",
         "Les verbes de mouvement et de changement d'état (aller, venir, partir, arriver, "
         "naître, mourir, rester, tomber, devenir…) se conjuguent avec « être » : je suis "
         "allé(e), elle est partie.", suggestion="je suis allé(e), elle est venue…",
         chapter="passe-compose"),
    Rule("malgre-que", "grammaire", _r(r"\bmalgré qu(e|['’])"),
         "« malgré que » est déconseillé.",
         "En français soigné, on dit « bien que » + subjonctif, ou « malgré » + nom : "
         "bien qu'il pleuve / malgré la pluie.", fix=_sub(r"bien qu\1"),
         chapter="phrases-complexes"),
    Rule("pallier-a", "grammaire", _r(r"\b(palli\w*) (à|au|aux)\b"),
         "« pallier » est transitif direct.",
         "On dit « pallier un problème » (sans « à »), comme « remédier à » qui, lui, "
         "prend « à ».", suggestion="pallier un manque / remédier à un manque",
         chapter="prepositions"),
    Rule("se-rappeler-de", "grammaire", _r(r"\b(rappel\w*|rappeler) de (ce|cette|ces|la|le|les|"
                                           r"mon|ma|mes|son|sa|ses|notre|nos)\b"),
         "« se rappeler » est transitif direct.",
         "On dit « se rappeler quelque chose » ou « se souvenir de quelque chose ».",
         suggestion="je me rappelle ce jour / je me souviens de ce jour",
         chapter="pronoms-personnels"),
    Rule("on-nous", "conjugaison", _r(r"\bon (?!pardons\b)\w+ons\b"),
         "« on » se conjugue à la 3e personne du singulier.",
         "Avec « on », le verbe est au singulier : on mange, on a fini (et non "
         "« on mangeons »). Avec « nous » : nous mangeons.", chapter="present"),
    Rule("vous-faisez", "conjugaison", _r(r"\bvous (faisez|disez|contredites)\b"),
         "Conjugaison irrégulière.",
         "Faire et dire sont irréguliers : vous faites, vous dites (mais : vous "
         "contredisez).", fix=lambda m: "vous " + {"faisez": "faites", "disez": "dites",
                                                   "contredites": "contredisez"}[
             m.group(1).lower()], chapter="present"),
    Rule("croivent", "conjugaison", _r(r"\b(croivent|voyent|croyent|envoit|essuit)\b"),
         "Conjugaison incorrecte.",
         "Croire : ils croient ; voir : ils voient ; envoyer : il envoie ; essuyer : "
         "il essuie.", fix=lambda m: _keep_case(m.group(0), {
             "croivent": "croient", "voyent": "voient", "croyent": "croient",
             "envoit": "envoie", "essuit": "essuie"}[m.group(1).lower()]),
         chapter="present"),
    Rule("plus-pire", "grammaire", _r(r"\bplus (pire|mieux|meilleure?s?)\b"),
         "Double comparatif.",
         "« Pire », « mieux » et « meilleur » sont déjà des comparatifs : on ne dit pas "
         "« plus pire » ni « plus meilleur ».", fix=_sub(r"\1"), chapter="comparaison"),
    Rule("beaucoup-des", "grammaire", _r(r"\b(beaucoup|peu|trop|assez) des "
                                         r"(gens|personnes|choses|problèmes|avantages|"
                                         r"inconvénients|jeunes|étudiants|enfants)\b(?! de\b|"
                                         r" qui\b| que\b| dont\b)"),
         "Après un adverbe de quantité : « de ».",
         "On dit « beaucoup de gens, trop de problèmes » : l'article disparaît après un "
         "adverbe de quantité (sauf si le nom est précisé : beaucoup des gens que je "
         "connais).", fix=_sub(r"\1 de \2"), chapter="articles"),
    Rule("negation-incomplete", "syntaxe",
         _r(rf"(?:^|[.!?]\s+|,\s*|\bmais\s+|\bet\s+)(?:{PRON}|c['’]|ça|ce)\s*"
            r"(?!ne\b|n['’]|que\b|qui\b)(\w+) (pas|jamais|rien|personne)\b(?!\s*n['’]|\s+ne\b)"
            r"(?! (?:que|de|en plus|du tout|mal|loin|seulement|à|d['’]))"),
         "Négation incomplète : « ne » manque.",
         "À l'écrit, la négation a deux éléments : « je ne sais pas », « ce n'est "
         "jamais ». L'omission de « ne » appartient à l'oral familier.",
         severity=ERROR, chapter="negation"),

    # ------------------------------------------------------------- registre
    Rule("familier", "registre",
         _r(r"\b(ouais|bouquins?|boulots?|bagnoles?|trucs?|machins?|mecs?|nanas?|"
            r"fringues|bosser|bosse|kiffer?|kiffe|marrant|flic|flics|fric|bouffer?|cool|"
            r"sympa|sympas)\b"),
         "Mot familier.",
         "Ce mot appartient au registre familier. À l'examen, préférez un équivalent "
         "standard : livre, travail, voiture, chose, travailler, aimer, drôle, argent, "
         "manger…", severity=ADVICE),
    Rule("au-jour-daujourdhui", "registre", _r(r"\bau jour d['’]aujourd['’]hui\b"),
         "Pléonasme.", "« Aujourd'hui » suffit (ou « de nos jours »).",
         fix=_sub("aujourd'hui"), severity=ADVICE),
    Rule("par-contre", "registre", _r(r"\bpar contre\b"), "« par contre » : registre courant.",
         "Accepté à l'oral, « par contre » est moins valorisé à l'écrit : « en revanche », "
         "« cependant », « toutefois ».", severity=ADVICE, suggestion="en revanche",
         chapter="connecteurs"),
    Rule("ca-fait-que", "registre", _r(r"\bdu coup\b|\bça fait que\b"),
         "Connecteur oral.",
         "« Du coup » et « ça fait que » sont oraux. À l'écrit : « donc », « par "
         "conséquent », « c'est pourquoi ».", severity=ADVICE, suggestion="par conséquent",
         chapter="connecteurs"),
    Rule("suite-a", "registre", _r(r"(?<!fais )(?<!fait )(?<!faire )(?<!faisons )\bsuite (à|au|aux)\b"), "« suite à » : tour administratif.",
         "Préférez « à la suite de » ou « après » dans un texte soigné.", severity=ADVICE,
         suggestion="à la suite de"),

    # -------------------------------------------------------------- lexique
    Rule("faire-sens", "lexique", _r(r"\bfai\w* (du )?sens\b"), "Anglicisme : « faire sens ».",
         "En français : « avoir du sens », « être logique ».", severity=ERROR,
         suggestion="avoir du sens"),
    Rule("realiser", "lexique", _r(r"\bréalis\w* (que|qu['’])"),
         "« réaliser que » est un anglicisme.",
         "« Réaliser » signifie « accomplir » (réaliser un projet). Pour « comprendre », "
         "dites « se rendre compte que ».", severity=ADVICE, suggestion="se rendre compte que"),
    Rule("definitivement", "lexique", _r(r"\bdéfinitivement (meilleur|mieux|plus|le|la|un|une|"
                                         r"pas)\b"),
         "« définitivement » au sens de « certainement » : anglicisme.",
         "« Définitivement » signifie « pour toujours ». Pour « sans aucun doute » : "
         "assurément, incontestablement.", severity=ADVICE, suggestion="assurément"),
    Rule("impacter", "lexique", _r(r"\bimpact(er|é|ée|és|ées|e|ent)\b"),
         "« impacter » : à éviter à l'écrit soigné.",
         "Préférez « avoir des conséquences sur », « affecter », « toucher ».",
         severity=ADVICE, suggestion="affecter / avoir des répercussions sur"),
    Rule("anglicismes", "lexique", _r(r"\b(deadline|feedback|meeting|job|"
                                      r"mail|mails|e-mail|email|challenge|focus)\b"),
         "Anglicisme.",
         "Un équivalent français est plus approprié : échéance, retour, réunion, emploi, "
         "fin de semaine, courriel, défi, se concentrer.", severity=ADVICE),

    # ---------------------------------------------------------- ponctuation
    Rule("espace-avant-virgule", "ponctuation", _r(r"(\w) +([,.])(?!\d)", 0),
         "Pas d'espace avant la virgule ni le point.",
         "En français, la virgule et le point se collent au mot qui précède.",
         fix=lambda m: m.group(1) + m.group(2), severity=ADVICE),
    Rule("espace-apres", "ponctuation", _r(r"([,;:!?]|(?<=[a-zà-ÿ]{2})\.(?=[a-zà-ÿ]{2}))"
                                          r"(?=[A-Za-zÀ-ÿ])", 0),
         "Espace manquant après la ponctuation.",
         "Une espace suit toujours la virgule, le point-virgule, les deux-points, le point "
         "d'exclamation et d'interrogation.", fix=lambda m: m.group(1) + " ",
         severity=ADVICE),
    Rule("point-majuscule", "ponctuation", _r(r"(?<!etc)(?<!\.)([.!?])\s+([a-zà-ÿ])", 0),
         "Majuscule en début de phrase.", "Après un point, la phrase commence par une "
         "majuscule.", fix=lambda m: m.group(1) + " " + m.group(2).upper(), severity=ERROR),
]

# Connecteurs logiques (par fonction) : cohérence et cohésion.
CASE_RULES = {"point-majuscule", "debut-majuscule"}

CONNECTORS: dict[str, list[str]] = {
    "addition": ["de plus", "en outre", "par ailleurs", "d'ailleurs", "également",
                 "de surcroît", "d'une part", "d'autre part", "non seulement", "aussi"],
    "énumération": ["d'abord", "tout d'abord", "premièrement", "ensuite", "puis",
                    "deuxièmement", "enfin", "pour commencer", "en premier lieu"],
    "opposition": ["mais", "cependant", "toutefois", "néanmoins", "en revanche", "pourtant",
                   "alors que", "tandis que", "au contraire", "par contre"],
    "concession": ["certes", "bien que", "même si", "malgré", "quoique", "il est vrai que",
                   "en dépit de", "pour autant", "quand bien même"],
    "cause": ["parce que", "car", "puisque", "en effet", "comme", "étant donné que",
              "grâce à", "à cause de", "du fait de", "vu que"],
    "conséquence": ["donc", "c'est pourquoi", "par conséquent", "ainsi", "de sorte que",
                    "si bien que", "alors", "c'est la raison pour laquelle", "d'où"],
    "but": ["pour que", "afin que", "afin de", "pour", "dans le but de", "de façon à"],
    "illustration": ["par exemple", "notamment", "comme", "tel que", "c'est le cas de",
                     "en particulier", "prenons l'exemple"],
    "conclusion": ["en conclusion", "pour conclure", "en somme", "en définitive",
                   "finalement", "bref", "tout compte fait", "en bref", "somme toute",
                   "pour finir"],
    "opinion": ["à mon avis", "selon moi", "je pense que", "je crois que", "pour ma part",
                "il me semble que", "je suis convaincu", "je suis convaincue",
                "d'après moi", "personnellement", "j'estime que", "je trouve que"],
}

# Structures complexes valorisées au niveau B2.
COMPLEX_STRUCTURES: list[tuple[str, re.Pattern]] = [
    ("pronom relatif composé ou « dont »",
     _r(r"\b(dont|lequel|laquelle|lesquels|lesquelles|auquel|auxquels|auxquelles|duquel|"
        r"desquels|desquelles)\b")),
    ("subjonctif", _r(r"\bqu(?:e|['’])\s*\w*\s*(soit|soient|aie|ait|aient|fasse|fassent|"
                      r"puisse|puissent|sache|sachent|veuille|aille|aillent|prenne|"
                      r"viennent|vienne|sois)\b")),
    ("conditionnel", _r(rf"\b{COND}\b")),
    ("gérondif", _r(r"\ben \w{3,}ant\b")),
    ("voix passive", _r(r"\b(est|sont|a été|ont été|sera|seront|était|étaient) "
                        r"\w+(é|ée|és|ées|is|ise|it|ite|u|ue|us|ues)\s+(par|de)\b")),
    ("hypothèse (si + imparfait / plus-que-parfait)",
     _r(r"\bs(?:i|['’])\s*\w+\s+\w*(ais|ait|ions|iez|aient)\b")),
    ("mise en relief", _r(r"\bc['’]est \w+(?: \w+)? (qui|que)\b|\bce qui\b|\bce que\b")),
    ("participe présent / proposition participiale", _r(r"(?:^|[.,;]\s*)\w{3,}ant\b")),
]

STOPWORDS = set("""
le la les un une des du de d l au aux et ou mais donc or ni car que qu qui quoi dont où
je j tu il elle on nous vous ils elles me m te t se s lui leur leurs y en ce c ces cet
cette mon ma mes ton ta tes son sa ses notre nos votre vos ne n pas plus très bien
est sont a ont été être avoir fait faire pour par avec sans dans sur sous chez entre
comme si aussi tout tous toute toutes cela ça ceci celle celui ceux celles même autre
autres peut peu beaucoup trop moins alors puis quand encore déjà vraiment ainsi
""".split())
