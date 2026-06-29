# Guide — modifier / brancher l'authentification

> **À qui ça sert** : tu veux protéger une brique par login, comprendre comment marche l'auth de
> Workplace, ou migrer une brique vers la lib partagée. Lis le périmètre d'abord — **trois schémas
> d'auth coexistent**, ne les confonds pas (le diagnostic « JWT ×6 » initial était faux).

## 0. Les trois schémas d'auth (NE PAS confondre)
| Schéma | Qui | Source de vérité | Périmètre de ce guide |
|---|---|---|---|
| **Keycloak RS256 / JWKS** | donnees, agenda, forge, oria | `shared/workplace_auth.py` | ✅ **OUI** — c'est ça, « l'auth » |
| **Sessions HMAC stdlib** | restaurant (comptes + jetons de table) | local à la brique | ❌ hors périmètre (autonome, voir §5) |
| **JWT HS256 symétrique** | memoire (projet Memory tiers) | local au projet vendu | ❌ hors périmètre |

« Modifier l'auth » = travailler sur le **Keycloak RS256**, unifié dans `shared/workplace_auth.py`
depuis S120 (une seule source de vérité, fini les copies vendored par brique).

## 1. La lib partagée — `shared/workplace_auth.py`
API publique stable :
```python
from shared.workplace_auth import (
    KeycloakSettings,     # dataclass de config (url, realm, audience, jwks_ttl, algorithms)
    verify_token,         # async : token -> payload décodé (lève jose.JWTError si invalide)
    verify_token_sync,    # variante sync (routers SQLAlchemy non-async, ex. Oria)
    has_role,             # (payload, role) -> bool  (realm role)
    require_role,         # factory de dependency FastAPI exigeant un rôle realm
)

KC = KeycloakSettings(url="http://identite:8080", realm="client-acme", audience="")
require_admin = require_role("admin", KC)
```
Détails importants :
- **JWKS mis en cache** (TTL `jwks_ttl`, défaut 600 s) — pas de refetch à chaque requête.
- **`audience=""` ⇒ `verify_aud` désactivé** : c'est le mode **multi-tenant** (le **realm** du
  bundle suffit à isoler ; pas besoin d'audience). Mets une audience seulement si tu veux la vérifier.
- `extra_decode_options` : options additionnelles passées à `jwt.decode` (ex. `verify_at_hash=False`
  pour Oria).
- `algorithms` par défaut `("RS256",)` — Keycloak signe en RS256, ne mets pas HS256 ici.

## 2. Activer l'auth sur une brique — le motif (exemple `donnees`)
Le comportement est **piloté par l'environnement, rétrocompatible par défaut** :

```python
# briques/<brique>/auth.py
import os
from shared.workplace_auth import KeycloakSettings, verify_token_sync

AUTH_ENABLED     = os.getenv("AUTH_ENABLED", "false").lower() in ("1", "true", "oui", "yes")
KEYCLOAK_URL     = os.getenv("KEYCLOAK_URL", "").rstrip("/")   # ex: http://identite:8080
KEYCLOAK_REALM   = os.getenv("KEYCLOAK_REALM", "")            # ex: client-acme
KEYCLOAK_AUDIENCE= os.getenv("KEYCLOAK_AUDIENCE", "").strip() # vide ⇒ verify_aud off
```
- `AUTH_ENABLED` absent/`false` ⇒ **garde no-op**, la brique reste ouverte (dev central inchangé,
  zéro régression). C'est le **défaut**.
- `AUTH_ENABLED=true` ⇒ tout appel exige un Bearer Keycloak valide, sinon **401**.
- Le packager de bundle pose `AUTH_ENABLED` + `KEYCLOAK_URL`/`REALM` sur le service du bundle livré.

> **Invariant** : une auth manquante/cassée doit renvoyer **401**, jamais **500**. (Le 500-sur-JWKS-
> injoignable d'agenda est un comportement pré-existant connu : il n'attrape que `JWTError`.)

## 3. Migrer une brique vers `shared/` (si elle a encore une copie locale)
Pattern build-context racine, **triplement prouvé** (S118 Gateway, S119 schémas, S120 auth) :
1. La brique **délègue** à `shared.workplace_auth` (garde son `auth.py` mince : config env + la
   dependency FastAPI ; **garde l'API publique** que ses tests appellent).
2. `docker-compose.yml` : `build.context: ../..` + `dockerfile: briques/<brique>/Dockerfile`.
3. `Dockerfile` : `COPY shared/ /app/shared/` **avant** le `COPY` du code brique +
   `pip install -r requirements.txt -c constraints-workplace.txt` (pins `python-jose==3.3.0`,
   `cryptography==44.0.0`).
4. `conftest.py` dans la brique : met la racine sur `sys.path` pour les **tests natifs**.
5. **Bundle** : `generateur/bundle.py::depend_de_shared()` détecte le contexte racine et reproduit
   `shared/` dans le bundle livré — rien à faire manuellement, mais vérifie que la brique reste
   bundlable.

> **Exception assumée — Oria** reste sur sa lib vendored (sous-stack découplé : son `shared/` est
> git-ignoré, son contexte de build `oria-stack/` ne voit pas la racine, et `oria-stack` est dans le
> `.dockerignore` racine pour ne pas gonfler le contexte de **toutes** les autres briques). Ne le
> rattache pas.

## 4. Multi-tenant (org) — S121
L'isolation par organisation passe par des **en-têtes propagés par le Cœur**
(`core/contexte_tenant.py`) : `X-Org-ID` (donnees, scope par **org**), `X-User-Id` (agenda, scope
par **user**), `X-Forge-User-Token` (forge). Côté brique auth, l'org se résout depuis le claim
Keycloak (`org_id` / `organization` / `sub`) quand l'auth est active, sinon repli `"defaut"`
(rétrocompatible). Voir `briques/donnees/auth.py::tenant_actuel`.

## 5. Ce que tu NE touches PAS depuis ce guide
- **restaurant** : sessions HMAC stdlib (comptes restaurateur + jetons d'adhésion de table), **pas
  de Keycloak**, délibérément autonome. Si tu veux changer son auth, c'est dans `briques/restaurant/`.
- **memoire** : JWT HS256 du projet Memory tiers — auth interne à ce projet vendu.

## 6. Tester
- Hors-ligne : `pytest briques/<brique>/` (avec le `conftest.py` racine-sur-path) — la posture
  401/200 et le chemin service-à-service doivent rester verts.
- LIVE (sur le HP, cf. `MIGRATION-HP.md` Niveau B) : un **vrai JWT** Keycloak → 401 sans / 200 avec,
  isolation par **claim** `org_id`, propagation `X-Forge-User-Token` réelle vers le core Forge.
