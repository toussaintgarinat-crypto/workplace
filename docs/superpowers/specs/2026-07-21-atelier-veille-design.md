# Design — Atelier Veille (front-end de la famille `veille`)

**Date** : 2026-07-21
**Statut** : validé, prêt pour plan d'implémentation

## Contexte

La famille de manifest `veille` (🔭, cf. `docs/superpowers/plans/2026-07-21-veille-famille-geo-retag.md`)
regroupe aujourd'hui deux briques backend séparées :
- `geo` (6110) : a déjà un front (`front.html`, carte Leaflet), embarqué en iframe dans le
  dashboard du Cœur (onglet dédié `vue-geo`, motif `switchVue`).
- `veille-info` (6120) : **aucun front** — sources RSS, digests (texte + audio) sont
  aujourd'hui strictement pilotables par API ou par l'assistant (capacités manifest).

L'utilisateur veut une troisième brique, **`atelier-veille`**, qui donne un vrai front à
`veille-info` et regroupe carte + RSS + digests dans un seul espace de travail — sur le
modèle exact de l'atelier Studio (6060) : une brique quasi uniquement front, qui compose
d'autres briques par HTTP sans dupliquer leur code, et qui apparaît comme une **tuile du hub
« Atelier » du dashboard** (le même hub où vivent déjà Studio, Personnages, Synopsis, Voix,
Mémoire — motif `ouvrirCreation` / `creation-iframe`).

Décisions actées en amont (brainstorming) :
- Une seule page unifiée (pas un hub qui renvoie vers geo et veille-info séparément).
- Backend d'atelier qui compose geo + veille-info (pas d'appels directs navigateur → geo/
  veille-info), sur le modèle de Studio composant voix/images/video/personnages.
- Carte : réutilisation de l'iframe existante vers le front de `geo`, zéro duplication.
- veille-info : gestion complète depuis l'atelier (sources RSS + lecture digests/audio +
  génération manuelle), pas seulement lecture seule.
- Zéro modification du code backend de `geo` et `veille-info`.

## État constaté du code (vérifié, pas supposé)

- `briques/veille-info/main.py` expose déjà tout ce dont l'atelier a besoin :
  `GET/POST /sources`, `DELETE /sources/{id}`, `GET /digests`, `GET /digests/{id}`,
  `POST /digest/executer` (gate `verifier_cle_horloge`, traite TOUTES les personnes d'un
  coup — c'est la route que le bouton « générer maintenant » de l'atelier appellera).
  `CreerSource` = `{nom: str, url: str}`.
- `GET /digests` et `GET /digests/{id}` renvoient déjà `audio_url`/`audio_duree` (LEFT JOIN
  sur `digest_audio`, palier audio du 2026-07-21) — `null`/`null` si pas encore généré.
- `briques/voix/main.py:257` construit `audio_url` depuis `VOIX_PUBLIC_URL` (ou
  `request.base_url` en repli) : **c'est déjà une URL directement jouable par le
  navigateur**, exactement comme `briques/studio/front.html:486`
  (`<audio controls src="${esc(ep.audio_url)}">`) l'utilise telle quelle. Aucun proxy audio
  à écrire côté atelier.
- `core/urls_ui.py` : table `BRIQUES_UI` = `{NOM: (port, chemin_spa)}`, résolue par
  `url_brique()` (scheme + host de la requête courante, gère LAN/mesh). Studio/Personnages/
  Transcription sont servis sous `/atelier` (`_FRONT = Path(__file__).parent / "front.html"`,
  `@app.get("/atelier", response_class=HTMLResponse)` dans `briques/studio/main.py:131-135`).
- `core/routers/dashboard.py` (~ligne 744-780) : le hub « Atelier » (section Créations) est
  une grille de `<button class="creation-tuile" onclick="ouvrirCreation('__X_UI_URL__',
  'Titre')">`, qui charge l'URL dans `#creation-iframe` en plein écran (fonction
  `ouvrirCreation`, ligne ~1437). C'est le motif exact à reproduire pour `atelier-veille`,
  **distinct** de l'onglet `vue-geo` existant (qui reste inchangé — carte accessible aussi
  via son propre onglet historique).
- `core/outils_communs.py:51` : `BRIQUES_PAR_PERSONNE` — les briques listées reçoivent
  l'identité de la personne connectée en `X-User-Id`, gagée par `{BRIQUE}_KEY`. `veille-info`
  y est déjà. `_entetes_brique()` normalise tiret→underscore pour le nom de variable d'env
  (`veille-info` → `VEILLE_INFO_KEY`, `atelier-veille` → `ATELIER_VEILLE_KEY`).
- Ports occupés : jusqu'à 6120 (`veille-info`). **6130 est libre.**

## Architecture

Nouvelle brique `briques/atelier-veille/` (port **6130**), calquée sur `briques/studio/` :
- `main.py` (FastAPI) : sert `front.html` sous `/atelier` (même convention que Studio), une
  poignée d'endpoints de **composition pure** vers `veille-info` (aucune logique métier
  propre, aucun état stocké côté atelier), et `/sante`.
- `front.html` : une page unique, onglets internes **Carte / Sources / Digests** (voir plus
  bas), design system partagé `shared/static/workplace.css` (comme Studio).
