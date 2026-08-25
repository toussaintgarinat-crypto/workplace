# World Engine — Mesure de charge LIVE Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Déployer `world-engine` en LIVE permanent sur le HP, y faire tourner un scénario de charge modeste (5 pays fédérés, 2 tenants), et produire un rapport chiffré (latence/dérive de tick, contention SQLite, avertissements de verrou, CPU/mémoire) qui servira de base factuelle au brainstorming Sprint E.

**Architecture:** Un script Python autonome, stdlib uniquement (`urllib.request`, pas de nouvelle dépendance), pilote l'API HTTP publique de `world-engine` déjà déployée — aucune ligne de la brique n'est modifiée. Le script a 4 sous-commandes exécutées dans l'ordre (`setup` → `demarrer-scheduler` + `observer` en parallèle → `arreter-scheduler` → `rafale-manuelle`), chacune lisant/écrivant un état JSON partagé sur disque. En parallèle de `observer`, une boucle shell séparée échantillonne `docker stats`/logs sur le HP via SSH. Le tout est exécuté une fois en conditions réelles (Task 5), puis condensé en rapport Markdown + mémoire.

**Tech Stack:** Python 3 stdlib (urllib, argparse, concurrent.futures, json, statistics), pytest pour la seule logique pure testable, bash+ssh pour l'échantillonnage `docker stats`, Docker Compose (déjà en place dans `briques/world-engine`).

## Global Constraints

