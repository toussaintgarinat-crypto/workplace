# S130 — Rendre Forge (SPA + SSO Keycloak) accessible à distance (mesh)

- **Date de préparation** : 2026-07-01
- **Statut** : 📋 Préparé (spec + plan) — pas encore implémenté. **Effort : élevé.**
- **Dépend de** : S128 (URLs relatives + Caddy ports décalés). Peut se faire après S129.
- **Objectif** : depuis l'iPhone/Mac hors LAN, la tuile « Forge » **s'affiche ET le login SSO
  aboutit** (realm `oria`), sans casser le SSO en LAN.

---

## État réel constaté (2026-07-01, sur le HP)
- **Keycloak EST en place et sain** (le `unhealthy` du conteneur `keycloak` est un faux négatif) :
  - `keycloak` (port **8080**) : realms **`forge` + `oria`** importés au boot (Keycloak 26.2.5).
  - `oria-keycloak-1` (port **8081**) : realm `oria`. **C'est celui que Forge utilise réellement.**
- **Forge** (`briques/forge/docker-compose.yml`) : SPA `oria-app` sur le realm `oria` @ **8081**,
  backend/adapter vérifient les JWT sur `host.docker.internal:8081`.
- **Le vrai blocage** : `VITE_KEYCLOAK_URL` est **figé au BUILD** du SPA
  (`http://localhost:8081` dans les assets servis). `localhost:8081` ne marche que depuis un
  navigateur tournant *sur le HP* → **le SSO Forge est déjà cassé depuis le Mac/iPhone**,
  indépendamment du mesh. Une URL bakée ne peut pas être à la fois bonne en LAN et sur le mesh.
- **2 obstacles cumulés** (comme S128) mais aggravés : URL Keycloak non joignable **+** login
  **dans une iframe** (Keycloak renvoie `X-Frame-Options` sur ses pages → un redirect OIDC rendu
  dans l'iframe est bloqué).

---

## Décisions de conception à trancher

### A. Comment le SPA obtient l'URL Keycloak (résoudre le « figé au build »)
- **A1 (recommandé) — Keycloak en same-origin derrière le SPA.** Le serveur du front Forge
  (nginx) **reverse-proxifie** `/<chemin-auth>/*` → `oria-keycloak:8080`. Le SPA configure
  keycloak-js avec une **URL relative** (`/<chemin-auth>`) → marche depuis N'IMPORTE QUEL hôte
  (LAN, mesh) sans rebuild par environnement. Un seul cert (celui de Forge). Coût : patch nginx
  Forge + `VITE_KEYCLOAK_URL=/auth` + rebuild front + realm `frontendUrl` cohérent.
- **A2 — config runtime.** Le SPA lit un `GET /config.json` (servi par nginx, non baké) au
  démarrage. Plus souple mais 1 aller-retour + refactor de l'init keycloak-js.
- **A3 — URL Keycloak absolue stable** (ex. HTTPS mesh `https://100.124.248.226:18081`) bakée :
  casse le LAN (même piège que les `*_UI_URL`). **Écartée** sauf à mettre le Keycloak derrière un
  vrai domaine unique joignable partout.

### B. Le login SSO dans une iframe (Keycloak = `X-Frame-Options`)
- **B1 (recommandé) — ouvrir Forge en ONGLET pour le mesh.** La tuile Forge ouvre un onglet
  plein écran (`target=_blank`) au lieu d'une iframe → le redirect OIDC se fait au niveau top,
  aucun souci de framing. Le lien « Ouvrir dans un onglet ↗ » existe déjà. Simple et robuste.
- **B2 — garder l'iframe + login en POPUP** (`keycloak-js` `{ onLoad:'check-sso', … }` +
  connexion via fenêtre popup). Marche mais UX iOS Safari capricieuse (bloqueurs de popup,
  cookies tiers). Plus fragile.
