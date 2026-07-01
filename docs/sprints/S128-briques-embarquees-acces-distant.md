# S128 — Rendre les briques embarquées accessibles à distance (mesh) sans casser le LAN

- **Date de préparation** : 2026-07-01
- **Statut** : ✅ CODE-COMPLET + testé (23/23) — 🔴 preuve LIVE mesh différée (dépend d'un pair + déploiement HP)
- **Dépend de** : accès distant NetBird + Caddy (`docs/decisions/2026-07-01-acces-distant-netbird.md`)
- **Objectif** : depuis l'iPhone/Mac **hors du réseau local**, les tuiles du dashboard qui
  embarquent une brique en iframe (Studio, Restaurant, Mail, Mémoire, Peertube, Voix, Synopsis,
  Personnages, Transcription, Gateway, Forge, IDE dev) **s'affichent**, tout en gardant l'accès
  **LAN** (Mac à la maison sur `http://192.168.1.89:5100`) intact.

---

## Contexte & problème
Le dashboard du Cœur est une **coquille** qui embarque chaque brique par `<iframe src=…>`. Les
URLs viennent d'`env` figées (`core/urls_ui.py` : `STUDIO_UI_URL`, `RESTAURANT_UI_URL`…) réglées
sur le HP à **`http://192.168.1.89:<port>`** (l'IP LAN, en HTTP).

Depuis un pair du mesh (iPhone), ça casse pour **deux** raisons cumulées :
1. **`192.168.1.89` est injoignable** hors LAN — le pair ne joint que l'IP mesh `100.124.248.226`.
2. **Mixed content** — le dashboard distant est servi en **HTTPS** (Caddy) ; une iframe `http://`
   y est **bloquée** par le navigateur.

Contrainte structurante : **on ne peut pas juste repointer les `*_UI_URL` sur l'IP mesh**, car ça
**casserait** l'accès LAN du Mac (qui n'est pas un pair du mesh et ne joint pas `100.124.248.226`).
Il faut que **les mêmes** URLs marchent selon d'où vient le navigateur.

---

## Décision de conception : URLs d'iframe **relatives à l'hôte** + Caddy **par port** en HTTPS
Deux pièces complémentaires :

### 1. Cœur — construire les URLs à partir de la requête (scheme + hôte), pas d'une env figée
Au lieu d'une URL absolue par brique, on garde seulement `{port, chemin}` et on **préfixe avec le
scheme + l'hôte de la requête courante** (`Host` / `X-Forwarded-Proto` quand on est derrière Caddy).
Résultat, la **même** logique donne la bonne URL partout :
- LAN direct : requête sur `http://192.168.1.89:5100` → iframe `http://192.168.1.89:<port>/…` *(inchangé)*
- Mesh via Caddy : requête sur `https://100.124.248.226` → iframe `https://100.124.248.226:<port>/…`
- Dev local : `http://localhost:5100` → `http://localhost:<port>/…`

Pré-requis : le Cœur doit **faire confiance aux en-têtes de proxy** (uvicorn `--proxy-headers`
/ lecture `X-Forwarded-Proto`) pour connaître le bon scheme derrière Caddy. On **garde une
surcharge env** par brique (repli / cas SSO Forge).

### 2. Caddy (mesh) — exposer chaque brique en HTTPS sur un port DÉCALÉ (+10000)
Sur l'IP mesh, un bloc Caddy `tls internal` par brique (le certificat racine est **déjà de
confiance** sur les appareils, cf. décision NetBird) :
```
https://100.124.248.226:16060 { tls internal; reverse_proxy localhost:6060 }   # studio  6060→16060
https://100.124.248.226:16010 { tls internal; reverse_proxy localhost:6010 }   # restaurant 6010→16010
… un bloc par port de brique …
```
Même scheme (HTTPS) que le dashboard → **plus de mixed content**. Caddy gère nativement l'**upgrade
WebSocket** (utile pour la voix). Aucune ré-écriture de chemin : chaque brique a son **port
dédié** (juste décalé de +10000), donc les SPA gardent leurs assets à la racine de leur port.

