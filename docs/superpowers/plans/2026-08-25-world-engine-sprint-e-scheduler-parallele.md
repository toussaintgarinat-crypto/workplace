# World Engine — Sprint E, scheduler parallélisé — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Éliminer la dérive de tick du scheduler `world-engine` (+14,0% mesurée en LIVE) en exécutant en parallèle les mondes dus dans chaque passage, et logger ce que le scheduler jette aujourd'hui silencieusement (avertissements de verrou, exceptions de tick).

**Architecture:** `main.py:_boucle_scheduler` reste une seule boucle `asyncio` réveillée toutes les `SCHEDULER_INTERVALLE_S`, mais le `for due in dues: await ...` séquentiel est remplacé par `asyncio.gather()` sur une coroutine `_executer_et_consigner` qui encapsule chaque tick (jamais d'exception qui remonte à `gather`) et logue avertissements/erreurs via `logging.getLogger("world-engine")`.

**Tech Stack:** Python 3.12, FastAPI, `asyncio` (stdlib), `logging` (stdlib), pytest + pytest-asyncio (tests, motif `@pytest.mark.asyncio` déjà utilisé dans `test_horloge_moteur.py`/`test_api.py`).

## Global Constraints

- Isolation d'erreur préservée : une erreur sur un monde n'interrompt jamais la boucle ni les autres mondes du même passage (spec, section « Décisions de conception »).
- Logging standard uniquement, aligné sur `calcul/main.py:34` (`logging.getLogger("<brique>")`) — pas de persistance en base, pas de nouvel endpoint (spec, section « Hors périmètre »).
- Pas de tâche `asyncio` indépendante par monde, pas de pool borné — `asyncio.gather()` sur chaque passage, seule approche retenue (spec, section « Décisions de conception »).
- Régime de preuve du projet : coder + tester nativement + pousser ICI (Task 1), la preuve LIVE Docker se fait sur le HP (Task 2) — jamais marquer « PROUVÉ LIVE » avant que Task 2 ait tourné.

---

### Task 1 : Scheduler parallélisé + logging

**Files:**
- Modify: `briques/world-engine/main.py:7-8` (ajout de l'import `logging`)
- Modify: `briques/world-engine/main.py:23-25` (ajout du logger de module)
- Modify: `briques/world-engine/main.py:367-387` (refactor de `_boucle_scheduler`, ajout de `_executer_et_consigner` et `_executer_passage`)
- Create: `briques/world-engine/test_scheduler.py`

**Interfaces:**
- Consumes : `horloge_moteur.executer_tick(monde_id: str, cle_api_val: str) -> dict` (existant, retourne un dict avec une clé `"avertissements": list[str]`) ; `stockage_horloge.horloges_actives_a_declencher(maintenant_iso: str) -> list[dict]` (existant, chaque dict a les clés `"monde_id"` et `"cle_api"`).
- Produces : `main._executer_et_consigner(monde_id: str, cle_api_val: str) -> None` et `main._executer_passage(dues: list[dict]) -> None`, toutes deux des coroutines — les tests de ce sprint et tout futur appelant les invoquent avec `await`.

- [ ] **Step 1 : Écrire les tests, d'abord en échec**

Créer `briques/world-engine/test_scheduler.py` :

```python
"""Tests du scheduler parallélisé (Sprint E) — même motif que
test_horloge_moteur.py : ticks mockés via monkeypatch, jamais de vraie
boucle de fond (HORLOGE_SCHEDULER_DESACTIVE=1 posé dans conftest.py)."""
import logging
import time

import pytest

import horloge_moteur
import main


@pytest.mark.asyncio
async def test_executer_passage_execute_les_mondes_dus_en_parallele(monkeypatch):
    import asyncio

    ordre_debut = []
    ordre_fin = []

    async def _tick_lent(monde_id, cle_api_val):
        ordre_debut.append(monde_id)
        await asyncio.sleep(0.2)
        ordre_fin.append(monde_id)
        return {"avertissements": []}

    monkeypatch.setattr(horloge_moteur, "executer_tick", _tick_lent)

    dues = [
        {"monde_id": "monde-a", "cle_api": "k1"},
        {"monde_id": "monde-b", "cle_api": "k1"},
        {"monde_id": "monde-c", "cle_api": "k1"},
    ]

    debut = time.monotonic()
    await main._executer_passage(dues)
    duree = time.monotonic() - debut

    # 3 ticks de 0.2s : en série ~0.6s, en parallèle ~0.2s. Seuil à 0.45s pour
    # absorber la latence de l'environnement de test sans rendre le test friable.
    assert duree < 0.45
    assert set(ordre_debut) == {"monde-a", "monde-b", "monde-c"}
    assert set(ordre_fin) == {"monde-a", "monde-b", "monde-c"}


@pytest.mark.asyncio
async def test_executer_passage_logue_les_avertissements(monkeypatch, caplog):
    async def _tick_avec_avertissement(monde_id, cle_api_val):
        return {"avertissements": [
            "Émigration de x vers y non appliquée : verrou du pays destination "
            "indisponible (retentera au tick suivant)."
        ]}

    monkeypatch.setattr(horloge_moteur, "executer_tick", _tick_avec_avertissement)

    with caplog.at_level(logging.WARNING, logger="world-engine"):
        await main._executer_passage([{"monde_id": "monde-a", "cle_api": "k1"}])

    avertissements = [r for r in caplog.records if r.levelname == "WARNING"]
    assert len(avertissements) == 1
    assert "monde-a" in avertissements[0].message
    assert "verrou du pays destination" in avertissements[0].message


@pytest.mark.asyncio
async def test_executer_passage_isole_une_exception_sans_arreter_les_autres(monkeypatch, caplog):
    appeles = []

    async def _tick_selon_monde(monde_id, cle_api_val):
        appeles.append(monde_id)
        if monde_id == "monde-en-echec":
            raise RuntimeError("panne simulée")
        return {"avertissements": []}

    monkeypatch.setattr(horloge_moteur, "executer_tick", _tick_selon_monde)

    dues = [
        {"monde_id": "monde-en-echec", "cle_api": "k1"},
        {"monde_id": "monde-ok", "cle_api": "k1"},
    ]

    with caplog.at_level(logging.ERROR, logger="world-engine"):
        await main._executer_passage(dues)  # ne doit lever aucune exception

    assert set(appeles) == {"monde-en-echec", "monde-ok"}
    erreurs = [r for r in caplog.records if r.levelname == "ERROR"]
    assert len(erreurs) == 1
    assert "monde-en-echec" in erreurs[0].message
```

- [ ] **Step 2 : Lancer les tests, vérifier qu'ils échouent**

Run: `cd briques/world-engine && python -m pytest test_scheduler.py -v`
Expected: FAIL — `AttributeError: module 'main' has no attribute '_executer_passage'` (les trois tests échouent à l'appel, `_executer_passage` n'existe pas encore).

- [ ] **Step 3 : Implémenter le logging et la parallélisation**

Dans `briques/world-engine/main.py`, remplacer les lignes 7-8 :

```python
import asyncio
import os
```

par :

```python
import asyncio
import logging
import os
```

Remplacer les lignes 23-25 :

```python
import stockage_spatial

app = FastAPI(title="World Engine — Génome Cosmique", version="0.1.0")
```

par :

```python
import stockage_spatial

_log = logging.getLogger("world-engine")

app = FastAPI(title="World Engine — Génome Cosmique", version="0.1.0")
```

Remplacer les lignes 367-387 (de `SCHEDULER_INTERVALLE_S = ...` jusqu'à la fin de `_boucle_scheduler`) :

```python
SCHEDULER_INTERVALLE_S = int(os.getenv("HORLOGE_SCHEDULER_INTERVALLE_S", "5"))
_SCHEDULER_ACTIF = os.getenv("HORLOGE_SCHEDULER_DESACTIVE", "").strip() != "1"


async def _boucle_scheduler():
    """Tâche de fond in-process (pas de queue externe — volume modéré visé ce
    sprint, voir design). Vérifie périodiquement les horloges actives dont
    l'intervalle est écoulé et déclenche leur tick. Une erreur sur un monde
    n'interrompt jamais la boucle ni les autres mondes."""
    while True:
        await asyncio.sleep(SCHEDULER_INTERVALLE_S)
        maintenant = datetime.now(timezone.utc).isoformat()
        try:
            dues = stockage_horloge.horloges_actives_a_declencher(maintenant)
        except Exception:
            continue
        for due in dues:
            try:
                await horloge_moteur.executer_tick(due["monde_id"], due["cle_api"])
            except Exception:
                continue
```

par :

```python
SCHEDULER_INTERVALLE_S = int(os.getenv("HORLOGE_SCHEDULER_INTERVALLE_S", "5"))
_SCHEDULER_ACTIF = os.getenv("HORLOGE_SCHEDULER_DESACTIVE", "").strip() != "1"


async def _executer_et_consigner(monde_id: str, cle_api_val: str) -> None:
    """Exécute un tick et consigne son issue. N'importe quelle exception est
    attrapée ici, jamais laissée remonter à `asyncio.gather` — c'est ce qui
    isole un monde en échec des autres mondes du même passage."""
    try:
        resultat = await horloge_moteur.executer_tick(monde_id, cle_api_val)
        for avertissement in resultat.get("avertissements", []):
            _log.warning("monde=%s %s", monde_id, avertissement)
    except Exception:
        _log.exception("tick en échec monde=%s", monde_id)


async def _executer_passage(dues: list[dict]) -> None:
    """Exécute tous les mondes dus d'un même passage EN PARALLÈLE — la durée
    du passage devient max(durées) au lieu de Σ(durées). Voir
    docs/superpowers/specs/2026-08-25-world-engine-sprint-e-scheduler-parallele-design.md."""
    await asyncio.gather(*(_executer_et_consigner(d["monde_id"], d["cle_api"]) for d in dues))


async def _boucle_scheduler():
    """Tâche de fond in-process (pas de queue externe — volume modéré visé ce
    sprint, voir design). Vérifie périodiquement les horloges actives dont
    l'intervalle est écoulé et déclenche leur tick."""
    while True:
        await asyncio.sleep(SCHEDULER_INTERVALLE_S)
        maintenant = datetime.now(timezone.utc).isoformat()
        try:
            dues = stockage_horloge.horloges_actives_a_declencher(maintenant)
        except Exception:
            continue
        await _executer_passage(dues)
```

- [ ] **Step 4 : Lancer les tests, vérifier qu'ils passent**

Run: `cd briques/world-engine && python -m pytest test_scheduler.py -v`
Expected: PASS — 3 tests verts.

- [ ] **Step 5 : Lancer toute la suite de la brique (non-régression)**

Run: `cd briques/world-engine && python -m pytest -v`
Expected: PASS — tous les tests existants (`test_api.py`, `test_horloge_moteur.py`, etc.) restent verts, aucune régression introduite par le refactor.

Si l'environnement local ne peut pas exécuter pytest nativement (dépendances absentes), utiliser le filet conteneurisé du repo :
Run: `scripts/tests_briques.sh world-engine`
Expected: `✓ world-engine` en sortie, aucun `ECHEC`.

- [ ] **Step 6 : Commit**

```bash
git add briques/world-engine/main.py briques/world-engine/test_scheduler.py
git commit -m "$(cat <<'EOF'
fix(world-engine): scheduler parallélisé — élimine la dérive de tick (+14%)

_boucle_scheduler awaitait chaque monde dû EN SÉRIE (mesuré en LIVE :
+14,0% de dérive systématique sur 5 mondes). Remplacé par asyncio.gather()
sur un passage, avec isolation d'erreur préservée et logging des
avertissements/exceptions désormais visibles (docker logs) au lieu d'être
jetés silencieusement.

Voir docs/superpowers/specs/2026-08-25-world-engine-sprint-e-scheduler-parallele-design.md
EOF
)"
```

---

### Task 2 : Validation LIVE sur le HP

**Files:** aucun (déploiement + mesure, pas de code) — dépend de la Task 1 poussée sur `main`.

**Interfaces:**
- Consomme : `scripts/mesure_charge_world_engine.py` (existant, sous-commandes `demarrer-scheduler`, `observer`, `arreter-scheduler`), état laissé sur le HP par la mesure du 2026-08-25 (`/tmp/world-engine-charge/mondes.json`, 5 mondes fédérés déjà peuplés, non supprimés).

- [ ] **Step 1 : Mettre à jour et rebuilder `world-engine` sur le HP**

```bash
ssh -o BatchMode=yes debian@192.168.1.89 '
  cd /home/debian/workplace &&
  git pull &&
  cd briques/world-engine &&
  docker compose build world-engine &&
  docker compose up -d world-engine
'
```
Expected : build réussi, conteneur recréé, aucune erreur.

- [ ] **Step 2 : Vérifier la santé du conteneur**

```bash
ssh -o BatchMode=yes debian@192.168.1.89 'curl -s http://localhost:6230/sante'
```
Expected : réponse HTTP 200 (endpoint santé, jamais protégé par clé — voir `test_sante_jamais_protegee_meme_avec_api_keys`).

- [ ] **Step 3 : Vérifier que l'état de la mesure précédente est toujours présent**

```bash
ssh -o BatchMode=yes debian@192.168.1.89 'test -f /tmp/world-engine-charge/mondes.json && echo present || echo absent'
```
Expected : `present`. Si `absent` (ex. `/tmp` vidé par un reboot du HP), il faut relancer `setup` avec les MÊMES clés API que celles déjà configurées pour cette brique sur le HP (`briques/world-engine/.env` pour le tenant local, `WORLD_ENGINE_KEY` du `.env` racine pour le second tenant — voir mémoire `sprint-world-engine-mesure-charge`) avant de poursuivre à l'étape 4 ; ne pas générer de nouvelles clés, la fédération et les adjacences existantes dépendent des clés d'origine.

- [ ] **Step 4 : Rejouer la fenêtre scheduler (même scénario que le rapport du 2026-08-25)**

```bash
ssh -o BatchMode=yes debian@192.168.1.89 '
  cd /home/debian/workplace &&
  python3 scripts/mesure_charge_world_engine.py demarrer-scheduler --intervalle-secondes 5 &&
  python3 scripts/mesure_charge_world_engine.py observer --duree-minutes 12 --intervalle-poll 2 | tee /tmp/world-engine-charge/observer-sprint-e.txt &&
  python3 scripts/mesure_charge_world_engine.py arreter-scheduler
'
```
Expected : sortie de `observer` avec, pour chacun des 5 mondes, le nombre de ticks observés et l'écart moyen — comparable en forme au tableau du Résultat 1 du rapport du 2026-08-25.

- [ ] **Step 5 : Comparer l'écart moyen à la mesure précédente**

Depuis la sortie de `observer` (Step 4), calculer l'écart moyen par monde comme dans le rapport (portée totale ÷ nombre d'incréments — jamais les percentiles, artefact du pas de polling, voir rapport du 2026-08-25). Comparer à la référence : 5,698s (+14,0% de dérive) avant correctif.

Expected : écart moyen proche de 5,0s (dérive proche de 0%) sur les 5 mondes après le correctif de la Task 1. Si l'écart reste significativement supérieur à 5,0s, c'est un signal que la cause structurelle n'est pas entièrement corrigée — ne pas conclure au succès sans revenir sur le code de la Task 1.

- [ ] **Step 6 : Vérifier que les avertissements de verrou, s'il y en a, sont désormais visibles dans les logs**

```bash
ssh -o BatchMode=yes debian@192.168.1.89 'docker logs --since 20m workplace_world_engine 2>&1 | grep -i "verrou du pays destination" | head -20'
```
Expected : soit aucune ligne (aucune contention pendant cette fenêtre, cohérent avec un scheduler qui reste principalement séquentiel dans les faits à ce volume), soit des lignes visibles avec `monde=<id>` — dans les deux cas, la preuve que ces avertissements ne sont plus jetés silencieusement (avant ce sprint, ils n'apparaissaient JAMAIS dans les logs, voir rapport du 2026-08-25, Résultat 2).

- [ ] **Step 7 : Consigner le résultat**

Ajouter une note courte (pas un nouveau rapport complet) en tête du fichier
`docs/superpowers/reports/2026-08-25-world-engine-mesure-charge-rapport.md`,
juste après le titre, avec les chiffres de la Step 5 et le commit de la
Task 1 :

```markdown
> **Correctif Sprint E (commit à compléter au moment du commit)** : la dérive
> de +14,0% mesurée ci-dessous a pour cause `_boucle_scheduler` en série
> (voir Résultat 1) — corrigée en parallélisant l'exécution des mondes dus
> par passage (`asyncio.gather`, voir
> `docs/superpowers/specs/2026-08-25-world-engine-sprint-e-scheduler-parallele-design.md`).
> Re-mesure du 2026-08-25 après correctif : écart moyen [valeur mesurée
> Step 5]s sur les 5 mondes (contre 5,698s avant). Le reste de ce rapport
> (Résultats 2-4, correctifs hors-plan) reste valable tel quel — seul le
> mécanisme du Résultat 1 a changé.
```

```bash
cd /Users/garinat_t/Desktop/Workplace
git add docs/superpowers/reports/2026-08-25-world-engine-mesure-charge-rapport.md
git commit -m "$(cat <<'EOF'
docs(world-engine): consigne la re-mesure LIVE après correctif scheduler

Sprint E (scheduler parallélisé) prouvé en LIVE sur le HP — dérive de
tick redescendue proche de 0% (contre +14,0% avant correctif).

EOF
)"
git push
```

## Self-Review

**Couverture de la spec** : parallélisation via `asyncio.gather()` (Task 1, Step 3) ; isolation d'erreur préservée (Task 1, Step 3 + test `test_executer_passage_isole_une_exception_sans_arreter_les_autres`) ; logging standard aligné sur `calcul`/`restaurant` (Task 1, Step 3, `_log = logging.getLogger("world-engine")`) ; avertissements en `WARNING`, exceptions en `ERROR` (Task 1, Step 3 + tests) ; tests unitaires (Task 1) ; validation LIVE avec re-mesure et comparaison au rapport existant (Task 2) ; hors périmètre (Redis/RabbitMQ, >5 mondes, verrou Sprint D, persistance en base) — non touchés par ce plan, conforme à la spec.

**Signatures** : `_executer_et_consigner(monde_id: str, cle_api_val: str) -> None` et `_executer_passage(dues: list[dict]) -> None` cohérentes entre la définition (Task 1, Step 3) et les tests (Task 1, Step 1) — noms et types identiques partout.

**Aucun placeholder** : toutes les étapes contiennent du code ou des commandes complets et exacts ; la seule branche conditionnelle (Task 2, Step 3, fichier d'état absent) documente la commande de secours exacte (`setup` avec les clés déjà configurées) plutôt que de renvoyer à une étape vague.
