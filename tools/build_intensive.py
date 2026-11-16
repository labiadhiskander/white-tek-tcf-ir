"""Génère tcfmaster/content/data/intensive.json : programme intensif B2 de 30 jours.

Règles du programme (plan v1.1, § 2.7) :
  * les quatre compétences (CO, CE, EE, EO) sont travaillées CHAQUE jour ;
  * un examen blanc B2 complet a lieu les jours 10, 20 et 29, suivi d'une
    analyse de la correction le jour même ;
  * trois phases : méthode (jours 1 à 9), intensification chronométrée
    (11 à 19), conditions d'examen (21 à 28), puis bilan (30) ;
  * environ deux heures par jour ; il complète le programme de 12 semaines
    sans le remplacer.

Chaque activité : {module, minutes, description, ref} où `ref` est la clé de
la page de l'application à ouvrir (bouton « Y aller »).

    python tools/build_intensive.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "tcfmaster" / "content" / "data" / "intensive.json"

MOCK_DAYS = {10: ("B2-BLANC-01", "Société et vie citoyenne"),
             20: ("B2-BLANC-05", "Éducation et jeunesse"),
             29: ("B2-BLANC-10", "Famille, solidarités et institutions")}
SKILLS = ("Compréhension orale", "Compréhension écrite", "Expression écrite",
          "Expression orale")

EE_TASK = {1: "tâche 1 : message ou courriel de 30 à 60 mots",
           2: "tâche 2 : récit ou compte rendu de 40 à 90 mots",
           3: "tâche 3 : synthèse de deux opinions et prise de position, 40 à 90 mots"}
EO_TASK = {1: "tâche 1 : entretien dirigé (3 min)",
           2: "tâche 2 : exercice en interaction (3 min 30)",
           3: "tâche 3 : expression d'un point de vue (3 min 30)"}

# Jour : (thème, collection CO, collection CE, tâche EE, tâche EO, travail de la langue)
DAYS: dict[int, tuple] = {
    # ---------------- Phase 1 : méthode, tâche par tâche (correction immédiate)
    1: ("Diagnostic et méthode du TCF IRN", "Actualités et société", "Articles de presse", 1, 1,
        ("Vidéothèque B2", "videos", "Regarder une fiche « Méthodologie TCF IRN » et noter le "
         "format des quatre épreuves ; faire l'exercice corrigé de la fiche")),
    2: ("Le monde du travail", "Vie professionnelle", "Travail", 2, 2,
        ("Grammaire", "grammar", "Le subjonctif : relire le cours et faire les exercices "
         "corrigés (il faut que, bien que, pour que)")),
    3: ("Environnement et climat", "Environnement et climat", "Environnement", 3, 3,
        ("Connecteurs logiques", "grammar", "Les connecteurs logiques : cause, conséquence, "
         "opposition ; réemployer cinq connecteurs dans la production écrite du jour")),
    4: ("Santé et bien-être", "Santé et bien-être", "Santé", 1, 1,
        ("Vocabulaire", "vocab", "Thème « Santé » : apprendre 15 mots en cartes de révision "
         "espacée et faire la révision du jour")),
    5: ("Éducation et formation", "Éducation et formation", "Éducation", 2, 2,
        ("Grammaire", "grammar", "Le conditionnel présent et passé : cours et exercices "
         "corrigés (politesse, hypothèse, information non confirmée)")),
    6: ("Débattre et argumenter", "Débats et opinions", "Textes argumentatifs", 3, 3,
        ("Expressions", "vocab", "Expressions « Donner son opinion » et « Nuancer son "
         "opinion » : en apprendre dix et les réutiliser à l'oral")),
    7: ("Technologie et numérique", "Technologie et intelligence artificielle", "Technologie",
        1, 2, ("Grammaire", "grammar", "Les pronoms relatifs simples et composés (dont, "
               "lequel, auquel) : cours et exercices corrigés")),
    8: ("Économie et consommation", "Économie et emploi", "Économie", 2, 3,
        ("Vocabulaire", "vocab", "Thèmes « Économie et entreprise » et « Consommation et "
         "argent » : 15 mots en révision espacée ; relire le vocabulaire noté sur les questions manquées")),
    9: ("Culture et médias, bilan de la phase 1", "Culture et médias", "Culture", 3, 1,
        ("Exercices personnalisés", "custom", "Série d'exercices personnalisés sur vos "
         "erreurs récurrentes des neuf premiers jours")),
    # ---------------- Phase 2 : intensification chronométrée
    11: ("Vie sociale et relations", "Relations sociales", "Débats de société", 1, 2,
         ("Grammaire", "grammar", "L'hypothèse et la condition (si + imparfait, au cas où, à "
          "condition que) : exercices corrigés")),
    12: ("Témoignages et parcours", "Témoignages et interviews", "Éditoriaux", 2, 3,
         ("Grammaire", "grammar", "Le discours direct et indirect, concordance des temps : "
          "exercices corrigés")),
    13: ("Démarches administratives", "Actualités et société", "Documents administratifs "
         "complexes", 1, 1, ("Vocabulaire", "vocab", "Thème « Administration et citoyenneté » "
                             "(titre de séjour, justificatif, démarche, délai) : 15 mots")),
    14: ("Conférences et émissions", "Conférences et émissions", "Actualités", 3, 2,
         ("Prononciation", "videos", "Fiche « Prononciation » de la vidéothèque : écouter, "
          "répéter, s'enregistrer sur une réponse de la tâche 3")),
    15: ("Travail et nouveaux modes de vie", "Vie professionnelle", "Travail", 2, 3,
         ("Grammaire", "grammar", "La voix passive : cours et exercices corrigés ; transformer "
          "trois phrases de la production écrite")),
    16: ("Environnement et territoires", "Environnement et climat", "Environnement", 3, 1,
         ("Grammaire", "grammar", "Les phrases complexes : but, concession, opposition "
          "(afin que, bien que, alors que, tandis que)")),
    17: ("Santé publique et sciences", "Santé et bien-être", "Santé", 1, 2,
         ("Conjugaison", "conj", "Conjugaison : subjonctif et conditionnel des verbes "
          "irréguliers fréquents (faire, pouvoir, savoir, aller, vouloir)")),
    18: ("Médias et information", "Culture et médias", "Articles de presse", 2, 3,
         ("Vocabulaire", "vocab", "Thème « Numérique et médias » : 15 mots en révision espacée")),
    19: ("Bilan de la phase 2", "Débats et opinions", "Textes argumentatifs", 3, 1,
         ("Exercices personnalisés", "custom", "Série personnalisée sur les erreurs relevées "
          "depuis le jour 10 (grammaire, accords, connecteurs)")),
    # ---------------- Phase 3 : conditions d'examen
    21: ("Analyse de l'examen n° 2 et reprise", "Économie et emploi", "Économie", 1, 2,
         ("Exercices personnalisés", "custom", "Reprendre les questions manquées à l'examen "
          "blanc du jour 20 et lancer une série personnalisée")),
    22: ("Ville, logement et mobilité", "Actualités et société", "Débats de société", 2, 3,
         ("Grammaire", "grammar", "Les accords (participe passé avec avoir, adjectifs) : "
          "exercices corrigés ; relire vos trois dernières productions")),
    23: ("Technologie et société", "Technologie et intelligence artificielle", "Technologie",
         3, 1, ("Vocabulaire", "vocab", "Révision espacée de tout le vocabulaire dû ; "
                "objectif : aucun élément en retard")),
    24: ("Éducation et jeunesse", "Éducation et formation", "Éducation", 1, 2,
         ("Connecteurs logiques", "grammar", "Connecteurs : réécrire une production en "
          "variant les articulateurs (en revanche, par conséquent, certes… mais)")),
    25: ("Culture, patrimoine et loisirs", "Conférences et émissions", "Culture", 2, 3,
         ("Expressions", "vocab", "Expressions « Argumenter » et « Conclure » : en réutiliser "
          "cinq dans la tâche 3 orale")),
    26: ("Solidarités et vie citoyenne", "Relations sociales", "Éditoriaux", 3, 1,
         ("Grammaire", "grammar", "Concordance des temps et subjonctif : série d'exercices "
          "corrigés")),
    27: ("Travail, santé et équilibre de vie", "Témoignages et interviews", "Santé", 1, 2,
         ("Techniques d'examen", "videos", "Fiche « Techniques d'examen » : gestion du temps, "
          "élimination des distracteurs, relecture")),
    28: ("Répétition générale", "Débats et opinions", "Documents administratifs complexes", 2,
         3, ("Exercices personnalisés", "custom", "Dernière série personnalisée sur vos deux "
             "erreurs les plus fréquentes")),
}

PHASES = [(range(1, 10), "Méthode", "entraînement avec correction immédiate : lisez chaque "
           "explication, y compris pour les bonnes réponses"),
          (range(11, 20), "Intensification", "séries chronométrées : correction à la fin "
           "seulement, comme à l'examen"),
          (range(21, 29), "Conditions d'examen", "épreuves complètes chronométrées, sans "
           "pause ni dictionnaire")]


def phase(day: int) -> tuple[str, str]:
    for rng, name, how in PHASES:
        if day in rng:
            return name, how
    return "Bilan", ""


def regular_day(day: int) -> dict:
    theme, co, ce, ee, eo, (lang_mod, lang_ref, lang_desc) = DAYS[day]
    name, how = phase(day)
    if name == "Méthode":
        co_d = (f"Collection « {co} » : un exercice complet en mode entraînement, puis "
                "réécouter le document avec la transcription")
        ce_d = (f"Collection « {ce} » : un exercice complet en mode entraînement ; noter les "
                "mots inconnus")
        ee_d = (f"Rédiger la {EE_TASK[ee]} sur le thème du jour, sans limite de temps, puis "
                "comparer avec le modèle et son commentaire")
        eo_d = (f"Préparer puis enregistrer la {EO_TASK[eo]} ; écouter la réponse modèle et "
                "réenregistrer")
        minutes = (25, 25, 30, 25, 15)
    elif name == "Intensification":
        co_d = (f"Collection « {co} » : deux exercices enchaînés en mode examen (correction à "
                "la fin), puis analyse de chaque erreur")
        ce_d = (f"Collection « {ce} » : deux exercices chronométrés en mode examen ; repérer "
                "le type de question manquée")
        ee_d = (f"{EE_TASK[ee].capitalize()} en temps limité (10 minutes), en respectant "
                "strictement le nombre de mots ; lire la correction détaillée")
        eo_d = (f"{EO_TASK[eo].capitalize()} chronométrée, avec l'examinateur virtuel "
                "(page « Conversation avec l'IA », mode examinateur) ou en enregistrement")
        minutes = (30, 30, 25, 20, 15)
    else:
        co_d = (f"Épreuve de compréhension orale d'un examen blanc déjà passé ou collection "
                f"« {co} » : 25 questions en 20 minutes, sans réécoute")
        ce_d = (f"Collection « {ce} » : série de 25 questions en 35 minutes, comme à "
                "l'examen")
        ee_d = (f"{EE_TASK[ee].capitalize()} dans le temps de l'épreuve complète (30 minutes "
                "pour les trois tâches) ; relire accords et connecteurs")
        eo_d = (f"{EO_TASK[eo].capitalize()} en conditions réelles, sans notes ; vérifier la "
                "durée et la variété des connecteurs")
        minutes = (25, 35, 25, 20, 15)
    acts = [
        {"module": SKILLS[0], "minutes": minutes[0], "description": co_d, "ref": "co"},
        {"module": SKILLS[1], "minutes": minutes[1], "description": ce_d, "ref": "ce"},
        {"module": SKILLS[2], "minutes": minutes[2], "description": ee_d, "ref": "ee"},
        {"module": SKILLS[3], "minutes": minutes[3], "description": eo_d, "ref": "eo"},
        {"module": lang_mod, "minutes": minutes[4], "description": lang_desc, "ref": lang_ref},
    ]
    focus = f"{name} · {theme}"
    return {"day": day, "focus": focus, "activities": acts, "is_mock_exam": False,
            "advice": how}


def mock_day(day: int) -> dict:
    code, theme = MOCK_DAYS[day]
    n = int(code[-2:])
    acts = [
        {"module": SKILLS[0], "minutes": 20, "ref": "mock",
         "description": f"Examen blanc B2 n° {n} ({code}) : compréhension orale, 25 questions "
                        "en 20 minutes, en conditions réelles"},
        {"module": SKILLS[1], "minutes": 35, "ref": "mock",
         "description": f"Examen blanc B2 n° {n} : compréhension écrite, 25 questions en "
                        "35 minutes"},
        {"module": SKILLS[2], "minutes": 30, "ref": "mock",
         "description": f"Examen blanc B2 n° {n} : expression écrite, 3 tâches en 30 minutes, "
                        "nombre de mots respecté"},
        {"module": SKILLS[3], "minutes": 10, "ref": "mock",
         "description": f"Examen blanc B2 n° {n} : expression orale, 3 tâches (3 min, "
                        "3 min 30, 3 min 30)"},
        {"module": "Analyse de la correction", "minutes": 30, "ref": "history",
         "description": "Lire la correction complète (chaque question, chaque tâche), noter "
                        "les trois priorités et vérifier le tableau de bord"},
    ]
    return {"day": day, "focus": f"Examen blanc B2 n° {n} · {theme}", "activities": acts,
            "is_mock_exam": True, "exam_code": code,
            "advice": "conditions réelles : une seule séance, sans pause ni dictionnaire ; "
                      "le résultat est une estimation pédagogique, pas une note officielle"}


def final_day() -> dict:
    acts = [
        {"module": SKILLS[0], "minutes": 15, "ref": "co",
         "description": "Réécouter deux documents déjà travaillés avec leur transcription, "
                        "sans chercher à faire de score"},
        {"module": SKILLS[1], "minutes": 15, "ref": "ce",
         "description": "Relire deux textes argumentatifs corrigés et leurs explications"},
        {"module": SKILLS[2], "minutes": 20, "ref": "ee",
         "description": "Relire vos meilleures productions et les modèles des trois tâches ; "
                        "mémoriser les formules d'ouverture et de clôture"},
        {"module": SKILLS[3], "minutes": 15, "ref": "eo",
         "description": "Se présenter à voix haute (tâche 1) et répéter deux introductions "
                        "de point de vue (tâche 3)"},
        {"module": "Bilan", "minutes": 15, "ref": "dashboard",
         "description": "Consulter le tableau de bord, exporter le bilan PDF et préparer la "
                        "logistique du jour de l'examen ; se reposer"},
    ]
    return {"day": 30, "focus": "Bilan final et révision légère", "activities": acts,
            "is_mock_exam": False, "advice": "veille d'examen : révision légère et repos"}


def build() -> list[dict]:
    out = []
    for day in range(1, 31):
        if day in MOCK_DAYS:
            out.append(mock_day(day))
        elif day == 30:
            out.append(final_day())
        else:
            out.append(regular_day(day))
    return out


def check(days: list[dict]) -> list[str]:
    errs = []
    if [d["day"] for d in days] != list(range(1, 31)):
        errs.append("Les jours doivent aller de 1 à 30.")
    for d in days:
        mods = {a["module"] for a in d["activities"]}
        missing = [m for m in SKILLS if m not in mods]
        if missing:
            errs.append(f"Jour {d['day']} : compétence(s) absente(s) : {', '.join(missing)}")
        for a in d["activities"]:
            if not a.get("description") or not a.get("ref") or a.get("minutes", 0) <= 0:
                errs.append(f"Jour {d['day']} : activité incomplète ({a.get('module')})")
    mocks = [d["day"] for d in days if d["is_mock_exam"]]
    if mocks != sorted(MOCK_DAYS):
        errs.append(f"Examens blancs attendus aux jours {sorted(MOCK_DAYS)}, trouvés {mocks}")
    return errs


def main() -> int:
    days = build()
    errs = check(days)
    for e in errs:
        print("ERREUR", e)
    if errs:
        return 1
    OUT.write_text(json.dumps(days, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    total = sum(a["minutes"] for d in days for a in d["activities"])
    print(f"{OUT.relative_to(ROOT)} : 30 jours, {total // 60} h {total % 60:02d} au total")
    return 0


if __name__ == "__main__":
    sys.exit(main())
