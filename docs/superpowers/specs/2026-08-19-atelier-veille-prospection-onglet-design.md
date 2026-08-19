# Onglet « Prospection » dans atelier-veille

## Contexte

La famille `veille` a 4 sous-briques : `geo` (carte, zones, enrichissement), `veille-info`
(RSS→digest), `veille-prospection` (S193 : campagnes zone→enrichissement→CRM) et
`atelier-veille` (front unique, port 6130, 3 onglets : Digests / Sources RSS / Carte).

`veille-prospection` n'a **aucune UI** : ses seules capacités sont exposées à l'assistant
(`veille_prospection_campagnes_lister/creer/supprimer`) ou en API directe. Piloter une
campagne (l'activer, voir ce qu'elle a trouvé, démarcher) n'est possible qu'en parlant à
l'assistant — l'utilisateur veut pouvoir le faire **manuellement, depuis un onglet dédié**,
comme les 3 autres sous-briques de la famille.

Contrainte technique découverte en amont : `veille-prospection` ne sait exécuter qu'un
passage horloge **global** (`POST /campagnes/executer`, jeton `VEILLE_PROSPECTION_KEY`,
traite toutes les personnes) — aucune route ne permet de lancer **une seule campagne, tout
de suite**. Autre contrainte : les leads du CRM Forge n'ont pas de colonne
zone_id/campagne_id (schéma du monolithe `forge/core`, hors périmètre) — seul le texte libre
`notes` porte des indices (NAF, commune).

## Non-objectifs

- Pas de modification du schéma CRM de Forge (`briques/forge/forge/core/`) — le filtrage
  par campagne se fait par texte (`notes`), pas par une vraie clé étrangère.
- Pas d'envoi automatique d'email — `mail_demarchage_preparer` reste un point d'arrêt humain
  (brouillons uniquement), inchangé.
- Pas de vue CRM générale (pipeline, valeur totale, etc.) dans cet onglet — seulement les
  prospects rattachables à une campagne de prospection. Le CRM complet reste dans Forge.
- Pas de campagnes b2c (logement) traitées différemment dans l'UI — le formulaire de
  création propose juste le choix b2b/b2c déjà supporté par le backend, sans logique
  supplémentaire.
- Pas de vraie authentification par personne pour cet onglet — même mode « pass-through »
  que les 3 onglets existants (identité inerte tant que les clés de service fleet-wide ne
  sont pas activées, cf. limite déjà documentée d'`atelier-veille`).

## Backend — `briques/veille-prospection`

### `stockage.py`

- Nouvelle colonne `zone_nom TEXT` sur `campagnes` (migration additive, même motif que la
  colonne `type` existante : `ALTER TABLE ... ADD COLUMN`, `try/except OperationalError`
  dans `init()`).
- `creer_campagne(user_id, zone_id, type_, zone_nom=None)` : stocke `zone_nom` tel que fourni
  par l'appelant (calculé côté route, pas ici — cf. `main.py`).
- `_campagne_dict` : ajoute `"zone_nom": r["zone_nom"]`.
- Nouvelle fonction `lire_campagne(user_id, campagne_id) -> dict | None` (campagne active
  ou non, scopée au tenant) — utilisée par la nouvelle route d'exécution manuelle.
- `lister_executions(campagne_id, limite=20)` existe déjà mais n'est appelée par aucune
  route : reste inchangée, sera enfin exposée (cf. `main.py`).

### `orchestration.py`

- `_appeler_forge(prospects, zone_nom=None)` : si `zone_nom` est fourni, ajoute
  `f"Zone : {zone_nom}"` aux `notes` de chaque prospect avant l'appel à
  `POST /crm/import-lot` (les notes existantes du prospect, si présentes, sont conservées —
  simple concaténation, motif déjà utilisé côté Forge pour composer les notes par segments).
- `_executer_campagne(campagne)` : passe `campagne.get("zone_nom")` à `_appeler_forge`.
- Nouvelle fonction `executer_campagne_unique(campagne: dict) -> dict` : factorise le corps
  actuel de `_executer_campagne_sans_planter` mais **retourne le résultat** au lieu de
  seulement persister + renvoyer un booléen (nécessaire pour qu'un appel manuel voie le
  résultat immédiatement). `_executer_campagne_sans_planter` est réécrite pour appeler cette
  fonction et ignorer sa valeur de retour côté horloge (comportement horloge inchangé).

### `main.py`

- `creer_campagne_route` : après validation du type, résout le nom de la zone via
  `orchestration.lire_zone_geo(body.zone_id)` (déjà appelée par `avertissement_type_zone` —
  réutiliser le même résultat pour ne pas doubler l'appel réseau) et le passe à
  `stockage.creer_campagne(..., zone_nom=...)`. Si `geo` est injoignable ou la zone
  introuvable : `zone_nom=None`, pas d'erreur (best-effort, cohérent avec
  `avertissement_type_zone`).
- Nouvelle route `POST /campagnes/{campagne_id}/executer`, scopée au **tenant** (dépend de
  `tenant_actuel`, pas `verifier_cle_horloge`) :
  ```python
  @app.post("/campagnes/{campagne_id}/executer", tags=["campagnes"])
  def executer_campagne_route(campagne_id: int, tenant: str = Depends(tenant_actuel)):
      campagne = stockage.lire_campagne(tenant, campagne_id)
      if not campagne or not campagne["actif"]:
          raise HTTPException(404, "Campagne introuvable ou inactive.")
      resultat = orchestration.executer_campagne_unique(campagne)
      stockage.inserer_execution(campagne_id, **resultat)
      stockage.maj_derniere_execution(campagne_id)
      return resultat
  ```
  Synchrone, peut prendre jusqu'à ~180s (timeout de l'appel `geo` sous-jacent) — assumé,
  cohérent avec la nature « lot borné, lectures web réelles » déjà documentée.
