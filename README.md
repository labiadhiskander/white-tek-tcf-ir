# WHITE-TEK – TCF IRN B2 MASTER

Application Windows de préparation intensive au **TCF IRN** (intégration, résidence,
nationalité), objectif **niveau B2** dans les quatre épreuves.

> Les notes et niveaux affichés sont des **estimations pédagogiques** ; ce ne sont pas
> des résultats officiels de France Éducation international.

## Fonctionnalités

* **v1.1 – Édition B2** : bibliothèque de plus de 100 exercices corrigés par
  compétence (CO, CE, EE, EO), 10 examens blancs 100 % B2, vidéothèque officielle
  en 12 catégories, administration du contenu, programme intensif de 30 jours,
  IA locale gratuite (Ollama, LM Studio). Détail : [CHANGELOG.md](CHANGELOG.md).
* 30 examens blancs complets (CO, CE, EE, EO) aux durées officielles, correction détaillée.
* Compréhension orale avec voix françaises (Piper ou Windows, hors ligne), écoute unique en examen.
* Expression écrite corrigée et annotée ; expression orale avec examinateur simulé,
  enregistrement, transcription hors ligne (Vosk) et analyse.
* Vocabulaire B2 (2 000 mots, 1 000 expressions, 500 phrases complexes, 300 exemples
  d'argumentation, 200 connecteurs), 23 chapitres de grammaire et de conjugaison.
* Tuteur IA (professeur, conversation, examinateur) : hors ligne, IA locale gratuite
  (Ollama / LM Studio) ou Claude (facultatif) ; aucune API payante n'est nécessaire.
* Exercices personnalisés à partir de vos erreurs, tableau de bord prudent
  (jamais « prêt » sur une seule note), programmes de 12 semaines et de 30 jours,
  export PDF.
* Sauvegardes automatiques, effacement des données sur demande, clés API dans le
  coffre Windows, vérification des mises à jour.

## Installation (utilisateurs)

Téléchargez `WhiteTekTCF-Setup-x.y.z.exe` depuis la page **Releases** du dépôt (ou
l'artefact du workflow « Installateur Windows ») et lancez-le. Voir le
[guide utilisateur](tcfmaster/docs/GUIDE_UTILISATEUR.md).

## Développement

```bash
python -m pip install -r requirements-dev.txt
python -m tcfmaster                       # lancer l'application
QT_QPA_PLATFORM=offscreen python -m pytest -q
python tools/build_content.py             # examens blancs (content_src/exams)
python tools/build_collections.py         # bibliothèque B2 (content_src/collections)
python tools/build_videos.py              # vidéothèque (content_src/videos)
python tools/build_intensive.py           # programme intensif de 30 jours
ruff check --select F tcfmaster tests tools
```

## Construire l'installateur

* **GitHub Actions** : onglet *Actions* › *Installateur Windows* › *Run workflow* ;
  l'installateur est dans les artefacts. Un tag `vX.Y.Z` publie aussi une Release.
* **En local (Windows)** : `powershell -ExecutionPolicy Bypass -File tools\build_windows.ps1`
  (nécessite Python 3.12 et Inno Setup 6).

Architecture détaillée : [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).
