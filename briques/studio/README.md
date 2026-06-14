# Brique `studio` — atelier d'audio-séries co-créées (port 6060)

Studio narratif extrait du backend Oria (S51) en **brique autonome**. Même usine
créative — bible → épisodes → audio → livre → arbre des choix — mais **sans dépendance à
la base, à l'auth Keycloak ni au `world_id` d'Oria**.

C'est un **composeur** : il appelle d'autres briques sans les absorber (chacune reste
vendable seule).

```
   ┌──────────────── brique studio (6060) ────────────────┐
   │      bible · épisodes · audio · livre · arbre         │
   └──┬───────────┬───────────────┬──────────────┬─────────┘
 Gateway (4001)  voix (5810)   images (5950)  personnages (5900)
 équipe créative sonorisation  portraits      distribution +
                               couvertures    casting vocal stable
```

**Composition (S52)** : le casting vocal et la proposition de distribution sont
**délégués à la brique personnages** (5900) — c'est son métier. Si elle est éteinte, le
Studio retombe sur sa logique internalisée (S51) et l'indique (`source: "studio"` au lieu
de `"personnages"`). Aucune production n'échoue parce qu'une brique sœur est absente.

## Ce qui change vs Oria (le couplage coupé)

| Couplage Oria | Dans la brique |
|---|---|
| 6 agents = `AgentDefinition` en base, par `world_id` | **internalisés** en prompts figés (`agents.py`) — l'IP du produit |
| `get_db` / SQLAlchemy | aucun — séries en **JSON** dans un volume propre (`STUDIO_DIR`) |
| `get_current_user` (Keycloak) | **auth BYO optionnelle** (`API_KEYS`), mode ouvert par défaut |
| `world_id` obligatoire | **facultatif** (simple métadonnée, pour le hook Oria S53) |

## Modules

| Fichier | Rôle |
|---|---|
| `agents.py` | équipe créative internalisée (6 prompts) + pont Gateway (cascade gratuite) |
| `studio.py` | toute la logique métier pure + persistance JSON (langue, cible, continuité, casting, épisodes, tâches, arbre, anglicismes, pont images) |
| `composition.py` | adaptateur client de la brique personnages (5900) : casting vocal stable + distribution, replis honnêtes (S52) |
| `main.py` | surface FastAPI |

## Lancer

```bash
docker compose up --build          # → http://localhost:6060/sante  (front : http://localhost:6060/)
# ou en local :
GATEWAY_KEY=… uvicorn main:app --port 6060
```

## Réglages (env)

| Variable | Défaut | Usage |
|---|---|---|
| `GATEWAY_URL` / `GATEWAY_MODEL` / `GATEWAY_KEY` | `…:4001` / `free/google/gemma-4-31b-it` / — | LLM (BYO key possible) |
| `VOIX_URL` | `…:5810` | service voix hôte (say + ffmpeg) |
| `IMAGES_URL` / `IMAGES_PUBLIC_URL` | `…:5950` / `localhost:5950` | brique images |
| `PERSONNAGES_URL` / `PERSONNAGES_KEY` | `…:5900` / — | brique personnages (casting/distribution) ; repli interne si absente |
| `STUDIO_DIR` | `/data/ateliers` | volume des séries (JSON) |
| `API_KEYS` | _(vide = ouvert)_ | clés acceptées pour vendre la brique seule |

## Tests (hors Oria)

```bash
python3 -m pytest -q     # 87 tests, 0 dépendance externe
```

Couvre : continuité (canon, anti-reboot, garde-langue), épisodes (~12 min, cliffhanger),
distribution (voix figées), multilingue (traduction au rendu, replis honnêtes), synergie
images (URL absolue, repli si brique absente), **composition personnages (casting/distribution
délégués à 5900, repli interne honnête, choix de `source`)**.

## Hors-périmètre

- Front servi par la brique + intégration iframe Oria → **S53**.
- Migration des séries JSON existantes d'Oria + décommission de l'`atelier_router` → **S54**.
- Partition des séries **par tenant** (la clé API identifie le créateur mais ne cloisonne
  pas encore le stockage).
