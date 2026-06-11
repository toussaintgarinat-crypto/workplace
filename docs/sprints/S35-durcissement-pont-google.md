# Sprint S35 — Durcissement du pont Google (state OAuth anti-CSRF)

**Objectif** : solder la dette de sécurité S27 avant toute ouverture publique du pont
Google Agenda. L'implémentation initiale posait `state = user_id` brut : **prévisible et
falsifiable**, et le callback faisait confiance à cet identifiant transmis en clair. S35
remplace ce state par un jeton **signé (HMAC-SHA256)**, opaque et vérifié — anti-CSRF.

**Statut** : ✅ LIVRÉ CODE + **31 tests verts dans l'image Docker réelle** (dont 7 nouveaux)
le 2026-06-11. Reste LIVE : rejouer le consentement Google réel avec le nouveau state
(même prérequis que S27 — identifiants Google Cloud + navigateur).

S'appuie sur : **pont Google S27** (`google_sync`, `google_oauth`, `vault`).

---

## Le défaut (S27) et le correctif (S35)

| | Avant (S27) | Après (S35) |
|---|---|---|
| `state` | `user["sub"]` brut (prévisible) | jeton **signé HMAC-SHA256** `{uid, exp, nonce}` |
| Callback | fait confiance à `state` comme `user_id` | **vérifie** signature + expiration, puis extrait `user_id` |
| CSRF | un tiers peut forger un callback ciblant un user_id deviné | state infalsifiable sans le secret serveur |
| Identité en clair | l'identifiant voyage dans l'URL | absent de l'URL (opaque) |

## Ce qui a été construit

| Pièce | Rôle |
|---|---|
| `briques/agenda/backend/services/oauth_state.py` | `emettre(user_id)` → state signé (TTL 10 min, aléa) ; `verifier(state)` → `user_id` après contrôle signature + expiration, lève `StateError` sinon. **Sans stockage serveur** (stateless) → survit aux redémarrages / multi-worker. |
| `briques/agenda/backend/routers/google_sync.py` | `/connect` émet un state signé ; `/callback` le **vérifie** (400 si invalide/expiré/falsifié) avant d'en extraire l'identité. |
| `briques/agenda/backend/config.py` | `GOOGLE_STATE_SECRET` (vide ⇒ **dérivé de `VAULT_SECRET`**, déjà requis dès qu'on stocke un token Google — aucun nouveau secret obligatoire). Commentaire prod sur `GOOGLE_REDIRECT_URI` (https). |
| `briques/agenda/backend/tests/test_oauth_state.py` | 7 scénarios (aller-retour, opacité, signature falsifiée, payload modifié, expiration, malformé, secret dédié). |

## Décisions d'architecture

- **Signé plutôt que stocké.** Un state signé (HMAC) est infalsifiable et **stateless** :
  pas de table de nonces à gérer, robuste au multi-worker et aux redémarrages, contrairement
  à un nonce gardé en mémoire. La courte expiration (10 min) borne le rejeu.
- **Secret dérivé, zéro provisioning.** La clé de signature dérive de `VAULT_SECRET` (label
  `google-oauth-state:`) si `GOOGLE_STATE_SECRET` n'est pas posé — on ne réutilise pas la
  clé du coffre telle quelle, et on n'impose pas un nouveau secret à déployer.
- **On ne fait plus confiance au client.** Le callback Google arrive sans le JWT de la
  brique ; l'identité vient désormais d'un payload **signé par le serveur**, plus d'un
  identifiant transmis en clair.
- **Redirect prod.** `GOOGLE_REDIRECT_URI` est déjà piloté par env (défaut localhost) ; le
  durcissement documente le passage `https://agenda.${DOMAIN}/google/callback` (à déclarer
  aussi côté Google Cloud).

## Tests

```
# Image Docker réelle (cryptography présent) — suite agenda complète
docker compose run --rm agenda pytest tests/ -q
  → 31 passed   (dont 7 nouveaux test_oauth_state + vault + google_oauth + google_sync)
```
Non-régression : `test_build_auth_url_carries_offline_and_state` et tout `google_sync`
restent verts (le contrat de `build_auth_url` est inchangé : il signe le state qu'on lui
passe). `py_compile` OK.

## Dettes / suites

- **Preuve LIVE Google** : rejouer un vrai consentement (identifiants Google Cloud +
  navigateur) pour vérifier le round-trip avec le state signé de bout en bout — même
  prérequis que la preuve LIVE de S27.
- **Rejeu (one-time-use)** : le state signé borne le rejeu par l'expiration (10 min) mais
  n'est pas strictement à usage unique ; un nonce serveur consommable l'interdirait
  totalement (au prix d'un état partagé).
