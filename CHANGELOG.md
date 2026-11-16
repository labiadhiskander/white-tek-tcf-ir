# Journal des modifications

Toutes les notes et tous les niveaux affichés par l'application sont des
estimations pédagogiques, jamais des résultats officiels de France Éducation
international.

## 1.1.0 – Édition B2 (novembre 2026)

Version entièrement centrée sur le niveau B2. Toutes les fonctionnalités et
toutes les données de la version 1.0 sont conservées : la mise à jour s'installe
par-dessus, la base est migrée sans perte (colonnes ajoutées, rien de supprimé)
et l'historique du candidat est intact.

### Contenu B2
* **Bibliothèque B2** : 100 exercices de compréhension orale (12 collections),
  102 de compréhension écrite (13 collections), 102 sujets d'expression écrite et
  102 situations d'expression orale, tous corrigés.
  * CO / CE : justification de chaque proposition (bonne et mauvaises),
    explication, vocabulaire du document, pièges ; bonnes réponses réparties
    équitablement entre A, B, C et D.
  * EE : réponse modèle respectant strictement le nombre de mots de la tâche
    (30–60, 40–90, 40–90), commentaire, points attendus, conseils, remarques de
    syntaxe.
  * EO : réponse modèle, relances de l'examinateur, expressions utiles,
    commentaire, conseils de prononciation.
* **10 examens blancs 100 % B2** (B2-BLANC-01 à 10), au format officiel :
  25 CO, 25 CE, 3 tâches EE, 3 tâches EO (3 min, 3 min 30, 3 min 30). Aucun
  doublon avec la bibliothèque. Les 20 examens de la v1.0 restent disponibles.
* Mode entraînement : correction immédiate ; mode examen : correction à la fin.
* Contenu compilé et validé (`tools/build_*.py`) : la compilation échoue si une
  correction manque, si un modèle dépasse le nombre de mots ou en cas de doublon.

### Audio
* Voix neuronales françaises **Piper** téléchargeables à la demande (gratuites,
  hors ligne) ; repli automatique sur les voix Windows.
* Expression orale : indications de prononciation à partir de la confiance de la
  reconnaissance vocale, réponse améliorée proposée.

### Vidéothèque B2
* 24 fiches réparties en **12 catégories** (méthodologie, CO, CE, EE, EO,
  argumentation, grammaire, conjugaison, connecteurs, vocabulaire, prononciation,
  techniques d'examen), chacune avec un exercice corrigé.
* Liens uniquement vers des sites officiels (liste blanche de domaines, https) ;
  les vidéos s'ouvrent dans le navigateur et ne sont **ni téléchargées ni
  redistribuées**. Bouton « Vérifier les liens » : un lien en erreur est masqué.

### Administration
* Page protégée par un code PIN facultatif (haché, jamais stocké en clair).
* Création, modification, validation, mise en brouillon et suppression des
  vidéos, exercices CO/CE, sujets EE et situations EO, avec les mêmes règles de
  validation que le contenu préinstallé.
* Une modification locale n'est jamais écrasée par une mise à jour ; un contenu
  préinstallé « supprimé » est seulement masqué (l'historique en dépend) ;
  « Rétablir l'original » est possible.

### Suivi
* **Programme intensif de 30 jours** (en plus du programme de 12 semaines) :
  environ 2 h par jour, les quatre compétences chaque jour, examens blancs B2
  aux jours 10, 20 et 29, cochés automatiquement une fois passés.
* **Tableau de bord** : exercices réalisés, historique des examens blancs,
  progression du programme intensif, **vocabulaire à revoir** (les mots des
  documents où une question a été manquée passent en révision espacée),
  nouvelles recommandations.

### IA
* **IA locale gratuite** compatible **Ollama** et **LM Studio** : nouveau moteur
  du tuteur, sans clé ni abonnement, rien n'est envoyé sur Internet.
* Bouton **« Approfondir la correction avec l'IA »** en expression écrite et
  orale (IA locale ou Claude) : la note reste celle du barème de l'application,
  la mention « estimation pédagogique » est toujours présente.
* Aucune API payante n'est nécessaire : le tuteur hors ligne reste disponible et
  sert de repli automatique.

## 1.0.0 – Première version (novembre 2026)

* 20 examens blancs complets aux durées officielles, correction détaillée.
* Compréhension orale avec voix françaises hors ligne ; expression écrite
  corrigée et annotée ; expression orale avec examinateur simulé, enregistrement
  et transcription hors ligne (Vosk).
* Vocabulaire, expressions, grammaire et conjugaison B2 ; tuteur IA (hors ligne
  ou Claude) ; exercices personnalisés ; tableau de bord ; programme de
  12 semaines ; export PDF ; sauvegardes ; vérification des mises à jour.
