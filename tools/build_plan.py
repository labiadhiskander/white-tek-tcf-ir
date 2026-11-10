"""Génère tcfmaster/content/data/plan.json : plan de préparation de 12 semaines.

Chaque semaine : 6 jours de travail (60 à 120 min) et un jour de bilan.
Un examen blanc (partiel ou complet) a lieu chaque samedi ; les semaines 1,
4, 8, 10, 11 et 12 comportent un examen complet chronométré.
"""
from __future__ import annotations

import json
from pathlib import Path

WEEKS = [
    # (thème, chapitres de grammaire, catégorie d'expressions, examen, type)
    ("Diagnostic et bases du présent", ["Le présent de l'indicatif", "Le passé composé"],
     "Donner son opinion", "n° 1", "complet"),
    ("Raconter au passé", ["L'imparfait et son emploi avec le passé composé", "Les articles"],
     "Argumenter", "n° 2", "partiel"),
    ("Situer dans le temps", ["Le plus-que-parfait", "Le futur simple et le futur proche",
                              "Les prépositions"], "Exprimer une opposition", "n° 3", "partiel"),
    ("Projets et anticipation", ["Le futur antérieur", "Les pronoms personnels"],
     "Exprimer une conséquence", "n° 4", "complet"),
    ("Hypothèses et souhaits", ["Le conditionnel présent et passé",
                                "L'hypothèse et la condition"],
     "Nuancer son opinion", "n° 5", "partiel"),
    ("Exprimer la nécessité et les sentiments", ["Le subjonctif présent et passé"],
     "Conclure", "n° 6", "partiel"),
    ("Enrichir ses phrases", ["Les pronoms relatifs simples et composés",
                              "Les accords"], "Argumenter", "n° 7", "partiel"),
    ("Rapporter et objectiver", ["La voix passive", "Le discours direct et indirect"],
     "Exprimer une opposition", "n° 8", "complet"),
    ("Précision et style", ["Les adjectifs", "Les adverbes", "La négation",
                            "La comparaison et le superlatif"],
     "Nuancer son opinion", "n° 9", "partiel"),
    ("Phrases complexes de niveau B2", ["Les phrases complexes",
                                        "La concordance des temps"],
     "Exprimer une conséquence", "n° 10", "complet"),
    ("Cohérence du discours", ["Les connecteurs logiques"], "Conclure", "n° 11", "complet"),
    ("Simulation finale et consolidation", [], "Donner son opinion", "n° 12", "complet"),
]

EE_TASKS = ["tâche 1 (message de 60 mots)", "tâche 2 (article de 90 mots)",
            "tâche 3 (texte argumentatif de 90 mots)"]
EO_TASKS = ["tâche 1 (entretien dirigé)", "tâche 2 (interaction)",
            "tâche 3 (point de vue argumenté)"]


def a(minutes: int, module: str, description: str) -> dict:
    return {"minutes": minutes, "module": module, "description": description}


def week_days(w: int, theme, chapters, expr_cat, exam, exam_kind) -> list[dict]:
    ch = chapters or ["Révision des chapitres les plus échoués"]
    ch1, ch2 = ch[0], ch[min(1, len(ch) - 1)]
    level = "B1" if w <= 4 else "B2"
    if w >= 11:
        level = "B2 et C1"
    ee = EE_TASKS[(w - 1) % 3]
    eo = EO_TASKS[(w - 1) % 3]
    days = [
        {"focus": f"Grammaire : {ch1}", "activities": [
            a(35, "Grammaire", f"Lire le cours « {ch1} » et faire les exercices corrigés"),
            a(20, "Compréhension orale", f"Entraînement : 10 questions de niveau {level}"),
            a(15, "Vocabulaire", f"Apprendre 10 expressions « {expr_cat} »"),
        ]},
        {"focus": "Lecture et écriture", "activities": [
            a(25, "Compréhension écrite", f"Entraînement : 12 questions de niveau {level}"),
            a(25, "Expression écrite", f"Rédiger la {ee} puis comparer au modèle"),
            a(10, "Vocabulaire", "Révision espacée des cartes du jour"),
        ]},
        {"focus": f"Grammaire : {ch2}", "activities": [
            a(30, "Grammaire" if ch2 != ch1 else "Conjugaison",
              f"Exercices : {ch2}" if ch2 != ch1 else "Quiz de conjugaison (20 formes)"),
            a(20, "Compréhension orale", "Entraînement en correction immédiate : 10 questions"),
            a(20, "Expression orale", f"S'enregistrer sur la {eo}"),
        ]},
        {"focus": "Argumentation", "activities": [
            a(25, "Compréhension écrite", "Entraînement : 12 questions (documents longs)"),
            a(25, "Expression écrite", "Rédiger un texte argumentatif en réutilisant 5 connecteurs"),
            a(15, "Vocabulaire", "Connecteurs logiques : 10 exemples et exercice de réutilisation"),
        ]},
        {"focus": "Oral et conversation", "activities": [
            a(15, "Conjugaison", "Quiz de conjugaison sur les temps de la semaine"),
            a(20, "Expression orale", f"Simulation chronométrée : {eo}"),
            a(25, "Professeur IA", f"Conversation sur le thème « {theme} »"),
        ]},
        {"focus": f"Examen blanc {exam} ({exam_kind})", "is_mock_exam": f"{exam} ({exam_kind})",
         "activities": (
             [a(120, "Examen blanc", f"Passer l'examen blanc {exam} en mode examen, "
                                     "les quatre épreuves")]
             if exam_kind == "complet" else
             [a(55, "Examen blanc", f"Examen blanc {exam} : compréhension orale et écrite"),
              a(30, "Examen blanc", f"Examen blanc {exam} : expression écrite")])},
        {"focus": "Bilan de la semaine", "is_review": True, "activities": [
            a(20, "Historique", "Analyser les résultats et les erreurs de l'examen blanc"),
            a(20, "Grammaire", "Refaire les exercices échoués de la semaine"),
            a(15, "Vocabulaire", "Révision espacée : toutes les cartes dues"),
            a(5, "Tableau de bord", "Vérifier les alertes et les compétences sous B2"),
        ]},
    ]
    if w == 12:
        days[0]["focus"] = "Révision ciblée des points faibles"
        days[0]["activities"][0] = a(35, "Grammaire",
                                     "Refaire les chapitres dont la maîtrise est inférieure à 70 %")
        days[4]["activities"].append(
            a(10, "Tableau de bord", "Relire les conseils du jour de l'examen"))
    out = []
    for i, d in enumerate(days, start=1):
        out.append({"week": w, "day": i, "focus": d["focus"],
                    "activities": d["activities"],
                    "is_mock_exam": d.get("is_mock_exam"),
                    "is_review": d.get("is_review", False)})
    return out


def build(src_root: Path, out_root: Path) -> list[str]:
    days = []
    for w, spec in enumerate(WEEKS, start=1):
        days += week_days(w, *spec)
    (out_root / "plan.json").write_text(json.dumps(days, ensure_ascii=False, indent=1),
                                        encoding="utf-8")
    print(f"plan : {len(WEEKS)} semaines, {len(days)} jours")
    errors = []
    for d in days:
        if not d["activities"]:
            errors.append(f"plan S{d['week']}J{d['day']}: aucune activité")
    return errors


if __name__ == "__main__":
    root = Path(__file__).resolve().parent.parent
    for e in build(root / "content_src", root / "tcfmaster" / "content" / "data"):
        print("ERREUR:", e)
