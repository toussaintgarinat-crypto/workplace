# World Engine — Sprint E, correctif contention de verrou — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Réduire la contention de verrou destination (Sprint D) qui a fait passer la dérive de tick de +14,0% à +94,6% après la parallélisation du scheduler — timeout de verrou 5.0s→1.0s, et jitter au premier démarrage d'une horloge pour désynchroniser les mondes partageant un intervalle.

**Architecture:** Deux changements indépendants, tous deux dans `briques/world-engine` : `horloge_moteur.VERROU_DESTINATION_TIMEOUT_S` passe de `5.0` à `1.0` (une constante) ; `stockage_horloge.demarrer()` initialise `derniere_execution` à une valeur jitterée (au lieu de `NULL`) lors du tout premier démarrage d'une horloge, laissant inchangé le cas d'un redémarrage après un arrêt.

**Tech Stack:** Python 3.12, stdlib `random`/`datetime` (aucune nouvelle dépendance), pytest (motif `monkeypatch` déjà utilisé dans `test_stockage_horloge.py`/`test_horloge_moteur.py`).

## Global Constraints

- Comportement de re-tentative de migration inchangé (« retentera au tick suivant », capturé dans `avertissements`) — seule la latence maximale d'attente de verrou change (spec, section « Décisions de conception »).
- Le jitter ne s'applique QU'au tout premier démarrage d'une horloge (`derniere_execution IS NULL`) — un redémarrage après arrêt garde sa phase existante, `demarrer` ne touche pas `derniere_execution` dans ce cas (spec, section « Décisions de conception »).
- Plafond du jitter = l'intervalle configuré lui-même (`random.uniform(0, intervalle_secondes)`), pas une valeur séparée — décision utilisateur explicite, pas un paramètre de configuration à exposer (spec, section « Hors périmètre »).
- Pas de refonte de la granularité du verrou lui-même — hors périmètre de ce sprint (spec, section « Hors périmètre »).

---

### Task 1 : Timeout de verrou + jitter au premier démarrage

**Files:**
- Modify: `briques/world-engine/horloge_moteur.py:72` (constante `VERROU_DESTINATION_TIMEOUT_S`)
- Modify: `briques/world-engine/stockage_horloge.py:16` (import, ajout `timedelta` + `random`)
- Modify: `briques/world-engine/stockage_horloge.py:79-85` (fonction `demarrer`)
- Modify: `briques/world-engine/test_stockage_horloge.py:45-50` (test existant à remplacer par deux tests déterministes)
- Modify: `briques/world-engine/test_horloge_moteur.py` (un test ajouté confirmant la nouvelle valeur par défaut)

**Interfaces:**
- Consomme : `stockage_horloge.lire_horloge(monde_id: str) -> dict | None` (existant, renvoie entre autres `"derniere_execution": str | None`).
- Produit : aucune nouvelle fonction publique — `demarrer(monde_id: str, intervalle_secondes: int) -> None` garde exactement la même signature, seul son comportement interne change.

- [ ] **Step 1 : Écrire les tests, d'abord en échec**

Dans `briques/world-engine/test_stockage_horloge.py`, remplacer les lignes 45-50 :

```python
def test_horloges_actives_a_declencher_jamais_executee_est_due():
    monde = stockage_spatial.creer_monde("cle-h4", _cellules_factices(), seed=1)
    stockage_horloge.initialiser_horloge(monde["id"])
    stockage_horloge.demarrer(monde["id"], 60)
    dues = stockage_horloge.horloges_actives_a_declencher("2026-01-01T00:00:00+00:00")
    assert any(d["monde_id"] == monde["id"] and d["cle_api"] == "cle-h4" for d in dues)
```

par :

```python
def test_demarrer_horloge_jamais_executee_initialise_derniere_execution_dans_les_bornes_du_jitter():
    from datetime import datetime, timedelta, timezone
    monde = stockage_spatial.creer_monde("cle-h4", _cellules_factices(), seed=1)
    stockage_horloge.initialiser_horloge(monde["id"])
    avant = datetime.now(timezone.utc)
    stockage_horloge.demarrer(monde["id"], 60)
    apres = datetime.now(timezone.utc)
    etat = stockage_horloge.lire_horloge(monde["id"])
    derniere_execution = datetime.fromisoformat(etat["derniere_execution"])
    # Jitter dans [0, intervalle_secondes] appliqué à l'instant de l'appel : la
    # valeur stockée doit tomber entre (avant - 60s) et (apres), quelle que soit
    # la valeur aléatoire tirée.
    assert (avant - timedelta(seconds=60)) <= derniere_execution <= apres


def test_horloges_actives_a_declencher_jamais_executee_est_due_au_plus_tard_apres_intervalle(monkeypatch):
    monkeypatch.setattr(stockage_horloge.random, "uniform", lambda a, b: b)  # pire cas : jitter maximal
    monde = stockage_spatial.creer_monde("cle-h4b", _cellules_factices(), seed=1)
    stockage_horloge.initialiser_horloge(monde["id"])
    stockage_horloge.demarrer(monde["id"], 60)
    maintenant = datetime.now(timezone.utc).isoformat()
    dues = stockage_horloge.horloges_actives_a_declencher(maintenant)
    assert any(d["monde_id"] == monde["id"] and d["cle_api"] == "cle-h4b" for d in dues)


def test_horloges_actives_a_declencher_jamais_executee_pas_forcement_due_immediatement(monkeypatch):
    monkeypatch.setattr(stockage_horloge.random, "uniform", lambda a, b: 0.0)  # jitter minimal
    monde = stockage_spatial.creer_monde("cle-h4c", _cellules_factices(), seed=1)
    stockage_horloge.initialiser_horloge(monde["id"])
    stockage_horloge.demarrer(monde["id"], 60)
    maintenant = datetime.now(timezone.utc).isoformat()
    dues = stockage_horloge.horloges_actives_a_declencher(maintenant)
    assert not any(d["monde_id"] == monde["id"] for d in dues)
```

