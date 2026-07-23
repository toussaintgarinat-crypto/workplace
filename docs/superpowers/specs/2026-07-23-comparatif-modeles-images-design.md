# Comparatif de modèles d'image dans l'Atelier Images & Vidéo

Date : 2026-07-23

## Contexte

Aujourd'hui, la génération d'image (`briques/images`) passe par un registre de
fournisseurs (`fournisseurs.py`) essayés dans l'ordre de préférence. Sur le HP en
production, seul le fournisseur `gateway` (via la Gateway Workplace → OpenRouter) est
configuré ; les autres (ComfyUI, fal, Replicate, OpenAI direct, Pruna) n'ont pas de
clé/URL et ne servent jamais.

Le modèle utilisé par chaque fournisseur est actuellement figé par une variable d'env
(`IMAGE_GATEWAY_MODEL`, `NANOBANANA_MODEL`, `FAL_MODEL`, …) : il n'y a aucun moyen de le
choisir par requête, ni de savoir a posteriori quel modèle a produit une image (la
réponse ne renvoie que le nom du *fournisseur*, pas du *modèle*).

L'utilisateur veut :
1. Savoir quel modèle est utilisé actuellement (réponse déjà donnée en conversation :
   `google/gemini-2.5-flash-image` via `gateway`, seul fournisseur configuré).
2. Pouvoir choisir/configurer le modèle utilisé au niveau de l'Atelier, pour comparer
   plusieurs modèles sur un même prompt — **en passant uniquement par la Gateway déjà
   configurée** (pas de nouvelles clés API à poser pour fal/Replicate/OpenAI direct).

OpenRouter agrège déjà plusieurs fournisseurs de modèles image (Google Gemini, OpenAI
GPT-Image, …) : router vers un modèle différent via la Gateway suffit donc à obtenir un
vrai comparatif multi-fournisseur, sans toucher aux autres classes de `fournisseurs.py`.

Vérifié en direct (curl sur `https://openrouter.ai/api/v1/models`, endpoint public, pas
de clé requise pour lister) : le champ `architecture.output_modalities` contient
`"image"` pour les modèles capables d'en générer. Au 2026-07-23, 11 entrées matchent,
dont 2 routeurs `openrouter/auto*` à exclure (ils choisissent eux-mêmes le modèle sous
le capot, faussant tout comparatif) :

```
google/gemini-3.1-flash-lite-image
google/gemini-3.1-flash-image
google/gemini-3-pro-image            (prix: 0.000002 $/token image)
google/gemini-3.1-flash-image-preview
google/gemini-3-pro-image-preview
google/gemini-2.5-flash-image        (prix: 0.0000003 $/token image — modèle par défaut actuel)
openai/gpt-5.4-image-2
openai/gpt-5-image-mini
openai/gpt-5-image
```

## Décisions retenues (brainstorming)

- Comparatif **multi-modèles/multi-fournisseurs mais uniquement via la Gateway**
  (aucune nouvelle clé API à configurer).
- Liste de modèles **dynamique** (interrogée en direct sur OpenRouter), pas figée en
  dur — l'utilisateur veut explicitement qu'elle reste à jour.
- UI : cases à cocher (multi-sélection) + tarif indicatif affiché à côté de chaque
  modèle, bouton « Comparer » qui lance tout en parallèle, résultats en grille avec le
  nom du modèle sous chaque image.
- Exclure les entrées `openrouter/auto*` de la liste proposée.
- Pas de nouvel endpoint « batch » côté backend : le comparatif est une orchestration
  **front-end** de l'endpoint `/images/generer` existant (N appels parallèles), pour ne
  pas grossir la surface backend.
