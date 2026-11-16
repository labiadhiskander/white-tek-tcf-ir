# Vidéothèque B2

`videos.txt` est compilé par `python3 tools/build_videos.py` vers
`tcfmaster/content/data/videos.json`.

Règles :
- uniquement des liens vers des sites officiels gratuits (liste `ALLOWED_DOMAINS`
  dans `tcfmaster/content/validator.py`) ; aucune vidéo n'est téléchargée ni
  redistribuée ;
- ne jamais inventer d'adresse : chaque lien est une page d'accueil ou de rubrique
  stable, et l'application le teste depuis le PC de l'utilisateur
  (« Vérifier les liens ») ; un lien en erreur est masqué ;
- l'exercice associé porte sur la méthode, jamais sur le contenu d'une vidéo
  précise (qui peut changer) ; chaque question a sa correction.

Format d'une fiche :

    ## VID-B2-001 | Catégorie | Source | durée
    TITRE: …
    URL: https://…
    DESCRIPTION: …
    CONSEIL: …
    Q: question
    + bonne réponse | explication
    - mauvaise réponse | explication   (×3)