> **Pourquoi décalé et pas le même port ?** (constaté LIVE) — les briques publient sur
> `0.0.0.0:<port>` (Docker) : ce port est **déjà occupé sur l'IP mesh**, Caddy ne peut donc pas
> l'écouter (`bind: address already in use`). On expose donc chaque brique sur `<port>+10000`
> (libres) et le Cœur émet ce port décalé **uniquement** quand la requête vient de l'hôte mesh
> (`MESH_HOST` + `MESH_PORT_OFFSET`). Avantage : **zéro changement sur les briques** (elles gardent
> `0.0.0.0`), donc rien à recréer sur le stack live et **aucune régression LAN**.

### Alternatives écartées
- **Chemin unique `/b/<brique>/…`** : casse les SPA (chemins d'assets absolus `/assets/…`) sans
  rebuild avec base-href → trop invasif par brique.
- **Sous-domaine par brique** : exige du DNS par brique ; le DNS NetBird n'est pas activé
  (`Nameservers 0/0`).
- **Repointer les `*_UI_URL` sur l'IP mesh** : casse l'accès LAN du Mac. *(sauf à mettre le Mac
  sur le mesh — utile, mais ne règle pas le principe pour d'autres appareils LAN.)*

---

## Périmètre — briques concernées (source `core/urls_ui.py`)
| Brique | Port | Chemin | Note / risque de framing |
|---|---|---|---|
| Studio | 6060 | /atelier | front autoporté |
| Personnages | 5900 | /atelier | |
| Transcription | 5980 | /atelier | |
| Restaurant | 6010 | / | multi-tenant, clé service |
| Mail | 6030 | / | |
| Synopsis | 6090 | / | |
| Voix | 5985 | / | **WebSocket** (test Piper/Kokoro) |
| Mémoire | 5600 | /memory | SPA + proxy `/api/v1` same-origin (OK) |
| Peertube | 9000 | / | héberge sa propre UI |
| Gateway (LiteLLM) | 4001 | /ui | ⚠️ peut poser `X-Frame-Options` |
| Générateur | 5400 | (liens aperçu/télécharger, pas iframe) | `GENERATEUR_URL_PUBLIQUE` |
| Agenda | 8400 | (`AGENDA_URL_PUBLIQUE`) | |
| Forge (SPA) | 3000 | / | ⚠️ **SSO Keycloak** — redirect URIs + realm frontend URL à étendre → **hors périmètre S128** (sous-sprint dédié) |
| IDE dev (code-server) | 8744 | / | ⚠️ auth propre + WS + bug EACCES sur HP → **différé** |

---

## Découpage (tâches)
1. **Cœur — URLs relatives à l'hôte** : refactor `core/urls_ui.py` + `core/routers/dashboard.py`
   pour bâtir `src` iframe et liens aperçu depuis `{scheme, host}` de la requête + table
   `{port, chemin}` par brique ; conserver surcharge env. Activer la confiance aux en-têtes de
   proxy (uvicorn `--proxy-headers` dans `core/Dockerfile`/compose). **Tests** dans
   `core/test_dashboard.py` (Host LAN → http://ip:port ; Host mesh + XFP=https → https://mesh:port ;
   localhost). *(Non-régression : le dashboard sert toujours les bonnes iframes en LAN.)*
2. **Caddy (mesh) — sites par port** : ajouter les blocs `tls internal` par brique dans
   `outils/mesh-https/` (fichier dédié `Caddyfile.briques` inclus, ou génération). Déployer sur
   la VM. **Preuve** : depuis un pair mesh, `curl -k https://100.124.248.226:<port>/… → 200` pour
   chaque brique.
3. **Framing + CORS par brique** : auditer `X-Frame-Options` / CSP `frame-ancestors` et
   `CORS_ORIGINS` ; autoriser l'origine mesh `https://100.124.248.226` là où c'est bloqué
   (Gateway/LiteLLM en tête). Documenter brique par brique ce qui embarque ✅ vs ❌.
4. **Vérif bout-en-bout** : ouvrir le dashboard distant, cliquer chaque tuile, constater le rendu
   (vérif finale = sur l'iPhone/Mac réel). Rapport honnête ✅/❌ par brique.
5. **Docs** : mettre à jour `docs/decisions/2026-07-01-acces-distant-netbird.md` (limite « briques
   embarquées » → résolue/partielle) + clore ce sprint avec le tableau de résultats.

---

## Risques & limites honnêtes
- **Forge (SSO Keycloak)** et **IDE dev (code-server)** : hors périmètre S128 (SSO/auth propres,
  redirect URIs, WS, bug EACCES). À traiter en sous-sprint si besoin réel à distance.
- **Gateway/LiteLLM** : susceptible de refuser l'`iframe` (X-Frame-Options) — peut rester « Ouvrir
  dans un onglet » si non débloquable proprement.
- **Sécurité** : construire une URL depuis l'en-tête `Host` est acceptable en réseau de confiance
  (mesh + LAN privés). En multi-tenant public, revalider.
- **Chaque nouvel appareil LAN** hors mesh continue de marcher via `192.168.1.89` ; chaque appareil
  du mesh via `100.124.248.226`. Pas de régression.

## Preuve attendue (definition of done)
Depuis un pair mesh (hors LAN) : dashboard HTTPS + **≥ 10 briques embarquées s'affichent** dans
leur iframe (hors Forge/IDE dev, documentés comme différés), voix incluse (WS). Accès LAN du Mac
inchangé. Le tout committé + le registre de décision à jour.

---

## Réalisation (2026-07-01)

### Fait (code + tests, prouvé ICI)
1. **Cœur — URLs relatives à l'hôte** ✅ `core/urls_ui.py` refactoré : table `BRIQUES_UI`
   `{NOM: (port, chemin)}` + `url_brique(nom, scheme, host)` (surcharge env `<NOM>_UI_URL`
   sinon `{scheme}://{hôte-sans-port}:{port}{chemin}`). `core/routers/dashboard.py` lit
   `X-Forwarded-Proto` (défaut = scheme requête) + `Host` et bâtit chaque `__*_UI_URL__`.
   `core/Dockerfile` : uvicorn `--proxy-headers --forwarded-allow-ips *`.
   **Tests** `core/test_dashboard.py` : LAN (`Host=192.168.1.89:5100` → `http://192.168.1.89:<port>`),
   mesh (`Host=100.124.248.226` + `XFP=https` → `https://100.124.248.226:<port>`, zéro `http://`),
   localhost, surcharge env, clé Studio (+ `core/test_urls_ui.py` : unités du constructeur —
   strip du port, IPv6, hôte vide, `DEV_IDE_URL`). **23/23 verts.**
2. **Caddy (mesh) — sites par port** ✅ `outils/mesh-https/Caddyfile.briques` (snippet
   `(brique_mesh)` + un `import` par port), inclus depuis `Caddyfile`, monté par le compose.
   **`caddy validate` = « Valid configuration ».**
3. **Framing/CORS** ✅ audit : **aucune brique** ne pose `X-Frame-Options` / CSP
   `frame-ancestors` → framing autorisé par défaut. CORS n'est pas le bloqueur des iframes
   (chaque SPA est servie *same-origin* sur son port ; la Mémoire proxifie `/api/v1` same-origin).
   **Seul point d'attention** = la console **Gateway/LiteLLM** (image tierce) susceptible d'envoyer
   `X-Frame-Options` → peut rester « Ouvrir dans un onglet » (à vérifier LIVE).

### Déploiement HP (fait le 2026-07-01)
- `core/docker-compose.override.yml` (HP-local) : **retiré** les 12 surcharges
  `<NOM>_UI_URL=192.168.1.89:…` (sinon la construction relative est court-circuitée) ;
  **ajouté** `MESH_HOST=100.124.248.226`. `GENERATEUR_URL_PUBLIQUE` (liens nouvel onglet) gardé.
- Rebuild du **seul** Cœur (`cd core && docker compose up -d --build`). Briques non touchées.
- `cd outils/mesh-https && docker compose up -d` (Caddy recharge les 11 sites décalés).
- **Preuve LIVE** (depuis le HP, côté mesh) : `curl -k https://100.124.248.226:1<port>/… → 200`.

### Reste (différé)
- **Preuve LIVE** bout-en-bout depuis l'iPhone/Mac réel sur le mesh (≥ 10 iframes + voix WS),
  LAN du Mac inchangé.
- **Forge (SSO)** et **IDE dev** : sous-sprint dédié si besoin réel à distance.
