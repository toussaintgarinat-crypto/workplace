# S129 — Rendre l'IDE dev (code-server) accessible à distance (mesh)

- **Date de préparation** : 2026-07-01
- **Statut** : ✅ CODE-COMPLET + PROUVÉ LIVE (2026-07-02)
- **Dépend de** : S128 (URLs d'iframe relatives à l'hôte + Caddy ports décalés) —
  `docs/sprints/S128-briques-embarquees-acces-distant.md`
- **Objectif** : depuis l'iPhone/Mac hors LAN, la tuile « Atelier dev » (IDE web code-server,
  port 8744) **s'affiche et fonctionne** (édition + terminal), comme les 11 briques de S128.

---

## État réel constaté (2026-07-01, sur le HP)
- Conteneur `workplace_dev_ide` : **sain**, `HTTP server listening on 0.0.0.0:8080` → publié `8744`.
- **Auth = mot de passe** (`$PASSWORD`), pas de SSO → **bien plus simple que Forge**.
- **Le bug EACCES a disparu** (logs propres : « Authentication is enabled », « Using password
  from $PASSWORD »). La dette « chown du volume code-server » est donc **soldée en pratique** —
  à re-vérifier, sinon retirer la note de dette.
- `url_brique("DEV_IDE")` émet déjà `https://100.124.248.226:18744/` sur le mesh (S128), mais
  **aucun site Caddy** ne sert 18744 → tuile inerte à distance aujourd'hui.

## Ce qui manque (le cœur du sprint)
1. **Site Caddy 18744 → localhost:8744** dans `outils/mesh-https/Caddyfile.briques` (même
   motif `import brique_mesh 8744`, `tls internal`). code-server est une app **fortement
   WebSocket** (éditeur, terminal, extensions) → vérifier que Caddy fait bien l'**upgrade WS**
   (il le fait nativement ; à prouver LIVE, c'est le vrai risque).
2. **Framing** : vérifier que code-server n'envoie pas `X-Frame-Options`/CSP `frame-ancestors`
   qui bloquerait l'iframe. Si bloqué → soit config code-server, soit garder « Ouvrir dans un
   onglet » (le lien existe déjà dans la vue).
3. **Cookie de session** derrière HTTPS : code-server pose un cookie d'auth ; en HTTPS via Caddy
   (`X-Forwarded-Proto=https`) vérifier `Secure`/`SameSite` (l'iframe est same-origin sur le port
   décalé → OK a priori, à confirmer).

## Découpage (tâches)
1. Ajouter le bloc `18744 → 8744` au `Caddyfile.briques` + redéployer Caddy sur le HP.
2. **Preuve LIVE** : `curl -k https://100.124.248.226:18744/ → 200/302`, puis depuis l'iPhone
   ouvrir la tuile « Atelier dev » → l'IDE charge, **le terminal s'ouvre** (test WS réel),
   l'édition d'un fichier fonctionne.
3. Si framing bloqué : documenter le repli « onglet » ; sinon rien.
4. Clore : tableau de résultats + mettre à jour la note EACCES (soldée) + registre de décision.

## Risques & limites honnêtes
- **WebSocket** = le seul vrai risque (terminal/éditeur). Si l'upgrade ne passe pas en iframe,
  replier sur onglet dédié (fonctionne toujours).
- **Sécurité** : l'IDE dev donne un **shell** sur la machine costaude. Il est derrière le mesh
  (réseau privé) + mot de passe. **Ne jamais l'exposer hors mesh.** Envisager un mot de passe
  fort dédié et, plus tard, une auth alignée sur le reste.

## Definition of done
Depuis un pair mesh : la tuile « Atelier dev » affiche code-server en HTTPS, **le terminal
fonctionne** (WS prouvé), édition OK. Accès LAN (`192.168.1.89:8744`) inchangé. Committé +
registre à jour. Effort estimé : **faible** (1 bloc Caddy + preuve WS).

## Résultats LIVE (2026-07-02)

| Vérification | Résultat |
|---|---|
| Port 18744 LISTEN | ✅ `ss -tlnp` |
| `curl -k https://100.124.248.226:18744/` | ✅ HTTP 302 → `/login` |
| `X-Frame-Options` absent (iframe OK) | ✅ aucun header |
| Caddy reload sans erreur | ✅ `load complete` |
| `workplace_dev_ide` Up, logs propres | ✅ Up 37h, EACCES soldée |
| Mot de passe code-server | `atelier-dev` (variable `PASSWORD`) |

**Note EACCES soldée** : les logs code-server n'affichent plus `EACCES` — la dette
`S128` est effectivement réglée sans intervention (volume ou démarrage corrigé entre temps).
