# Nouvelle brique `jeu-factions-public` — exposition publique du jeu (S220, sous-projet 4 restant)

## Contexte

Le backlog [`S216-S220-jeu-factions-sous-projets-restants.md`](../../sprints/S216-S220-jeu-factions-sous-projets-restants.md)
laissait S220 explicitement non scopé : « est-ce que jeu-factions doit un jour sortir du cercle
privé ? ». Décision (brainstorming du 2026-08-03) : **oui**, avec ambition produit réelle — pas
un test technique jetable.

Discussion de cadrage (résumé des choix tranchés, dans l'ordre où ils ont été posés) :

- **Brique séparée, pas une modification de `jeu-factions`.** `briques/jeu-factions/` reste
  intacte pour le cercle privé (Keycloak, `JEU_FACTIONS_KEY`, aucun repli — cf. spec S217). Le
  public est servi par une brique différente, `briques/jeu-factions-public/`.
- **Dans le repo Workplace, pas un dépôt Git séparé** — mais conçue pour ne **jamais** importer
  `core/` ni dépendre de Keycloak, afin qu'une extraction future (motif déjà rodé sur
  app-builder, S213) se réduise à copier le dossier de la brique.
- **Réutilisation des moteurs par copie-adaptation**, pas par appel HTTP vers `jeu-factions` ni
  réécriture from scratch : `combat_moteur.py`, `combat.py`, `archetypes.py`, `zones.py`,
  `groupes.py`, `mobs.py`, `mobs_archetype.py` sont copiés tels quels dans la nouvelle brique
  (fonctions pures/logique métier identique — rien dans ces fichiers n'est spécifique au cercle
  privé). Seuls les fichiers qui portent l'identité/l'accès (`jeton.py`, la fonction `cle_api`
  de `main.py`, `stockage.py` pour la partie comptes) divergent.
- **Identité : compte email + mot de passe**, propre à la brique — pas d'OAuth (pas de
  dépendance à un fournisseur tiers pour la V1), pas de compte anonyme (récupération de compte
  impossible sinon).
- **Hébergement : HP, exposée à part.** Même machine physique que le reste de Workplace, mais
  domaine public dédié + config Caddy séparée + base de données propre à la brique — aucun
  partage réseau ou données avec le mesh privé.
- **Exposition réelle : port-forward sur la box domicile** (confirmé explicitement par
  l'utilisateur — pas le motif `Caddyfile.duckdns` existant, qui ne résout que vers l'IP mesh
  et n'est donc joignable que par des pairs déjà enrôlés).
- **Périmètre fonctionnel V1 : parité complète** avec `jeu-factions` cercle privé — personnages,
  zones de signe (monde PvE partagé), voies d'archétype (combat joué + les 30 textes de lore
  S219), idle (S216), groupes carry (S218).
- **Anti-abus V1 : protections de base seulement** — rate limiting sur inscription/connexion,
  filtre de pseudo basique. Pas de captcha, pas de file de modération, pas de détection de
  triche avancée.
- **Scaling V1 : mono-process asyncio**, sharding par instance de combat comme aujourd'hui
  (`combat.py::capacite()`). Pas de multi-process/multi-node avant signal de charge réel.
- **Aucune intégration au dashboard du Cœur** — pas de `manifest.json`, pas de tuile. Point
  d'entrée et identité visuelle entièrement autonomes (pas `workplace.css`).

## Non-objectifs

- **Pas d'OAuth, pas de compte anonyme.** Explicitement écarté au profit d'email + mot de
  passe (cf. ci-dessus). Pourrait être ajouté dans un sprint ultérieur, pas ce spec.
- **Pas de modification de `briques/jeu-factions/`.** Zéro changement à la brique cercle privé
  existante — deux briques indépendantes qui partagent une ascendance de code, pas un lien
  d'exécution.
- **Pas d'appel réseau entre les deux briques jeu-factions.** `jeu-factions-public` n'appelle
  jamais `jeu-factions` (cercle privé) ni l'inverse. Le seul appel externe conservé est celui,
  déjà existant, vers `personnages` (5900) — serveur-à-serveur sur le même hôte, jamais exposé
  publiquement lui-même.
- **Pas de réduction fonctionnelle.** Contrairement à ce qu'un lancement public prudent
  suggérerait souvent, la décision de cadrage est la parité complète dès la V1 — pas d'idle ou
  de quêtes « à venir ».
- **Pas de scaling horizontal, pas de captcha, pas de file de modération, pas d'anti-cheat
  avancé.** Décisions de cadrage explicites, à revisiter seulement si l'audience réelle le
  justifie (cf. Contexte).
- **Pas de tuile Cœur, pas de `manifest.json`.** Décision explicite — cohérente avec « brique
  facile à sortir du repo un jour ».
- **Pas de config du routeur domicile dans ce spec.** Le port-forward est une action réseau côté
  utilisateur, hors du repo — ce spec prépare uniquement ce qui est fait depuis le repo (Caddy,
  docker-compose, brique).

## Mécanique

### Structure de la brique

`briques/jeu-factions-public/`, calquée sur `briques/jeu-factions/` :

