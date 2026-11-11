# WHITE-TEK – TCF IRN B2 MASTER — Architecture technique

## 1. Vue d'ensemble

Application de bureau Windows, 100 % fonctionnelle hors ligne pour les examens,
exercices, cours et le suivi. L'IA en ligne est facultative et configurable.

```
┌──────────────────────────── Interface (PySide6) ─────────────────────────────┐
│ ui/  fenêtre principale, menu 15 entrées, pages, chronomètres, graphiques    │
└───────────────▲──────────────────────────────────────────────────────────────┘
                │ appelle uniquement des services (aucun SQL dans l'interface)
┌───────────────┴──────────────── Logique métier ──────────────────────────────┐
│ services/ exam_service · progress · review (SM-2) · settings · plan          │
│           correction (EE) · speaking (EO) · ai (moteurs) · audio (TTS/STT)   │
│           export PDF · backup · updates                                      │
└───────────────▲──────────────────────────────────────────────────────────────┘
┌───────────────┴──────────────── Données ─────────────────────────────────────┐
│ db/ models.py (SQLAlchemy 2) · database.py (WAL, intégrité, sauvegardes)     │
│ content/ data/*.json (contenu préinstallé) · validator · seeder              │
└──────────────────────────────────────────────────────────────────────────────┘
core/ paths (dossier de données au choix) · logging · niveaux CECRL · contexte
```

## 2. Arborescence

| Dossier | Rôle |
|---|---|
| `tcfmaster/core` | Chemins, journalisation, barèmes CECRL, assemblage (`bootstrap`) |
| `tcfmaster/db` | Modèle de données et moteur SQLite protégé |
| `tcfmaster/content` | Contenu JSON préinstallé, validation du format TCF, import |
| `tcfmaster/services` | Toute la logique métier, testable sans interface |
| `tcfmaster/ui` | Interface PySide6 (phase 2) |
| `tests` | Tests automatisés (pytest) |
| `installer` | PyInstaller + Inno Setup (phase 10) |

## 3. Modèle de données

**Contenu** : `exams` → `questions` (CO/CE, 25 par épreuve) → `choices` (A–D, une seule
correcte, justification de chaque proposition) ; `writing_tasks` (3 par examen, limites
30–60 / 40–90 / 40–90 mots, réponse modèle B2) ; `speaking_tasks` (3 par examen, 180 s /
210 s / 210 s, relances de l'examinateur, réponse modèle) ; `expressions` (expression,
phrase complexe, argumentation, connecteur : sens, niveau, exemple, équivalent simple,
exercice + correction) ; `vocab_words` ; `grammar_chapters` → `grammar_exercises`
(cours, exemples simples et B2, exercices corrigés) ; `verbs` (conjugaisons) ;
`plan_days` (12 semaines × 7 jours).

**Activité** : `profile`, `attempts` (examen ou entraînement, résultats JSON),
`answers`, `writing_submissions`, `speaking_submissions` (audio, transcription,
évaluation), `error_log` (difficultés récurrentes), `review_items` (répétition espacée),
`study_sessions` (temps d'entraînement), `plan_progress`, `settings`, `schema_info`.

## 4. Règles métier clés

* Format officiel : CO 20 min / 25 QCM, CE 35 min / 25 QCM, EE 30 min / 3 tâches,
  EO 10 min / 3 tâches. Vérifié par `content/validator.py` à chaque import.
* Aucune question importée si elle n'a pas exactement une bonne réponse.
* Réécoute CO autorisée uniquement en mode entraînement.
* Score CO/CE sur 699 pondéré par la difficulté ; EE/EO sur 20 ; conversion CECRL selon
  les barèmes TCF.
* « Prêt pour B2 » seulement si les 3 derniers résultats de **chaque** compétence sont
  au niveau B2 (jamais sur une seule note).
* Toute évaluation porte la mention : estimation pédagogique, pas un résultat officiel
  de France Éducation international.

## 5. Données et sécurité

* Dossier de données au choix de l'utilisateur (mémorisé dans `%APPDATA%\WhiteTekTCF`).
* SQLite en WAL + `synchronous=FULL`, contrôle d'intégrité au démarrage, restauration
  automatique de la dernière sauvegarde saine, sauvegardes à chaud avec rotation.
* Clés API dans le Gestionnaire d'identification Windows (`keyring`), jamais en base ni
  dans le code.
* Journaux tournants dans `journaux/`.
* Enregistrements vocaux supprimables à la demande.

## 6. IA, audio, voix

* Moteur IA abstrait : moteur **local** (règles, correcteur, banque de relances) toujours
  disponible ; moteurs en ligne optionnels (Claude API ou compatible OpenAI).
* Synthèse vocale : fichiers audio pré-générés pour les examens + voix Windows (SAPI)
  en secours.
* Reconnaissance vocale : moteur local hors ligne (Vosk, modèle français) et moteur en
  ligne facultatif.

## 7. Distribution

PyInstaller (exécutable autonome, Python embarqué) puis Inno Setup (installateur
`.exe`, raccourci bureau, désinstallation, choix du dossier). Construction automatisée
sur un runner Windows GitHub Actions. Mise à jour : vérification d'un manifeste de
version en ligne et téléchargement du nouvel installateur.
