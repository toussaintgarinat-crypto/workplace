# Décision — Le contrat manifeste ↔ route est vérifié par un test, et le manifeste dit vrai

- **Date** : 2026-07-28
- **Statut** : ✅ Adopté (S210)
- **Portée** : les 39 `briques/*/manifest.json` et leur route FastAPI ; le catalogue du Cœur
  (`core/catalogue.py`, `core/outils.py`, `core/outils_communs.py`)
- **Fichiers liés** : `tests/test_contrat_capacites.py`, `briques/connexion/manifest.json`,
  `briques/donnees/manifest.json`, `briques/etl/manifest.json`,
  `briques/generateur/manifest.json`, `briques/personnages/manifest.json`,
  `briques/transcription/manifest.json`

> **But de ce document** : consigner *pourquoi* le manifeste est désormais tenu de décrire la
> vraie route, *comment* on tranche quand les deux divergent, et *ce qu'on renonce* à vérifier.

---

## En bref (l'état retenu)

- Un test paramétré sur les 242 capacités du parc **importe la brique** et lit la signature
  FastAPI réelle (dépendances, modèle Pydantic du corps). Trois règles :
  1. le couple `methode` + `chemin` doit correspondre à une route existante ;
  2. tout `param` déclaré doit être accepté par cette route ;
  3. tout champ **requis** par la route doit figurer dans `params`.
- Onze capacités étaient en écart. **Quatre étaient mortes** : `connexion_envoyer` (422 à
  chaque envoi), `donnees_modifier` et `donnees_supprimer` (404, un segment d'URL manquant),
  `transcription_fichier` (endpoint multipart, inatteignable par l'assistant).
- Sauf raison contraire, **c'est le manifeste qui s'aligne sur le code**, pas l'inverse.

## Pourquoi c'est un vrai risque, pas de l'hygiène

`core/outils_communs.py::_appel_dynamique` construit l'appel **à partir du manifeste** : il
substitue les `{placeholders}` du `chemin`, puis envoie le reste en corps JSON (en query pour
un GET). Le manifeste n'est donc pas de la documentation, c'est **le code d'appel**. Deux
conséquences, dont la seconde est la pire :

- un champ requis absent des `params` n'est **jamais rempli** par le LLM → 422 systématique.
  La capacité est morte, mais visible : l'assistant la propose, elle échoue.
- un `param` que la route n'accepte pas est **ignoré en silence** — FastAPI jette les query
  params inconnus sans erreur, Pydantic ignore les clés en trop d'un corps. L'assistant croit
  filtrer, classer, renommer ; la brique répond 200 et n'en tient aucun compte. Aucun log,
  aucune alerte : c'est le défaut le plus cher à trouver, et il n'était détecté par rien.

`tests/test_briques_smoke.py` ne vérifiait que la présence d'un `nom` par capacité.

## Comment on tranche quand manifeste et code divergent

Le manifeste s'aligne sur le code **par défaut** : le code est exécuté, testé, appelé par
d'autres briques ; le manifeste ne l'est pas. Renommer un champ de modèle pour faire plaisir
au manifeste déplace le risque là où il coûte le plus.

Deux exceptions, à motiver capacité par capacité :

- **le vocabulaire de la brique prime sur celui du manifeste.** `connexion_envoyer` annonçait
  `destinataire`/`message` là où le modèle `Envoi` exige `id_externe`/`texte`. On a gardé
  `id_externe` : c'est le mot employé par `correspondance.py`, `adaptateurs.py` et le modèle
  `Liaison`. Un second nom pour la même chose aurait coûté plus cher que la gêne de lecture —
  laquelle se règle dans la `description` du param, que le LLM lit aussi.
- **une capacité que l'assistant ne peut pas appeler n'est pas une capacité.**
  `transcription_fichier` pointait sur `POST /transcrire`, qui attend un `UploadFile`
  multipart : `_appel_dynamique` n'envoie que du JSON. Elle a été **retirée** du manifeste
  (l'endpoint reste, il sert le front de la brique) et `transcription_depuis_url` dit
  désormais qu'elle est la seule porte d'entrée en conversation.

Corollaire : quand une capacité recouvrait **deux** routes (`personnage_fiche_modifier`
promettait le renommage *et* le rangement, qui vit sur `PATCH /fiches/{fid}/categorie`), on la
réduit à la route qu'elle appelle vraiment plutôt que d'élargir la route.

## Ce qu'on renonce à vérifier, et pourquoi

- **Les corps `dict` libres** (`corps: dict = Body(...)`, motif des proxys de `forge`
  vers son core) n'exposent aucun schéma introspectable : leurs clés sont lues dans le corps
  de la fonction, parfois par boucle sur une constante. Le test les **saute explicitement**
  (`skip`, pas un silence) au lieu de deviner : une lecture par AST des `corps.get("x")`
  produisait des faux positifs sur `forge_crm_creer` et
  `personnage_distribution_perso_modifier`, qui sont corrects. Les champs requis hors-corps
  y restent vérifiés.
- **Les briques dont une dépendance manque à l'environnement** (`ecoute` → numpy,
  `export` → markdown) sont sautées avec le nom du module absent. Elles restent couvertes
  dans leur conteneur (`scripts/tests_briques.sh`).
- **Le nom des paramètres de chemin côté code** est ignoré à dessein : le Cœur substitue les
  placeholders du manifeste par position. Que la route nomme `{did}` ce que le manifeste
  appelle `{id}` est sans effet — seuls les placeholders **déclarés** doivent figurer dans
  `params`, et ça, c'est vérifié.

## Ce qui devra faire rouvrir ce document

- Si un jour une brique non-Python (ou non-FastAPI) porte des capacités : le test ne saura pas
  l'introspecter. La règle est alors une **exemption nommée avec son motif écrit**, jamais une
  omission silencieuse. Aujourd'hui il n'y en a aucune — `agenda`, dont les routes vivent dans
  `backend/routers/`, est bien couverte (17 capacités).
- Si les corps `dict` libres se multiplient, la zone non vérifiée grandit sans qu'on le voie.
  Le remède serait de typer ces proxys avec un modèle Pydantic, pas de rendre le test devin.
- Si le Cœur cesse d'envoyer les arguments en corps **et** en query pour les non-GET
  (comportement actuel de `_appel_dynamique`), la règle 2 devra distinguer les deux.
