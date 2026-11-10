# WHITE-TEK – TCF IRN B2 MASTER

Application Windows de préparation intensive au **TCF IRN** (intégration, résidence,
nationalité), objectif **niveau B2** dans les quatre épreuves.

> Les notes et niveaux affichés sont des **estimations pédagogiques** ; ce ne sont pas
> des résultats officiels de France Éducation international.

## Fonctionnalités

* 20 examens blancs complets (CO, CE, EE, EO) aux durées officielles, correction détaillée.
* Compréhension orale avec voix françaises (synthèse hors ligne), écoute unique en examen.
* Expression écrite corrigée et annotée ; expression orale avec examinateur simulé,
  enregistrement, transcription hors ligne (Vosk) et analyse.
* Vocabulaire B2 (2 000 mots, 1 000 expressions, 500 phrases complexes, 300 exemples
  d'argumentation, 200 connecteurs), 23 chapitres de grammaire et de conjugaison.
* Tuteur IA (professeur, conversation, examinateur), hors ligne ou avec Claude.
* Exercices personnalisés à partir de vos erreurs, tableau de bord prudent
  (jamais « prêt » sur une seule note), programme de 12 semaines, export PDF.
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
python tools/build_content.py             # régénérer le contenu depuis content_src/
```

## Construire l'installateur

* **GitHub Actions** : onglet *Actions* › *Installateur Windows* › *Run workflow* ;
  l'installateur est dans les artefacts. Un tag `vX.Y.Z` publie aussi une Release.
* **En local (Windows)** : `powershell -ExecutionPolicy Bypass -File tools\build_windows.ps1`
  (nécessite Python 3.12 et Inno Setup 6).

Architecture détaillée : [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).
