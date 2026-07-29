# S216 → S220 — Jeu holistique : les 3 sous-projets restants (2026-07-29)

Backlog **écrit, rien codé**. Suite directe de la décomposition en 5 posée dans
`docs/superpowers/specs/2026-07-29-jeu-factions-design.md` : le sous-projet 1 (personnages +
factions/territoire) et le sous-projet 2 (combat temps réel) sont livrés. Restent : progression
idle, infra multi-joueurs publique, système de quêtes complet.

**Ordre = risque décroissant, pas l'ordre de la décomposition d'origine.** L'idle (S216) est le
plus petit et le plus autonome — aucune dépendance, valeur visible vite. L'identité réelle
(S217) est contenue **si on la scope au cercle privé déjà outillé par le Cœur** (Keycloak,
session multi-utilisateur) plutôt qu'à un vrai hébergement public — c'est justement la question
à trancher avant d'écrire quoi que ce soit. Les quêtes (S218-S219) sont le plus gros morceau,
majoritairement du contenu plus qu'un nouveau moteur, et profitent d'attendre que S216/S217
existent (récompenses idle, quêtes par compte réel). L'exposition publique (S220) est mise à
part et explicitement conditionnelle : c'est un choix de portée, pas un développement.

Chaque sprint est indépendant sauf mention explicite. Le spec détaillé + le plan
d'implémentation (`docs/superpowers/specs/` et `docs/superpowers/plans/`, motif déjà suivi pour
les sous-projets 1 et 2) s'écrivent **au moment d'attaquer**, pas d'avance — motif du repo.

---

## S216 — Progression idle

**Pourquoi maintenant.** C'est le sous-projet le plus petit des trois, sans dépendance sur les
deux autres, et il retombe sur une vraie question de conception que jeu-factions a déjà
tranchée une fois différemment : le spec du sous-projet 1 avait une résolution automatique par
tick (« idle » de fait) sur les zones de signe — le sous-projet 2 l'a **remplacée** par du
combat joué en temps réel, précisément parce que « jouer » et « accumuler passivement » sont
deux mécaniques concurrentes sur le même contenu. « Idle » ici doit donc viser autre chose que
« refaire l'ancien système » : une progression qui s'accumule **pendant l'absence du joueur**
(hors ligne), pas une résolution automatique d'un combat qui, lui, doit rester joué.

**Question ouverte à trancher avant le spec.** Qu'est-ce qui progresse pendant l'absence ?
Options non exclusives : (a) une ressource/monnaie qui s'accumule au temps réel écoulé,
dépensable ensuite (achats, boosts) ; (b) une file de personnages « en mission » hors combat
(façon garnison/exploration) qui rapportent à échéance ; (c) un multiplicateur de progression
d'archétype pour les personnages **non engagés** dans un combat actif, sur la voie déjà entamée.
(c) est le plus proche du système existant (`progression_archetype`) mais réintroduit la tension
avec le sous-projet 2 si mal bordé — à documenter explicitement dans le spec quel que soit le
choix, pour ne pas recréer accidentellement l'ancien tick.

**Périmètre.**
- Un mécanisme de progression liée au temps réel écoulé hors ligne, indépendant du combat joué
  (ne touche pas `combat_moteur.py`/`combat.py`).
- Persistance de « depuis quand » un personnage est en état idle, calcul du gain au retour
  (pas un tick serveur permanent — motif déjà établi : `boucle_tick`/`_boucle_instance` ne sont
  pas la bonne brique pour de l'offline, un calcul à la lecture suffit et évite un
  `asyncio.sleep` de plus qui tourne pour rien).
- Exposition dans `front.html` (ou un nouveau `front_idle.html` si le contenu le justifie).

**Hors périmètre.** Pas de nouvelle monnaie/économie complexe si l'option (a) est retenue —
rester sur un seul type de gain pour la V1. Pas de notifications (« ta mission est finie ») —
lu au retour du joueur, comme le reste de la brique.

**Critère de sortie.** Un personnage laissé de côté 24h montre une progression mesurable au
retour, sans qu'aucune boucle serveur n'ait tourné pendant l'absence pour la calculer.

**Effort.** ~2-3 jours une fois le choix (a)/(b)/(c) tranché. **Dépend de.** Rien côté code ;
dépend d'une décision produit (la question ouverte ci-dessus).

