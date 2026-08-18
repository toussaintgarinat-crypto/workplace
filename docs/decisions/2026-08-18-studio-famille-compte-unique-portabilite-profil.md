# Décision — Studio : « famille » = compte unique, portabilité garantie par profil

- **Date** : 2026-08-18
- **Statut** : ✅ Décidé — aucune implémentation requise aujourd'hui (contrainte à respecter dès que la mémoire/parcours sera codée)
- **Portée** : brique `studio` — `main.py` (scoping `cree_par`, motif S187), `studio.py` (`PROFILS_DIR`, `ATELIERS_DIR`)
- **Fichiers liés** : `briques/studio/main.py`, `briques/studio/studio.py`

> **But de ce document** : trancher si le Studio a besoin d'une entité `Famille` séparée
> pour porter le futur système de parcours/mémoire (proposé dans le rapport stratégique du
> 2026-08-18 sur la « saga familiale »), et poser la règle de stockage qui garantit qu'un
> enfant pourra plus tard récupérer ses propres données s'il se crée son compte.

---

## En bref (l'état actuel)

- `main.py` scope déjà tout — séries **et** profils lecteurs — par une seule valeur
  `cree_par` (motif S187). Une série est un fichier JSON, un profil lecteur un autre
  fichier JSON, tous deux indexés par leur propre id, filtrés à la lecture par `cree_par`.
- Un seul compte parent se connecte aujourd'hui ; les profils « Fils »/« Fille » vivent
  dessous. Il n'existe **aucune** notion de compte partagé entre plusieurs adultes.

## Contexte & objectif

Le rapport stratégique propose une entité `Family` au-dessus des profils, avec ses propres
membres, sa mémoire, ses relations. Avant de construire quoi que ce soit, deux questions
distinctes se posent :

1. Faut-il un magasin `Famille` qui regroupe **plusieurs identités de connexion**
   (ex. deux parents avec des logins séparés) ?
2. Si un enfant se crée un jour son propre compte, peut-on lui **transférer ce qui le
   concerne** sans dépendre du compte parent ?

## Décision

**1. Pas de nouvelle entité `Famille` maintenant.** Tant qu'une seule identité se
connecte pour tout le foyer, `cree_par` **est** la famille au sens du système — c'est déjà
le regroupement naturel de tous les profils lecteurs et de toutes les séries d'un foyer.
Aucun nouveau magasin transversal à créer pour ça.

**2. Contrainte de conception retenue pour la portabilité future** (S'applique à partir du
jour où le parcours/mémoire par enfant sera codé, pas aujourd'hui) :

> Toute donnée future propre à **un seul enfant** (choix faits, thèmes déjà explorés,
> progression narrative, relations avec des personnages) doit être stockée **indexée par
> `profil_id`**, dans le fichier du profil lui-même ou dans un fichier annexe référencé par
> `profil_id` — **jamais fusionnée ou embarquée dans le JSON de la série** (`serie["episodes"]`,
> `serie["cycles"]`). La série et ses chapitres restent un objet **partagé**, propriété du
> compte, jamais dupliqué par enfant.

Cette règle ne coûte rien aujourd'hui : les profils lecteurs sont déjà stockés
séparément des séries (`PROFILS_DIR/{profil_id}.json` vs `ATELIERS_DIR/{serie_id}.json`,
S231). Elle évite seulement qu'une future fonctionnalité « mémoire » soit codée en
écrivant des champs `enfant_a_choisi_X` à l'intérieur du JSON de la série — ce qui rendrait
n'importe quelle extraction ultérieure impossible à démêler proprement.

**3. Le transfert futur (enfant → son propre compte)**, le jour où il sera codé, se
résume à : réassigner `cree_par` sur le(s) fichier(s) qui portent ce `profil_id` vers la
nouvelle identité. Grâce à la règle 2, c'est un changement de métadonnée sur des fichiers
déjà isolés, **pas** une migration de données ni une extraction depuis un blob partagé.

## Alternatives considérées & quand basculer

| Approche | Coût | Bon quand… |
|---|---|---|
| Compte unique = famille, portabilité par `profil_id` (choisi) | 0 | une seule identité de connexion gère le foyer |
| Entité `Famille` multi-comptes | nouveau magasin + endpoints de partage/invitation + contrôle d'accès par membre | plusieurs adultes (ex. les deux parents, un grand-parent) se connectent **séparément** et doivent piloter les mêmes profils/séries |

**Déclencheurs de bascule vers une entité `Famille` multi-comptes** (l'un suffit) :
1. Un deuxième adulte veut son propre login et doit voir/modifier les mêmes profils
   enfants et séries que le compte principal ;
2. Un enfant devenu autonome doit continuer à interagir avec l'univers familial partagé
   (pas seulement récupérer *son* parcours, mais rester co-auteur de la saga commune) ;
3. Besoin de droits différenciés (ex. un grand-parent en lecture seule).

La migration n'est pas bloquée par la décision d'aujourd'hui : comme les profils et
séries sont déjà des fichiers isolés par id, ajouter un objet `Famille` plus tard revient
à ajouter une couche de regroupement au-dessus de plusieurs `cree_par`, pas à réécrire le
stockage existant.

## Limites connues

- Le contenu narratif partagé (bible, chapitres, univers) **n'est pas** transférable à
  l'enfant dans ce modèle — seul son parcours personnel (profil + future mémoire) l'est.
  Si un jour la demande est « l'enfant part avec une copie de l'histoire », ce sera un
  choix produit distinct (copie vs référence), pas couvert par cette décision.
- Cette décision ne code rien : elle fixe la règle de stockage que **la prochaine
  fonctionnalité de mémoire/parcours** devra respecter dès sa première ligne.

## Références

- Rapport stratégique « Studio de séries audio IA qui accompagne l'enfant » (conversation
  du 2026-08-18).
- `briques/studio/main.py:72` (normalisation `cree_par` à la lecture, S187).
- Mémoire : sprint S231 profils lecteurs (adaptation par âge, stockage par `profil_id`).
