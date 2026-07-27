# Guide — ajouter une brique à Workplace

> **À qui ça sert** : tu veux ajouter un service métier (un produit autonome) et le rendre
> pilotable par l'assistant du Cœur **sans écrire une ligne de code dans le Cœur**. C'est le
> contrat de l'architecture « noyau + briques » (cf. `WORKPLACE.md` §3).
>
> **Principe non négociable** : une brique est **autonome** (démarre seule, a son `docker-compose`,
> son port, sa santé). Le Cœur ne la connaît pas en dur : il la **découvre** via son `manifest.json`.

## 0. Le contrat en une phrase
Une brique = **un dossier `briques/<nom>/`** qui contient (au minimum) un `manifest.json`, un
`Dockerfile`, un `docker-compose.yml` et un service HTTP exposant un endpoint de santé.
Le Cœur la branche automatiquement si le manifest est bien formé.

## 1. Le `manifest.json` — la carte d'identité
C'est le seul fichier que le Cœur lit. Champs **requis** (validés hors-ligne par
`tests/test_briques_smoke.py`, le filet S116) :

```json
{
  "nom": "ma_brique",
  "version": "0.1.0",
  "description": "Ce que fait la brique, en une phrase honnête.",
  "role": "ma_brique",
  "couche": "backend",
  "statut": "a_tester",
  "port": 6100,
  "url_sante": "http://host.docker.internal:6100/sante",
  "depends_on": [],
  "capacites": []
}
```

Règles vérifiées par le filet (à respecter, sinon échec smoke) :
- `couche: "backend"` ⇒ `port` **et** `url_sante` obligatoires, et `url_sante` doit **encoder le
  port** (`:6100`). `couche: "frontend"` est exempté (UI statique, port `null` toléré).
- **Aucune collision de port** entre briques (piège connu images/dev sur 5950) — choisis un port
  libre. Convention actuelle : 5xxx/6xxx, voir la liste dans `Lancer Workplace.command`.
- `nom` unique dans tout le registre.
- **Le chemin de santé est `/sante`** (S207). C'est la convention du parc : une sonde écrite
  d'après elle doit trouver ta brique. Si tu sers déjà `/health` (héritage, service tiers),
  expose les DEUX — `@router.get("/health")` + `@router.get("/sante")` sur la même fonction,
  motif `core/routers/systeme.py` — et ne retire jamais l'ancien chemin : les healthchecks
  Docker pointent dessus. Seule exception admise à ce jour : `gateway`, image LiteLLM
  officielle dont on ne peut pas ajouter de route (elle est nommée dans
  `tests/test_briques_smoke.py::EXCEPTIONS_SANTE`).

## 2. Rendre la brique pilotable par l'assistant — les `capacites`
C'est **le** mécanisme déclaratif (le plus simple, **zéro code Cœur**). Chaque entrée de
`capacites` devient un **outil du LLM** que le Cœur fabrique tout seul à partir du manifest
(`core/catalogue.py::collecter_capacites`). Champs **requis** : `nom` et `chemin`.

```json
"capacites": [
  {
    "nom": "ma_brique_etat",
    "description": "Décris PRÉCISÉMENT quand l'assistant doit appeler ça (le LLM choisit là-dessus).",
    "methode": "GET",
    "chemin": "/sante",
    "params": {},
    "action": false
  },
  {
    "nom": "ma_brique_faire",
    "description": "Une action qui modifie l'état. À n'appeler qu'après accord explicite.",
    "methode": "POST",
    "chemin": "/faire",
    "params": {
      "cible": { "type": "string", "description": "Sur quoi agir." }
    },
    "action": true
  }
]
```

- `action: true` ⇒ l'outil est **gardé par la porte de confirmation** du Cœur : refus tant que
  l'utilisateur n'a pas confirmé (cf. `GUIDE-ajouter-un-outil.md`). Toute capacité qui **écrit**
  doit avoir `action: true`.
- `action: false` ⇒ lecture, exécutable directement.
- `niveau` (optionnel, défaut 0) : `0` = toujours visible du LLM ; `≥1` = **différé** derrière
  `competence_charger` (divulgation progressive S90, pour ne pas noyer le contexte).