- **Copiés tels quels** (aucune dépendance à `core/` dans ces fichiers aujourd'hui, donc rien à
  changer) : `combat_moteur.py`, `combat.py`, `archetypes.py`, `zones.py`, `groupes.py`,
  `mobs.py`, `mobs_archetype.py`, `moteur_personnages.py`.
- **Divergent** : `jeton.py` (émission locale, pas de secret partagé avec le Cœur), `stockage.py`
  (nouvelle table `comptes`, `cle_api` devient l'identifiant du compte plutôt qu'un `sub`
  Keycloak), `main.py` (routes d'inscription/connexion, `cle_api()` adaptée, pas de route `GET /`
  qui attend un jeton d'URL du Cœur), `front.html`/CSS (identité visuelle propre, page de
  connexion/inscription au lieu de « coller ta clé »/« rouvrir depuis le Cœur »).
- Port `6220` (prochain libre après `6210`, cf. `docker-compose.yml` des autres briques).

### Identité : comptes email + mot de passe

Nouveau module `jeton.py` (divergent de celui de `jeu-factions` — plus de secret partagé avec
le Cœur, la brique est son propre émetteur) :

```python
COOKIE_NOM = "jeu_factions_public_utilisateur"

def hacher_mot_de_passe(mot_de_passe: str) -> str: ...      # passlib + bcrypt (précédent : oria-stack/backend)
def verifier_mot_de_passe(mot_de_passe: str, hash_: str) -> bool: ...
def emettre(compte_id: str, ttl: int) -> str: ...            # HMAC, même mécanique que jeu-factions S217
def verifier(jeton: str | None) -> str | None: ...
```

Secret : `JEU_FACTIONS_PUBLIC_SECRET` (nouvelle variable, propre à cette brique — sans lien avec
`JEU_FACTIONS_KEY`). `bcrypt`/`passlib` : déjà des dépendances éprouvées dans le repo
(`oria-stack/oria/backend/requirements.txt`), pas une nouveauté d'infra.

**TTL du cookie : 30 jours**, pas 8h comme le motif Cœur — décision de cadrage : un produit
public n'a pas de session Keycloak amont à revalider, l'attente d'un joueur est de rester
connecté. Cookie `httponly`, `samesite=lax`, `secure=true` (le domaine public est en HTTPS,
contrairement au cercle privé qui peut tourner en HTTP interne).

**Flux :**

1. `POST /inscription` (email, mot de passe, pseudo) : crée un compte
   (`comptes.id` = UUID généré serveur, jamais l'email — évite de faire fuiter l'email dans
   `personnages_jeu.cle_api` ou les logs), hache le mot de passe, pose le cookie, retourne
   `{"ok": true}`.
2. `POST /connexion` (email, mot de passe) : vérifie, pose le cookie.
3. `POST /deconnexion` : supprime le cookie.
4. Toutes les autres routes lisent `cle_api()` depuis le cookie uniquement (même motif que
   `jeu-factions` post-S217, sans le jeton d'URL — il n'y a pas de Cœur qui construit l'URL
   ici).

### Anti-abus V1

- **Rate limiting** sur `/inscription` et `/connexion` : compteur en mémoire par IP (dict
  `{ip: [horodatages]}`, fenêtre glissante, ex. 10 tentatives / 5 minutes) — pas de nouvelle
  dépendance, cohérent avec la décision « mono-process pour la V1 » (un compteur en mémoire par
  process suffit tant qu'il n'y a qu'un process ; se réinitialise à chaque redémarrage,
  acceptable en V1).
- **Filtre de pseudo/nom de personnage** : liste statique de mots bannis, vérifiée à la création
  de compte et de personnage — rejet `422` si match, pas de file de modération.