- `Dockerfile` + `docker-compose.yml` calqués sur ceux de Studio : image taguée (pas de
  `:latest`), `extra_hosts: host.docker.internal:host-gateway` (piège fleet-wide déjà
  documenté — ne pas l'oublier dès la version 1), healthcheck `/sante`.
- `manifest.json` : `"nom": "atelier-veille"`, `"famille": "veille"`, `"couche": "frontend"`,
  `"port": 6130`, `"url_ui": "http://localhost:6130/atelier"`, `"depends_on": []` (soft —
  repli honnête si `geo`/`veille-info` injoignables, jamais bloquant au démarrage).
  Pas de nouvelle capacité assistant (l'atelier est une SURFACE humaine, pas un outil LLM) ;
  `offre: ["front_atelier_veille"]` pour cohérence avec le motif `offre` des autres manifests.

### Endpoints de composition (`main.py`)

Tous préfixés `/veille/*`, tous `async def` avec `httpx.AsyncClient`, motif identique à
`briques/studio/main.py:1010-1028` (try/except → `HTTPException(502, ...)` avec message
explicite si la brique composée est injoignable — jamais un 500 nu) :

| Méthode | Chemin atelier | Proxifie vers veille-info |
|---|---|---|
| GET | `/veille/sources` | `GET /sources` |
| POST | `/veille/sources` | `POST /sources` |
| DELETE | `/veille/sources/{id}` | `DELETE /sources/{id}` |
| GET | `/veille/digests` | `GET /digests` |
| POST | `/veille/digest/executer` | `POST /digest/executer` |

Chaque appel transmet les en-têtes reçus par l'atelier (motif *pass-through pur*, voir
Identité ci-dessous) — l'atelier ne décide jamais lui-même de l'identité, il relaie
seulement ce que le Cœur lui a transmis.

Pas d'endpoint dédié pour la carte : la section Carte du front charge directement
l'iframe existante de `geo` (même `url_ui` que celle déjà utilisée par `vue-geo` dans le
dashboard), aucun hop serveur.

### `front.html` — trois onglets

1. **Carte** : `<iframe>` pointant vers l'URL de `geo` (résolue côté serveur par le Cœur au
   moment du rendu du dashboard — voir Intégration dashboard ; en accès direct au port 6130,
   l'atelier construit l'URL geo lui-même via une variable d'env `GEO_URL` publique, motif
   `IMAGES_PUBLIC_URL`/`VIDEO_PUBLIC_URL` de Studio).
2. **Sources** : liste des sources RSS (`GET /veille/sources`), formulaire ajout
   (nom + URL), bouton suppression par ligne.
3. **Digests** : liste des digests (date, texte résumé, `<audio src>` si `audio_url` non
   null, sinon mention discrète « pas encore de version audio »), bouton « Générer le
   digest maintenant » (`POST /veille/digest/executer`) avec état de chargement.

## Intégration dashboard

- `core/urls_ui.py` : ajout `"ATELIER_VEILLE": (6130, "/atelier")` dans `BRIQUES_UI`.
- `core/routers/dashboard.py` :
  - une nouvelle tuile dans la grille du hub Atelier, à côté de Studio/Personnages/
    Synopsis/Voix/Mémoire : `<button class="creation-tuile"
    onclick="ouvrirCreation('__ATELIER_VEILLE_UI_URL__', 'Veille')">` (emoji 🔭, cohérent
    avec la famille).
  - `.replace("__ATELIER_VEILLE_UI_URL__", u("ATELIER_VEILLE"))` dans le rendu HTML.
  - **L'onglet `vue-geo` existant reste inchangé** (pas de suppression, pas de fusion) —
    l'atelier est un point d'entrée ADDITIONNEL, pas un remplacement.
- `core/outils_communs.py` : ajout `"atelier-veille"` à `BRIQUES_PAR_PERSONNE`, pour que le
  Cœur lui transmette l'identité de la personne connectée (même motif que `veille-info`) —
  nécessaire pour que l'atelier puisse la relayer à son tour à `veille-info`.

## Identité / auth

`atelier-veille` ne prend AUCUNE décision d'identité elle-même : elle relaie tels quels les
en-têtes que le Cœur lui a transmis (`X-Compte-Id`, `X-API-Key` si `ATELIER_VEILLE_KEY` est
posée) vers `veille-info`. Cohérent avec la réalité actuelle du parc (aucune
`{BRIQUE}_KEY` n'est configurée nulle part aujourd'hui, mono-tenant `public` de facto) — le
jour où le foyer active les clés de service fleet-wide, l'atelier suit sans modification.

## Erreurs / dégradation

- `veille-info` injoignable : chaque endpoint de composition renvoie une erreur explicite
  (502 avec message), le front affiche un bandeau « veille-info injoignable » au lieu de
  planter la page — les onglets Sources/Digests dégradent proprement, l'onglet Carte
  (indépendant, iframe directe) continue de fonctionner.
- `geo` injoignable : l'iframe Carte affiche l'erreur native du navigateur (comportement
  déjà celui de l'onglet `vue-geo` existant, rien de nouveau à gérer côté atelier).
- Aucun état n'est stocké côté `atelier-veille` : un redémarrage du conteneur ne perd rien
  (tout vit dans `veille-info`/`geo`).

## Tests

- `test_manifest.py` : format du manifest, capacité `offre` cohérente (mirroring des tests
  manifest existants des autres briques).
- `test_front.py` : `/atelier` sert bien le HTML, contient les trois sections attendues
  (mirroring `briques/studio/test_front.py`).
- `test_composition.py` : chaque endpoint `/veille/*` avec `httpx` mocké (aucun réseau réel) :
  cas nominal (proxy réussi, JSON transmis tel quel) + cas `veille-info` injoignable (502
  explicite, pas de 500 nu).

## Hors périmètre (explicitement)

- Toute modification du code backend de `geo` ou `veille-info`.
- Authentification/autorisation nouvelle : l'atelier suit le motif `{BRIQUE}_KEY` existant,
  ne l'active pas lui-même (cohérent avec l'état actuel du parc, aucune clé posée nulle
  part).
- Reconstruction native de la carte (iframe réutilisée telle quelle, décision actée).
- Sous-brique « prospection géo-scrapée » : spec séparé, à venir juste après celui-ci.
