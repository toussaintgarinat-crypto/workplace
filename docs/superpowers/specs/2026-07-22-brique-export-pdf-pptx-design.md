# Brique export (PDF + PPTX) — design

Statut : **validé avec l'utilisateur le 2026-07-22**.

Origine : veille du dépôt `nexu-io/open-design` (2026-07-22) — trou identifié : aucune
génération PDF ni PPTX nulle part dans le repo, alors que plusieurs usages potentiels
existent déjà (export livre Studio, deck de présentation Forge, rapports internes
`docs/*.md`). Cf. mémoire `veille-projets-github-2026-07` pour le reste de l'évaluation
du projet (le reste ne recoupe rien de neuf : MCP server, multi-fournisseurs, habillage
vidéo déterministe sont déjà couverts par le Gateway/S74/S188).

## But

Ajouter une capacité d'export PDF et PPTX **générique et réutilisable**, sous forme d'une
nouvelle brique autonome, plutôt qu'une implémentation ad hoc par consommateur. Les trois
usages identifiés (livre Studio, deck Forge, rapports internes) partagent le même besoin
de rendu — pas de raison de le dupliquer trois fois.

## Décisions validées avec l'utilisateur

- **Cas d'usage** : les trois à la fois (livre Studio, deck Forge, rapports internes), pas
  un seul prioritaire — d'où le choix d'une capacité générique plutôt qu'un export
  spécifique à un consommateur.