- Aucune modification du code de `briques/world-engine` (`main.py`, `horloge_moteur.py`, etc.) — spec §Hors périmètre.
- Le script de mesure vit HORS de `briques/world-engine/` (racine `scripts/`).
- Scénario : 5 mondes fédérés, **au moins 2 `cle_api` distinctes**, quelques centaines d'habitants au total, scheduler automatique 5-10s, fenêtre d'observation ~10-15 minutes / ~100 ticks — spec §Décisions de conception.
- Déploiement HP **permanent**, pas jetable — décision utilisateur en brainstorming.
- Le rapport ne tranche PAS Redis vs RabbitMQ (ça, c'est Sprint E) — seulement des chiffres et une lecture factuelle.

---

## Contexte technique (lu dans le code, pour l'implémenteur)

- `POST /genome/croiser` accepte `parent_a`/`parent_b` comme fiches brutes complètes
  (`prenoms`, `nom`, `date_naissance`, `heure_naissance` "HH:MM", `latitude`,
  `longitude`, `utc_offset` — tous requis pour un thème complet, sinon 422) ou comme
  référence `{"id": ...}` vers un enfant déjà stocké. Pour peupler des mondes depuis
  zéro (aucune lignée existante), on utilise deux fiches parents FIXES et arbitraires
  pour CHAQUE fondateur — seul l'enfant (le fondateur lui-même) varie et est placé via
  `monde_id`.
- Un enfant créé par `/genome/croiser` avec `monde_id` est TOUJOURS placé comme
  nouveau-né (`ne_au_tick = tick_actuel` du monde, donc 0 à la création) — il n'existe
  aucun moyen par l'API de créer un fondateur déjà adulte. Avec `AGE_ADULTE_MIN = 16`
  (`horloge.py:21`), les fondateurs ne pourront former des couples/se reproduire qu'à
  partir du tick 16 — attendu, pas un bug du scénario.
- Le scheduler in-process (`main.py:_boucle_scheduler`) appelle
  `horloge_moteur.executer_tick` directement (pas de route HTTP) et **jette le
  résultat**, `avertissements` inclus (`except Exception: continue`). Un tick
  déclenché par le scheduler ne laisse donc AUCUNE trace exploitable de ses
  avertissements (pas de log, pas de valeur de retour observable). C'est pourquoi ce
  plan sépare deux phases : le scheduler pour mesurer la cadence/dérive (`GET
  /horloge/{id}` donne `tick_actuel`), et une rafale de **ticks manuels** (`POST
  /horloge/{id}/tick`, dont la réponse contient `avertissements`) pour mesurer la
  contention de verrou. Cette limite d'observabilité est elle-même un résultat à
  consigner dans le rapport final (Task 5).
- Authentification : `cle_api()` (`main.py:35`) accepte le header `X-API-Key`. Le
  jeu de clés acceptées = `API_KEYS` (CSV, `.env` racine, **partagé par ~22 briques,
  ne JAMAIS y ajouter une clé pour ce seul scénario**) `∪ {WORLD_ENGINE_KEY}` (clé
  dédiée, `main.py:31-32`). `WORLD_ENGINE_KEY` n'existe pas encore dans `.env` racine
  (vérifié : `API_KEYS` n'a qu'une seule clé aujourd'hui) — Task 1 en ajoute une,
  scoping le second tenant à `world-engine` sans toucher l'auth des 21 autres briques.

---

### Task 1: Déploiement permanent de world-engine sur le HP + second tenant

**Files:**
- Modify: `.env` (racine, **fichier de secrets, non versionné** — ajout d'une ligne
  `WORLD_ENGINE_KEY=...`, aucune autre variable touchée)

**Interfaces:**
- Produces: une instance `world-engine` `healthy` joignable en HTTP sur
  `http://192.168.1.89:6220`, acceptant deux `cle_api` distinctes (la valeur de
  `API_KEYS` existante = tenant A, la nouvelle `WORLD_ENGINE_KEY` = tenant B) — Task 2
  les reçoit en paramètres `--cle-api-a`/`--cle-api-b`.

- [ ] **Step 1: Vérifier la connectivité SSH vers le HP**

Run: `ssh -o BatchMode=yes -o ConnectTimeout=8 debian@192.168.1.89 'echo OK'`
Expected: `OK`. Si la commande time out ou refuse la connexion, **STOP** — le Mac
n'est pas sur le même réseau/mesh que le HP (voir mémoire `netbird-mesh-topologie`) ;
informer l'utilisateur et attendre qu'il reconnecte avant de continuer. Ne pas
tenter de contourner (pas de mot de passe en dur, pas de désactivation de clé).

- [ ] **Step 2: Vérifier que `personnages` tourne déjà sur le HP (dépendance dure)**

Run: `ssh debian@192.168.1.89 'docker ps --format "{{.Names}}\t{{.Status}}" | grep -i personnages'`
Expected: une ligne `workplace_personnages   Up ... (healthy)`. Si absent :
`ssh debian@192.168.1.89 'cd /home/debian/workplace/briques/personnages && docker compose up -d --build'`
puis revérifier. `world-engine` ne peut peupler aucun monde sans cette brique.

- [ ] **Step 3: Mettre à jour le dépôt sur le HP**

Run: `ssh debian@192.168.1.89 'cd /home/debian/workplace && git fetch && git status --short --branch'`
Expected : `## main...origin/main` sans retard côté local pour les commits déjà sur
`origin/main` (Sprints A→D + la spec de ce plan). Si `behind` : `git pull --ff-only`.
Si des modifications locales non commitées existent, **STOP** et signaler à
l'utilisateur (ne jamais `git reset --hard`/`git stash` sans confirmation — voir
consignes de sécurité git).

- [ ] **Step 4: Générer et ajouter `WORLD_ENGINE_KEY` au `.env` racine du HP**

Run (sur le HP, en SSH) :
```bash
ssh debian@192.168.1.89 '
  cd /home/debian/workplace
  if grep -q "^WORLD_ENGINE_KEY=" .env; then
    echo "WORLD_ENGINE_KEY déjà présent — rien à faire" 
  else
    CLE=$(openssl rand -hex 32)
    echo "WORLD_ENGINE_KEY=${CLE}" >> .env
    echo "WORLD_ENGINE_KEY ajouté"
  fi
'
```
Expected : `WORLD_ENGINE_KEY ajouté` (ou le message « déjà présent » si ce step est
rejoué). **Ne jamais afficher la valeur de la clé dans les logs de session partagée**
— seule sa présence est confirmée, pas sa valeur. Cette clé sera relue directement
depuis le `.env` du HP au Step 6 (jamais recopiée à la main dans une commande).

- [ ] **Step 5: Builder et démarrer world-engine sur le HP**

Run:
```bash
ssh debian@192.168.1.89 'cd /home/debian/workplace/briques/world-engine && docker compose up -d --build'
```
Expected : `Container workplace_world_engine  Started` (ou `Running` si déjà up —
dans ce cas le `--build` reconstruit quand même l'image si le Dockerfile/code a
changé depuis Sprint D).

- [ ] **Step 6: Vérifier la santé et récupérer les deux clés pour Task 2**

Run:
```bash
ssh debian@192.168.1.89 'docker inspect --format "{{.State.Health.Status}}" workplace_world_engine'
curl -sf http://192.168.1.89:6220/sante
```
Expected : `healthy` puis `{"statut":"ok","brique":"world-engine"}`. Si `unhealthy`
après `start_period` (15s) : `ssh debian@192.168.1.89 'docker logs --tail 50 workplace_world_engine'`
et diagnostiquer avant de continuer (ne pas passer à Task 2 sur une instance non
saine).

Récupérer les deux clés pour Task 5 (jamais affichées en clair dans la session — les
lire directement depuis `.env` au moment de l'exécution du script, ex.
`WORLD_ENGINE_KEY=$(ssh debian@192.168.1.89 'grep ^WORLD_ENGINE_KEY= /home/debian/workplace/.env | cut -d= -f2')`
et la même chose pour `API_KEYS` — première valeur si la liste en contient
plusieurs).

- [ ] **Step 7: Commit (aucun changement de code — rien à committer ici)**

Ce task ne modifie que le `.env` non versionné du HP. Rien à committer dans le
dépôt git. Passer directement à Task 2.

---

### Task 2: Client HTTP du script + sous-commande `setup`

**Files:**
- Create: `scripts/mesure_charge_world_engine.py`

**Interfaces:**
- Produces: `appeler(base_url, methode, chemin, cle_api, corps=None) -> dict`,
  `ErreurAPI` (exception), et les sous-commandes CLI `setup` — Task 3/4 les
  réutilisent et ajoutent leurs propres sous-commandes au même `argparse.ArgumentParser`.
  Écrit `<sortie>/mondes.json` = `{"federation_id": str, "mondes": [{"id": str, "cle_api": str}, ...]}`
  — Task 3/4 le relisent tel quel.

- [ ] **Step 1: Créer le script avec le client HTTP et les sous-commandes `spatial`/`federation`/`genome`**

```python
#!/usr/bin/env python3
"""Scénario de charge LIVE pour world-engine (préalable Sprint E) — voir
docs/superpowers/specs/2026-08-25-world-engine-mesure-charge-design.md.
Appels HTTP purs contre l'API publique : aucun code de la brique n'est importé."""
from __future__ import annotations

import argparse
import concurrent.futures
import json
import random
import time
import urllib.error
import urllib.request
from pathlib import Path

TIMEOUT_S = 15


class ErreurAPI(Exception):
    """Réponse HTTP non-2xx de world-engine — message = corps de la réponse."""


def appeler(base_url: str, methode: str, chemin: str, cle_api: str,
            corps: dict | None = None) -> dict:
    """Appelle `methode chemin` sur world-engine avec le header X-API-Key. Lève
    ErreurAPI sur toute réponse non-2xx (le message inclut le corps renvoyé)."""
    data = json.dumps(corps).encode() if corps is not None else None
    req = urllib.request.Request(
        f"{base_url}{chemin}", data=data, method=methode,
        headers={"X-API-Key": cle_api, "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
            brut = resp.read()
            return json.loads(brut) if brut else {}
    except urllib.error.HTTPError as e:
        raise ErreurAPI(f"{methode} {chemin} -> {e.code} : "
                         f"{e.read().decode(errors='replace')}") from e


def creer_monde(base_url: str, cle_api: str, nb_cellules: int = 30) -> dict:
    return appeler(base_url, "POST", "/spatial/mondes", cle_api, {"nb_cellules": nb_cellules})


def creer_federation(base_url: str, cle_api: str, nom: str) -> dict:
    return appeler(base_url, "POST", "/federation", cle_api, {"nom": nom})


def rattacher_pays(base_url: str, cle_api: str, federation_id: str, monde_id: str) -> dict:
    return appeler(base_url, "POST", f"/federation/{federation_id}/rattacher", cle_api,
                    {"monde_id": monde_id})


def declarer_adjacence(base_url: str, cle_api: str, federation_id: str,
                        monde_id_a: str, monde_id_b: str) -> dict:
    return appeler(base_url, "POST", f"/federation/{federation_id}/adjacence", cle_api,
                    {"monde_id_a": monde_id_a, "monde_id_b": monde_id_b})


# Fiches parents FIXES et arbitraires, réutilisées pour chaque fondateur : seul
# l'enfant (le fondateur lui-même) doit varier pour ce scénario de charge, sa
# lignée n'a aucune importance narrative.
FICHE_PARENT_A = {"prenoms": "Fondateur", "nom": "A", "date_naissance": "1990-03-12",
                   "heure_naissance": "08:15", "latitude": 45.75, "longitude": 4.85,
                   "utc_offset": 1.0}
FICHE_PARENT_B = {"prenoms": "Fondateur", "nom": "B", "date_naissance": "1988-07-02",
                   "heure_naissance": "19:40", "latitude": 40.71, "longitude": -74.0,
                   "utc_offset": -5.0}


def creer_fondateur(base_url: str, cle_api: str, monde_id: str, sexe: str,
                     rng: random.Random) -> dict:
    corps = {
        "parent_a": FICHE_PARENT_A, "parent_b": FICHE_PARENT_B,
        "prenoms_enfant": "Fondateur", "nom_enfant": "",
        "latitude_enfant": rng.uniform(-60.0, 60.0),
        "longitude_enfant": rng.uniform(-170.0, 170.0),
        "heure_naissance_enfant": f"{rng.randrange(24):02d}:{rng.randrange(60):02d}",
        "utc_offset_enfant": float(rng.randrange(-11, 12)),
        "annee_enfant": 1990,
        "sexe_enfant": sexe,
        "monde_id": monde_id,
    }
    return appeler(base_url, "POST", "/genome/croiser", cle_api, corps)


def commande_setup(args: argparse.Namespace) -> None:
    rng = random.Random(args.graine)
    cles = [args.cle_api_a, args.cle_api_b]
    mondes = []
    for i in range(5):
        cle = cles[0] if i < 3 else cles[1]
        monde = creer_monde(args.base_url, cle, nb_cellules=30)
        mondes.append({"id": monde["id"], "cle_api": cle})
        print(f"monde {i + 1}/5 créé : {monde['id']} "
              f"(tenant {'A' if cle == cles[0] else 'B'})")

    federation = creer_federation(args.base_url, cles[0], "mesure-charge-sprint-e")
    for m in mondes:
        rattacher_pays(args.base_url, m["cle_api"], federation["id"], m["id"])
    for i in range(len(mondes)):
        j = (i + 1) % len(mondes)
        declarer_adjacence(args.base_url, mondes[i]["cle_api"], federation["id"],
                            mondes[i]["id"], mondes[j]["id"])
    print(f"fédération {federation['id']} : 5 pays en anneau (adjacence circulaire, "
          f"2 tenants mêlés)")

    taches = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.concurrence) as pool:
        for m in mondes:
            for n in range(args.fondateurs_par_monde):
                sexe = "F" if n % 2 == 0 else "M"
                rng_tache = random.Random(rng.random())
                fut = pool.submit(creer_fondateur, args.base_url, m["cle_api"],
                                   m["id"], sexe, rng_tache)
                taches[fut] = m["id"]
        ok = ko = 0
        for fut in concurrent.futures.as_completed(taches):
            try:
                fut.result()
                ok += 1
            except ErreurAPI as e:
                ko += 1
                print(f"  fondateur échoué ({taches[fut]}) : {e}")
    print(f"peuplement : {ok} fondateurs créés, {ko} échecs "
          f"({len(mondes)} mondes × {args.fondateurs_par_monde})")

    Path(args.sortie).mkdir(parents=True, exist_ok=True)
    (Path(args.sortie) / "mondes.json").write_text(json.dumps(
        {"federation_id": federation["id"], "mondes": mondes}, indent=2))
    print(f"état écrit dans {args.sortie}/mondes.json")


def construire_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--base-url", default="http://192.168.1.89:6220")
    p.add_argument("--sortie", default="/tmp/world-engine-charge")
    sous = p.add_subparsers(dest="commande", required=True)

    s = sous.add_parser("setup", help="crée 5 mondes fédérés + peuple de fondateurs")
    s.add_argument("--cle-api-a", required=True)
    s.add_argument("--cle-api-b", required=True)
    s.add_argument("--fondateurs-par-monde", type=int, default=40)
    s.add_argument("--concurrence", type=int, default=5)
    s.add_argument("--graine", type=int, default=42)
    s.set_defaults(func=commande_setup)

    return p


def main() -> None:
    args = construire_parser().parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Vérifier que le script s'importe sans erreur (pas de dépendance manquante)**

Run: `python3 -c "import sys; sys.path.insert(0, 'scripts'); import mesure_charge_world_engine"`
Expected : aucune sortie, code de retour 0 (stdlib uniquement, doit toujours réussir).

- [ ] **Step 3: Vérifier l'aide CLI**

Run: `python3 scripts/mesure_charge_world_engine.py --help`
Expected : affiche l'usage avec la sous-commande `setup` listée.

- [ ] **Step 4: Commit**

```bash
git add scripts/mesure_charge_world_engine.py
git commit -m "feat(scripts): mesure de charge world-engine — client HTTP + setup"
```

---

### Task 3: Fonction pure de latence/dérive (TDD) + sous-commandes `demarrer-scheduler`/`observer`

**Files:**
- Create: `scripts/test_mesure_charge_world_engine.py`
- Modify: `scripts/mesure_charge_world_engine.py`

**Interfaces:**
- Consumes: `appeler` de Task 2 (import direct, même module).
- Produces: `calculer_latences_tick(observations: list[tuple[float, int]]) -> dict`
  (fonction pure, réutilisée par le rapport en Task 5) ; sous-commandes
  `demarrer-scheduler` et `observer`, cette dernière écrivant
  `<sortie>/observations.jsonl` (une ligne JSON par lecture :
  `{"ts": float, "monde_id": str, "tick_actuel": int|None, "actif": bool|None, "erreur": str|None}`)
  — Task 5 le relit pour le rapport.

- [ ] **Step 1: Écrire le test qui échoue**

```python
# scripts/test_mesure_charge_world_engine.py
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from mesure_charge_world_engine import calculer_latences_tick


def test_calculer_latences_tick_ignore_les_lectures_sans_increment():
    # 3 lectures au même tick (polling plus rapide que le tick) puis un
    # incrément : un seul écart doit être compté, pas deux.
    observations = [(100.0, 5), (101.0, 5), (102.0, 5), (105.0, 6)]
    resultat = calculer_latences_tick(observations)
    assert resultat["nb_ticks_observes"] == 1
    assert resultat["ecart_p50_s"] == 3.0  # 105 - 102


def test_calculer_latences_tick_calcule_percentiles_sur_plusieurs_increments():
    observations = [(0.0, 1), (5.0, 2), (11.0, 3), (14.0, 4)]
    resultat = calculer_latences_tick(observations)
    assert resultat["nb_ticks_observes"] == 3
    assert resultat["ecart_min_s"] == 3.0
    assert resultat["ecart_max_s"] == 6.0


def test_calculer_latences_tick_vide_si_moins_de_deux_increments():
    assert calculer_latences_tick([(0.0, 1), (2.0, 1)]) == {}
    assert calculer_latences_tick([]) == {}
```

- [ ] **Step 2: Lancer les tests, vérifier qu'ils échouent (fonction absente)**

Run: `python3 -m pytest scripts/test_mesure_charge_world_engine.py -v`
Expected: FAIL — `ImportError: cannot import name 'calculer_latences_tick'`

- [ ] **Step 3: Implémenter `calculer_latences_tick` dans le script**

Ajouter dans `scripts/mesure_charge_world_engine.py`, juste après `creer_fondateur` :

```python
def calculer_latences_tick(observations: list[tuple[float, int]]) -> dict:
    """`observations` = [(timestamp_epoch, tick_actuel), ...] pour UN monde, dans
    n'importe quel ordre. Ne retient que les instants où `tick_actuel` a
    RÉELLEMENT augmenté (déduplique le polling qui observe plusieurs fois le même
    tick) et calcule l'écart de temps entre deux incréments consécutifs. Renvoie
    {} si moins de 2 incréments observés (rien à mesurer)."""
    vus = sorted(observations, key=lambda o: o[0])
    increments = []
    dernier_tick = None
    for ts, tick in vus:
        if dernier_tick is None or tick > dernier_tick:
            increments.append((ts, tick))
            dernier_tick = tick
    if len(increments) < 2:
        return {}
    ecarts = sorted(increments[i][0] - increments[i - 1][0] for i in range(1, len(increments)))
    return {
        "nb_ticks_observes": len(increments) - 1,
        "ecart_min_s": ecarts[0],
        "ecart_p50_s": ecarts[len(ecarts) // 2],
        "ecart_p95_s": ecarts[min(len(ecarts) - 1, int(len(ecarts) * 0.95))],
        "ecart_max_s": ecarts[-1],
    }
```

- [ ] **Step 4: Relancer les tests, vérifier qu'ils passent**

Run: `python3 -m pytest scripts/test_mesure_charge_world_engine.py -v`
Expected: `3 passed`

- [ ] **Step 5: Ajouter les fonctions HTTP et les sous-commandes `demarrer-scheduler`/`observer`**

Ajouter dans `scripts/mesure_charge_world_engine.py`, après `calculer_latences_tick` :

```python
def demarrer_horloge(base_url: str, cle_api: str, monde_id: str, intervalle_s: int) -> dict:
    return appeler(base_url, "POST", f"/horloge/{monde_id}/demarrer", cle_api,
                    {"intervalle_secondes": intervalle_s})


def arreter_horloge(base_url: str, cle_api: str, monde_id: str) -> dict:
    return appeler(base_url, "POST", f"/horloge/{monde_id}/arreter", cle_api)


def lire_horloge(base_url: str, cle_api: str, monde_id: str) -> dict:
    return appeler(base_url, "GET", f"/horloge/{monde_id}", cle_api)


def _charger_mondes(sortie: str) -> dict:
    return json.loads((Path(sortie) / "mondes.json").read_text())


def commande_demarrer_scheduler(args: argparse.Namespace) -> None:
    etat = _charger_mondes(args.sortie)
    for m in etat["mondes"]:
        demarrer_horloge(args.base_url, m["cle_api"], m["id"], args.intervalle_secondes)
        print(f"scheduler démarré pour {m['id']} (intervalle {args.intervalle_secondes}s)")


def commande_observer(args: argparse.Namespace) -> None:
    etat = _charger_mondes(args.sortie)
    mondes = etat["mondes"]
    fin = time.monotonic() + args.duree_minutes * 60
    chemin_obs = Path(args.sortie) / "observations.jsonl"
    with chemin_obs.open("a") as f:
        while time.monotonic() < fin:
            for m in mondes:
                try:
                    horloge = lire_horloge(args.base_url, m["cle_api"], m["id"])
                    ligne = {"ts": time.time(), "monde_id": m["id"],
                             "tick_actuel": horloge.get("tick_actuel"),
                             "actif": horloge.get("actif"), "erreur": None}
                except ErreurAPI as e:
                    ligne = {"ts": time.time(), "monde_id": m["id"],
                             "tick_actuel": None, "actif": None, "erreur": str(e)}
                f.write(json.dumps(ligne) + "\n")
            f.flush()
            time.sleep(args.intervalle_poll)
    print(f"observation terminée, écrit dans {chemin_obs}")
```

- [ ] **Step 6: Enregistrer les deux sous-commandes dans `construire_parser`**

Dans `construire_parser`, juste avant `return p`, ajouter :

```python
    s = sous.add_parser("demarrer-scheduler", help="active le scheduler auto sur les 5 mondes")
    s.add_argument("--intervalle-secondes", type=int, default=5)
    s.set_defaults(func=commande_demarrer_scheduler)

    s = sous.add_parser("observer", help="échantillonne tick_actuel de chaque monde")
    s.add_argument("--duree-minutes", type=float, default=12.0)
    s.add_argument("--intervalle-poll", type=float, default=2.0)
    s.set_defaults(func=commande_observer)
```

- [ ] **Step 7: Vérifier l'aide CLI mise à jour**

Run: `python3 scripts/mesure_charge_world_engine.py --help`
Expected : `demarrer-scheduler` et `observer` apparaissent dans la liste des
sous-commandes, en plus de `setup`.

- [ ] **Step 8: Commit**

```bash
git add scripts/mesure_charge_world_engine.py scripts/test_mesure_charge_world_engine.py
git commit -m "feat(scripts): mesure de charge world-engine — latence de tick (TDD) + scheduler/observer"
```

---

### Task 4: Sous-commandes `arreter-scheduler` et `rafale-manuelle` (avertissements de verrou)

**Files:**
- Modify: `scripts/mesure_charge_world_engine.py`

**Interfaces:**
- Consumes: `arreter_horloge`, `appeler`, `_charger_mondes` (Task 3).
- Produces: `<sortie>/avertissements.jsonl` (une ligne JSON par tick manuel :
  `{"round": int, "monde_id": str, "duree_s": float|None, "tick_actuel": int|None, "avertissements": list[str], "erreur": str|None}`)
  — Task 5 le relit pour le rapport.

- [ ] **Step 1: Ajouter `tick_manuel` et la sous-commande `rafale-manuelle`**

Ajouter dans `scripts/mesure_charge_world_engine.py`, après `commande_observer` :

```python
def tick_manuel(base_url: str, cle_api: str, monde_id: str) -> dict:
    return appeler(base_url, "POST", f"/horloge/{monde_id}/tick", cle_api)


def commande_arreter_scheduler(args: argparse.Namespace) -> None:
    etat = _charger_mondes(args.sortie)
    for m in etat["mondes"]:
        arreter_horloge(args.base_url, m["cle_api"], m["id"])
        print(f"scheduler arrêté pour {m['id']}")


def commande_rafale_manuelle(args: argparse.Namespace) -> None:
    """Déclenche des ticks manuels CONCURRENTS sur les 5 mondes, round par round —
    seul chemin qui expose `avertissements` (le scheduler les jette, voir
    Contexte technique du plan). Sollicite volontairement les verrous destination
    (Sprint D) en faisant tiquer plusieurs pays adjacents en même temps."""
    etat = _charger_mondes(args.sortie)
    mondes = etat["mondes"]
    chemin_avert = Path(args.sortie) / "avertissements.jsonl"
    with chemin_avert.open("a") as f:
        for round_ in range(args.nb_rounds):
            debuts = {m["id"]: time.time() for m in mondes}
            with concurrent.futures.ThreadPoolExecutor(max_workers=len(mondes)) as pool:
                futurs = {pool.submit(tick_manuel, args.base_url, m["cle_api"], m["id"]): m
                          for m in mondes}
                for fut, m in futurs.items():
                    try:
                        resultat = fut.result()
                        ligne = {"round": round_, "monde_id": m["id"],
                                  "duree_s": time.time() - debuts[m["id"]],
                                  "tick_actuel": resultat.get("tick_actuel"),
                                  "avertissements": resultat.get("avertissements", []),
                                  "erreur": None}
                    except ErreurAPI as e:
                        ligne = {"round": round_, "monde_id": m["id"], "duree_s": None,
                                  "tick_actuel": None, "avertissements": [], "erreur": str(e)}
                    f.write(json.dumps(ligne) + "\n")
            f.flush()
    print(f"{args.nb_rounds} rounds de tick manuel concurrent écrits dans {chemin_avert}")
```

- [ ] **Step 2: Enregistrer les deux sous-commandes dans `construire_parser`**

Dans `construire_parser`, juste avant `return p` (après les ajouts de Task 3) :

```python
    s = sous.add_parser("arreter-scheduler", help="désactive le scheduler auto sur les 5 mondes")
    s.set_defaults(func=commande_arreter_scheduler)

    s = sous.add_parser("rafale-manuelle", help="ticks manuels concurrents, capture les avertissements")
    s.add_argument("--nb-rounds", type=int, default=20)
    s.set_defaults(func=commande_rafale_manuelle)
```

- [ ] **Step 3: Vérifier l'aide CLI complète**

Run: `python3 scripts/mesure_charge_world_engine.py --help`
Expected : les 5 sous-commandes (`setup`, `demarrer-scheduler`, `observer`,
`arreter-scheduler`, `rafale-manuelle`) apparaissent.

- [ ] **Step 4: Relancer toute la suite de tests pure (aucune régression)**

Run: `python3 -m pytest scripts/test_mesure_charge_world_engine.py -v`
Expected: `3 passed` (inchangé — ce task n'a touché aucune fonction pure testée).

- [ ] **Step 5: Commit**

```bash
git add scripts/mesure_charge_world_engine.py
git commit -m "feat(scripts): mesure de charge world-engine — rafale manuelle (avertissements de verrou)"
```

---

### Task 5: Exécution réelle sur le HP + rapport chiffré + mémoire

**Files:**
- Create: `docs/superpowers/reports/2026-08-25-world-engine-mesure-charge-rapport.md`
- Create (mémoire, hors dépôt git) : entrée `sprint-world-engine-mesure-charge` +
  mise à jour de `backlog-world-engine-genome-cosmique-phases-suivantes` dans
  `/Users/garinat_t/.claude/projects/-Users-garinat-t-Desktop-Workplace/memory/`

**Interfaces:**
- Consumes: toutes les sous-commandes de Tasks 2-4, l'instance HP déployée en Task 1.

- [ ] **Step 1: Récupérer les deux clés sans les afficher en clair, lancer `setup`**

```bash
CLE_A=$(ssh debian@192.168.1.89 'grep ^API_KEYS= /home/debian/workplace/.env | cut -d= -f2 | cut -d, -f1')
CLE_B=$(ssh debian@192.168.1.89 'grep ^WORLD_ENGINE_KEY= /home/debian/workplace/.env | cut -d= -f2')
python3 scripts/mesure_charge_world_engine.py setup \
  --cle-api-a "$CLE_A" --cle-api-b "$CLE_B" \
  --fondateurs-par-monde 40 --concurrence 5
```
Expected : 5 mondes créés, 1 fédération à 5 pays en anneau, `peuplement : ~200
fondateurs créés, 0 échecs` (quelques échecs isolés sont tolérables — les
consigner dans le rapport s'il y en a plus de quelques-uns). Durée attendue :
quelques minutes (chaque fondateur déclenche ~4 appels internes vers
`personnages`).

- [ ] **Step 2: Démarrer le scheduler et observer pendant ~12 minutes**

```bash
python3 scripts/mesure_charge_world_engine.py demarrer-scheduler --intervalle-secondes 5
python3 scripts/mesure_charge_world_engine.py observer --duree-minutes 12 --intervalle-poll 2 &
OBSERVER_PID=$!
```

- [ ] **Step 3: Échantillonner `docker stats` et les logs sur le HP EN PARALLÈLE de l'observation**

Dans une session shell séparée, pendant que `observer` tourne (Step 2) :
```bash
ssh debian@192.168.1.89 '
  for i in $(seq 1 24); do
    date -u +%FT%TZ
    docker stats --no-stream --format "{{.CPUPerc}}\t{{.MemUsage}}" workplace_world_engine
    sleep 30
  done
' > /tmp/world-engine-charge/docker_stats.log
ssh debian@192.168.1.89 'docker logs --since 15m workplace_world_engine 2>&1 | grep -i "locked\|traceback\|error"' \
  > /tmp/world-engine-charge/logs_contention.log
wait $OBSERVER_PID
```
Expected : `docker_stats.log` avec ~24 échantillons (12 min / 30s) ;
`logs_contention.log` peut être vide (bon signe : aucune contention/erreur
visible) ou contenir des lignes à citer dans le rapport.

- [ ] **Step 4: Arrêter le scheduler, lancer la rafale de ticks manuels**

```bash
python3 scripts/mesure_charge_world_engine.py arreter-scheduler
python3 scripts/mesure_charge_world_engine.py rafale-manuelle --nb-rounds 20
```
Expected : `20 rounds de tick manuel concurrent écrits dans .../avertissements.jsonl`.

- [ ] **Step 5: Calculer les latences et lire les avertissements collectés**

```bash
python3 -c "
import json, collections
from pathlib import Path
import sys
sys.path.insert(0, 'scripts')
from mesure_charge_world_engine import calculer_latences_tick

par_monde = collections.defaultdict(list)
for ligne in Path('/tmp/world-engine-charge/observations.jsonl').read_text().splitlines():
    d = json.loads(ligne)
    if d['tick_actuel'] is not None:
        par_monde[d['monde_id']].append((d['ts'], d['tick_actuel']))
for monde_id, obs in par_monde.items():
    print(monde_id, calculer_latences_tick(obs))

avertissements = [json.loads(l) for l in Path('/tmp/world-engine-charge/avertissements.jsonl').read_text().splitlines()]
nb_avert = sum(len(a['avertissements']) for a in avertissements)
nb_erreurs = sum(1 for a in avertissements if a['erreur'])
print(f'rafale manuelle : {nb_avert} avertissements, {nb_erreurs} erreurs de transport sur {len(avertissements)} ticks')
for a in avertissements:
    if a['avertissements']:
        print(' ', a['monde_id'], a['round'], a['avertissements'])
"
```
Expected : une ligne de latence par monde (`ecart_p50_s`/`ecart_p95_s` proches de
5s si le scheduler tient sa cadence, nettement au-delà sinon) et le décompte des
avertissements de la rafale manuelle. Noter ces chiffres bruts pour le Step 6 —
ne rien arrondir/interpréter à ce stade.

- [ ] **Step 6: Rédiger le rapport Markdown**

Créer `docs/superpowers/reports/2026-08-25-world-engine-mesure-charge-rapport.md`
avec les sections : Contexte (1 phrase, lien vers la spec) ; Scénario exécuté
(chiffres réels : nb mondes/fondateurs/tenants, durée) ; Résultat 1 — latence/dérive
de tick par monde (tableau des `ecart_p50_s`/`ecart_p95_s`/`ecart_max_s`) ; Résultat
2 — avertissements de verrou (décompte + exemples cités, ou constat d'absence) ;
Résultat 3 — contention SQLite (contenu de `logs_contention.log`, ou constat
d'absence) ; Résultat 4 — CPU/mémoire (plage observée dans `docker_stats.log`) ;
Limite d'observabilité découverte (le scheduler jette les avertissements, voir
Contexte technique du plan) ; **pas de section « recommandation Sprint E »** — ce
rapport nourrit un brainstorming séparé, il ne le préempte pas.

- [ ] **Step 7: Committer le rapport**

```bash
git add docs/superpowers/reports/2026-08-25-world-engine-mesure-charge-rapport.md
git commit -m "docs(world-engine): rapport de mesure de charge LIVE (préalable Sprint E)"
```

- [ ] **Step 8: Mettre à jour la mémoire projet**

Créer la mémoire `sprint-world-engine-mesure-charge` (type `project`) résumant ce
qui a été mesuré et le lien vers le rapport committé, et mettre à jour
`backlog-world-engine-genome-cosmique-phases-suivantes` (section « Comment
reprendre ») pour pointer vers cette nouvelle mémoire au lieu de renvoyer
directement à un Sprint E pas encore brainstormé.

---

## Self-Review

**Couverture spec** : Objectif 1 (latence tick) → Task 3+5 Step 5. Objectif 2
(contention SQLite) → Task 5 Step 3. Objectif 3 (comportement scheduler,
dérive/ticks manqués) → Task 3 (`observer`) + Task 5 Step 2/5. Objectif 4
(CPU/mémoire) → Task 5 Step 3. Déploiement permanent → Task 1. ≥2 `cle_api` → Task 1
Step 4 + Task 2 `setup`. Peuplement via l'API existante (pas d'insertion DB directe)
→ Task 2 `creer_fondateur`. Rapport Markdown + mémoire → Task 5 Step 6-8. Hors
périmètre respecté : aucune ligne de `briques/world-engine/*.py` modifiée dans
aucun task ; aucun test pytest de CI ajouté pour le scénario lui-même (seule
`calculer_latences_tick`, une fonction pure, est testée).

**Placeholders** : aucun — chaque step contient soit du code complet, soit une
commande exacte avec sortie attendue.

**Cohérence des types** : `mondes.json` = `{"federation_id": str, "mondes": [{"id", "cle_api"}]}`
produit par Task 2, consommé identiquement par `_charger_mondes` en Task 3/4.
`calculer_latences_tick(list[tuple[float, int]]) -> dict` : signature identique
entre le test (Task 3 Step 1) et l'implémentation (Task 3 Step 3), et entre
l'implémentation et son usage en Task 5 Step 5.
