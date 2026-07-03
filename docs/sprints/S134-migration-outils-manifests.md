# S134 — Migration des outils statiques vers les manifests

**Date** : 2026-07-02  
**Statut** : ✅ LIVRÉ (2026-07-03)  
**Objectif** : Supprimer les définitions d'outils dupliquées dans `core/outils.py` au profit des manifests de briques. Après S133 (nouvelles capacités), S134 est la phase de nettoyage : chaque brique déclare ses outils dans son manifest, le Cœur n'en a aucun en dur pour ces domaines.

---

## Périmètre

| Domaine | Outils à migrer | Verdict |
|---|---|---|
| **Forge** | 14 outils (RAG, factures, CRM, paiements, relances) | → manifest `briques/forge/manifest.json` |
| **Mémoire** | 2 outils (rappeler, retenir) | déjà dans manifest (prep S134) — retirer des statiques |
| **Studio** | 12 outils (séries, bible, perso, audio) | → manifest `briques/studio/manifest.json` |
| **Personnages** | 2 outils (fiches_lister, importer_serie) | → manifest `briques/personnages/manifest.json` |
| **Hors périmètre** | Agenda + TimeTree (module Python interne), ETL (filtre côté client), `forge_capacites` (méta-outil), `personnage_creer_holistique` (helper complexe) | sprint futur |

## Stratégie

- Ajouter les capacités aux manifests
- Retirer les entrées de `OUTILS` dans `core/outils.py`  
- Vider les cas correspondants dans les dispatchers (`core/outils_domaines/`)
- Mettre à jour les tests impactés

**Invariants** :
- Le Cœur auto-découvre les capacités via `catalogue.py` au démarrage
- `_appel_dynamique` gère confirmation + appel HTTP (fonctionnellement équivalent)
- Limites acceptées : headers tenant `X-Forge-User-Token` non propagés (mono-user inchangé) ; `X-Org-ID` pour données (même chose)

## Fix memoire brique

L'espace "perso" dans le manifest est envoyé en minuscules au brique, mais la brique attend "Perso" (créé avec majuscule). Fix : normalisation dans `briques/memoire/main.py`.

---

## Définition de DONE

- [x] Forge : 14 capacités dans manifest, plus dans OUTILS, dispatcher vidé
- [x] Mémoire : plus dans OUTILS + OUTILS_ACTION + dispatcher
- [x] Studio : 12 capacités dans manifest, plus dans OUTILS, dispatcher vidé  
- [x] Personnages : 2 capacités dans manifest, plus dans OUTILS, dispatcher allégé
- [x] memoire brique : normalise "perso"→"Perso" et "solution"→None
- [x] Tests mis à jour et verts (39 passent)
