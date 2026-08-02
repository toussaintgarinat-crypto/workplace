# jeu-factions — création de personnage + factions/territoire (PvE)

Premier sous-projet du jeu holistique (voir `docs/superpowers/specs/2026-07-29-jeu-factions-design.md`).
Réutilise le moteur de `personnages` (5900) en HTTP — aucun calcul de tradition/stat dupliqué ici.

## Démarrer

```bash
docker compose up -d --build      # API sur http://localhost:6210
curl localhost:6210/sante
```

## Configuration

Si la brique `personnages` a `API_KEYS` configuré, définis `PERSONNAGES_KEY` (même valeur des deux côtés, voir `.env.example` racine) — sinon chaque création de personnage se fait rejeter (401) par `moteur_personnages.py`.

`JEU_FACTIONS_KEY` (S217) est **obligatoire** — secret partagé avec le Cœur pour le jeton signé de la tuile du dashboard. Sans elle, la brique refuse tout accès (aucun repli mono-tenant, contrairement aux autres briques cercle privé) : voir `.env.example` racine.

## Concepts

- **Nation** = élément du signe solaire (Feu/Terre/Air/Eau).
- **Guilde** = signe solaire (12).
- **Classe** = archétype calculé (10) — orthogonal à la politique.
- **Zones de signe** (12) : PvE **partagé**, tous comptes confondus, pas de possession exclusive (pas de PvP dans ce spec).
- **Voies d'archétype** (10 × 3 étapes) : PvE **personnel et séquentiel**, non-rejouable une fois vaincu. Groupes ouverts : n'importe qui peut aider (« carry »), mais seul celui pour qui l'étape est sa PROCHAINE progresse réellement.

## Exception au cloisonnement

Contrairement au reste de Workplace, `/zones` et `/archetypes/*/etapes` sont un **monde partagé** : toute identité authentifiée les voit toutes. Seuls `/personnages` et `/groupes` restent cloisonnés par propriétaire. Voir le spec pour la justification.

## Combat temps réel

`GET /zones/{zone_id}/combat` (WebSocket) : rejoint (ou crée) une instance de combat pour la zone,
simulée à tick fixe (`combat_moteur.py`, fonction pure) et diffusée à toutes les connexions —
état des joueurs/mobs, dégâts/soin/bouclier/étourdissement/DOT selon la compétence, et les
événements du tick (`evenements`). Front minimal : `front_combat.html` (Phaser, HUD PV + journal
de combat). Voir `docs/superpowers/specs/2026-07-29-jeu-factions-combat-design.md`.

`GET /groupes/{groupe_id}/combat` (WebSocket, S218) : même moteur de combat temps réel, mais pour
une étape de voie d'archétype — la mort du boss fait progresser chaque membre du groupe pour qui
c'était réellement sa propre prochaine étape (règle carry), et ne dissout que les groupes de ces
personnages-là, jamais ceux d'autres tenants visant la même étape sans avoir progressé.

## Non fait ici (specs séparés à venir)

PvP, hébergement public (cercle privé uniquement, S217).

## Tests

```bash
python -m pytest -q
```
