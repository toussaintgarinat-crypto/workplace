# Atelier Images & Vidéo — design

Statut : **validé avec l'utilisateur le 2026-07-23**.

Origine : les briques `images` (5950) et `video` (5970) existent depuis S51/S52 —
provider-agnostiques, repli placeholder honnête — mais n'ont jamais eu de front dédié.
Leur seul point d'entrée UI aujourd'hui est câblé DANS le Studio (`AtelierPanel.jsx`,
boutons Portrait/Couverture/Animer/Teaser liés à une série précise). Il manque un endroit
pour utiliser ces deux moteurs en génération libre (sans passer par une série Studio), et
pour retrouver les créations passées.

Référence de design regardée avant de figer le périmètre (à la demande de l'utilisateur) :
Kubock (« AI studio for filmmakers », workflow script→génération→montage en 6 étapes,
génération 4-variantes en parallèle), CapCut/Seedream/Seedance (workflow simple
prompt→review→édition, modèle choisi abstrait derrière un nom produit), Flova AI
(bibliothèque de créations passées + « Skills » = presets de prompts réutilisables). Aucun
n'est reproduit tel quel — seules les idées de galerie et de presets ont été retenues,
adaptées à l'infra existante plutôt qu'à une nouvelle plateforme.

## But

Un front unique, **`briques/atelier-images-video/`**, sur le modèle exact de l'Atelier
Veille (`briques/atelier-veille/`) : une brique proxy légère, sans état propre, qui
compose des briques déjà livrées sans dupliquer leur code — ici `images` (5950), `video`
(5970), `studio` (6060) et `memoire` (5600).

## Décisions validées avec l'utilisateur

- **Périmètre** : génération libre (image/vidéo) **+** synergies Studio (portrait,
  couverture, teaser, animer), pas seulement la génération libre.
- **Source des données de synergie** : piochées dans les séries/personnages Studio déjà
  créés (menus déroulants), pas de ressaisie manuelle.
- **Architecture des synergies** : proxy vers les endpoints déjà câblés et étatés du
  Studio (`/series/{id}/personnages/{pid}/portrait`, `.../animer`,
  `/series/{id}/episode/{n}/couverture`, `.../teaser`) — pas d'appel direct
  images/video en parallèle du Studio, pour ne rien dupliquer.
- **Nom + port** : `atelier-images-video`, port **6160** (suite de la numérotation des
  ateliers après `atelier-veille`/6130, `veille-prospection`/6140, `export`/6150).
- **Sélecteur de fournisseur** : liste TOUS les fournisseurs connus de chaque brique
  (`GET /fournisseurs`), avec leur statut configuré/non affiché honnêtement — `gateway`
  inclus normalement, aucune exclusion. Respecte l'ordre par défaut de chaque brique ;
  l'utilisateur peut forcer un choix précis.
- **Sécurité de l'accès aux synergies Studio** : l'atelier est servi/proxié par le Cœur
  (nouveau `core/routers/atelier_images_video_proxy.py`, mirror exact de
  `studio_proxy.py`) — seule la session Cœur (cookie) pose `X-User-Id` de confiance ;
  aucun en-tête d'identité envoyé par le navigateur n'est honoré. Évite de rouvrir le trou
  corrigé en S183 pour Studio.
- **Galerie** : pas de nouveau stockage — réutilise la brique **mémoire** (5600, déjà
  per-personne) comme bibliothèque des créations sauvegardées. Sauvegarde **explicite**
  (bouton « Ajouter à la galerie » après une génération), pas d'auto-save — pour ne pas
  polluer la mémoire avec des essais ratés ou des placeholders.
- **Presets de prompts** : simple confort d'usage, stockage **`localStorage` navigateur**,
  aucun backend dédié.
- **Génération multi-variantes (façon Kubock « Swift »)** : **écarté** — une image/vidéo
  à la fois. Chaque appel a un coût réel chez les fournisseurs hébergés (fal, replicate…) ;
  multiplier par 4 par défaut n'est pas justifié tant qu'un besoin réel ne le demande pas.

## Architecture

Brique HTTP autonome `briques/atelier-images-video/`, port 6160 — même famille que
`atelier-veille` : **surface humaine, `capacites: []`** dans le manifest (ce n'est pas un
outil que l'assistant appelle, c'est une page que l'utilisateur ouvre).

```
Navigateur
   │  (session Cœur, cookie)
   ▼
Cœur  /atelier-images-video-app/*  (core/routers/atelier_images_video_proxy.py)
   │  X-User-Id posé depuis la session (jamais depuis le navigateur)
   ▼
briques/atelier-images-video (6160)
   │                    │                    │
   │ sans auth          │ STUDIO_KEY         │ MEMOIRE_KEY
   │ (stateless)        │ + X-User-Id relayé │ + X-User-Id relayé
   ▼                    ▼                    ▼
images (5950)      studio (6060)        memoire (5600)
video  (5970)
```

## Composants

### `core/routers/atelier_images_video_proxy.py` (nouveau)

Mirror de `core/routers/studio_proxy.py` : sert le front de la brique 6160 sous
`/atelier-images-video-app/*`, monté dans `core/main.py` avec
`Depends(exiger_session)` + `Depends(lire_contexte_tenant)`. Sur chaque appel proxié,
injecte `X-User-Id` via `contexte_tenant.entetes_par_personne()` — c'est la SEULE source
d'identité ; tout en-tête envoyé par le navigateur est ignoré (même garde-fou que S183).

### `briques/atelier-images-video/main.py`

- `GET /`, `GET /atelier`, `GET /workplace.css`, `GET /sante` — mêmes routes que
  `atelier-veille`.
- **Génération libre** (proxy simple, sans auth — comme `studio.py::_appeler_images`
  aujourd'hui, ces briques ne stockent rien par utilisateur) :
  - `POST /images/generer`, `GET /images/fournisseurs` → `IMAGES_URL:5950`
  - `POST /video/generer`, `GET /video/fournisseurs` → `VIDEO_URL:5970`
- **Synergies Studio** (`X-API-Key: STUDIO_KEY` + `X-User-Id` reçu du Cœur et relayé tel
  quel, motif `_entetes_aval` déjà présent dans `atelier-veille/main.py`) :
  - `GET /studio/series` → liste des séries de l'utilisateur
  - `GET /studio/series/{id}/personnages`, `GET /studio/series/{id}/episodes`
  - `POST /studio/series/{id}/personnages/{pid}/portrait`, `.../animer`
  - `POST /studio/series/{id}/episode/{n}/couverture`, `.../teaser`
- **Galerie mémoire** (`X-API-Key: MEMOIRE_KEY` + `X-User-Id` relayé, même motif) :
  - `POST /galerie` → `POST /retenir` sur `memoire:5600` avec
    `{type: "ressource", wing: "atelier-images-video", room: "image"|"video",
    titre, contenu: prompt, metadata: {url, fournisseur, place_holder}}`
  - `GET /galerie` → `GET /souvenirs?wing=atelier-images-video` sur `memoire:5600`
  - `DELETE /galerie/{id}` → `DELETE /souvenir/{id}` sur `memoire:5600`

### `briques/atelier-images-video/front.html`

4 onglets (motif `front.html` d'atelier-veille : onglets + panels, pas de framework) :

1. **Image libre** — prompt, négatif, largeur/hauteur, sélecteur fournisseur (peuplé par
   `/images/fournisseurs`), bouton Générer, résultat (`<img>` + avertissement si
   `place_holder`), bouton « Ajouter à la galerie ». Un petit menu « mes prompts favoris »
   (presets `localStorage`) à côté du champ prompt.
2. **Vidéo libre** — même schéma sur `/video/*`, plus un champ optionnel « image de
   départ (URL) » pour l'image→vidéo.
3. **Synergies** — sélecteur de série (`/studio/series`) → puis personnage (Portrait /
   Animer) ou épisode (Couverture / Teaser) → résultat affiché + confirmation que c'est
   sauvegardé côté Studio (comportement déjà existant, juste rendu accessible ici aussi).
4. **Galerie** — grille des souvenirs (`/galerie`), filtrable image/vidéo (`room`),
   suppression par souvenir.

### `briques/atelier-images-video/manifest.json`

`famille: "media"`, port 6160, `capacites: []`, `depends_on: ["images", "video",
"studio", "memoire"]`.

### `briques/atelier-images-video/docker-compose.yml`

Env : `IMAGES_URL`, `VIDEO_URL`, `STUDIO_URL`, `STUDIO_KEY`, `MEMOIRE_URL`,
`MEMOIRE_KEY`, `CORS_ORIGINS`. Healthcheck `/sante`, volume aucun (pas d'état propre).

## Gestion d'erreurs

Même convention que `atelier-veille` : une brique composée injoignable → `502` avec
message explicite (« images injoignable (URL) : … »), jamais un `500` opaque. Un
placeholder renvoyé par images/video (`place_holder: true`) n'est PAS une erreur — affiché
normalement avec un avertissement visuel, jamais masqué (honnêteté technique).

## Tests

100% offline, `httpx` mocké vers `images`/`video`/`studio`/`memoire` (aucun réseau réel) :
- Génération libre : payload transmis tel quel, réponse (dont `place_holder`) relayée.
- Fournisseurs : `/fournisseurs` relayé tel quel (catalogue + statut configuré).
- Synergies : les 4 routes Studio relayées avec les bons `STUDIO_KEY`/`X-User-Id` ;
  brique Studio injoignable → `502`.
- Galerie : `POST/GET/DELETE /galerie` relayés vers `memoire` avec les bons
  `wing`/`room`/`metadata`.
- Nouveau routeur Cœur : un `X-User-Id` envoyé par le navigateur est ignoré ; seule la
  session compte (même test que `studio_proxy` s'il existe déjà, à dupliquer/adapter).

## Hors périmètre v1 (suites possibles, pas ce sprint)

- Génération multi-variantes en parallèle (façon Kubock « Swift »).
- Auto-save systématique en galerie (v1 = bouton explicite).
- Éditeur d'image intégré (retouche, inpainting — façon Kubock « Image Editor »).
- Habillage vidéo (carte-titre, sous-titrage — déjà dans `briques/video` mais pas exposé
  dans cet atelier, reste un outil Studio).
- Presets synchronisés côté serveur (v1 = `localStorage`, perdu si navigateur/appareil
  change).