- **Formats** : PDF et PPTX **en même temps** dès ce sprint (pas de séquencement).
- **Emplacement** : nouvelle brique dédiée `briques/export/`, sur le modèle des briques
  service existantes (`video`, `images`, `voix`) — pas de duplication par consommateur, pas
  de module partagé dans `core/` (romprait l'isolation par brique/conteneur).
- **Techno de rendu** : **WeasyPrint** (Markdown→HTML→PDF) + **python-pptx** (diapositives
  structurées→PPTX). 100% Python, pas de navigateur headless. Choisi contre Chromium
  headless (image Docker +300-500 Mo, empreinte RAM risquée — cf. incidents RAM déjà vécus
  sur le HP avec Coqui XTTS-v2 et le blocage VoxCPM2, mémoire `sprint-s188-s192-pistes-
  veille-github`) et contre LibreOffice headless (paquet Debian complet, démarrage lent,
  fragile en conteneur). Cohérent avec l'esprit S188 (habillage vidéo ffmpeg) : rendu
  déterministe, local, sans IA ni coût.

## Architecture

Brique HTTP autonome `briques/export/`, port **6150** (suite de la numérotation des ports
de briques, après `veille-prospection`/6140). Service appelé par les briques
consommatrices (Studio, Forge, scripts de rapports) via HTTP interne, comme tout autre
service de la stack — aucun import Python direct entre briques.

## Composants

- **`rendu_pdf.py`** — convertit du Markdown en HTML (`python-markdown`) puis en PDF via
  WeasyPrint. Deux thèmes CSS embarqués, choisis par nom :
  - `livre` : typographie roman, grandes marges, pas d'en-tête/pied de page.
  - `rapport` : en-tête/pied de page, numérotation de page, mise en page plus dense.
- **`rendu_pptx.py`** — convertit une liste de diapositives structurées (titre + points
  à puces + notes optionnelles) en PPTX via python-pptx. Un thème v1 : `sobre` (texte
  seul, pas d'images ni de graphiques générés).
- **`main.py`** — endpoints FastAPI (voir contrat ci-dessous) + `GET /sante` (health check
  standard de toutes les briques) + `GET /fichiers/{nom}` (sert les fichiers produits,
  même convention que `video`/`images`).
- **`manifest.json`** — capacités LLM `export_pdf` et `export_pptx`, niveau 0,
  `action:true` (ÉCRIVENT un fichier → gardées par la porte de confirmation, comme toute
  capacité qui écrit — cf. `GUIDE-ajouter-une-brique.md` §2 ; correction par rapport à la
  version initiale de ce document, qui disait `action:false` à tort : le précédent réel,
  `video_carte_titre`/`video_sous_titrer` en S188, a bien `action:true` malgré l'absence
  de coût/IA).
- **`Dockerfile`** — `python:3.12-slim` + dépendances système WeasyPrint (Pango, Cairo,
  GDK-Pixbuf, polices de base) via `apt-get`. Pas de Chromium, pas de ffmpeg.

## Sécurité

Même convention que les autres briques service (`video`, `images`, `voix`) : `API_KEYS`
(CSV via env, `Depends(cle_api)` sur chaque endpoint d'écriture) + `CORS_ORIGINS` (CSV via
env, défaut `*` en dev). Pas de notion multi-tenant/`X-User-Id` ici — la brique ne stocke
aucune donnée persistante liée à un utilisateur, elle rend un fichier à la demande et le
sert une fois (pas de base de données d'export par personne en v1).

## Contrat d'entrée/sortie

```
POST /pdf
  { "titre": str, "markdown": str, "theme": "livre" | "rapport" }
  → { "fichier": str, "url": "/fichiers/<nom>.pdf" }

POST /pptx
  { "titre": str,
    "diapositives": [ { "titre": str, "points": [str], "notes": str? } ],
    "theme": "sobre" }
  → { "fichier": str, "url": "/fichiers/<nom>.pptx" }

GET /fichiers/{nom}
  → fichier binaire (PDF ou PPTX)
```

Pas de CSS arbitraire fourni par l'appelant en v1 — seulement les thèmes nommés
ci-dessus. Ajouter un thème = ajouter un fichier CSS/gabarit dans la brique, pas un
paramètre d'injection libre. Cohérent avec le refus déjà tranché sur les abstractions
prématurées (registre pluggable refusé en S192, YAGNI tant qu'un vrai second besoin
n'existe pas).

## Gestion d'erreurs

- `titre` ou `markdown`/`diapositives` vide ou absent → `422` (validation Pydantic native
  FastAPI).
- Thème inconnu → `422` (valeur hors énumération autorisée).
- Échec de rendu interne (WeasyPrint/python-pptx lève une exception) → `400` avec message
  d'erreur clair, jamais un `500` opaque — même convention que les autres briques.

## Tests

100% offline, aucune dépendance réseau (aucun fournisseur externe à mocker, contrairement
à `video`/`voix`/`images`) :
- `POST /pdf` avec un Markdown valide → fichier produit commence par l'en-tête `%PDF`,
  relisible (page count > 0).
- `POST /pptx` avec des diapositives valides → fichier produit est une structure OOXML
  valide, relisible par `python-pptx` en relecture (nombre de diapos = nombre attendu,
  texte retrouvé).
- Cas d'erreur : entrée vide → 422 ; thème inconnu → 422.
Même esprit de vérification « fichier réel valide » que `test_habillage.py` (qui vérifie
via `ffprobe` que le MP4 produit est un vrai MP4 H.264).

## Hors périmètre v1 (suites possibles, pas ce sprint)

- Brancher un bouton « Exporter en PDF » sur `/atelier/series/{id}/livre` (Studio) qui
  appelle `POST /pdf` avec le Markdown déjà produit par cet endpoint.
- Construire, côté Forge, le JSON de diapositives à partir des données d'un bundle
  client, pour un deck de présentation.
- Un script ou une capacité qui convertit `docs/*.md` (rapports/sprints) en PDF à la
  demande.
- CSS personnalisé fourni par l'appelant, si un thème nommé de plus ne suffit pas un jour.
- Images/graphiques dans les PPTX (v1 = texte seul).

Chacun de ces branchements est indépendant et peut être fait dans un sprint séparé une
fois la brique `export` elle-même testée et déployée — même pattern que S188 (« reste
optionnel : brancher l'appel depuis le Studio »).
