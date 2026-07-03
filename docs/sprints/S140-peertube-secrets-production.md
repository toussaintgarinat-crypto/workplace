# Sprint S140 — PeerTube : secrets de production à changer avant activation

> **But du sprint** : remplacer les credentials par défaut de la brique PeerTube
> (`workplace2026`, `peertube_secret`, `changeme_min_32_chars_PLEASE_SET`) par des valeurs
> uniques et fortes, avant toute exposition réseau de la brique.

- **Sprint** : S140
- **Catégorie** : Sécurité
- **Statut** : À planifier (bloquer avant mise en production de la brique PeerTube)
- **Date de planification** : 2026-07-03
- **Brique concernée** : `briques/peertube/`

---

## Contexte

La brique PeerTube (`chocobozzz/peertube:v7.2.2-bookworm`) est un hébergeur vidéo
souverain. Son `docker-compose.yml` contient trois valeurs par défaut problématiques :

| Variable | Valeur par défaut | Risque |
|---|---|---|
| `PEERTUBE_SECRET` | `changeme_min_32_chars_PLEASE_SET` | Clé de chiffrement des sessions — si inchangée, n'importe qui peut forger des tokens |
| `PEERTUBE_ADMIN_PASSWORD` | `workplace2026` | Mot de passe admin connu, visible dans le dépôt |
| `POSTGRES_PASSWORD` | `peertube_secret` | Mot de passe DB visible dans le dépôt |

Ces valeurs sont aussi dans `.env.example` peertube, ce qui les rend facilement devinables.

La brique est configurée avec `restart: unless-stopped` et expose les ports `9000` et `1935`.
Si elle est accessible sur le réseau local (HP Proxmox), ces credentials permettent un accès
admin immédiat.

---

## Chantiers

### C0 — Créer le `.env` peertube avec des valeurs fortes

Créer `briques/peertube/.env` (ce fichier est dans `.gitignore`) :

```bash
# Générer des valeurs fortes
PEERTUBE_SECRET=$(openssl rand -hex 32)
PEERTUBE_ADMIN_PASSWORD=$(openssl rand -base64 20 | tr -d '=+/')
POSTGRES_PASSWORD=$(openssl rand -hex 24)
PEERTUBE_ADMIN_USER=admin
```

Coller ces valeurs dans `briques/peertube/.env` et les noter dans un gestionnaire de mots
de passe (Bitwarden, 1Password…).

### C1 — Mettre à jour `.env.example` peertube

Remplacer les valeurs actuelles par des placeholders clairs qui ne ressemblent pas à de
vrais mots de passe :

```diff
- PEERTUBE_SECRET=changeme_en_production_32_chars_min
+ PEERTUBE_SECRET=GENERER_openssl_rand_-hex_32

- PEERTUBE_ADMIN_PASSWORD=workplace2026
+ PEERTUBE_ADMIN_PASSWORD=GENERER_mot_de_passe_fort

- POSTGRES_PASSWORD=peertube_secret
+ POSTGRES_PASSWORD=GENERER_openssl_rand_-hex_24
```

### C2 — Vérifier le tag postgres:13-alpine

La brique utilise `postgres:13-alpine` (tag non épinglé au patch). Vérifier la matrice de
compatibilité PeerTube v7.2.2, puis épingler à la version exacte.

PeerTube supporte PostgreSQL 13, 14, 15, 16 (voir docs officiels). Recommandé : migrer vers
`postgres:16.14-alpine` (même version que les autres briques Workplace) pour éviter de
maintenir deux versions de Postgres différentes.

```diff
- image: postgres:13-alpine
+ image: postgres:16.14-alpine
```

⚠️ Ce changement nécessite une migration des données si un volume PeerTube existe déjà.
Si le volume est vide (première installation), c'est transparent.

### C3 — Vérifier que PEERTUBE_WEBSERVER_HOSTNAME est correct

Dans le compose, `PEERTUBE_WEBSERVER_HOSTNAME=192.168.1.89` est en dur. Si l'IP du HP
change ou si la brique est déployée ailleurs, les URLs des vidéos seront cassées.

Remplacer par une variable :
```yaml
- PEERTUBE_WEBSERVER_HOSTNAME=${PEERTUBE_HOST:-192.168.1.89}
```

---

## Critère d'acceptation

- `briques/peertube/.env` existe avec des valeurs fortes (non committé)
- `.env.example` ne contient plus `workplace2026` ni `peertube_secret`
- Connexion admin PeerTube (`http://HP:9000`) avec le nouveau mot de passe fonctionnelle

---

## Effort estimé

**1 heure.** Génération de secrets + mise à jour des fichiers.

## Risque si non fait

Accès admin PeerTube avec `workplace2026` depuis n'importe quelle machine du réseau local.
Chiffrement des sessions avec une clé connue publiquement (dans ce dépôt).