Ces trois tests ont besoin de `from datetime import datetime, timezone` déjà utilisé ailleurs dans le fichier (import local, même motif que `test_horloges_actives_a_declencher_respecte_intervalle` existant) — le premier test importe aussi `timedelta` localement.

Ajouter en tête de `briques/world-engine/test_horloge_moteur.py` (n'importe où après les imports existants, par exemple juste après la dernière fonction de test du fichier) :

```python
def test_verrou_destination_timeout_par_defaut_est_1_0s():
    assert horloge_moteur.VERROU_DESTINATION_TIMEOUT_S == 1.0
```

- [ ] **Step 2 : Lancer les tests, vérifier qu'ils échouent**

Run: `cd briques/world-engine && python -m pytest test_stockage_horloge.py test_horloge_moteur.py -v -k "jitter or jamais_executee or timeout_par_defaut"`
Expected : FAIL — `test_demarrer_horloge_jamais_executee_initialise_derniere_execution_dans_les_bornes_du_jitter` échoue avec `TypeError`/`AttributeError` (`derniere_execution` toujours `None`, `datetime.fromisoformat(None)` lève) ; `test_horloges_actives_a_declencher_jamais_executee_pas_forcement_due_immediatement` échoue (l'horloge EST due, comportement actuel) ; `test_verrou_destination_timeout_par_defaut_est_1_0s` échoue (`5.0 != 1.0`). `test_horloges_actives_a_declencher_jamais_executee_est_due_au_plus_tard_apres_intervalle` peut déjà passer par accident (comportement actuel = toujours due) — normal, pas un problème, sa valeur vient du couple avec le test suivant.

- [ ] **Step 3 : Implémenter le timeout et le jitter**

Dans `briques/world-engine/horloge_moteur.py`, remplacer la ligne 72 :

```python
VERROU_DESTINATION_TIMEOUT_S = 5.0
```

par :

```python
VERROU_DESTINATION_TIMEOUT_S = 1.0
```

Dans `briques/world-engine/stockage_horloge.py`, remplacer la ligne 16 :

```python
from datetime import datetime, timezone
```

par :

```python
import random
from datetime import datetime, timedelta, timezone
```

Remplacer les lignes 79-85 (fonction `demarrer`) :

```python
def demarrer(monde_id: str, intervalle_secondes: int) -> None:
    """`lire_horloge` d'abord : garantit la ligne `horloges` (rattrapage paresseux)
    pour que l'UPDATE ci-dessous ne porte jamais sur zéro ligne en silence."""
    lire_horloge(monde_id)
    with _conn() as c:
        c.execute("UPDATE horloges SET actif=1, intervalle_secondes=? WHERE monde_id=?",
                   (intervalle_secondes, monde_id))
```

par :

```python
def demarrer(monde_id: str, intervalle_secondes: int) -> None:
    """`lire_horloge` d'abord : garantit la ligne `horloges` (rattrapage paresseux)
    pour que l'UPDATE ci-dessous ne porte jamais sur zéro ligne en silence.

    Jitter au tout premier démarrage (`derniere_execution` encore `NULL`) : évite
    que plusieurs mondes démarrés ensemble avec le même intervalle restent
    perpétuellement dus au même instant (mesuré en LIVE, Sprint E — voir
    docs/superpowers/specs/2026-08-26-world-engine-sprint-e-correctif-contention-verrou-design.md).
    Un monde déjà tické avant garde sa phase existante : `derniere_execution`
    n'est pas modifié dans ce cas."""
    horloge = lire_horloge(monde_id)
    with _conn() as c:
        if horloge["derniere_execution"] is None:
            derniere_execution_initiale = (
                datetime.now(timezone.utc) - timedelta(seconds=random.uniform(0, intervalle_secondes))
            ).isoformat()
            c.execute(
                "UPDATE horloges SET actif=1, intervalle_secondes=?, derniere_execution=? WHERE monde_id=?",
                (intervalle_secondes, derniere_execution_initiale, monde_id))
        else:
            c.execute("UPDATE horloges SET actif=1, intervalle_secondes=? WHERE monde_id=?",
                       (intervalle_secondes, monde_id))
```

- [ ] **Step 4 : Lancer les tests, vérifier qu'ils passent**

Run: `cd briques/world-engine && python -m pytest test_stockage_horloge.py test_horloge_moteur.py -v`
Expected : PASS — tous les tests des deux fichiers verts, y compris les 3 nouveaux et le test ajouté dans `test_horloge_moteur.py`.

- [ ] **Step 5 : Lancer toute la suite de la brique (non-régression)**

Run: `cd briques/world-engine && python -m pytest -v`
Expected : PASS — tous les tests existants restent verts (`test_api.py`, `test_horloge_moteur.py`, `test_federation.py`, etc.), aucune régression.

Si l'environnement local ne peut pas exécuter pytest nativement :
Run: `scripts/tests_briques.sh world-engine`
Expected : `✓ world-engine` en sortie, aucun `ECHEC`.

- [ ] **Step 6 : Commit**

```bash
git add briques/world-engine/horloge_moteur.py briques/world-engine/stockage_horloge.py briques/world-engine/test_stockage_horloge.py briques/world-engine/test_horloge_moteur.py
git commit -m "$(cat <<'EOF'
fix(world-engine): réduit la contention de verrou (timeout 5s→1s + jitter)

La re-mesure LIVE du scheduler parallélisé (2676b4a) a montré une dérive de
+94,6% (contre +14,0% avant) : 328 avertissements de verrou destination sur
~366 ticks en 12 min, causés par 5 mondes partageant le même intervalle et
restant en permanence dus ensemble (attente circulaire dans la topologie en
anneau). Un tick isolé mesuré à ~0,2s justifie de réduire le timeout de
verrou de 5.0s à 1.0s. Un jitter au premier démarrage d'une horloge
désynchronise les mondes qui partagent un intervalle.

Voir docs/superpowers/specs/2026-08-26-world-engine-sprint-e-correctif-contention-verrou-design.md
EOF
)"
```

---

### Task 2 : Validation LIVE sur le HP

**Files:** aucun (déploiement + mesure, pas de code) — dépend de la Task 1 poussée sur `main`.

**Interfaces:**
- Consomme : `scripts/mesure_charge_world_engine.py` (existant, sous-commandes `demarrer-scheduler`, `observer`, `arreter-scheduler`), les 5 mondes fédérés déjà en place sur le HP (population vivante ~1437 au 26/08, vérifiée via `GET /federation/{id}/etat` et `GET /spatial/mondes`).

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
Expected : build réussi, conteneur recréé, aucune erreur. Vérifier que le commit qui atterrit correspond bien à celui de la Task 1 (`git pull` affiche le SHA de fast-forward).

- [ ] **Step 2 : Vérifier la santé du conteneur**

```bash
ssh -o BatchMode=yes debian@192.168.1.89 'curl -s -o /tmp/sante_out.txt -w "HTTP_CODE=%{http_code}\n" http://localhost:6230/sante; cat /tmp/sante_out.txt'
```
Expected : `HTTP_CODE=200`.

- [ ] **Step 3 : Vérifier la présence de l'état de mesure**

```bash
ssh -o BatchMode=yes debian@192.168.1.89 'test -f /tmp/world-engine-charge/mondes.json && echo present || echo absent'
```
Expected : `present` (reconstruit lors de la Task 2 précédente, le 26/08 — ne devrait pas avoir été affecté par ce redéploiement, qui ne fait que `build`+`up -d`, pas de reboot). Si `absent` (nouveau reboot du HP entre-temps), reconstruire le fichier via l'API exactement comme documenté dans `.superpowers/sdd/task-2-report.md` (interroger `/federation` et `/spatial/mondes` avec les clés déjà configurées dans `briques/world-engine/.env` et le `.env` racine, sans jamais relancer `setup` ni régénérer de clés) avant de poursuivre — ne pas improviser une autre approche.

- [ ] **Step 4 : Rejouer la fenêtre scheduler**

```bash
ssh -o BatchMode=yes debian@192.168.1.89 '
  cd /home/debian/workplace &&
  rm -f /tmp/world-engine-charge/observations.jsonl &&
  python3 scripts/mesure_charge_world_engine.py demarrer-scheduler --intervalle-secondes 5 &&
  python3 scripts/mesure_charge_world_engine.py observer --duree-minutes 12 --intervalle-poll 2 | tee /tmp/world-engine-charge/observer-correctif-verrou.txt &&
  python3 scripts/mesure_charge_world_engine.py arreter-scheduler
'
```
Expected : sortie de `observer` sans erreur ; vérifier ensuite via `GET /horloge/{id}` sur les 5 mondes que `actif` est bien repassé à `false` (scheduler correctement arrêté).

Le `rm -f` initial est nécessaire : `commande_observer` ouvre le fichier en mode append (`"a"`), et la précédente fenêtre du 26/08 y a déjà écrit — sans ce nettoyage, la nouvelle mesure serait mélangée à l'ancienne.

- [ ] **Step 5 : Calculer l'écart moyen et comparer**

Récupérer le fichier d'observations et calculer, pour chaque monde, l'écart moyen non biaisé EXACTEMENT comme `calculer_ecart` dans `scripts/mesure_charge_world_engine.py` (portée totale des timestamps ÷ écart de valeur de tick, JAMAIS les percentiles) :

```bash
scp -o BatchMode=yes debian@192.168.1.89:/tmp/world-engine-charge/observations.jsonl /tmp/observations-correctif-verrou.jsonl
```

```python
import json
from collections import defaultdict

obs = defaultdict(list)
with open('/tmp/observations-correctif-verrou.jsonl') as f:
    for line in f:
        o = json.loads(line)
        if o.get("tick_actuel") is not None:
            obs[o["monde_id"]].append((o["ts"], o["tick_actuel"]))

def calculer_ecart(observations):
    vus = sorted(observations, key=lambda o: o[0])
    if not vus:
        return {}
    increments = []
    dernier_tick = None
    i = 0
    while i < len(vus):
        current_tick = vus[i][1]
        last_ts = vus[i][0]
        j = i + 1
        while j < len(vus) and vus[j][1] == current_tick:
            last_ts = vus[j][0]
            j += 1
        if dernier_tick is None or current_tick > dernier_tick:
            increments.append((last_ts, current_tick))
            dernier_tick = current_tick
        i = j
    if len(increments) < 2:
        return {}
    ecart_moyen = (increments[-1][0] - increments[0][0]) / (increments[-1][1] - increments[0][1])
    return {"nb_ticks_observes": len(increments) - 1, "ecart_moyen_s": ecart_moyen}

for monde_id, o in obs.items():
    print(monde_id, calculer_ecart(o))
```

Expected : `ecart_moyen_s` nettement inférieur aux 9,73s mesurés avant ce correctif — idéalement proche de 5,0-5,7s. Si l'écart moyen reste proche de 9,73s ou pire, c'est un signal que le correctif n'a pas résolu la contention — ne pas conclure au succès sans revenir sur le code de la Task 1 (ex. le jitter n'a peut-être pas suffi à désynchroniser des mondes déjà en phase depuis leur historique de ticks antérieur — voir Risques dans le design).

- [ ] **Step 6 : Compter les avertissements de verrou dans les logs**

```bash
ssh -o BatchMode=yes debian@192.168.1.89 'docker logs --since 20m workplace_world_engine 2>&1 | grep -ci "verrou du pays destination"'
```
Expected : nettement inférieur aux 328 avertissements mesurés avant ce correctif (idéalement proche de 0, mais un nombre résiduel faible est acceptable — le mécanisme de contention reste possible en théorie, seulement rendu rare).

- [ ] **Step 7 : Vérifier l'absence de régression sur les migrations transfrontières**

```bash
ssh -o BatchMode=yes debian@192.168.1.89 '
KEY_A=$(grep "^API_KEYS=" /home/debian/workplace/briques/world-engine/.env | cut -d= -f2-)
curl -s -H "X-API-Key: $KEY_A" "http://localhost:6230/federation/c18fd628c09a49cf8ea13225e42875f8/etat"
'
```
Expected : `population_totale` cohérente avec une activité normale (naissances/morts/migrations continuent de se produire) — pas de blocage total du mécanisme de migration.

- [ ] **Step 8 : Consigner le résultat**

Ajouter une note courte en tête du fichier
`docs/superpowers/reports/2026-08-25-world-engine-mesure-charge-rapport.md`,
juste après la note du correctif scheduler déjà présente (voir Task 2 du
plan `2026-08-25-world-engine-sprint-e-scheduler-parallele.md`), avec les
chiffres réels de cette validation et le commit de la Task 1 de CE plan :

```markdown
> **Correctif contention de verrou (commit à compléter au moment du
> commit)** : la parallélisation du scheduler ci-dessus a révélé un
> nouveau goulot — 328 avertissements de verrou destination sur ~366 ticks
> en 12 min (dérive +94,6%), causé par des mondes synchronisés sur le même
> intervalle restant en permanence dus ensemble. Corrigé par un timeout de
> verrou réduit (5.0s→1.0s, mesure directe : tick isolé ~0,2s) et un
> jitter au premier démarrage d'une horloge (voir
> `docs/superpowers/specs/2026-08-26-world-engine-sprint-e-correctif-contention-verrou-design.md`).
> Re-mesure du 2026-08-26 après ce correctif : écart moyen [valeur mesurée
> Step 5]s, [nombre mesuré Step 6] avertissements de verrou sur la fenêtre
> (contre 9,73s / 328 avant ce correctif).
```

```bash
cd /Users/garinat_t/Desktop/Workplace
git add docs/superpowers/reports/2026-08-25-world-engine-mesure-charge-rapport.md
git commit -m "$(cat <<'EOF'
docs(world-engine): consigne la re-mesure LIVE après correctif verrou

Sprint E (correctif contention de verrou) prouvé en LIVE sur le HP.

EOF
)"
git push
```

---

### Task 3 : Jitter à chaque démarrage (pas seulement le premier)

**Contexte** : la Task 2 (validation LIVE) a montré que le jitter de la
Task 1 ne s'est jamais déclenché — les 5 mondes de test étaient déjà
synchronisés depuis avant que ce correctif n'existe (`derniere_execution`
n'était plus `NULL`). Dérive descendue à +40,4% (7,02s) grâce au seul
timeout réduit, avertissements montés à 608 (contre 328 avant tout
correctif de verrou). Décision utilisateur : étendre le jitter à CHAQUE
appel à `demarrer()`, pas seulement au tout premier — voir
`docs/superpowers/specs/2026-08-26-world-engine-sprint-e-correctif-contention-verrou-design.md`,
section « Mise à jour post-validation LIVE ».

**Files:**
- Modify: `briques/world-engine/stockage_horloge.py:80-110` (fonction `demarrer`, simplifiée)
- Modify: `briques/world-engine/test_stockage_horloge.py:60-69` (test remplacé)

**Interfaces:**
- `demarrer(monde_id: str, intervalle_secondes: int) -> None` — signature inchangée, comportement simplifié (plus de branche conditionnelle).

- [ ] **Step 1 : Écrire le test, d'abord en échec**

Dans `briques/world-engine/test_stockage_horloge.py`, remplacer les lignes 60-69 :

```python
def test_demarrer_horloge_deja_tickee_garde_sa_phase():
    monde = stockage_spatial.creer_monde("cle-h4d", _cellules_factices(), seed=1)
    stockage_horloge.initialiser_horloge(monde["id"])
    stockage_horloge.marquer_execution(monde["id"], 5)  # simule un tick manuel avant tout démarrage automatique
    etat_avant = stockage_horloge.lire_horloge(monde["id"])
    stockage_horloge.demarrer(monde["id"], 60)
    etat_apres = stockage_horloge.lire_horloge(monde["id"])
    assert etat_apres["derniere_execution"] == etat_avant["derniere_execution"]
    assert etat_apres["tick_actuel"] == 5
    assert etat_apres["actif"] is True
```

par :

```python
def test_demarrer_horloge_deja_tickee_est_rejitteree_au_redemarrage():
    from datetime import datetime, timedelta, timezone
    monde = stockage_spatial.creer_monde("cle-h4d", _cellules_factices(), seed=1)
    stockage_horloge.initialiser_horloge(monde["id"])
    stockage_horloge.marquer_execution(monde["id"], 5)  # simule un tick manuel avant tout démarrage automatique
    avant = datetime.now(timezone.utc)
    stockage_horloge.demarrer(monde["id"], 60)
    apres = datetime.now(timezone.utc)
    etat_apres = stockage_horloge.lire_horloge(monde["id"])
    derniere_execution = datetime.fromisoformat(etat_apres["derniere_execution"])
    # Correctif v2 : un redémarrage rejitte toujours, il ne garde plus l'ancienne
    # phase — mêmes bornes que le tout premier démarrage.
    assert (avant - timedelta(seconds=60)) <= derniere_execution <= apres
    assert etat_apres["tick_actuel"] == 5  # tick_actuel (la progression réelle) n'est jamais touché par demarrer
    assert etat_apres["actif"] is True
```

- [ ] **Step 2 : Lancer le test, vérifier qu'il échoue**

Run: `cd briques/world-engine && python -m pytest test_stockage_horloge.py -v -k rejitteree`
Expected : FAIL — avec le code actuel (Task 1/A), un monde déjà tické garde sa `derniere_execution` inchangée (comportement v1), donc `derniere_execution` ne tombe PAS dans les bornes `[avant-60s, apres]` (elle vaut la valeur de `marquer_execution`, antérieure à `avant`).

- [ ] **Step 3 : Simplifier `demarrer` — jitter inconditionnel**

Dans `briques/world-engine/stockage_horloge.py`, remplacer les lignes 80-110 (toute la fonction `demarrer`) :

```python
def demarrer(monde_id: str, intervalle_secondes: int) -> None:
    """`lire_horloge` d'abord : garantit la ligne `horloges` (rattrapage paresseux)
    pour que la transaction ci-dessous ne porte jamais sur zéro ligne en silence.

    Jitter au tout premier démarrage (`derniere_execution` encore `NULL`) : évite
    que plusieurs mondes démarrés ensemble avec le même intervalle restent
    perpétuellement dus au même instant (mesuré en LIVE, Sprint E — voir
    docs/superpowers/specs/2026-08-26-world-engine-sprint-e-correctif-contention-verrou-design.md).
    Un monde déjà tické avant garde sa phase existante : `derniere_execution`
    n'est pas modifié dans ce cas.

    Lecture de `derniere_execution` et écriture dans LA MÊME transaction
    (`BEGIN IMMEDIATE`, correctif revue) : lire puis écrire dans deux
    connexions séparées laissait une fenêtre où un tick manuel concurrent sur
    ce même monde (`marquer_execution`, autorisé même horloge inactive)
    pouvait faire écraser sa `derniere_execution` fraîchement posée par la
    valeur jitterée calculée avant lui."""
    lire_horloge(monde_id)  # rattrapage paresseux uniquement, résultat non utilisé ici
    with _conn() as c:
        c.execute("BEGIN IMMEDIATE")
        r = c.execute("SELECT derniere_execution FROM horloges WHERE monde_id=?", (monde_id,)).fetchone()
        if r is not None and r["derniere_execution"] is None:
            derniere_execution_initiale = (
                datetime.now(timezone.utc) - timedelta(seconds=random.uniform(0, intervalle_secondes))
            ).isoformat()
            c.execute(
                "UPDATE horloges SET actif=1, intervalle_secondes=?, derniere_execution=? WHERE monde_id=?",
                (intervalle_secondes, derniere_execution_initiale, monde_id))
        else:
            c.execute("UPDATE horloges SET actif=1, intervalle_secondes=? WHERE monde_id=?",
                       (intervalle_secondes, monde_id))
```

par :

```python
def demarrer(monde_id: str, intervalle_secondes: int) -> None:
    """`lire_horloge` d'abord : garantit la ligne `horloges` (rattrapage paresseux)
    pour que l'UPDATE ci-dessous ne porte jamais sur zéro ligne en silence.

    Jitter à CHAQUE démarrage, pas seulement le premier (correctif v2, Sprint
    E — voir docs/superpowers/specs/2026-08-26-world-engine-sprint-e-correctif-contention-verrou-design.md,
    section « Mise à jour post-validation LIVE ») : un monde déjà en lockstep
    avec ses voisins (même intervalle, déjà tické ensemble par le passé) ne
    se désynchronise jamais tout seul — mesuré en LIVE, un jitter limité au
    tout premier démarrage ne s'est jamais déclenché sur des mondes déjà
    actifs avant ce correctif (dérive encore +40,4% après ce correctif limité,
    contre +94,6% avant). `derniere_execution` est donc recalculée à chaque
    appel, premier démarrage ou redémarrage — seul `tick_actuel` (la
    progression réelle) n'est jamais affecté par cette fonction. La
    simplification élimine aussi la race TOCTOU fermée en revue de la Task 1 :
    plus de lecture conditionnelle avant écriture, donc plus besoin de
    `BEGIN IMMEDIATE`."""
    lire_horloge(monde_id)  # rattrapage paresseux uniquement, résultat non utilisé ici
    derniere_execution_initiale = (
        datetime.now(timezone.utc) - timedelta(seconds=random.uniform(0, intervalle_secondes))
    ).isoformat()
    with _conn() as c:
        c.execute(
            "UPDATE horloges SET actif=1, intervalle_secondes=?, derniere_execution=? WHERE monde_id=?",
            (intervalle_secondes, derniere_execution_initiale, monde_id))
```

- [ ] **Step 4 : Lancer les tests, vérifier qu'ils passent**

Run: `cd briques/world-engine && python -m pytest test_stockage_horloge.py test_horloge_moteur.py -v`
Expected : PASS — tous les tests verts, y compris le test réécrit et les tests existants du jitter « jamais exécutée » (`test_demarrer_horloge_jamais_executee_initialise_derniere_execution_dans_les_bornes_du_jitter`, `test_horloges_actives_a_declencher_jamais_executee_est_due_au_plus_tard_apres_intervalle`, `test_horloges_actives_a_declencher_jamais_executee_pas_forcement_due_immediatement`) qui restent valides sans modification — le mécanisme de jitter lui-même ne change pas, seule sa condition de déclenchement disparaît.

- [ ] **Step 5 : Lancer toute la suite de la brique (non-régression)**

Run: `cd briques/world-engine && python -m pytest -v`
Expected : PASS — aucune régression. Si l'environnement local ne peut pas exécuter pytest nativement : `scripts/tests_briques.sh world-engine` depuis la racine du repo, attendre `✓ world-engine`.

- [ ] **Step 6 : Commit**

```bash
git add briques/world-engine/stockage_horloge.py briques/world-engine/test_stockage_horloge.py
git commit -m "$(cat <<'EOF'
fix(world-engine): jitter à chaque démarrage, pas seulement le premier

Re-mesure LIVE du correctif v1 (jitter limité à derniere_execution IS NULL) :
dérive encore +40,4% (contre +94,6% avant, +14,0% avant tout correctif de
verrou) — le jitter ne s'est jamais déclenché sur les mondes de test, déjà
synchronisés depuis avant ce correctif. demarrer() rejitte désormais à
chaque appel, premier démarrage ou redémarrage. Simplifie aussi le code :
plus de lecture conditionnelle avant écriture, donc plus besoin du
BEGIN IMMEDIATE ajouté en revue de la Task 1 pour fermer une race TOCTOU
qui disparaît avec la condition qui la rendait possible.

Voir docs/superpowers/specs/2026-08-26-world-engine-sprint-e-correctif-contention-verrou-design.md
EOF
)"
```

---

### Task 4 : Re-validation LIVE sur le HP

**Files:** aucun (déploiement + mesure) — dépend de la Task 3 poussée sur `main`.

Mêmes étapes que la Task 2 de ce plan (redéploiement, vérification santé,
vérification état de mesure, rejeu de la fenêtre scheduler 12 min avec
`rm -f` préalable de `observations.jsonl`, calcul de l'écart moyen avec
`calculer_ecart`, comptage des avertissements de verrou dans les logs,
vérification absence de régression sur les migrations). Cible cette fois :
écart moyen nettement inférieur aux 7,02s mesurés après la Task 2, et
avertissements nettement inférieurs aux 608 mesurés après la Task 2 —
idéalement proche des 5,698s / 0 avertissement significatif du régime
sériel d'avant tout correctif de scheduler. Consigner le résultat dans la
même note du rapport (`docs/superpowers/reports/2026-08-25-world-engine-mesure-charge-rapport.md`),
en ajoutant les chiffres de cette troisième mesure à la suite des deux
précédentes plutôt qu'en les remplaçant — l'historique des 3 mesures
(scheduler seul, timeout seul, timeout+jitter systématique) est la preuve
que chaque cause a été isolée avant d'être corrigée.

---

### Task 5 : Verrou destination non-bloquant

**Contexte** : la Task 4 (re-validation LIVE) a montré que le jitter
systématique (Task 3) n'apporte aucune amélioration mesurable au-delà du
timeout seul (~7,02s/+40% dans les deux cas, avertissements 608→522) —
cause statistique documentée dans le design v3 (5 mondes sur un cycle de
5s : l'écart minimal attendu entre 2 mondes est ~0,17s, bien en dessous du
coût max d'une collision, 1,0s). Décision utilisateur : rendre
`_acquerir_verrou_destination` non-bloquant plutôt que de continuer à
ajuster le timing — voir
`docs/superpowers/specs/2026-08-26-world-engine-sprint-e-correctif-contention-verrou-design.md`,
section « Mise à jour n°2 ».

**Files:**
- Modify: `briques/world-engine/horloge_moteur.py:72` (suppression de la constante `VERROU_DESTINATION_TIMEOUT_S`)
- Modify: `briques/world-engine/horloge_moteur.py:75-94` (fonction `_acquerir_verrou_destination`, réécrite non-bloquante)
- Modify: `briques/world-engine/horloge_moteur.py:115-119` (commentaire sur l'auto-adjacence, référence obsolète au timeout)
- Modify: `briques/world-engine/test_horloge_moteur.py:628-629` (retire le monkeypatch du timeout, devenu inexistant)
- Modify: `briques/world-engine/test_horloge_moteur.py:702-708` (docstring du test d'auto-adjacence, référence obsolète)
- Modify: `briques/world-engine/test_horloge_moteur.py:841-842` (supprime le test du timeout par défaut, obsolète)
- Modify: `briques/world-engine/test_horloge_moteur.py` (ajoute 2 nouveaux tests du comportement non-bloquant)

**Interfaces:**
- `_acquerir_verrou_destination(monde_id: str) -> asyncio.Lock | None` — signature inchangée, comportement non-bloquant.

- [ ] **Step 1 : Écrire les tests, d'abord en échec**

Dans `briques/world-engine/horloge_moteur.py`, lire d'abord les lignes exactes actuelles (elles ont pu bouger depuis l'écriture de ce plan) autour de `VERROU_DESTINATION_TIMEOUT_S` et `_acquerir_verrou_destination` pour confirmer les numéros de ligne avant d'éditer — le contenu ci-dessous est ce qui doit changer, pas forcément aux lignes exactes indiquées si d'autres correctifs sont passés entre-temps.

Dans `briques/world-engine/test_horloge_moteur.py`, ajouter ces deux tests (n'importe où après les imports, par exemple juste avant `test_emigration_timeout_verrou_destination_echoue_proprement`) :

```python
@pytest.mark.asyncio
async def test_acquerir_verrou_destination_libre_est_acquis_immediatement():
    monde_id = "monde-verrou-libre-sprint-e-v3"
    verrou = horloge_moteur._verrou_tick(monde_id)
    resultat = await horloge_moteur._acquerir_verrou_destination(monde_id)
    assert resultat is verrou
    assert verrou.locked()
    verrou.release()


@pytest.mark.asyncio
async def test_acquerir_verrou_destination_deja_tenu_echoue_sans_attendre():
    import time
    monde_id = "monde-verrou-tenu-sprint-e-v3"
    verrou = horloge_moteur._verrou_tick(monde_id)
    await verrou.acquire()
    try:
        debut = time.monotonic()
        resultat = await horloge_moteur._acquerir_verrou_destination(monde_id)
        duree = time.monotonic() - debut
    finally:
        verrou.release()
    assert resultat is None
    # Avant ce correctif, cet appel attendait jusqu'à VERROU_DESTINATION_TIMEOUT_S
    # (1.0s) avant d'échouer. Seuil large pour absorber la latence de test sans
    # rendre le test friable, tout en prouvant qu'il n'y a plus d'attente réelle.
    assert duree < 0.1
```

Puis remplacer dans `test_emigration_timeout_verrou_destination_echoue_proprement` la ligne :

```python
    monkeypatch.setattr(horloge_moteur, "VERROU_DESTINATION_TIMEOUT_S", 0.05)
```

par : (rien — supprimer la ligne entièrement, `VERROU_DESTINATION_TIMEOUT_S` n'existera plus).

Puis remplacer le docstring de `test_auto_adjacence_ignoree_jamais_d_emigration_vers_soi_meme` :

```python
    """Un pays déclaré adjacent à LUI-MÊME ne doit jamais être une destination de
    migration : sinon chaque émigrant viserait le pays dont le verrou de tick est
    déjà tenu par ce tick même (verrou non réentrant) et attendrait le timeout
    complet, un par un — N × VERROU_DESTINATION_TIMEOUT_S de blocage par tick
    (correctif revue Task 4). Le timeout est volontairement laissé à sa valeur
    NORMALE ici : si l'auto-adjacence n'était pas filtrée, le test durerait des
    dizaines de secondes au lieu de terminer instantanément."""
```

par :

```python
    """Un pays déclaré adjacent à LUI-MÊME ne doit jamais être une destination de
    migration : sinon chaque émigrant viserait le pays dont le verrou de tick est
    déjà tenu par ce tick même (verrou non réentrant) — depuis le correctif v3
    (acquisition non-bloquante), chaque tentative échouerait instantanément au
    lieu d'attendre, donc ce filtre n'est plus qu'une question de correction
    (un pays n'est pas sa propre destination), pas de performance."""
```

Puis supprimer entièrement (les 2 lignes) :

```python
def test_verrou_destination_timeout_par_defaut_est_1_0s():
    assert horloge_moteur.VERROU_DESTINATION_TIMEOUT_S == 1.0
```

- [ ] **Step 2 : Lancer les tests, vérifier qu'ils échouent**

Run: `cd briques/world-engine && python -m pytest test_horloge_moteur.py -v -k "verrou_destination_libre or verrou_destination_deja_tenu"`
Expected : FAIL — avec le code actuel, `_acquerir_verrou_destination` attend `asyncio.wait_for(..., timeout=1.0)` : le test `deja_tenu_echoue_sans_attendre` échoue car `duree` sera proche de 1.0s, pas `< 0.1`.

- [ ] **Step 3 : Réécrire `_acquerir_verrou_destination` sans attente**

Dans `briques/world-engine/horloge_moteur.py`, supprimer la ligne de la constante :

```python
VERROU_DESTINATION_TIMEOUT_S = 1.0
```

Remplacer la fonction :

```python
async def _acquerir_verrou_destination(monde_id: str) -> asyncio.Lock | None:
    """Tente d'acquérir le verrou de tick du pays DESTINATION d'une migration
    transfrontière, avec un timeout court.

    Un ordre d'acquisition trié par `monde_id` ne suffirait PAS à éliminer
    l'interblocage ici : le verrou du pays D'ORIGINE est déjà tenu en entrée du
    tick (`executer_tick`), avant même de savoir qu'une migration transfrontière
    aura lieu — l'ordre n'est donc jamais neutre, et 2 tics concurrents faisant le
    mouvement inverse l'un de l'autre (A→B et B→A au même instant) resteraient en
    interblocage classique malgré un tri (voir design, section corrigée).

    Renvoie le verrou ACQUIS (à libérer par l'appelant), ou None si le timeout est
    dépassé — dans ce cas CETTE émigration précise échoue proprement (capturée
    dans `avertissements`), sans jamais bloquer indéfiniment."""
    verrou = _verrou_tick(monde_id)
    try:
        await asyncio.wait_for(verrou.acquire(), timeout=VERROU_DESTINATION_TIMEOUT_S)
        return verrou
    except asyncio.TimeoutError:
        return None
```

par :

```python
async def _acquerir_verrou_destination(monde_id: str) -> asyncio.Lock | None:
    """Tente d'acquérir le verrou de tick du pays DESTINATION d'une migration
    transfrontière — tentative NON-BLOQUANTE (correctif v3, Sprint E) : mesuré
    en LIVE (3 tours de mesure, avec et sans jitter de démarrage), une attente
    même courte (1.0s) coûtait presque à chaque collision sans réduire le
    nombre d'échecs qui finissaient par se produire de toute façon — voir
    docs/superpowers/specs/2026-08-26-world-engine-sprint-e-correctif-contention-verrou-design.md,
    section « Mise à jour n°2 ». Le verdict (retentera au tick suivant) est
    identique, seule l'attente disparaît.

    Un ordre d'acquisition trié par `monde_id` ne suffirait PAS à éliminer
    l'interblocage ici : le verrou du pays D'ORIGINE est déjà tenu en entrée du
    tick (`executer_tick`), avant même de savoir qu'une migration transfrontière
    aura lieu — l'ordre n'est donc jamais neutre. Sans objet avec une tentative
    non-bloquante (aucune attente possible, donc aucun interblocage possible ici
    non plus).

    Renvoie le verrou ACQUIS (à libérer par l'appelant), ou `None` s'il est déjà
    tenu — dans ce cas CETTE émigration précise échoue proprement (capturée
    dans `avertissements`), sans attendre. `verrou.locked()` puis `acquire()`
    sans `await` entre les deux : dans le modèle coopératif d'asyncio, aucune
    tâche ne peut s'intercaler entre le test et l'acquisition, donc pas de
    fenêtre de course."""
    verrou = _verrou_tick(monde_id)
    if verrou.locked():
        return None
    await verrou.acquire()
    return verrou
```

Puis mettre à jour le commentaire sur l'auto-adjacence, quelques lignes plus bas dans le même fichier :

```python
    # Un pays n'est JAMAIS adjacent à lui-même pour la migration (correctif revue
    # Task 4, Important) : une auto-adjacence stockée en amont ferait cibler à chaque
    # émigrant le pays dont le verrou de tick est DÉJÀ tenu par ce tick — verrou non
    # réentrant, donc N émigrants = N × VERROU_DESTINATION_TIMEOUT_S de blocage, le
    # verrou d'origine tenu pendant tout ce temps. Filtré au point d'usage, quoi que
    # la table d'adjacences contienne.
```

par :

```python
    # Un pays n'est JAMAIS adjacent à lui-même pour la migration (correctif revue
    # Task 4, Important) : une auto-adjacence stockée en amont ferait cibler à chaque
    # émigrant le pays dont le verrou de tick est DÉJÀ tenu par ce tick — verrou non
    # réentrant, donc chaque émigrant échouerait (correctement, mais inutilement).
    # Filtré au point d'usage, quoi que la table d'adjacences contienne.
```

- [ ] **Step 4 : Lancer les tests, vérifier qu'ils passent**

Run: `cd briques/world-engine && python -m pytest test_horloge_moteur.py -v`
Expected : PASS — tous les tests du fichier verts, y compris les 2 nouveaux et `test_emigration_timeout_verrou_destination_echoue_proprement`/`test_auto_adjacence_ignoree_jamais_d_emigration_vers_soi_meme` modifiés.

- [ ] **Step 5 : Lancer toute la suite de la brique (non-régression)**

Run: `cd briques/world-engine && python -m pytest -v`
Expected : PASS. Si l'environnement local ne peut pas exécuter pytest nativement : `scripts/tests_briques.sh world-engine` depuis la racine du repo, attendre `✓ world-engine`.

- [ ] **Step 6 : Commit**

```bash
git add briques/world-engine/horloge_moteur.py briques/world-engine/test_horloge_moteur.py
git commit -m "$(cat <<'EOF'
fix(world-engine): verrou destination non-bloquant (retire le timeout)

3 tours de mesure LIVE (timeout seul, +timeout+jitter démarrage) plafonnent
tous deux à ~7,02s/+40% de dérive — cause statistique documentée (5 mondes
sur un cycle de 5s, écart de phase minimal attendu ~0,17s, bien en dessous
du coût max d'une collision). _acquerir_verrou_destination devient
non-bloquant (verrou.locked() puis acquire() immédiat) au lieu d'attendre
jusqu'à 1.0s — même verrou, même portée, aucun invariant Sprint D touché,
le verdict d'échec (retentera au tick suivant) est inchangé. Élimine tout
coût d'attente au lieu d'essayer d'éviter les collisions.

Voir docs/superpowers/specs/2026-08-26-world-engine-sprint-e-correctif-contention-verrou-design.md
EOF
)"
```

---

### Task 6 : Re-validation LIVE sur le HP

**Files:** aucun (déploiement + mesure) — dépend de la Task 5 poussée sur `main`.

Mêmes étapes que les Tasks 2/4 de ce plan (redéploiement, vérification
santé, vérification/reconstruction de l'état de mesure si le HP a
rebooté entre-temps — voir la procédure déjà documentée dans
`.superpowers/sdd/task-2-report.md`, ne jamais relancer `setup`, rejeu de
la fenêtre scheduler 12 min avec `rm -f` préalable de `observations.jsonl`,
calcul de l'écart moyen avec `calculer_ecart`, comptage des avertissements
de verrou dans les logs, vérification absence de régression sur les
migrations). Cible : écart moyen nettement inférieur aux 7,02s des deux
mesures précédentes — idéalement proche de 5,0-5,7s (le régime sériel
d'avant tout correctif de scheduler). Consigner cette 4e mesure à la suite
des 3 précédentes dans la même note du rapport
(`docs/superpowers/reports/2026-08-25-world-engine-mesure-charge-rapport.md`).
Si le résultat reste proche de 7s malgré ce correctif, c'est un signal
qu'autre chose contribue à la dérive au-delà de la contention de verrou
mesurée jusqu'ici — ne pas conclure au succès sans creuser, escalader
plutôt que de re-tenter un ajustement de plus sans nouvelle hypothèse.

## Self-Review

**Couverture de la spec** : timeout 5.0→1.0 (Task 1, Step 3) ; jitter au premier démarrage plafonné à l'intervalle configuré, comportement inchangé pour un redémarrage (Task 1, Step 3) ; test existant remplacé pour refléter le nouveau contrat (Task 1, Step 1, les deux tests min/max jitter remplacent l'ancien) ; validation LIVE avec comparaison chiffrée aux deux régimes précédents (avant tout correctif : 5,698s/+14,0% ; après scheduler seul : 9,73s/+94,6%) et consignation (Task 2) ; hors périmètre (granularité du verrou, paramètre de config pour le jitter) non touchés, conforme à la spec.

**Signatures** : `demarrer(monde_id: str, intervalle_secondes: int) -> None` inchangée ; `VERROU_DESTINATION_TIMEOUT_S` reste un `float` au niveau module, cohérent avec son usage existant dans `_acquerir_verrou_destination` (déjà lu dynamiquement, pas figé à l'import — les tests existants qui le monkeypatchent continuent de fonctionner sans changement).

**Aucun placeholder** : toutes les étapes contiennent du code ou des commandes complets ; la seule branche conditionnelle (Task 2, Step 3, fichier d'état absent) renvoie explicitement à la procédure déjà exécutée et documentée dans `.superpowers/sdd/task-2-report.md`, pas à une improvisation.