---

## S217 — Identité réelle, scopée au cercle privé du Cœur

**Pourquoi maintenant.** Le spec du sous-projet 1 posait explicitement : « un joueur est juste
`cle_api` + `pseudo` — pas de vrais comptes ». Le Cœur, lui, a **déjà** une identité
multi-utilisateur complète (Keycloak, session par personne, motif déjà appliqué à Studio, Atelier
Images & Vidéo, Mémoire — cf. `core/routers/dashboard.py`, jeton signé par personne pour Mémoire,
proxy `/studio-app/` pour Studio). jeu-factions vient d'être câblé dans le dashboard du Cœur
(tuile Atelier) sans reprendre ce motif — il tourne encore sur le `cle_api` générique de la
brique, pas sur l'identité de la personne connectée. Fermer cet écart est *contenu* : ce n'est
pas construire un système de comptes, c'est appliquer à jeu-factions un motif déjà prouvé sur 3
autres briques.

**Périmètre.**
- Le Cœur transporte l'identité de la personne connectée vers jeu-factions, comme il le fait
  déjà pour Mémoire (jeton signé) ou Studio (proxy + `X-User-Id`) — choisir lequel des deux
  motifs colle le mieux au cloisonnement déjà en place dans `stockage.py` (`joueurs.cle_api`
  PRIMARY KEY) sans le casser.
- `personnages_jeu`/`groupes` restent cloisonnés comme aujourd'hui (par `cle_api`), sauf que ce
  `cle_api` devient l'identité réelle de la personne, pas une clé API partagée.
- Pas de changement à l'exception délibérée déjà documentée (zones/scores restent un monde
  partagé, cf. spec sous-projet 1).

**Hors périmètre — explicitement renvoyé à S220.** Aucun hébergement public, aucun compte pour
quelqu'un hors du cercle privé déjà enrôlé sur le mesh/Keycloak. C'est tout l'écart entre
« vrais comptes » (ce sprint) et « infra multi-joueurs **publique** » (le nom du sous-projet 4
d'origine, plus ambitieux) — ce sprint livre le premier sans le second.

**Critère de sortie.** Deux personnes du cercle privé, connectées séparément au Cœur, voient
chacune leurs propres personnages/groupes sans clé à copier-coller — même test d'isolation que
celui déjà audité sur 28 briques (cf. mémoire « épopée identité multi-utilisateur du Cœur »).

**Effort.** ~2 jours (motif déjà rodé 3 fois). **Dépend de.** Rien de nouveau — réutilise
l'infra Keycloak/session déjà en place.

---

## S218 — Quêtes : rendre les voies d'archétype jouées, pas juste résolues

**Pourquoi maintenant.** Le sous-projet 1 pose déjà la structure minimale (étapes ordonnées +
texte de lore fixe, cf. `zones_archetype`/`progression_archetype`). Le sous-projet 2
(combat) a résolu, en cours de route, la moitié du non-objectif « pas d'effets de compétences »
du spec d'origine — les compétences ont maintenant de vrais effets (`degats`/`soin`/`bouclier`/
`etourdissement`/`dot`). Ce qui manque encore pour un « système de quêtes complet » : que
franchir une étape de voie soit un combat joué (comme les zones de signe le sont devenues),
pas une comparaison de stats automatique côté groupe — aujourd'hui `groupes.resoudre_groupes_actifs()`
tourne encore sur l'ancien modèle que S209→combat a remplacé pour les zones.

