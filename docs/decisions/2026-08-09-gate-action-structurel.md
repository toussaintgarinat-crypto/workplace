# Décision — L'accord humain sur une action est tenu par le Cœur, pas par le prompt

- **Date** : 2026-08-09
- **Statut** : ✅ Adopté (S222)
- **Portée** : les 133 capacités marquées `action: true` sur les 253 du parc ; la boucle
  d'inférence du Cœur et la route `/assistant/chat` (toutes surfaces : web, Telegram,
  Mini App)
- **Fichiers liés** : `core/accord_action.py`, `core/assistant.py`,
  `core/routers/assistant.py`, `core/outils_communs.py` (`_confirmation`)
- **Origine** : veille sur [LIA-Assistant](https://github.com/jgouviergmail/LIA-Assistant)
  (AGPL-3.0 — **idée reprise, aucun code**), leurs seuils HITL et leur ADR-106. Backlog :
  `docs/sprints/S221-S226-emprunts-lia-assistant.md`

> **But de ce document** : consigner ce que le gate garantissait *réellement* avant ce
> sprint, ce qu'il garantit maintenant, et surtout **ce qu'il ne garantit toujours pas** —
> pour que personne ne lui prête plus de pouvoir qu'il n'en a.

---

## Le trou (il existait en production)

Le gate d'action était **purement déclaratif**. Une capacité `action: true` appelée sans
`confirme` recevait le JSON de `_confirmation()` — dont le contenu est un **texte** qui
demande poliment au LLM d'attendre l'accord de l'utilisateur :

> « Action « X » sur « Y » PAS encore exécutée. Si l'utilisateur a DÉJÀ donné son accord […]
> tu DOIS rappeler MAINTENANT le même outil avec `confirme=true` […] »

Côté Cœur, `assistant.py` se contentait de :

```python
confirmation = '"confirmation_requise": true' in resultat
```

— un drapeau posé sur l'événement SSE, à usage d'affichage. **Rien n'empêchait le modèle de
rappeler le même outil avec `confirme=true` dans le même tour**, sans que l'humain ait jamais
vu la question. Le seul rempart était son obéissance au prompt, sur 133 capacités dont les
envois de la brique prospection/démarchage (S169/S170).

## La décision

Le Cœur tient l'accord **côté serveur**, dans `accord_action.REGISTRE`, indexé par fil de
conversation :

1. Appel d'une action **sans** `confirme` → le Cœur enregistre une **demande en attente**
   (capacité + empreinte des arguments). Le reste du flux est inchangé.
2. Un **message utilisateur** arrive sur ce fil (`/assistant/chat`) → les demandes en attente
   deviennent des **accords**. C'est le seul chemin qui en crée.
3. Appel avec `confirme=true` → le Cœur cherche un accord pour **ces arguments exacts**.
   Absent → l'action n'est pas exécutée, `outils.executer` n'est jamais atteint.

L'accord est à **usage unique**, expire (`ACCORD_TTL_SECONDES`, 600 s par défaut), et est
cloisonné par fil.

### L'empreinte, et pourquoi elle remplace un « seuil de masse »

LIA borne les mutations en masse par un seuil sur l'expansion `FOR_EACH` de son plan. Nous
n'avons pas de plan — mais l'accord porte sur une **empreinte des arguments**, ce qui produit
la même garantie sans notion de plan : un accord obtenu pour « écrire à Alice » ne peut pas
être dépensé sur « écrire à Bob », ni recyclé sur 50 destinataires. N mutations exigent N
accords, donc **N tours de parole humains**. C'est le « seuil 1 » de LIA, obtenu autrement.

Pour un envoi en lot légitime, le LLM doit demander l'accord sur le lot lui-même — ce qui est
exactement l'UX souhaitée : une question, un oui, un lot.

## Ce que ça ne garantit PAS

**Que l'humain ait dit « oui ».** Le Cœur ne fait aucune analyse sémantique : interpréter la
réponse reste le travail du LLM. Ce qui est garanti structurellement, c'est qu'**un vrai tour
de parole humain s'est intercalé** entre la demande et l'exécution. Le LLM ne peut plus
fabriquer l'aller-retour tout seul — il pouvait avant.

Le Cœur tranche dans un seul sens, le conservateur : si le message ressemble à un refus
explicite (`non`, `annule`, `stop`, `laisse tomber`… insensible à la casse et aux accents),
l'accord est **révoqué** quoi qu'en dise le modèle. Un refus détecté à tort coûte une
redemande ; un accord accordé à tort exigeait déjà un tour humain. Les deux erreurs penchent
du bon côté.

Le motif de refus est volontairement **court et ancré sur des frontières de mots** : un
motif large attraperait « pas » dans « oui mais pas à Bob » et transformerait un accord
nuancé en refus incompréhensible.

## Limites assumées

- **En mémoire vive, par processus.** Un redémarrage du Cœur perd les accords en attente : il
  faut reconfirmer. Sens sûr.
- **Les chemins sans tour de parole humain gardent le comportement antérieur** : co-agent
  autonome (`coagent.py`) et Gateway MCP appellent `outils.executer` sans passer par
  `converser`. Ils ne sont pas couverts. Le co-agent mériterait de ne pas pouvoir exécuter
  d'action confirmée **du tout** — c'est un sprint à part, pas un effet de bord de
  celui-ci.
- `converser()` **sans `fil`** refuse toute action confirmée. C'est délibéré : un appelant
  qui n'a pas de tour de parole humain n'a pas à pouvoir déclencher d'action confirmée.

## Les seuils de lecture : consultatifs, et c'est volontaire

LIA borne aussi les lectures en lot (avis à 5, blocage à 10). Ici, au-delà de
`ACCORD_SEUIL_LECTURE_LOT` (8) lectures d'une même capacité dans un tour, le résultat est
**annoté** — jamais bloqué. Bloquer une lecture légitime coûterait plus cher que le risque
couvert. Seul le côté mutation est un vrai garde-fou ; ne pas lire ce paramètre comme une
protection.

## Filet

- `core/test_accord_action.py` — 31 cas sur le registre.
- `core/test_gate_action_bout_en_bout.py` — 8 cas **dans la boucle d'inférence**, là où le
  trou vivait. Vérifié en neutralisant le gate : les 5 tests de sécurité échouent, les 3 de
  non-régression continuent de passer. Un test qui passe avant *et* après ne prouve rien.
