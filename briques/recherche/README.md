# Brique `browser` — recherche web multi-providers + lecture de page (moteur HuntR)

Les **yeux du Cœur sur le web**. Remplace l'ancienne brique `recherche` en gardant son
contrat (capacités `recherche_web` et `page_lire`, port **6040**), mais avec un moteur
beaucoup plus riche **porté du plugin HuntR de [Gungnir](https://github.com/kevinggraphiste-hub/Gungnir)**.

## Deux gestes (capacités exposées au Cœur)

| Capacité | Endpoint | Rôle |
|---|---|---|
| `recherche_web` | `POST /rechercher` | une requête → liens classés cliquables, **fusion multi-moteurs par consensus** |
| `page_lire` | `POST /lire-page` | une URL → texte principal (Trafilatura) + liens, pour résumer en gardant les sources |

## Ce que HuntR apporte par rapport à l'ancienne `recherche`

- **Jusqu'à 9 moteurs en parallèle** : SearXNG (souverain), DuckDuckGo (sans clé), puis
  Tavily, Brave, Exa, Serper, SerpAPI, Kagi, Bing (à clé, **inertes** sans clé).
- **Fusion par consensus** (`multi_search`) : dédup par URL canonique, score
  `nb de moteurs × poids du moteur × 1/rang`, bonus +25 % par moteur supplémentaire qui
  confirme une URL. Le `content` plein de Tavily est conservé quand il est présent.
- **Multi-thème** (`topic`) : `web` (défaut), `news` (actualités datées),
  `academic` (arXiv/PubMed/Scholar, Scholar boosté en tête), `code` (GitHub/StackOverflow/docs).
- **Filtres de source opt-in** : blocklist de départ (propagande d'État sanctionnée UE/UK
  + désinfo documentée) + blocklist/allowlist maison (modes `boost`/`strict`).

## Souveraineté & honnêteté

Souverain par défaut (SearXNG auto-hébergé conteneur voisin + repli DuckDuckGo sans clé).
Aucune clé embarquée : chaque moteur à clé se configure par variable d'env et reste inerte
sinon. Repli honnête : **jamais de lien inventé ni de faux texte** — si aucun moteur ne
répond, la réponse est une liste vide qui le DIT ; si une page est illisible, on rend
l'erreur, pas un placeholder.

## Configuration (env)

| Variable | Défaut | Rôle |
|---|---|---|
| `SEARXNG_URL` | `http://searxng:8080` | métamoteur souverain (conteneur voisin) |
| `BROWSER_DDG` | `1` | repli DuckDuckGo sans-infra (`0` = éteint) |
| `BROWSER_PROVIDERS` | _(vide)_ | force/ordonne les moteurs (CSV), sinon tous les configurés |
| `TAVILY_API_KEY` … `BING_API_KEY` | _(vide)_ | active les moteurs à clé |
| `BROWSER_STARTER_BLOCKLIST` | `0` | `1` = active la blocklist propagande/désinfo |
| `BROWSER_BLOCKLIST` / `BROWSER_ALLOWLIST` | _(vide)_ | CSV de domaines ; `BROWSER_ALLOWLIST_MODE` = `off`/`boost`/`strict` |
| `BROWSER_MAX_OCTETS` / `BROWSER_TIMEOUT` / `BROWSER_ROBOTS` | 3 Mo / 25 s / `1` | garde-fous de `page_lire` |

> Les anciennes variables `RECHERCHE_*` restent acceptées en repli (compat).

## Tests

```bash
cd briques/browser && python3 -m pytest -q   # 25 tests offline, sans réseau
```

## Provenance

Moteur porté de `backend/plugins/browser` (HuntR) de Gungnir, plugin Python intégré au
backend monolithique, **réemballé en brique Workplace autonome** (service Docker + manifest
auto-découvert). La dépendance au cœur Gungnir (`web_fetch.web_search_lite`) a été remplacée
par un client DuckDuckGo souverain local (`ddg_lite.py`). La lecture de page reprend
l'extraction Trafilatura souveraine de l'ancienne brique `recherche`.
