# WHITE-TEK – TCF IRN B2 MASTER — Architecture technique

## 1. Vue d'ensemble

Application de bureau Windows, 100 % fonctionnelle hors ligne pour les examens,
exercices, cours et le suivi. L'IA en ligne est facultative et configurable.

```
┌──────────────────────────── Interface (PySide6) ─────────────────────────────┐
│ ui/  fenêtre principale, menu 19 entrées, pages, chronomètres, graphiques    │
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
  disponible ; moteur en ligne optionnel (Claude, SDK officiel `anthropic`). Voir 6 quater.
* Synthèse vocale (`services/audio.py`) : chaque document CO « H: … / F: … » est
  découpé en répliques ; chaque réplique est lue par une voix française du système
  (SAPI via pyttsx3) choisie selon le genre puis l'accent (fr-FR, fr-CA, fr-BE, fr-CH),
  et les répliques sont assemblées en un WAV mis en cache dans `cache_audio/`.
  Ordre de priorité : enregistrement `content/audio/exam-NN_coMM.wav` (humain ou
  pré-généré par `tools/pregen_audio.py`), puis cache, puis synthèse à la volée.
* Lecture (`services/audio_player.py`) : génération dans un fil séparé, lecture par
  Qt Multimedia. En mode examen, une écoute qui échoue est rendue au candidat ; en
  entraînement, la transcription est proposée.
* Reconnaissance vocale : moteur local hors ligne (Vosk, modèle français) et moteur en
  ligne facultatif.

## 6 bis. Correction de l'expression écrite

* `services/writing_rules.py` : environ 50 règles d'erreurs fréquentes des apprenants
  (orthographe, élision, accents, accords, subjonctif, hypothèse, auxiliaire, négation,
  registre, anglicismes, ponctuation). Chaque règle a une explication, une correction
  automatique quand elle est sûre et un lien vers un chapitre de grammaire. Les règles
  visent la précision (des tests vérifient l'absence de faux positifs sur des phrases
  correctes et sur les 60 réponses modèles).
* `services/writing_eval.py` : analyse de la tâche (mots, éléments de la consigne),
  cohérence (connecteurs par fonction, phrases), lexique (variété, répétitions,
  structures complexes) et note estimée sur 20 en quatre critères de 5 points.
  Plafonds : 16/20 au maximum (au-delà, seul un humain peut juger), 9,5 si le texte
  contient au moins 7 erreurs pour 100 mots, 7,5 au-delà de 12, 5 si le texte fait
  moins de la moitié du minimum. Le résultat porte toujours l'avertissement officiel.
* `services/writing_service.py` : enregistrement (`writing_submissions`) et note EE
  d'une tentative (moyenne des 3 tâches, une tâche non rendue vaut 0).

## 6 ter. Expression orale

* `services/recorder.py` : enregistrement du micro (WAV mono 16 kHz, sounddevice),
  mis en pause pendant que l'examinateur simulé parle ; `speech_profile()` mesure le
  temps de parole et les longues pauses à partir de l'énergie du signal.
* `services/stt.py` : reconnaissance vocale hors ligne Vosk (modèle
  `vosk-model-small-fr-0.22`, cherché dans le paramètre `stt_model_path`, puis
  `<données>/modeles`, puis les ressources embarquées ; `tools/fetch_vosk_model.py`
  le télécharge avant la création de l'installateur). Sans micro ou sans modèle,
  la réponse peut être saisie au clavier.
* `services/speaking_eval.py` : quatre critères (tâche, aisance, lexique,
  morphosyntaxe) ; éléments attendus propres à chaque tâche ; débit, pauses,
  hésitations ; plafonds pour les productions courtes ; la prononciation n'est pas
  notée. Avertissement officiel + mise en garde sur la transcription automatique.
* `services/speaking_service.py` : enregistrement en base, réévaluation après
  correction de la transcription, suppression d'un enregistrement ou d'une
  production ; si « Conserver les enregistrements » est décoché, le fichier audio
  est supprimé dès la transcription.

## 6 quater. Tuteur IA et exercices personnalisés

* `services/ai/` : `base.py` (modes, `Conversation`, `TutorReply`), `local.py` (tuteur
  hors ligne), `anthropic_engine.py` (Claude), `prompts.py` (consignes système),
  `tutor.py` (`TutorService` : choix du moteur, repli, évaluation).
* Trois modes : **professeur** (corrige avec les règles de `writing_rules`, explique un
  chapitre de grammaire et propose un exercice corrigé, définit un mot du lexique),
  **conversation libre** (banque de 8 thèmes, relances, reformulation discrète de deux
  erreurs au plus), **examinateur** (tâche EO tirée de la base, relances et objections,
  puis note estimée par `speaking_eval` sur les réponses tapées ; durée estimée à
  130 mots/min et signalée comme telle).
* Claude : modèle `claude-opus-5-5` par défaut, réflexion adaptative, niveau d'effort
  réglable, replis côté serveur activés (`server-side-fallback-2026-07-01`,
  `fallbacks="default"`), refus final signalé poliment. Toute erreur (clé, réseau, quota)
  bascule sur le tuteur local avec un message. La note d'un examen simulé est toujours
  calculée localement ; Claude n'ajoute qu'un retour qualitatif. Le prompt système
  interdit de présenter une évaluation comme un résultat officiel de France Éducation
  international et la mention est ajoutée si elle manque.
* Clé API : saisie dans Paramètres › Tuteur IA, enregistrée par `keyring` dans le
  Gestionnaire d'identification Windows, jamais dans la base, un fichier ou le journal.
  Avant le premier envoi en ligne, un avertissement de confidentialité doit être accepté.
* Journal des erreurs (`services/error_tracking.py`) : les erreurs des productions EE,
  EO (hors réévaluation) et du tuteur alimentent `error_log` (`rule` = « [id] … »).
* Exercices personnalisés (`services/custom_exercises.py`) : corrections tirées des
  productions de l'apprenant, exercices des chapitres liés aux difficultés récurrentes,
  diagnostic si le journal est vide ; chaque exercice indique pourquoi il est proposé.

## 6 quinquies. Tableau de bord

* `services/progress.py` : historique par compétence, niveau estimé (moyenne des
  5 derniers résultats), statut de préparation par compétence (« stabilisé »,
  « à confirmer », « insuffisant », « non évalué »), avis global prudent, minutes
  d'entraînement par jour (exercices, examens plafonnés à 3 h, productions libres),
  avancement du programme de 12 semaines et recommandations priorisées avec la page
  à ouvrir.
* Règle « prêt » : les 3 derniers résultats ET la moyenne récente de CHAQUE
  compétence atteignent B2, et au moins 2 examens blancs complets (4 épreuves) ont
  été passés. Une seule bonne note ne suffit jamais.
* `ui/pages/dashboard_page.py` : bandeau d'avis, 12 indicateurs, tableau de
  préparation, courbes CECRL, minutes par semaine, programme, erreurs fréquentes,
  recommandations avec boutons « Y aller », mention d'estimation pédagogique.

## 6 sexies. Sécurité, confidentialité et export PDF

* `services/pdf_export.py` (ReportLab) : `export_attempt` (synthèse des 4 épreuves,
  détail EE/EO avec critères, erreurs et productions) et `export_progress` (bilan :
  avis, indicateurs, préparation par compétence, erreurs, recommandations). La
  mention d'estimation pédagogique figure en pied de chaque page. Police Arial
  (Windows) ou DejaVu si disponible, sinon Helvetica.
* Secrets : `settings.set_` refuse toute clé de réglage ressemblant à un secret ;
  les clés API passent uniquement par `keyring`. `privacy.SecretFilter` masque les
  clés et mots de passe dans tous les journaux. Un test vérifie qu'aucune clé ne
  figure dans le code source.
* `privacy.purge_learning_data` : effacement de toutes les données d'apprentissage
  (résultats, productions, enregistrements, erreurs, révisions, séances, programme),
  précédé d'une sauvegarde ; le contenu pédagogique est conservé.
* Restauration : une sauvegarde n'est restaurée qu'après `PRAGMA integrity_check`,
  et l'état courant est copié avant remplacement.

## 7. Distribution et mises à jour

* `packaging/tcfmaster.spec` (PyInstaller, mode dossier) : embarque le contenu
  (`content/data`), l'audio pré-généré s'il existe, le modèle Vosk français
  (`tcfmaster/models`, téléchargé par `tools/fetch_vosk_model.py`), l'icône et le guide.
  `packaging/launch.py` est le point d'entrée ; `tools/write_version_info.py` écrit les
  métadonnées Windows de l'exécutable.
* `packaging/installer.iss` (Inno Setup 6, en français) : installation sans droits
  administrateur, raccourcis menu Démarrer et Bureau, désinstallation ; les données
  restent dans le profil (`%APPDATA%`, `%LOCALAPPDATA%`) et survivent aux mises à jour.
* GitHub Actions :
  * `ci.yml` : analyse statique et tests sur Ubuntu et Windows à chaque push/PR ;
  * `release.yml` : sur un runner Windows, tests, modèle Vosk, audio CO (voix SAPI),
    PyInstaller, test de démarrage de l'exécutable, Inno Setup, puis artefact
    téléchargeable ; sur un tag `vX.Y.Z`, publication d'une Release avec l'installateur.
* Mises à jour (`services/updates.py`) : requête anonyme vers la dernière Release
  GitHub au démarrage (désactivable), comparaison de versions, proposition d'ouvrir la
  page de téléchargement. Le nouvel installateur s'installe par-dessus ; au démarrage,
  le contenu est réimporté sans perdre l'historique (identifiants stables).
* Guide utilisateur : `tcfmaster/docs/GUIDE_UTILISATEUR.md`, ouvert depuis
  Paramètres › Aide et mises à jour. Journal des modifications : `CHANGELOG.md`.

## 8. Version 1.1 – Édition B2

Principe : tout ce qui existait en 1.0 est conservé. La base est migrée de façon
additive (`database.add_missing_columns` ajoute les colonnes manquantes, ne supprime
ni ne modifie rien) ; le contenu est réimporté sur place à chaque changement de
version ou d'empreinte du contenu, identifiants stables, historique intact.

### 8.1 Chaîne de contenu

| Source (texte balisé) | Compilateur | Données | Contrôles bloquants |
|---|---|---|---|
| `content_src/collections/<co\|ce\|ee\|eo>/*.txt` | `tools/build_collections.py` | `data/collections/` | correction de chaque proposition, nombre de mots des modèles EE (`validator.count_words`), commentaires et conseils, réponses équilibrées A–D |
| `content_src/exams/exam_b2_NN.txt` (`@series B2`) | `tools/build_content.py` | `data/exams/` | format 25/25/3/3, niveau B2 partout, durées EO 180/210/210 s, `validate_b2_series`, doublons avec la bibliothèque |
| `content_src/videos/videos.txt` | `tools/build_videos.py` | `data/videos.json` | 12 catégories couvertes, https, liste blanche de domaines (`ALLOWED_DOMAINS`), exercice corrigé |
| `tools/build_intensive.py` | — | `data/intensive.json` | 30 jours, 4 compétences par jour, examens blancs aux jours 10, 20, 29 |

Le seeder (`content/seeder.py`) valide de nouveau à l'import et ignore tout contenu
marqué `locally_modified` (modifié dans l'administration).

### 8.2 Nouveaux modules

* `services/collections.py` : bibliothèque, séries d'entraînement ou d'examen,
  correction (`services/correction.py`). Une question manquée alimente le journal des
  difficultés et le **lexique à revoir** (`review.enqueue_lexicon` : `review_items`
  de type `lexique`, `item_id = id de l'exercice × 1000 + rang du terme`, SM-2).
* `services/piper_tts.py` : voix Piper téléchargées à la demande (binaire MIT,
  voix `rhasspy/piper-voices`, fiche du modèle affichée avant téléchargement) ;
  repli SAPI.
* `services/videos.py` et `ui/pages/videos_page.py` : vidéothèque, vérification des
  liens (HEAD puis GET, statut `erreur` = masqué), exercice à correction immédiate.
* `services/admin.py` et `ui/pages/admin_page.py` : PIN facultatif (PBKDF2-SHA256,
  sel aléatoire), inventaire, édition validée, brouillon, suppression (réelle pour un
  contenu créé localement, masquage pour un contenu préinstallé), « rétablir
  l'original ».
* `services/intensive.py` et `ui/pages/intensive_page.py` : programme de 30 jours
  (`intensive_days`, `intensive_progress`), date de démarrage (réglage
  `intensive_start`), jour du calendrier, retard, examens blancs cochés
  automatiquement (`sync_mock_days`).
* `services/progress.py` : `exercises_done`, `mock_history`, recommandations
  « vocabulaire à revoir » et « programme intensif en retard » ; le tableau de bord
  affiche 14 indicateurs, l'historique des examens blancs, les deux programmes et le
  lexique à revoir.

### 8.3 IA locale

* `services/ai/local_llm.py` : `LocalLLMEngine`, client de l'API compatible OpenAI
  (`/v1/models`, `/v1/chat/completions`) d'**Ollama** (`localhost:11434`) ou de
  **LM Studio** (`localhost:1234`), en `urllib` (aucune dépendance). Les adresses
  locales contournent tout proxy ; les blocs `<think>` des modèles à raisonnement
  sont retirés ; toute erreur devient `AIUnavailable` (repli sur le tuteur hors
  ligne).
* `TutorService` : fournisseurs `local` (défaut), `local_llm`, `anthropic`.
  Réglages `local_ai_url`, `local_ai_model` (vide = premier modèle installé).
  Aucun consentement n'est demandé si l'adresse est locale ou privée ; une adresse
  distante exige l'avertissement de confidentialité, comme Claude.
* `TutorService.deepen(kind, submission_id)` et `ui/ai_deepen.py` : correction
  approfondie d'une production EE ou EO (`prompts.DEEPEN_SYSTEM`). Le moteur reçoit la
  note et les erreurs du barème local, a l'interdiction de proposer une autre note,
  et la mention d'estimation pédagogique est ajoutée si elle manque.

### 8.4 Tests

`tests/test_v11_step*.py` couvrent chaque étape (contenu, compilateurs, B2,
équilibre des réponses, doublons, vidéothèque, administration, programme intensif,
tableau de bord, IA locale avec serveur simulé). La CI lance
`ruff check --select F tcfmaster tests tools` puis `pytest`.