- **B3 — silent check-sso en iframe** : nécessite que Keycloak autorise le framing par le SPA
  (`Web Origins` + `X-Frame-Options`/CSP `frame-ancestors` desserrés sur Keycloak) → surface
  de sécurité + config Keycloak 26 pointue. À éviter en v1.

### C. Keycloak joignable en HTTPS depuis le mesh + hostname
Keycloak 26 est strict sur le **hostname**. Exposer un site Caddy `https://100.124.248.226:18081`
→ `oria-keycloak:8080`, et régler `KC_HOSTNAME`/`frontendUrl` du realm pour **accepter** cet
hôte (sinon redirects/issuer incohérents). Vérifier l'`issuer` du token vs ce que le backend
valide. *(Avec A1, Keycloak est same-origin derrière Forge → ce point se simplifie : un seul
hôte public = celui de Forge.)*

### D. Client `oria-app` — Redirect URIs & Web Origins
Ajouter dans le realm `oria`, client `oria-app` : les **Redirect URIs** et **Web Origins** de
CHAQUE origine d'où on se connecte (LAN `http://192.168.1.89:3000/*`, mesh
`https://100.124.248.226:13000/*` **ou** l'origine same-origin de A1). Idempotent, versionné
dans `oria-realm.json` si possible (pas seulement à la main dans l'admin).

---

## Approche recommandée (v1 la plus sûre)
**A1 (Keycloak same-origin derrière Forge) + B1 (Forge en onglet sur le mesh) + D (URIs/origins).**
→ Le SPA utilise une URL Keycloak **relative** (marche LAN + mesh sans rebuild par env), le login
se fait **hors iframe** (onglet), et on n'ouvre que les origines nécessaires. Caddy sert Forge sur
`13000` (déjà émis par `url_brique`) → `localhost:3000` ; Keycloak passe par le même hôte.

## Découpage (tâches)
1. **Front Forge same-origin auth (A1)** : nginx Forge proxifie `/auth` → keycloak ; `VITE_*` en
   relatif ; rebuild `forge-frontend`. Vérifier LAN d'abord (le SSO Forge cassé aujourd'hui doit
   REMARCHER en LAN depuis le Mac).
2. **Realm/oidc (C+D)** : `frontendUrl`/hostname cohérents + redirect URIs/web origins (LAN +
   origine Forge mesh) ; idéalement dans `oria-realm.json`.
3. **Caddy (mesh)** : site `13000 → 3000` (Forge) ; Keycloak via le même hôte (A1) donc **pas**
   de site Keycloak séparé. Ajouter au `Caddyfile.briques` (retirer Forge de la liste des différés).
4. **Tuile en onglet (B1)** : sur le mesh, la tuile Forge ouvre un onglet (garder l'iframe en LAN
   si on veut, ou onglet partout pour homogénéité).
5. **Preuve LIVE** : login realm `oria` **depuis le Mac LAN** puis **depuis l'iPhone mesh** →
   session Forge active, un appel API authentifié passe (JWT accepté par le backend). Rapport ✅/❌.

## Risques & limites honnêtes
- **Rebuild du front Forge** requis (URL auth relative) — non trivial, tester le LAN en premier.
- **Deux Keycloak** (8080 standalone forge+oria vs 8081 oria) : **clarifier lequel est canonique**
  pour Forge et documenter/consolider (dette de confusion). Forge = 8081 aujourd'hui.
- **Cookies tiers / Safari iOS** si on s'entête à l'iframe (B2/B3) — d'où la reco onglet.
- **Sécurité** : n'ouvrir que les origines strictement nécessaires ; Keycloak reste derrière le
  mesh + LAN privés.

## Definition of done
SSO realm `oria` fonctionnel **en LAN (Mac)** ET **sur le mesh (iPhone)** : la tuile Forge mène à
un login qui aboutit, session active, un appel API Forge authentifié réussit. Aucune régression du
SSO en LAN. Committé + `oria-realm.json` versionné + registre de décision à jour.