- Le Cœur appelle la capacité en **HTTP** à `url_sante`-base + `chemin`. Seuls les contrats
  **JSON** sont déclarables ainsi (le passe-plat `_appel_dynamique` ne sait que le JSON). Un flux
  binaire (audio, multipart) reste appelé en direct par son client, pas déclaré comme outil texte.

> Convention de nommage : préfixe les capacités par le nom de la brique (`ma_brique_*`) pour éviter
> les collisions — `collecter_capacites` + `doublons()` détectent les noms partagés.

## 3. Dockerfile & shared/ — si la brique a besoin des libs partagées
Le monorepo a une **lib partagée** `shared/` (client Gateway `llm_client`, auth `workplace_auth`,
schémas). **Si** ta brique l'importe (`import shared.llm_client`), le **build-context** doit être la
**racine** du repo (pattern triplement prouvé S118/S119/S120) :

```yaml
# briques/ma_brique/docker-compose.yml
services:
  ma_brique:
    build:
      context: ../..                       # ← la RACINE, pas le dossier brique
      dockerfile: briques/ma_brique/Dockerfile
    ...
```
```dockerfile
# briques/ma_brique/Dockerfile
COPY shared/ /app/shared/                  # la lib partagée
COPY briques/ma_brique/ /app/             # le code de la brique
RUN pip install -r requirements.txt -c constraints-workplace.txt   # versions alignées S117
```
Pour les **tests natifs** (hors conteneur), ajoute un `conftest.py` dans la brique qui met la
racine sur `sys.path` (motif déjà présent dans donnees/agenda/generateur).

> **Si ta brique n'importe PAS `shared/`** : garde le build-context local classique
> (`context: .`), c'est plus léger. N'adopte le contexte racine que sur besoin réel.

Aligne tes dépendances d'infra sur `constraints-workplace.txt` (fastapi/httpx/pydantic/uvicorn… —
cf. `make deps-audit` détecte la dérive).

## 4. Câbler au launcher
Ajoute une ligne dans `Lancer Workplace.command` (liste `briques`), format `nom|chemin|url_sante` :
```
"ma_brique|$RACINE/briques/ma_brique|http://localhost:6100/sante"
```
Place-la **avant `core`** si le Cœur doit la découvrir au démarrage ; **après `core`** si la brique
appelle le Cœur (ex. `connexion`).

## 5. Tester & prouver
1. `make smoke` (racine) — valide le contrat manifest **hors-ligne** (champs, port, santé,
   pas de collision). Doit passer **avant** tout démarrage.
2. Démarre la brique seule : `docker compose -f briques/ma_brique/docker-compose.yml up -d --build`
   puis `curl http://localhost:6100/sante` → 200.
3. Démarre le Cœur, vérifie la découverte : `curl http://localhost:5100/capacites` doit lister
   `ma_brique_*`. Puis demande à l'assistant d'utiliser la capacité → preuve **bout-en-bout**.

> ⚠️ Piège connu (`piege-launcher-sans-rebuild`) : `up -d` **sans `--build`** sert l'ancienne image
> après un commit. Après une modif de code, rebuild la brique et bumpe son tag.

## Récapitulatif — où va quoi
| Élément | Fichier | Rôle |
|---|---|---|
| Carte d'identité | `briques/<nom>/manifest.json` | découverte + capacités (outils LLM) |
| Service | `briques/<nom>/` (FastAPI…) | le métier + `/sante` |
| Image | `briques/<nom>/Dockerfile` + `docker-compose.yml` | autonomie ; contexte racine si `shared/` |
| Démarrage | `Lancer Workplace.command` | ordre de boot + santé |
| Filet | `tests/test_briques_smoke.py` (auto) | contrat manifest validé hors-ligne |

**Tu n'as touché à AUCUN fichier du Cœur.** C'est le test : si tu as dû éditer `core/`, c'est que
ta capacité n'est pas exprimable en déclaratif — voir alors `GUIDE-ajouter-un-outil.md` (§ outil en dur).

## Recherches dans le code

La brique dev (5955) crée des snapshots de travail dans `.dev-ateliers/` (gitignoré, exclu du
build Docker). Pour ne pas tripler les résultats lors d'une recherche :

```bash
grep -r "terme" . --exclude-dir=.dev-ateliers
find . -path "./.dev-ateliers" -prune -o -name "*.py" -print
```

La variable d'env `DEV_ATELIERS` contrôle où vivent ces worktrees (voir `briques/dev/.env.example`).
