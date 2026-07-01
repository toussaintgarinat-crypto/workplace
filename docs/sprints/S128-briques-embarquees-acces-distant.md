# S128 — Rendre les briques embarquées accessibles à distance (mesh) sans casser le LAN

- **Date de préparation** : 2026-07-01
- **Statut** : 📋 Préparé (spec + plan) — pas encore implémenté
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

### 2. Caddy (mesh) — exposer chaque brique en HTTPS sur son port
Sur l'IP mesh, un bloc Caddy `tls internal` par brique (le certificat racine est **déjà de
confiance** sur les appareils, cf. décision NetBird) :
```
https://100.124.248.226:6060 { tls internal; reverse_proxy localhost:6060 }   # studio
https://100.124.248.226:6010 { tls internal; reverse_proxy localhost:6010 }   # restaurant
… un bloc par port de brique …
```
Même scheme (HTTPS) que le dashboard → **plus de mixed content**. Caddy gère nativement l'**upgrade
WebSocket** (utile pour la voix). *(Le port reste le même qu'en LAN → aucune ré-écriture de
chemin, les SPA gardent leurs assets à la racine de leur port.)*

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
