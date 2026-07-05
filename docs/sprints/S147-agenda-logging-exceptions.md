# Sprint S147 — Agenda : logging des exceptions silencieuses

> **But du sprint** : ajouter un `logger.warning` dans les 14 `except Exception`
> de `core/routers/agenda.py`, afin que toute panne de la brique agenda soit visible
> dans les logs serveur et pas seulement dans la réponse HTTP client.

- **Sprint** : S147
- **Catégorie** : Observabilité / Qualité / Cœur
- **Statut** : CODE-COMPLET
- **Date de planification** : 2026-07-04
- **Date de livraison** : 2026-07-04
- **Briques concernées** : `core/routers/agenda.py`
- **Prérequis** : aucun

---

## Contexte

Chaque endpoint agenda du Cœur est enveloppé dans un `try/except Exception as e`
qui retourne une liste vide avec `"detail": str(e)` en cas d'erreur :

```python
@router.get("/agenda/evenements", ...)
async def agenda_evenements(...):
    try:
        return {"evenements": await agenda.lister_evenements(registre, debut, fin)}
    except Exception as e:  # noqa: BLE001
        return {"evenements": [], "detail": str(e)}
```

Ce pattern est intentionnel : l'agenda ne doit jamais faire planter le Cœur.
**Problème** : l'erreur est retournée au client mais jamais loggée côté serveur.

En production sur le HP :
- Le dashboard affiche silencieusement l'agenda vide
- Aucun log dans `docker logs core` ne signale le problème
- Diagnostic impossible sans intercepter les réponses HTTP clientes

**14 occurrences** : lignes 19, 31, 41, 57, 77, 86, 107, 119, 129, 149, 180, 196,
209, 218 de `core/routers/agenda.py`.

---

## Chantiers

### C0 — Ajouter le logger en tête de fichier

```python
import logging
logger = logging.getLogger(__name__)
```

### C1 — Ajouter `logger.warning` dans chaque except

Pattern à appliquer sur les 14 occurrences :

```python
    except Exception as e:  # noqa: BLE001
        logger.warning("agenda/%s : %s", "<nom_endpoint>", e)
        return {"evenements": [], "detail": str(e)}
```

Le `<nom_endpoint>` est le nom de la fonction Python (ex. `evenements`, `timetree_sync`,
`google_disconnect`, `commentaire_ajouter`…).

Aucun changement de comportement : la réponse reste identique, le log s'ajoute.

### C2 — Choisir le bon niveau de log

| Cas | Niveau recommandé |
|---|---|
| Brique agenda down / connexion refusée | `logger.warning` |
| Erreur de parsing / KeyError inattendue | `logger.warning` |
| Token expiré TimeTree / Google | `logger.info` (attendu, pas une panne) |

Utiliser `logger.warning` pour tous par défaut — suffisant, homogène, peu de bruit.

### C3 — Test : vérifier que le log est émis

Dans `core/test_agenda_proxys.py` (fichier existant), ajouter :

```python
def test_erreur_agenda_loggee(caplog, monkeypatch):
    """Une panne de la brique agenda doit apparaître dans les logs serveur."""
    import agenda
    monkeypatch.setattr(agenda, "lister_evenements", AsyncMock(side_effect=RuntimeError("brique down")))
    with caplog.at_level(logging.WARNING, logger="core.routers.agenda"):
        resp = client.get("/agenda/evenements")
    assert resp.status_code == 200
    assert resp.json()["evenements"] == []
    assert "brique down" in caplog.text
```

---

## Critère d'acceptation

- `import logging` + `logger = logging.getLogger(__name__)` présent dans le fichier
- 14 `except` blocs ont un `logger.warning(…)` avant le `return`
- 1 test vérifiant l'émission du log en cas de panne
- Comportement client identique (aucune régression)
- `make test-core` reste vert

---

## Effort estimé

**< 45 min**
- C0+C1 (ajout logs) : 20 min — édition mécanique sur 14 blocs
- C2 (choix niveau) : inclus dans C1
- C3 (test) : 20 min

## Valeur

Les pannes agenda deviennent visibles dans `docker logs core` sans nécessiter
d'intercepter les réponses HTTP clientes. Diagnostic réduit de « chercher pourquoi
c'est vide » à « lire le log ».
