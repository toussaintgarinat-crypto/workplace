# Sprint S142 — Taxonomie des briques : 7 familles + dashboard organisé

> **But du sprint** : ajouter un champ `famille` dans chaque `manifest.json` de brique,
> puis utiliser ce champ dans le dashboard du Cœur pour afficher les briques par famille
> plutôt qu'en liste plate. Rend Workplace lisible d'un coup d'œil pour un nouvel utilisateur
> ou un client.

- **Sprint** : S142
- **Catégorie** : UX / architecture
- **Statut** : ✅ LIVRÉ (2026-07-04)
- **Date de planification** : 2026-07-03
- **Briques concernées** : toutes (29 manifestes) + `core/` (dashboard)

---

## Contexte

Aujourd'hui le Cœur lit les `manifest.json` et affiche les briques dans l'ordre
alphabétique. Il y a 29 briques et ce nombre va croître. Sans organisation, le dashboard
devient une longue liste incompréhensible.

Les manifestes ont un champ `role` (granulaire, 1 rôle par brique) mais pas de champ
`famille` (regroupement). L'audit du 2026-07-03 a identifié 7 familles naturelles.

---

## Les 7 familles proposées

| Famille | Slug | Briques |
|---|---|---|
| Socle IA | `ia` | gateway, memoire, forge, recherche |
| Ingestion & Analyse | `ingestion` | etl, audit, vision |
| Génération & Livraison | `generation` | generateur, app-builder, noyau |
| Collaboration & Communication | `collaboration` | oria, mail, voix, telephonie, transcription, ecoute |
| Média & Contenu | `media` | peertube, video, synopsis, images, studio |
| Applications Métier | `metier` | restaurant, agenda, paiements, calcul, connexion, personnages |
| Persistance & Dev | `dev` | donnees, dev |

---

## Chantiers

### C0 — Ajouter le champ `famille` dans chaque manifest.json

Modifier les 29 fichiers `briques/*/manifest.json` en ajoutant :

```json
{
  "nom": "gateway",
  "famille": "ia",
  ...
}
```

Correspondance complète :

| Brique | famille |
|---|---|
| gateway | `ia` |
| memoire | `ia` |
| forge | `ia` |
| recherche | `ia` |
| etl | `ingestion` |
| audit | `ingestion` |
| vision | `ingestion` |
| generateur | `generation` |
| app-builder | `generation` |
| noyau | `generation` |
| oria | `collaboration` |
| mail | `collaboration` |
| voix | `collaboration` |
| telephonie | `collaboration` |
| transcription | `collaboration` |
| ecoute | `collaboration` |
| peertube | `media` |
| video | `media` |
| synopsis | `media` |
| images | `media` |
| studio | `media` |
| restaurant | `metier` |
| agenda | `metier` |
| paiements | `metier` |
| calcul | `metier` |
| connexion | `metier` |
| personnages | `metier` |
| donnees | `dev` |
| dev | `dev` |

### C1 — Définir les métadonnées d'affichage des familles dans le Cœur

Dans `core/` (ou un fichier de config dédié), déclarer les familles avec leur label,
icône et ordre d'affichage :

```python
FAMILLES = [
    {"slug": "ia",            "label": "Socle IA",                   "icone": "🧠", "ordre": 1},
    {"slug": "ingestion",     "label": "Ingestion & Analyse",         "icone": "📄", "ordre": 2},
    {"slug": "generation",    "label": "Génération & Livraison",      "icone": "🏗️", "ordre": 3},
    {"slug": "collaboration", "label": "Collaboration & Communication","icone": "💬", "ordre": 4},
    {"slug": "media",         "label": "Média & Contenu",             "icone": "🎬", "ordre": 5},
    {"slug": "metier",        "label": "Applications Métier",         "icone": "🏢", "ordre": 6},
    {"slug": "dev",           "label": "Persistance & Dev",           "icone": "🛠️", "ordre": 7},
]
```

Fichier proposé : `core/familles.py` (ou directement dans `core/registre.py` si ce fichier
existe).

### C2 — Modifier l'endpoint `/briques` du Cœur pour grouper par famille

Ajouter un paramètre `?grouper=famille` à l'endpoint existant (rétrocompatible) :

```
GET /briques              → liste plate (comportement actuel)
GET /briques?grouper=famille → dict groupé par famille
```

Réponse groupée :
```json
{
  "ia": {
    "label": "Socle IA",
    "icone": "🧠",
    "briques": [{"nom": "gateway", ...}, {"nom": "forge", ...}]
  },
  "collaboration": {
    "label": "Collaboration & Communication",
    "icone": "💬",
    "briques": [...]
  }
}
```

### C3 — Mettre à jour le dashboard HTML du Cœur

Dans le template HTML de `core/` (ou le front React si le Cœur en a un) :

- Remplacer la liste plate par des **sections par famille** avec titre + icône
- Chaque famille est un accordéon ou un groupe de cartes
- Les briques inactives (`statut != "actif"`) sont affichées en grisé dans leur famille,
  pas cachées (permet de voir ce qui est prévu)

Maquette (ASCII) :
```
┌─────────────────────────────────────────────┐
│ 🧠 Socle IA                          [4/4] │
│  ✅ gateway  ✅ memoire  ✅ forge  ✅ recherche │
├─────────────────────────────────────────────┤
│ 📄 Ingestion & Analyse               [3/3] │
│  ✅ etl  ✅ audit  ⬜ vision                │
├─────────────────────────────────────────────┤
│ 💬 Collaboration & Communication     [2/6] │
│  ✅ oria  ✅ mail  ⬜ voix  ⬜ telephonie…  │
└─────────────────────────────────────────────┘
```

### C4 — (Optionnel) Ajouter `famille` à la réponse de `/sante-globale`

Pour que l'assistant (Jarvis) puisse dire « la famille Socle IA est entièrement opérationnelle »
plutôt que lister brique par brique.

---

## Critère d'acceptation

- Tous les `manifest.json` ont le champ `famille`
- Le dashboard Cœur affiche les briques groupées par famille avec icône et label
- `GET /briques?grouper=famille` renvoie la structure groupée
- Une brique nouvellement ajoutée sans `famille` ne fait pas planter le Cœur (fallback `"autre"`)

---

## Effort estimé

**1 journée** (principalement C0 + C3 qui sont les plus visibles).
- C0 (manifestes) : 30 min — éditions JSON répétitives
- C1 (config familles) : 15 min
- C2 (endpoint groupé) : 1h
- C3 (dashboard) : 2h
- C4 (sante-globale) : 30 min

## Valeur

Rend Workplace compréhensible en 5 secondes pour n'importe qui qui ouvre le dashboard.
Essentiel pour les démos clients et pour la montée en charge (on passe de 29 à potentiellement
50+ briques).