- Erreurs indépendantes par modèle (une case en erreur n'empêche pas les autres de
  s'afficher).
- Pas de liste de secours figée si OpenRouter est injoignable : erreur claire + retry,
  cohérent avec « je veux que ça reste à jour » (une liste de secours périmée serait
  trompeuse).

## Architecture

Trois couches, dans le sens du flux existant (même motif que l'existant, pas de
nouvelle brique) :

1. **`briques/images`** (le moteur) : nouvelle capacité de lister dynamiquement les
   modèles image OpenRouter, et d'accepter un `modele` en override par requête pour le
   fournisseur `gateway`.
2. **`briques/atelier-images-video`** (proxy fonctionnel) : relaie le nouvel endpoint de
   liste + le nouveau champ `modele`, sans logique propre.
3. **`front.html`** : nouvel onglet **Comparatif**.

## Composants

### `briques/images/fournisseurs.py`

- `Gateway._requete(prompt, negatif, largeur, hauteur, seed, modele=None)` : le modèle
  effectif devient `modele or os.getenv("IMAGE_GATEWAY_MODEL", "google/gemini-2.5-flash-image")`
  au lieu de toujours lire l'env. Seule la classe `Gateway` a besoin de cet override
  (c'est le seul chemin concerné par le comparatif) ; les autres fournisseurs gardent
  leur unique modèle par env, inchangés (YAGNI — pas de sur-généralisation avant besoin
  réel sur ces fournisseurs, qui ne sont de toute façon pas configurés en prod).
- Nouvelle fonction `modeles_image_openrouter() -> list[dict]` :
  - `GET https://openrouter.ai/api/v1/models` (httpx, timeout court ~10s, **pas** de
    header `Authorization` — endpoint public, confirmé en direct).
  - Filtre : `"image" in (m.get("architecture", {}).get("output_modalities") or [])`
    ET `not m["id"].startswith("openrouter/auto")`.
  - Retourne `[{"id": m["id"], "prix_image": m.get("pricing", {}).get("image")}]`,
    trié par id pour un affichage stable.
  - **Cache mémoire 1h** (module-level : `_cache = {"ts": 0, "modeles": []}`) — pas de
    dépendance externe (Redis, etc.) pour un besoin aussi simple ; si l'appel OpenRouter
    échoue et qu'un cache existe encore (même périmé), on le sert quand même plutôt que
    de casser l'UI (dégradation), mais on ne fabrique JAMAIS de liste par défaut si le
    cache est vide ET l'appel échoue (erreur propagée).

### `briques/images/moteur.py`

- `generer(prompt, negatif, largeur, hauteur, seed=None, fournisseur=None, modele=None)`.
- Le `modele` n'est transmis qu'au fournisseur qui l'accepte (`Gateway.generer` gagne le
  paramètre ; les autres l'ignorent silencieusement — signature commune `**kwargs`
  n'est PAS nécessaire, on ajoute juste le paramètre nommé partout où `generer()` est
  déjà défini, avec valeur par défaut `None`).
- Réponse : ajoute `"modele": modele_utilise` (le modèle réellement utilisé si connu,
  `None` sinon — ex. ComfyUI n'a pas cette notion).

### `briques/images/main.py`

- `Generer` (pydantic) gagne `modele: Optional[str] = None`.
- `POST /generer` transmet `body.modele` à `moteur.generer(...)`.
- Nouvel endpoint `GET /modeles` → `{"modeles": fournisseurs.modeles_image_openrouter()}`.
  Erreurs OpenRouter → HTTP 502 avec message clair (même motif que les autres appels
  externes de la brique).

### `briques/atelier-images-video/main.py`

- `GenererImage` (pydantic) gagne `modele: Optional[str] = None` ; déjà transmis tel
  quel car `body.model_dump()` est générique.
- Nouveau `GET /images/modeles` → relaie `IMAGES_URL/modeles` (même motif exact que
  `GET /images/fournisseurs` déjà présent).

### `briques/atelier-images-video/front.html`

- Nouvel onglet **Comparatif** (4e onglet après Galerie), dans la même structure que
  les onglets existants (`nav.onglets` + `.vue`).
- Contenu :
  - Une `textarea` de prompt dédiée (indépendante de celle d'« Image libre »).
  - Une liste de cases à cocher, une par modèle renvoyé par `GET /images/modeles`,
    label = `id` du modèle + tarif indicatif s'il est connu (`prix_image`), chargée à
    l'ouverture de l'onglet (même motif que `chargerFournisseurs`/`chargerSeries`).
  - Un bouton **Comparer** : pour chaque modèle coché, lance un appel
    `POST /images/generer` avec `{prompt, fournisseur: "gateway", modele: id}`, tous en
    parallèle via `Promise.allSettled` (pas `Promise.all` : un échec ne doit pas annuler
    les autres résultats).
  - Résultats affichés en grille (réutilise les classes CSS `.grille`/`.carte`
    existantes) : une carte par modèle, avec l'image (ou le message d'erreur si l'appel
    a échoué), le nom du modèle en légende, et un bouton « Ajouter à la galerie »
    (réutilise `ajouterGalerie()` existant — titre = `"{prompt tronqué} ({modèle})"`).
  - Si aucune case n'est cochée, message d'erreur simple (pas d'appel lancé).
  - Si `GET /images/modeles` échoue au chargement de l'onglet : message d'erreur clair
    + bouton « Réessayer » — jamais de liste figée en repli.

## Gestion d'erreurs

- Chaque génération du comparatif est indépendante : un modèle qui échoue (timeout,
  erreur OpenRouter, modèle retiré entre-temps) affiche son erreur dans SA carte sans
  affecter les autres.
- Le chargement de la liste de modèles peut échouer (OpenRouter injoignable) : erreur
  affichée, pas de liste de secours périmée.
- Le comportement de repli placeholder honnête existant (`place_holder: true` si le
  moteur échoue) reste inchangé et s'applique aussi dans le comparatif (chaque carte
  peut afficher un placeholder si sa génération individuelle y a recours).

## Tests

- `briques/images/test_fournisseurs.py` :
  - `Gateway._requete` utilise le `modele` passé en argument plutôt que l'env quand il
    est fourni ; retombe sur l'env (puis le défaut `google/gemini-2.5-flash-image`) sinon.
  - `modeles_image_openrouter()` filtre bien sur `output_modalities` contenant `"image"`
    et exclut les ids `openrouter/auto*` (réponse OpenRouter mockée via `respx`/monkeypatch
    du client httpx, cohérent avec les tests existants de la brique).
  - Le cache : deux appels rapprochés ne déclenchent qu'une seule requête HTTP sortante ;
    passé la fenêtre de validité (1h), un nouvel appel est fait.
- `briques/images/test_moteur.py` : `generer(..., modele="x")` propage bien `modele` au
  fournisseur choisi et le restitue dans la réponse (`"modele": "x"`).
- `briques/images/test_api.py` : `POST /generer` avec `modele` dans le corps ; `GET
  /modeles` renvoie bien la structure attendue (mock de la fonction sous-jacente).
- `briques/atelier-images-video/test_images_video.py` (ou fichier équivalent existant) :
  `modele` transmis tel quel dans le relais `/images/generer` ; `GET /images/modeles`
  relaie bien `IMAGES_URL/modeles`.
- `briques/atelier-images-video/test_front.py` : présence du nouvel onglet Comparatif et
  de ses fonctions JS (`chargerModelesComparatif`, `lancerComparatif` ou noms
  équivalents choisis à l'implémentation), sur le même modèle que les tests de
  couverture déjà existants (`test_front_couvre_...`).

## Hors périmètre (YAGNI, explicitement exclu)

- Pas de comparatif pour la vidéo (l'utilisateur n'a demandé que les images).
- Pas d'ajout de clés API pour fal/Replicate/OpenAI direct/Pruna — le comparatif reste
  scopé à ce qui passe par la Gateway déjà configurée.
- Pas de persistance de l'historique des comparatifs au-delà de la galerie existante
  (« Ajouter à la galerie » reste l'unique mécanisme de sauvegarde, déjà en place).
- Pas de nouvel endpoint backend « batch » : orchestration côté front uniquement.
