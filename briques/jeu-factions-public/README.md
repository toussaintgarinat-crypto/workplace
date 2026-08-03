# jeu-factions-public — exposition publique du jeu (S220)

Brique **indépendante** de `briques/jeu-factions/` (cercle privé, Keycloak) — mêmes moteurs
de jeu (copie-adaptation depuis `jeu-factions`, cf.
`docs/superpowers/specs/2026-08-03-jeu-factions-public-design.md`), mais comptes email + mot
de passe propres à la brique, aucune dépendance à `core/` ni à Keycloak.

## Démarrer

```bash
docker compose up -d --build      # API sur http://localhost:6220
curl localhost:6220/sante
```

## Configuration

`JEU_FACTIONS_PUBLIC_SECRET` est **obligatoire** — secret HMAC de session, propre à cette
brique (pas partagé avec le Cœur). `JEU_FACTIONS_PUBLIC_CORS_ORIGINS` doit être le domaine
public exact en production — voir `.env.example` racine.

### Réinitialisation de mot de passe

Les variables SMTP (`JEU_FACTIONS_PUBLIC_SMTP_HOST`, `JEU_FACTIONS_PUBLIC_SMTP_USER`, etc.)
sont **optionnelles**. Laisser vides → mode simulé (dev/test), aucun email ne part réellement.
Configurées → la brique envoie des emails de réinitialisation via le fournisseur SMTP spécifié.
`JEU_FACTIONS_PUBLIC_URL` doit être le domaine public exact pour que le lien de réinitialisation
(clic utilisateur) pointe vers l'adresse joignable (pas l'IP LAN interne du conteneur).

## Concepts

Identiques à `jeu-factions` (cercle privé) — voir son README pour le détail des concepts
(nation/guilde/classe, zones de signe partagées, voies d'archétype personnelles). Seule
l'identité change : un compte email + mot de passe remplace l'identité Keycloak.

## Exposition publique

Domaine public dédié, port-forward sur la box domicile vers ce HP (config réseau côté
utilisateur, hors repo) + `outils/mesh-https/Caddyfile.jeu-factions-public` côté repo.

## Non fait ici (V1)

PvP, OAuth/comptes anonymes, scaling multi-process, captcha, file de modération, tuile
dashboard Cœur — voir le spec, sections Non-objectifs.

## Tests

```bash
python -m pytest -q
```
