# Brique `recherche` — recherche web + lecture de page (port 6040)

« Les yeux du Cœur sur le web ». Deux gestes composables, **souverains par défaut**,
exposés comme **capacités auto-découvertes** (le Cœur les transforme en outils du LLM via
le manifest, sans aucune ligne de code côté Cœur) :

| Capacité       | Endpoint       | Rôle |
|----------------|----------------|------|
| `recherche_web`| `POST /rechercher` | une requête → **liens classés cliquables** (titre, url, extrait) |
| `page_lire`    | `POST /lire-page`  | une URL → **texte principal nettoyé + liens** de la page (pour résumer en gardant les sources) |

Le couple est pensé pour l'usage agent : *cherche → choisis une source → lis-la → résume
en citant les liens*.

## Souveraineté & repli honnête

**Recherche** (cf. `fournisseurs.py`, cascade configurable par `RECHERCHE_PROVIDERS`) :

1. **`searxng`** — métamoteur [SearXNG](https://docs.searxng.org/) auto-hébergé (conteneur
   voisin, **0 clé**), agrège Google/Bing/DDG/Wikipédia… et rend du JSON propre. Défaut.
2. **`duckduckgo`** — repli **zéro-infra** : scraping de la page HTML « lite » de DDG.
   Fragile (pas d'API officielle), mais ni conteneur ni clé. Filet de sécurité.
3. **`tavily`** — API à clé (`TAVILY_API_KEY`), **inerte** sans clé. Matérialise l'extension
   « fournisseur payant par tenant » (Brave, Serper… suivront le même contrat).

**Lecture de page** (cf. `extraction.py`) : extraction **locale** via Trafilatura (repli
nettoyage HTML basique si absent), **bornée** en taille (`RECHERCHE_MAX_OCTETS`, 3 Mo) et
temps (`RECHERCHE_TIMEOUT`), **polie** (respecte `robots.txt`, opt-out `RECHERCHE_ROBOTS=0`),
**sans rendu JavaScript** en v1.

> Honnêteté : aucun lien inventé, aucun faux texte. Sans moteur configuré, `/rechercher`
> rend une liste vide qui le **dit** ; une page illisible rend une erreur, pas un placeholder.

## Démarrage

```bash
docker compose up -d        # lance la brique (6040) + le conteneur SearXNG (interne)
curl -s localhost:6040/sante | jq
curl -s localhost:6040/rechercher -H 'content-type: application/json' \
     -d '{"requete":"sobriété numérique","n":5}' | jq
curl -s localhost:6040/lire-page -H 'content-type: application/json' \
     -d '{"url":"https://fr.wikipedia.org/wiki/Logiciel_libre"}' | jq '.titre, .nb_caracteres'
```

## Image SearXNG

Le conteneur tierce est **épinglé en dur** dans `docker-compose.yml`
(`searxng/searxng:2026.6.22-952896d29`) — pas via une variable d'env : le lanceur fait
`cd dossier && docker compose up -d` sans sourcer le `.env` racine, donc un
`${SEARXNG_TAG:-…}` retomberait toujours sur son défaut (piège « env shadow »). Pour
mettre à jour : `docker pull searxng/searxng:latest`, relever le `DOCKER_TAG`
(`docker inspect … org.opencontainers.image.version`) et changer la ligne `image:`.

## Réglages (env, tous facultatifs)

| Variable | Défaut | Rôle |
|----------|--------|------|
| `SEARXNG_URL` | `http://searxng:8080` | URL interne du métamoteur |
| `SEARXNG_SECRET` | dev | secret de signature SearXNG (à définir en prod) |
| `RECHERCHE_PROVIDERS` | (ordre par défaut) | force l'ordre des moteurs |
| `RECHERCHE_DDG` | `1` | active le repli DuckDuckGo |
| `TAVILY_API_KEY` | (vide) | active le moteur Tavily |
| `RECHERCHE_MAX_OCTETS` | `3145728` | taille max d'une page lue |
| `RECHERCHE_ROBOTS` | `1` | respecte `robots.txt` |
| `API_KEYS` | (vide = ouvert) | clés acceptées (`X-API-Key`) |

## Tests

```bash
pytest -q   # offline : parseurs purs (SearXNG/DDG/Tavily), extraction, API en repli honnête
```
