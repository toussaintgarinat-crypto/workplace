---
name: hpworkplace
description: >
  Gérer en SSH le serveur « HP » (Proxmox HP 800 G4 i7-8700, Debian) qui héberge le stack
  Docker complet de Workplace. Couvre : état/santé du stack, mise à jour du code (git pull +
  rebuild brique par brique), réparation d'un conteneur, et (re)déploiement depuis le runbook
  MIGRATION-HP.md. Cible SSH = debian@192.168.1.89 (clé dédiée déjà posée). Use when user says
  "hpworkplace", "/hpworkplace", "gère le hp", "le hp", "état du hp", "santé du hp",
  "déploie sur le hp", "mets à jour le hp", "redémarre une brique sur le hp",
  "les dockers sur le hp", "bascule hp".
---

# Gérer le HP (stack Docker Workplace) en SSH

Le **HP** (Proxmox HP 800 G4 i7-8700, Debian x86_64) héberge le **stack Docker complet de
Workplace** (~38 conteneurs : Cœur + toutes les briques + gateway + keycloak + memoire/forge…).
C'est la machine « costaude » du régime **« coder+tester+pousser sur le Mac, prouver LIVE en
Docker sur le HP »** (le Mac sature en disque dès qu'on build les grosses images). Voir le
runbook de référence dans le repo : **`MIGRATION-HP.md`**.

## Accès

- **Cible** : `ssh debian@192.168.1.89` (LAN). Mot de passe `debian` (compte sudo).
- **Clé** : une clé dédiée `claude-code-mac->hp` (`~/.ssh/id_ed25519`) est **déjà autorisée**
  sur le HP → toutes les commandes passent en `ssh -o BatchMode=yes debian@192.168.1.89 '...'`
  (non-interactif, pas de mot de passe).
- Si un jour la clé manque, la (ré)autoriser :
  ```bash
  PUB=$(cat ~/.ssh/id_ed25519.pub)
  sshpass -p 'debian' ssh -o StrictHostKeyChecking=accept-new debian@192.168.1.89 \
    "mkdir -p ~/.ssh && chmod 700 ~/.ssh && grep -qxF '$PUB' ~/.ssh/authorized_keys 2>/dev/null \
     || echo '$PUB' >> ~/.ssh/authorized_keys; chmod 600 ~/.ssh/authorized_keys"
  ```
- **Repo sur le HP** : `/home/debian/workplace`, branche `main`.
- **Dashboard** : `http://192.168.1.89:5100/dashboard`.

## Toujours commencer par : ÉTAT (lecture seule)

```bash
ssh -o BatchMode=yes debian@192.168.1.89 '
echo "== conteneurs =="; docker ps --format "{{.Names}}\t{{.Status}}" | sort
echo "== disque =="; df -h / | tail -1
echo "== Cœur =="; curl -s -o /dev/null -w "/health -> %{http_code}\n" localhost:5100/health
curl -s localhost:5100/sante-globale | python3 -m json.tool 2>/dev/null | head -60
echo "== repo =="; cd ~/workplace && git branch --show-current && git log --oneline -1
'
```
Lire la santé brique par brique dans `/sante-globale` (chaque brique = `ok` / code HTTP).

## METTRE À JOUR (git pull + rebuild)

> ⚠️ **Toujours `--build`** après un `git pull` (sinon images périmées — piège connu).
> Builder **une brique à la fois** (risque `ENOSPC` si tout en parallèle).

```bash
ssh -o BatchMode=yes debian@192.168.1.89 '
cd ~/workplace && git pull --ff-only
# rebuild ciblé d une brique modifiée :
( cd briques/<nom> && docker compose up -d --build )
# le Cœur :
( cd core && docker compose up -d --build )
'
```
Après coup, relancer l'ÉTAT et vérifier `/sante-globale`.

## RÉPARER un conteneur

```bash
# logs d un conteneur qui boucle / unhealthy :
ssh -o BatchMode=yes debian@192.168.1.89 'docker logs --tail 30 <conteneur> 2>&1'
# recreate d UNE brique seulement (sans toucher au reste) :
ssh -o BatchMode=yes debian@192.168.1.89 '( cd ~/workplace/briques/<nom> && docker compose up -d )'
```

## (RE)DÉPLOYER de zéro

Suivre **`MIGRATION-HP.md`** (clone `main` → poser les `.env` → préflight → build dans l'ordre
`gateway → briques socle → core`). Ne re-déployer **que** si le stack est absent ou cassé ;
sinon préférer « mettre à jour ».

## Pièges Linux connus (Docker Engine, vs macOS Docker Desktop)

1. **Réseau `proxy_net`** (référencé `external: true` par gateway/agenda/core) doit exister :
   `docker network create proxy_net` (idempotent).
2. **`host.docker.internal`** n'existe pas nativement sur Linux : les briques *consommatrices*
   (core, audit, generateur, agenda, forge ; donnees en Niveau B) ont un
   `docker-compose.override.yml` qui ajoute
   `extra_hosts: ["host.docker.internal:host-gateway"]`.
3. **`keycloak` affiché `unhealthy`** = souvent un **faux négatif** (healthcheck strict) : vérifier
   les logs (« started in Xs », realms importés) avant de conclure à une panne.
4. **`workplace_dev_ide`** peut boucler sur `EACCES … /home/coder/.config/code-server`
   (permissions du volume code-server / UID `coder`) — c'est l'IDE web de la brique `dev`, le
   reste du stack n'en dépend pas. Fix = corriger les droits du volume monté, pas rebuild global.
5. **`ENOSPC`** : `docker system prune -af` (+`--volumes` si on accepte de perdre les données de
   dev), builder une brique à la fois.
6. **env-shadow** : ne pas mettre `environment: VAR=${VAR:-}` (écrase le `.env` racine par du vide).

## Principe

**Honnêteté technique** : « le code existe » ≠ « ça tourne ». Toujours prouver par `curl`/logs
réels (l'ÉTAT ci-dessus), et rapporter fidèlement ce qui est `ok` vs ce qui ne l'est pas.
Ne jamais redéployer/rebuilder un stack qui tourne sans raison — c'est conséquent.
