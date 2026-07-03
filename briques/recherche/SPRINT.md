# Épopée S135→S139 — Amélioration brique `recherche`

> Audit du : 2026-07-03  
> Port : 6040  
> Fichiers concernés : `main.py`, `cache.py`, `search_providers.py`, `ddg_lite.py`, `extraction.py`  
> Suite de : S134 (migration outils statiques → manifests)

---

## Contexte

La brique est solide dans son architecture (9 moteurs, consensus, Trafilatura, filtres source),
mais 5 problèmes ont été identifiés lors de l'audit : du code mort (cache non branché),
des données utiles non exposées (score), un paramètre ignoré (langue), et deux fonctionnalités
manquantes (synthèse LLM, lecture de pages JS/SPA).

---

## S135 — Brancher le cache *(~30 min)*

**Problème** : `cache.py` contient une `TavilyCache` complète (TTL, LRU, 500 entrées) mais
`main.py` ne l'importe jamais. Chaque requête identique refait tous les appels réseau,
grille les quotas gratuits inutilement et ralentit les réponses.

**Solution** : créer un `RechercheCache` générique (pas spécifique à Tavily) dans `cache.py`
et l'appeler dans l'endpoint `/rechercher` avant de lancer `multi_search`.

**Clé de cache** : `(requete_normalisée, topic, n, providers_actifs_triés)`  
**TTL** : configurable via `RECHERCHE_CACHE_TTL` — défaut 1800 s (30 min).  
**Invalidation** : si les providers actifs changent (redémarrage, env), le cache se vide
naturellement (la clé inclut les providers).

**Fichiers** : `cache.py` (refacto), `main.py` (import + appel)

---

## S136 — Exposer le score de consensus dans la réponse *(~15 min)*

**Problème** : `multi_search()` calcule un score de consensus (nombre de providers × poids ×
1/rang) pour classer les résultats, mais ce score n'est **pas inclus dans la réponse API**.
L'UI et le LLM ne peuvent pas distinguer un résultat trouvé par 5 moteurs d'un trouvé par 1.

**Solution** : ajouter deux champs à chaque résultat dans `/rechercher` :
- `"score"` : float arrondi à 3 décimales (le score de consensus normalisé)
- `"nb_providers"` : int — combien de moteurs ont retourné cet URL

**Fichiers** : `search_providers.py` (SearchResult + multi_search), `main.py` (sortie dict)

---

## S137 — Transmettre la langue aux providers *(~1h)*

**Problème** : le paramètre `langue` est documenté dans le manifest et accepté par l'API,
mais dans `main.py` il est reçu et… ignoré. Il n'est transmis à aucun provider.
Résultat : une recherche `langue="en"` retourne quand même des résultats français.

**Solution** : passer `langue` à chaque provider qui le supporte :

| Provider | Paramètre |
|---|---|
| DDG (ddg_lite) | `kl` (ex. `fr-fr`, `en-us`) — déjà présent mais codé en dur `fr-fr` |
| SearXNG | `language` dans les params GET |
| Brave | `country` (ex. `fr`, `us`) |
| Bing | `mkt` (ex. `fr-FR`, `en-US`) |
| Tavily | ajouter `search_lang` |
| Serper | `hl` (déjà `fr` codé en dur → rendre dynamique) |
| SerpAPI | `hl` (déjà `fr` codé en dur → rendre dynamique) |

**Fichiers** : `main.py`, `search_providers.py` (signature + corps des providers), `ddg_lite.py`

---

## S138 — Endpoint `/synthétiser` *(~2h)*

**Problème** : la brique renvoie des liens et snippets bruts. L'assistant (Jarvis / forge)
doit recevoir cette liste et faire lui-même le travail de synthèse, sans aucune aide de la
brique. Pour les cas d'usage "donne-moi la réponse directement", c'est un aller-retour
inutile.

**Solution** : nouvel endpoint `POST /synthétiser` qui enchaîne :
1. `multi_search(...)` — récupère les résultats comme `/rechercher`
2. Formate les N premiers snippets en contexte
3. Appelle le gateway LLM (`http://gateway:4001`) avec le contexte + la requête
4. Retourne la synthèse en langage naturel + les sources utilisées

**Corps de requête** :
```json
{
  "requete": "...",
  "n": 8,
  "topic": "web",
  "langue": "fr",
  "instructions": "Réponds en 3 points clés avec les sources."
}
```

**Réponse** :
```json
{
  "requete": "...",
  "synthese": "Voici ce que j'ai trouvé...",
  "sources": [{"titre": "...", "url": "...", "provider": "brave"}],
  "backend": "brave,duckduckgo",
  "nb_sources": 5
}
```

**Si gateway indisponible** : retour gracieux avec les résultats bruts + `"synthese": null`.

**Fichiers** : `main.py` (nouveau endpoint), nouveau fichier `synthese.py`

---

## S139 — Lecture des pages JS/SPA *(~demi-journée)*

**Problème** : `extraction.py` lit le HTML statique brut. Les sites Next.js, React SPA, etc.
retournent un squelette HTML quasi-vide côté serveur — Trafilatura extrait alors moins de
300 caractères. La brique le retourne honnêtement, mais c'est inutile pour l'assistant.

**Solution** : ajout d'un mode Playwright optionnel dans `/lire-page` :

- **Détection automatique** : si le texte extrait est < 300 chars ET que Playwright est
  disponible → retry silencieux avec headless Chromium.
- **Paramètre explicite** : `"js": true` dans le corps pour forcer Playwright.
- **Opt-in infra** : Playwright n'est installé que si `RECHERCHE_PLAYWRIGHT=1` dans l'env
  (allège l'image Docker de base).

**Fichiers** : `extraction.py`, `requirements.txt`, `Dockerfile`, `docker-compose.yml`, `main.py`

---

## Ordre d'exécution

```
S135 (cache)  →  S136 (score)  →  S137 (langue)  →  S138 (synthèse)  →  S139 (SPA)
   30 min           15 min            1h                  2h             demi-journée
```

S135 et S136 sont des quick wins sans risque — ils ne changent pas les contrats API.  
S137 est un changement de signature → vérifier que les appelants passent bien `langue`.  
S138 ajoute un endpoint → il faut que le gateway tourne (`make up` dans `briques/gateway`).  
S139 est le plus risqué (image Docker plus lourde) → à faire en dernier, en branche séparée.

---

## Tests à lancer après chaque sprint

```bash
cd /Users/garinat_t/Desktop/Workplace/briques/recherche

# S135
python -m pytest test_api.py -k "cache" -v

# S136
curl -s -X POST http://localhost:6040/rechercher \
  -H "Content-Type: application/json" \
  -d '{"requete":"test","n":3}' | python3 -m json.tool | grep -E "score|nb_providers"

# S137
curl -s -X POST http://localhost:6040/rechercher \
  -H "Content-Type: application/json" \
  -d '{"requete":"latest news","n":3,"langue":"en"}' | python3 -m json.tool

# S138
curl -s -X POST http://localhost:6040/synthétiser \
  -H "Content-Type: application/json" \
  -d '{"requete":"qu est-ce que FastAPI","n":5}' | python3 -m json.tool

# S139
curl -s -X POST http://localhost:6040/lire-page \
  -H "Content-Type: application/json" \
  -d '{"url":"https://react.dev","js":true}' | python3 -m json.tool
```
