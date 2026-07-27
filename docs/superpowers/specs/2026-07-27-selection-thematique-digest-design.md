# Sélection de la thématique lors de la création d'un digest (veille-info / atelier-veille)

## Contexte

L'onglet Digests de l'atelier-veille expose un unique bouton « Générer le digest maintenant
(pour tout le foyer) », qui déclenche `POST /digest/executer` sans paramètre. Ce point
d'entrée traite systématiquement **toutes les thématiques actives, pour tous les
utilisateurs du foyer** — aucune sélection possible.

Le système de pause par thématique (S199, `PATCH /thematiques/pause`) permet d'exclure une
thématique de **tous** les digests futurs de façon persistante, mais ne permet pas de
générer **ponctuellement** un digest sur une thématique précise.

Objectif : ajouter, à côté du bouton existant (conservé tel quel), la possibilité de
déclencher un digest pour **une seule thématique choisie**, y compris si elle est
actuellement en pause.

## Non-objectifs

- Pas de sélection multiple (plusieurs thématiques à la fois) — un menu déroulant, un choix.
- Pas de restriction par utilisateur : le périmètre reste le foyer entier, comme aujourd'hui,
  simplement filtré sur la thématique choisie (pas de scoping par tenant sur cette route).
- Pas de changement à la règle « 1 digest par thématique et par jour » (idempotence
  inchangée : si un digest existe déjà aujourd'hui pour cette thématique, rien n'est
  régénéré).
- Pas d'exposition de cette capacité à l'assistant/LLM (reste une action 100% humaine, comme
  la pause).

## Backend — `briques/veille-info`

### `stockage.py`

Deux nouvelles fonctions, symétriques de celles utilisées par le fetch/comptage actuel mais
qui **ignorent l'état `enabled`** (nécessaire pour forcer une thématique en pause) :

```python
def lister_sources_thematique(user_id: str, thematique: str) -> list[dict]:
    """Sources d'une thématique donnée pour cet utilisateur, actives OU en pause — utilisé
    pour forcer le fetch d'une thématique explicitement choisie (génération ponctuelle),
    contrairement à lister_sources(actives_seulement=True) qui ne verrait rien si toutes les
    sources de la thématique sont en pause."""

def lister_user_ids_thematique(thematique: str) -> list[str]:
    """Utilisateurs ayant au moins une source (active ou en pause) dans cette thématique.
    Contrairement à lister_user_ids_actifs(), n'exclut pas quelqu'un dont la seule
    thématique concernée est en pause."""
```

### `digest.py`

`_traiter_utilisateur` et `executer_digest_quotidien` gagnent un paramètre optionnel
`thematique: str | None = None`, propagé jusqu'à `_traiter_utilisateur_sans_planter`.

Quand `thematique` est fourni :
- la liste de thématiques à traiter devient `[thematique]` au lieu de
  `stockage.thematiques_actives(user_id)`
- le fetch RSS itère `stockage.lister_sources_thematique(user_id, thematique)` au lieu de
  `stockage.lister_sources(user_id, actives_seulement=True)`
- `executer_digest_quotidien` calcule ses cibles via
  `stockage.lister_user_ids_thematique(thematique)` au lieu de
  `stockage.lister_user_ids_actifs()` (sauf si `user_ids` est fourni explicitement, chemin
  déjà réservé aux tests)

Le reste du pipeline (vérification `digest_existe`, `articles_non_digestes`, appel LLM,
insertion du digest, audio best-effort, mémoire best-effort) est **strictement inchangé** —
ces fonctions acceptent déjà un paramètre `thematique` (S199). Si la thématique demandée est
inconnue (aucune source ne la porte), `lister_user_ids_thematique` renvoie une liste vide :
0 utilisateur traité, 0 digest créé, aucune erreur levée (cohérent avec le style
best-effort du reste du module).

Sans `thematique` (valeur par défaut `None`), le comportement actuel est identique
bit-à-bit : c'est un paramètre additif, pas une réécriture du chemin existant.

### `main.py`

```python
class ExecuterDigestBody(BaseModel):
    thematique: str | None = None

@app.post("/digest/executer", tags=["digest"])
def executer_digest_route(body: ExecuterDigestBody | None = None,
                          _: None = Depends(verifier_cle_horloge)):
    return digest.executer_digest_quotidien(thematique=body.thematique if body else None)
```

Corps optionnel : l'appel actuel de l'horloge (`core/horloge.py`, aucun corps envoyé) continue
de fonctionner sans modification.

## Backend — `briques/atelier-veille` (proxy)

```python
class ExecuterDigest(BaseModel):
    thematique: str | None = None

@app.post("/veille/digest/executer", tags=["veille"])
async def executer_digest(body: ExecuterDigest | None = None):
    ...
    r = await c.post(f"{VEILLE_INFO_URL}/digest/executer", headers=entetes,
                     json=body.model_dump() if body else None)
```

Le jeton `VEILLE_INFO_KEY` continue d'être injecté côté serveur, jamais exposé au
navigateur — inchangé.

## Frontend — `briques/atelier-veille/front.html` (onglet Digests)

Le bouton existant « Générer le digest maintenant (pour tout le foyer) » est conservé sans
aucune modification de comportement. À côté :

```
Générer pour une thématique précise :
[ Tech (en pause) ▾ ]  [ Générer pour cette thématique ]
```

- `<select id="selectThematiqueDigest">`, peuplé via `GET /veille/thematiques` (endpoint déjà
  utilisé par `chargerSources()` dans l'onglet Sources RSS). Options : `thematique || 'Général'`,
  suffixées `" (en pause)"` si `en_pause === true` — la thématique en pause reste
  sélectionnable (fetch forcé côté backend, cf. ci-dessus).
- Chargement lors de l'affichage de l'onglet Digests, fonction `chargerThematiquesDigest()`.
- Si aucune thématique n'existe encore (aucune source ajoutée) : select désactivé, option
  unique « Aucune thématique — ajoute une source dans Sources RSS ».
- Bouton → `genererDigestThematique()` : `POST /veille/digest/executer` avec
  `{thematique: valeurChoisie}`. Affichage du résultat dans le même style que le bouton
  existant : nombre de digests créés, ou message neutre si 0 (« déjà généré aujourd'hui ou
  aucun nouvel article »).

## Tests

Backend (`briques/veille-info/test_digest.py`, `test_stockage.py`, `test_main.py`) :
- `lister_sources_thematique` / `lister_user_ids_thematique` renvoient les sources/utilisateurs
  même quand `enabled=0` sur toutes les sources concernées.
- `executer_digest_quotidien(thematique="tech")` ne traite que les utilisateurs ayant la
  thématique `"tech"`, ignore les autres thématiques de ces mêmes utilisateurs.
- Génération forcée sur une thématique 100% en pause : le fetch RSS est bien déclenché
  (mock RSS appelé), un digest est créé s'il y a des articles.
- Idempotence : si `digest_existe(user_id, thematique="tech")` est déjà vrai aujourd'hui,
  aucun appel LLM, `digests_crees == 0`.
- Thématique inconnue : `executer_digest_quotidien(thematique="inexistante")` renvoie
  `{"utilisateurs_traites": 0, "digests_crees": 0}` sans lever d'exception.
- `POST /digest/executer` avec et sans corps (rétrocompatibilité horloge).

Frontend/proxy (`briques/atelier-veille/test_main.py`) :
- `POST /veille/digest/executer` relaie correctement le corps `{"thematique": ...}` vers
  veille-info, avec le jeton service en en-tête.
- `POST /veille/digest/executer` sans corps continue de fonctionner (rétrocompatibilité).
