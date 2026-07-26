# sip-stack — infra SIP de la brique standard-telephonique

Ce dossier verse dans le monorepo ce qu'il faut pour **reconstruire** la pile SIP
(Kamailio + rtpengine + livekit-sip + LiveKit standalone) sur une VM neuve. Ce n'est
pas du code applicatif Workplace : c'est de l'infra tierce (projet
[roomkit-visio](https://github.com/suitenumerique) de La Suite Numérique) + une
surcouche `compose.override.yml` écrite pour Workplace au S197.

## Ce qui est versionné ici

- `roomkit-visio/` — copie de la config qui tourne réellement sur le HP
  (`~/workplace/sip-stack/roomkit-visio/` là-bas), **sans** secrets : `.env`,
  `certs/*.crt`, `certs/*.key` et `gst-dots/*` restent gitignorés (voir
  `roomkit-visio/.gitignore`, hérité du projet amont).
- `roomkit-visio/compose.override.yml` — surcouche Workplace (S197, voir commentaire
  en tête de fichier) : redis + LiveKit standalone jetables, dédiés au test SIP↔LiveKit,
  sans dépendance sur `oria-stack/`. Volontairement séparée de `compose.yml` pour
  faciliter une resynchronisation avec l'amont plus tard.

## Ce qui n'est PAS versionné (et pourquoi)

`livekit-sip/` n'est pas vendored ici : c'est un clone Go de
`github.com/suitenumerique/livekit-sip` (~6 Mo), sans modification locale. Il se
reconstruit avec :

```sh
git clone -b sip-video https://github.com/suitenumerique/livekit-sip.git sip-stack/livekit-sip
cd sip-stack/livekit-sip
git checkout c44a792f57a4b81ec9b2067bfce329ff9cccb13d   # commit exact utilisé sur le HP (vérifié 2026-07-26)
```

## Reconstruire sur une VM neuve

```sh
# 1. Cloner livekit-sip au commit épinglé (voir ci-dessus), à côté de ce repo :
#    parent/
#    ├── workplace/              # ce monorepo (contient sip-stack/roomkit-visio/)
#    └── livekit-sip/            # cloné séparément, PAS versionné

# 2. Bootstrap roomkit-visio (build livekit-sip:local, certs auto-signés puisqu'il n'y a
#    pas de checkout "meet", pull des autres images)
cd workplace/sip-stack/roomkit-visio
LIVEKIT_SIP_SRC=../../../livekit-sip make bootstrap

# 3. Compléter .env généré par `make bootstrap` (copié depuis .env.example) :
#    LIVEKIT_API_KEY / LIVEKIT_API_SECRET doivent avoir la MÊME valeur que
#    STANDARD_TEL_LIVEKIT_API_KEY / _SECRET dans le .env racine du monorepo.

# 4. Démarrer (compose.override.yml est repris automatiquement par docker compose)
make start          # ou `make start-all` pour la stack monitoring
```

Vérifier : `make sql Q="SELECT destination FROM dispatcher;"`, `make ports`,
`make logs SVC=livekit-sip`.

## Lien avec la brique standard-telephonique

Le worker `standard-telephonique-agent` (voir
[`briques/standard-telephonique/README.md`](../briques/standard-telephonique/README.md))
se connecte à `ws://<IP_LAN>:7890` (LiveKit standalone monté par
`compose.override.yml`), pas au LiveKit d'Oria — la fonctionnalité SIP de LiveKit
exige redis, absent de la config Oria actuelle (voir commentaire en tête de
`compose.override.yml`).

**CPU virtuel Proxmox** : `livekit-sip` (et sa dépendance native
`livekit-local-inference`) plante en SIGILL sur un CPU virtuel sans AVX2. Une VM
dédiée à cette pile, avec `cpu: host` (passthrough) côté Proxmox, résout ce point ET
isole ce service exposé (SIP) du reste du stack.