- Nouvelle route `GET /campagnes/{campagne_id}/executions` (scopée tenant, 404 si la
  campagne n'appartient pas à l'appelant) : expose enfin `stockage.lister_executions`.

## Backend — `briques/atelier-veille` (composition, proxy pur)

Même motif exact que les routes `/veille/*` existantes (`_entetes_aval`, gestion d'erreur
502 uniforme, timeouts par appel). Nouvelles variables d'env (même style que
`VEILLE_INFO_URL` — défauts `host.docker.internal`, clés service via `.env` racine par
`env_file`, jamais codées dans `environment:`) : `VEILLE_PROSPECTION_URL` (6140),
`GEO_URL` (6110, **serveur→serveur**, distinct de `GEO_PUBLIC_URL` déjà utilisé pour
l'iframe de la Carte), `FORGE_URL` (5700), `MAIL_URL` (6030).

```python
@app.get("/prospection/campagnes", tags=["prospection"])
async def lister_campagnes(...): ...   # → GET veille-prospection /campagnes

@app.post("/prospection/campagnes", tags=["prospection"])
async def creer_campagne(...): ...     # → POST veille-prospection /campagnes

@app.delete("/prospection/campagnes/{id}", tags=["prospection"])
async def supprimer_campagne(...): ... # → DELETE veille-prospection /campagnes/{id}

@app.post("/prospection/campagnes/{id}/executer", tags=["prospection"])
async def executer_campagne(...): ...  # → POST veille-prospection /campagnes/{id}/executer
                                        #   timeout httpx élevé (200s) — appel lent assumé

@app.get("/prospection/zones", tags=["prospection"])
async def lister_zones_geo(...): ...   # → GET geo /zones (peuple le <select> de création)
```

### `GET /prospection/prospects?campagne_id=`

Appelle `GET forge /crm` (liste complète, pas de filtre serveur possible), puis **filtre en
Python** les leads dont `notes` contient `f"Zone : {zone_nom}"` de la campagne demandée
(zone_nom lu via `GET veille-prospection /campagnes`, mise en correspondance par
`campagne_id`). Limite assumée et documentée dans le docstring : si deux campagnes
référencent des zones de même nom, ou si une zone a été renommée après la création de la
campagne, le filtrage peut être imprécis — acceptable pour un usage manuel supervisé, pas
pour une isolation stricte.

```python
@app.get("/prospection/prospects", tags=["prospection"])
async def prospects_campagne(campagne_id: int, x_user_id, x_api_key):
    campagnes = await _get_json(f"{VEILLE_PROSPECTION_URL}/campagnes", entetes)
    campagne = next((c for c in campagnes if c["id"] == campagne_id), None)
    if not campagne:
        raise HTTPException(404, "Campagne introuvable.")
    zone_nom = campagne.get("zone_nom")
    crm = await _get_json(f"{FORGE_URL}/crm", entetes_forge)
    prospects = crm["prospects"]
    if zone_nom:
        prospects = [p for p in prospects if zone_nom in (p.get("notes") or "")]
    return {"campagne_id": campagne_id, "zone_nom": zone_nom, "prospects": prospects}
```

### `POST /prospection/demarchage`

Proxy vers `mail POST /demarchage/preparer`. Le corps `{expediteur, sujet, message,
prospect_ids: [...]}` envoyé par le front est enrichi côté backend : pour chaque
`prospect_id`, la ville est extraite au mieux depuis `notes` par une regex
`r"Commune : ([^·]+)"` (miroir exact du format écrit par
`briques/forge/main.py::_prospect_vers_lead`), défaut `""` si absente — cohérent avec
`mail::_personnaliser` qui traite déjà `ville` manquante comme une chaîne vide, pas une
erreur. Best-effort documenté : un changement de format de notes côté Forge casserait cette
extraction silencieusement (regex, pas un contrat), acceptable car non bloquant (le
placeholder `{ville}` reste juste vide).

## Frontend — `briques/atelier-veille/front.html`

4ᵉ onglet « Prospection » (`<button id="btn-prospection">`), même style CSS que les 3
existants.

**Section campagnes** :
- Liste des campagnes actives : zone (nom), type (b2b/b2c), dernière exécution (date
  relative ou « jamais »), bouton **Lancer maintenant** (désactivé + spinner pendant
  l'appel), bouton **Désactiver**.
- Formulaire de création : `<select>` peuplé par `GET /prospection/zones`, `<select>`
  type b2b/b2c, bouton **Créer la campagne**. Si `avertissement` renvoyé par le backend
  (zone/type incohérents), affiché en warning inline — n'empêche pas la création.

**Section prospects** (repliable par campagne, chargée à l'ouverture) :
- Appelle `GET /prospection/prospects?campagne_id=` après un « Lancer maintenant » réussi,
  ou à la demande (bouton « Voir les prospects »).
- Tableau nom / entreprise / email / statut, case à cocher par ligne (uniquement les lignes
  avec email — les autres affichées grisées, non sélectionnables, avec l'info "pas d'email
  trouvé" pour rester honnête plutôt que de les cacher).

**Section démarchage** (visible dès qu'au moins un prospect est coché, toutes campagnes
confondues) :
- Champs : expéditeur (texte libre, obligatoire — rappel LCEN inline reprenant le message
  d'erreur de `mail`), sujet, message (textarea, rappel des variables `{nom}` `{entreprise}`
  `{ville}` sous le champ).
- Bouton **Préparer les brouillons** → `POST /prospection/demarchage`. Affiche le résumé
  renvoyé (préparés / ignorés par motif : sans email, désinscrit, cadence atteinte, trop
  récent) — jamais de bouton d'envoi ici, cohérent avec le garde-fou existant
  (`mail_brouillon_envoyer` reste un geste séparé, hors de cet onglet).

## Tests

**`briques/veille-prospection`** (`test_stockage.py`, `test_orchestration.py`,
`test_main.py`) :
- `creer_campagne` stocke et relit `zone_nom` ; `None` accepté (zone injoignable au moment
  de la création).
- `_appeler_forge` avec `zone_nom` ajoute bien `"Zone : ..."` aux notes sans écraser des
  notes déjà présentes sur le prospect.
- `executer_campagne_unique` renvoie le décompte (trouvés/déjà_connus/nouveaux_crm/erreur),
  ne lève jamais.
- `POST /campagnes/{id}/executer` : 404 sur campagne d'un autre tenant ou inactive ; 200
  avec le décompte sur succès ; n'affecte pas les autres campagnes du tenant (mock `geo`
  appelé une seule fois, avec le bon `zone_id`).
- `GET /campagnes/{id}/executions` : scopé tenant, ordre décroissant, limite respectée.

**`briques/atelier-veille`** (`test_main.py`, `test_composition.py`) :
- Chaque route `/prospection/*` relaie correctement corps + en-têtes vers la brique cible,
  propage un 502 propre si injoignable (motif déjà appliqué aux routes `/veille/*`).
- `GET /prospection/prospects` : filtre bien par `zone_nom` (mock Forge renvoyant des leads
  de deux zones différentes, seule la bonne moitié revient) ; renvoie liste vide sans erreur
  si `zone_nom` est `None` (campagne créée avant la résolution de zone, ou zone jamais
  résolue).
- `POST /prospection/demarchage` : extraction `{ville}` depuis les notes au format Forge
  réel (`"... · Commune : Castres · ..."`) ; absence de "Commune :" → chaîne vide, pas
  d'erreur.

Aucun test n'appelle de vrai réseau (mocks `httpx` sur chaque appel aval, motif déjà en
place dans les deux briques).