**Périmètre.**
- Réutiliser `combat_moteur.py`/`combat.py` (S217 précédent, sous-projet 2) pour les étapes de
  voie d'archétype, exactement comme cela a été fait pour les zones de signe : une étape devient
  une instance de combat (mobs dédiés par étape, cf. `mobs_zone` mais scopé par
  `zone_archetype_id` plutôt que `zone_id`), pas un seuil de stats.
  **Décision de conception explicite à faire** : instancier par étape (30 fois plus de gabarits
  de mobs) ou réutiliser un contenu générique paramétré par la difficulté de l'étape — la spec
  du sous-projet combat avait volontairement laissé cette extension hors scope (« ne touche pas
  à la résolution des voies d'archétype/groupes »), donc rien n'impose l'un ou l'autre ici.
- `groupes.py` (créer/rejoindre un groupe « carry ») reste tel quel — seule la résolution change
  de mécanique, pas le motif social (n'importe qui rejoint, seul le personnage dont c'est la
  prochaine étape progresse réellement).

**Hors périmètre.** Le contenu narratif lui-même (lore par étape) est une tâche séparée, plus
proche de la rédaction que du code — cf. S219.

**Critère de sortie.** Un groupe « carry » sur l'étape 2 du « Meneur Charismatique » ouvre une
vraie instance de combat jouée, pas une somme de stats — mêmes garanties de progression
(carry ne fait pas progresser, sauf étape 1, cf. spec sous-projet 1) qu'aujourd'hui.

**Effort.** ~1 semaine (essentiellement de la réutilisation de S217-combat, pas un nouveau
moteur). **Dépend de.** Sous-projet 2 (combat, déjà livré).

## S219 — Quêtes : contenu narratif réel

**Pourquoi maintenant.** Après S218, la mécanique de chaque étape de voie est un vrai combat
joué — mais le texte reste générique (`_LORE_GENERIQUE` dans `archetypes.py` : « étape 1, étape
2… »). C'est explicitement noté comme dette dans le sous-projet 1 (« lore quasi inexistant »).
Ce sprint est majoritairement de la rédaction, pas de l'architecture.

**Périmètre.** Écrire un texte de lore réel pour les 3 étapes × 10 archétypes (30 textes),
remplaçant `_LORE_GENERIQUE`. Pas de dialogue interactif ni d'embranchement — le spec du
sous-projet 1 exclut explicitement ça (« sans dialogue, embranchement, ni catalogue de
récompenses élaboré »), et rien ici ne le remet en cause.

**Hors périmètre.** Dialogue, embranchement narratif, PNJ, journal de quêtes avec objectifs
multiples — tout ça resterait un sous-projet 6 non écrit si un jour souhaité, pas ce sprint.

**Critère de sortie.** Les 30 textes sont écrits et affichés ; aucune étape n'affiche plus
« étape 1, étape 2 ».

**Effort.** Variable selon l'ambition du texte — une session de rédaction suffit pour une V1
correcte. **Dépend de.** Rien côté code (peut se faire même avant S218, c'est juste plus motivant
après puisque l'étape sera jouée, pas juste résolue).

---

## S220 — Exposition publique (conditionnel — décision de portée, pas un sprint prêt à écrire)

**Pourquoi c'est à part.** « Infra multi-joueurs publique » dans le spec d'origine mélangeait
deux choses que S217 sépare déjà : l'identité réelle (S217, fait avec l'infra Keycloak
existante) et l'**exposition à des joueurs hors du cercle privé déjà enrôlé sur le mesh**. Le
second est un changement de nature pour tout Workplace, pas juste pour jeu-factions — chaque
autre brique du repo est pensée pour un cercle privé (famille/associés), jamais pour des
inconnus d'Internet. Ouvrir ça pose des questions que ce backlog ne tranche pas : modération,
abus, charge (le spec combat a déjà scopé le sharding pour un usage cercle privé, pas pour un
vrai pic public), support, et surtout — **est-ce même souhaité**, ou est-ce que jeu-factions
reste un jeu du cercle privé comme le reste de Workplace ?

**Ce sprint n'a pas de périmètre écrit.** Il ne s'écrit que si la réponse à cette question est
oui, et seulement après S216-S219, une fois qu'il y a un vrai jeu à exposer et pas seulement un
squelette.

---

## Résumé de l'ordre

| Sprint | Sous-projet (numérotation spec) | Dépend de | Nature |
|---|---|---|---|
| S216 | Progression idle (3) | Décision produit (a/b/c) | Petit, autonome |
| S217 | Identité réelle (4, partiel) | Rien (motif Keycloak déjà rodé) | Petit, contenu |
| S218 | Quêtes — mécanique jouée (5, partiel) | Sous-projet 2 (combat, fait) | Moyen |
| S219 | Quêtes — contenu narratif (5, partiel) | Rien | Rédaction |
| S220 | Exposition publique (4, reste) | S216-S219 + décision de portée | Non scopé |