- Les bornes de mouvement du combat sont déjà validées côté serveur dans `combat_moteur.py`
  (clamp aux limites de l'arène, `min(max(...))`) — copiées telles quelles, aucun changement
  nécessaire pour la V1.

### Scaling V1

Mono-process asyncio, sharding par instance de combat identique à `jeu-factions`
(`combat.py::capacite()` : une instance pleine en crée une nouvelle pour la même zone). Aucun
changement à cette mécanique — décision de cadrage : on mesure la charge réelle avant d'investir
dans du multi-process/multi-node.

### Exposition réseau

- Nouveau bloc Caddy (fichier séparé, ex. `outils/mesh-https/Caddyfile.jeu-factions-public`,
  **pas** une modification de `Caddyfile.duckdns` qui reste dédié au mesh privé) :
  domaine public dédié → `reverse_proxy localhost:6220`, certificat Let's Encrypt standard
  (HTTP-01, puisque cette fois le port **est** ouvert publiquement — contrairement au DNS-01
  utilisé pour le mesh privé qui n'a justement pas de port ouvert).
- `CORS_ORIGINS` réglé sur le domaine public exact (pas `"*"` — la brique cercle privé a ce
  défaut par commodité de dev, la brique publique ne doit pas l'hériter).
- Port-forward sur la box domicile (port 443 ou un port dédié → HP:443 ou HP:6220 selon ce que
  Caddy écoute) : action réseau côté utilisateur, hors de ce spec/repo.

## Modèle de données

Nouvelle table, en tête de `stockage.py` (le reste du schéma est copié tel quel depuis
`jeu-factions/stockage.py`, `cle_api` y désigne déjà une chaîne opaque — devient l'id du compte
plutôt qu'un `sub` Keycloak, sans changement de type) :

```sql
CREATE TABLE IF NOT EXISTS comptes (
    id TEXT PRIMARY KEY, email TEXT NOT NULL UNIQUE,
    mot_de_passe_hash TEXT NOT NULL, pseudo TEXT NOT NULL,
    cree_le TEXT NOT NULL
)
```

`joueurs.cle_api` / `personnages_jeu.cle_api` référencent `comptes.id` (pas de contrainte
`FOREIGN KEY` explicite — le repo n'en utilise pas ailleurs dans cette brique, cohérence avec
l'existant). Base séparée : `JEU_FACTIONS_PUBLIC_DB` (nouvelle variable, jamais le même fichier
que `JEU_FACTIONS_DB`).

Pas de `migrer_public_si_premiere_connexion` — ce mécanisme n'a de sens que pour la migration
d'un tenant partagé `"public"` vers une vraie identité (motif S217, base déjà peuplée avant
l'authentification réelle). La brique publique n'a jamais eu de tenant partagé : chaque compte
commence vide.

## Routes

**Nouvelles (auth) :**
- `POST /inscription` — `{email, mot_de_passe, pseudo}` → `201` + cookie posé, `409` si email
  déjà pris, `422` si mot de passe trop court (`>= 8` caractères) ou pseudo banni.
- `POST /connexion` — `{email, mot_de_passe}` → `200` + cookie, `401` si identifiants invalides.
- `POST /deconnexion` — supprime le cookie, `200`.

**Reprises de `jeu-factions` (contrat identique, seule l'auth change de mécanisme) :**
`POST /personnages`, `GET /personnages`, `GET /personnages/{pid}`,
`PATCH /personnages/{pid}/zone`, `GET /personnages/{pid}/competences`, `POST /presence`,
`GET /zones`, `GET /zones/{zid}`, `GET /archetypes/{archetype}/etapes`, `POST /groupes`,
`POST /groupes/{gid}/rejoindre`, `GET /zones/{zone_id}/combat` (WS),
`GET /groupes/{groupe_id}/combat` (WS). `GET /sante` reste public, sans auth.

**Retirée :** `GET /` version « lit un jeton d'URL du Cœur » — remplacée par une page d'accueil
statique qui redirige vers connexion/inscription selon la présence du cookie.

## Front

- Nouvelle page d'accueil : formulaire connexion/inscription (pas de « coller ta clé API »,
  motif déjà retiré de `jeu-factions` en S217 — cette brique ne l'a jamais eu).
- Identité visuelle propre (nouveau fichier CSS, pas `workplace.css` — décision de cadrage,
  cohérente avec « produit autonome, pas une brique Workplace visible du joueur »).
- `front_combat.html` : logique WS copiée telle quelle (le cookie est déjà là au moment de la
  connexion) ; seul le message d'erreur 401 change (« email ou mot de passe incorrect, reconnecte-toi »
  plutôt que « rouvre depuis le tableau de bord du Cœur »).

## Configuration (env)

Nouvelles variables (`.env.example`, section dédiée `jeu-factions-public`) :

- `JEU_FACTIONS_PUBLIC_SECRET` — secret HMAC local (pas partagé avec le Cœur, contrairement à
  `JEU_FACTIONS_KEY`).
- `JEU_FACTIONS_PUBLIC_DB` — chemin SQLite dédié.
- `CORS_ORIGINS` — domaine public exact de la brique.
- Réutilisées telles quelles : `PERSONNAGES_URL`, `PERSONNAGES_KEY` (appel serveur-à-serveur
  vers `personnages`, identique à `jeu-factions`).

`docker-compose.yml` de la brique : `env_file: ../../.env` (même motif que les autres briques —
piège déjà documenté, ne pas déclarer ces variables dans `environment:` d'un compose, ça les
figerait à vide).

## Tests

- `jeton.py` : hachage/vérification mot de passe (roundtrip, faux mot de passe → `False`) ;
  émission/vérification HMAC (même batterie que le spec S217 : signature invalide, expiré,
  malformé → `None`).
- Routes `/inscription`/`/connexion`/`/deconnexion` : email déjà pris → `409` ; mot de passe
  trop court ou pseudo banni → `422` ; identifiants invalides → `401` ; succès → cookie posé.
- Rate limiting : dépassement du seuil sur `/connexion` depuis la même IP → `429` ; IP
  différente → toujours `200`/`401` selon les identifiants (pas bloquée par le compteur de
  l'autre IP).
- `test_isolation.py` (repris et renforcé) : deux comptes distincts ne voient jamais les
  personnages/groupes l'un de l'autre — critique ici, ce sont de vrais inconnus, pas seulement
  des comptes du cercle privé testés en interne.
- Non-régression sur les routes reprises de `jeu-factions` : mêmes contrats de payload/erreurs
  que la brique cercle privé (la logique métier copiée ne change pas).
