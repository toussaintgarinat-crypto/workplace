# S248 partie 3b — Remise à zéro et restitution par utilisateur, preuve liée à la cible — Plan d'implémentation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal :** Qu'une remise à zéro des données d'UN utilisateur d'une app à contrat (Studio) ne puisse être approuvée sur Telegram qu'après un verdict VALIDE sur CE couple (app, utilisateur), puis puisse être restituée par l'assistant — avec preuve LIVE.

**Architecture :** Le Cœur gagne une clé de preuve composite `app|sha256(utilisateur)[:16]` pour les preuves « par cible » (seul `paquet_verifie` en fait partie ; `preuve_sauvegarde` est inchangée). `livraison` ajoute deux routes `reinitialiser` / `restituer` qui enchaînent : paquet vérifié valide et frais → relecture/déchiffrement du stockage → ré-export, empreinte identique (les données n'ont pas bougé depuis la vérification) → reset de l'app → ré-export et comptages tous à zéro (parade au reset « ressuscité » par un handler async du Studio). Prérequis de partie 3a : stockage, chiffrement, registre des paquets, outils `livraison_donnees_exporter` / `_verifier`.

**Tech Stack :** Python 3.12, FastAPI/httpx (livraison), SQLite (approbations du Cœur), pytest.

## Global Constraints

- Une preuve `paquet_verifie` pour (app A, utilisateur U) ne satisfait JAMAIS un prérequis pour (A, U') ni pour A seule ; elle n'est jamais issue des arguments seuls : elle vient du RÉSULTAT de la brique (`ok`, `verdict`, `preuve_id`, `expire_a`), seule la CLÉ est calculée depuis les arguments, comme pour `preuve_sauvegarde`.
- `preuve_sauvegarde` (S247) garde sa clé = nom d'app : aucune régression (tests S247 inchangés).
- Fail closed : argument `app` ou `utilisateur` absent/vide pour une preuve par cible → aucune clé → aucune preuve possible.
- Fraîcheur : la preuve vit au plus `PREUVE_TTL_S = 6 h` (`paquets.py`) ; le Cœur la plafonne déjà à 24 h. La restitution, elle, reste possible pendant toute la rétention (14 jours) : le paquet est la seule copie de l'utilisateur.
- Reset : refusé (409) si (a) aucun paquet vérifié frais pour la cible, (b) le paquet stocké est illisible, (c) les données courantes n'ont plus l'empreinte du paquet vérifié, (d) une autre opération est en cours sur la même cible ; après le reset, si un comptage n'est pas à zéro → 409 « incomplet » (jamais un succès).
- L'identité de l'utilisateur ciblé apparaît dans le résumé de la demande d'approbation Telegram (l'approbateur doit savoir qui est visé) ; elle n'apparaît ni dans les logs de livraison, ni dans le registre (hachée), ni dans les réponses des routes.
- Niveau d'approbation : `donnees` pour reset ET restitution (TTL 120 min existant). Aucun appel au LLM pour manipuler le paquet.
- Tests purs, aucun réseau (sauf la tâche LIVE). Commits en français, un par tâche, terminés par les lignes d'attribution du système.

## Structure des fichiers

| Fichier | Rôle |
|---|---|
| `core/approbations.py` (modifier) | `PREUVES_PAR_CIBLE`, `cle_preuve(nom, args)` ; 4 sites passent par elle |
| `core/outils.py` (modifier) | `_enregistrer_preuve_eventuelle` : clé composite pour les preuves par cible |
| `core/test_approbations_cible.py` (créer) | Isolation par cible, non-régression, mutation |
| `core/test_approbations_cible_garde.py` (créer) | Câblage outils : verdict → preuve → reset libéré, autre utilisateur refusé |
| `briques/livraison/paquets.py` (modifier) | `dernier_verifie`, `marquer_consomme` |
| `briques/livraison/donnees_utilisateur.py` (modifier) | `reinitialiser_donnees`, `restituer_donnees`, verrou par cible |
| `briques/livraison/main.py` (modifier) | Routes `/contrats/{app}/reinitialiser` et `/restituer` ; `preuve_id` dans le verdict |
| `briques/livraison/manifest.json` (modifier) | 2 nouveaux outils ; `fournit_preuve` sur le vérificateur |
| `briques/livraison/test_donnees_reset.py` (créer) | Orchestration reset/restitution, résurrection, concurrence |
| `docs/s248/preuve-donnees-utilisateur.md` (créer) | Preuve LIVE |

---

### Task 0 : L'identité hors de l'URL (prérequis levé par la revue finale de 3a)

**Pourquoi :** `/support/verifier` et `/support/importer` reçoivent `?utilisateur=` : l'identité visée apparaît dans les journaux d'accès d'uvicorn (Studio), ce qui contredit « jamais en clair ». Les routes `exporter`/`reinitialiser` la reçoivent déjà dans un corps JSON. On la passe en en-tête `X-Utilisateur` pour `verifier` et `importer`, et on ne l'accepte PLUS en query.

**Files :**
- Modify : `briques/studio/main.py` (routes `support_verifier`, `support_importer`, `_cible`)
- Modify : `briques/livraison/contrats.py` (`AppContrat.verifier`, `AppContrat.importer`)
- Modify (tests) : `briques/studio/test_support_routes.py` (toutes les occurrences de `?utilisateur=` / `params={"utilisateur"…}`, y compris l'adaptateur `AdaptateurStudio` du harnais), `briques/livraison/test_contrats.py` (`test_verifier_envoie_les_octets_et_l_utilisateur_en_query` → en-tête)
- Modify (docs) : `docs/GUIDE-contrat-donnees.md` (tableau §3 : `verifier`/`importer` prennent l'en-tête `X-Utilisateur` ; retirer la limite « identité dans la query string »)

**Interfaces :**
- Produces : en-tête `X-Utilisateur` (texte ASCII, mêmes règles que `_cible`) obligatoire sur `POST /support/verifier` et `POST /support/importer` ; `?utilisateur=` n'est plus lu (une requête sans l'en-tête → 422 `utilisateur manquant`, même avec la query).

- [ ] **Step 1 : Tests qui échouent** — dans `test_support_routes.py`, ajouter :

```python
def test_verifier_et_importer_exigent_l_entete_et_ignorent_la_query():
    for route in ("verifier", "importer"):
        r = client.post(f"/support/{route}?utilisateur=claire", content=b"x", headers=H)
        assert r.status_code == 422, route                       # la query ne suffit plus
        r = client.post(f"/support/{route}", content=b"x", headers={**H, "X-Utilisateur": "  "})
        assert r.status_code == 422, route


def test_importer_lit_l_utilisateur_dans_l_entete():
    peupler("claire")
    paquet = client.post("/support/exporter", json={"utilisateur": "claire"}, headers=H).content
    r = client.post("/support/verifier", content=paquet, headers={**H, "X-Utilisateur": "claire"})
    assert r.status_code == 200 and r.json()["ok"] is True
```
et mettre à jour dans `test_contrats.py` le test d'envoi pour qu'il asserte `req.headers["x-utilisateur"] == "claire"` et `"utilisateur" not in req.url.params` (et l'absence de `utilisateur` dans `str(req.url)`).

- [ ] **Step 2 :** `cd briques/studio && /usr/local/bin/python3.11 -m pytest test_support_routes.py -q -p no:cacheprovider` et `cd ../livraison && … test_contrats.py` → FAIL.

- [ ] **Step 3 : Implémenter** — `briques/studio/main.py`, après `_cible` :

```python
def _cible_entete(x_utilisateur: Optional[str] = Header(None)) -> str:
    """Identité visée par `verifier`/`importer` : EN-TÊTE, jamais la query (les journaux d'accès
    d'uvicorn écrivent l'URL). Mêmes contrôles que `_cible`."""
    return _cible(x_utilisateur or "")
```
et remplacer, dans `support_verifier` et `support_importer`, le paramètre `utilisateur: str` par `u: str = Depends(_cible_entete)` (supprimer la ligne `u = _cible(utilisateur)`). `briques/livraison/contrats.py` : dans `verifier` et `importer`, remplacer `params={"utilisateur": utilisateur}` par `headers={"X-Utilisateur": utilisateur}` et faire fusionner `_appel` les en-têtes : `headers={"X-Support-Key": self._cle, **kw.pop("headers", {})}`.
Mettre à jour tous les autres appels de test (grep `utilisateur=` dans `briques/studio/test_*.py` et `shared/`) vers l'en-tête.

- [ ] **Step 4 :** `cd briques/studio && … pytest -q -p no:cacheprovider` ; `cd ../livraison && … pytest -q -p no:cacheprovider` ; `cd ../.. && /usr/local/bin/python3.11 -m pytest shared -q -p no:cacheprovider` → PASS.

- [ ] **Step 5 : Commit** `git commit -am "fix(s248): l'identité visée passe en en-tête X-Utilisateur (plus dans l'URL des journaux d'accès)"`

---

### Task 1 : Cœur — clé de preuve composite par cible

**Files :**
- Modify : `core/approbations.py` (lignes ~247, 503, 546, 583 : tous les `.get("app")` passés à `_preuve_valide_c` / `_cle_canonique`)
- Create : `core/test_approbations_cible.py`

**Interfaces :**
- Produces : `PREUVES_PAR_CIBLE: frozenset[str] = frozenset({"paquet_verifie"})` ; `cle_preuve(nom: str, args: dict | None) -> str | None` : pour un nom hors `PREUVES_PAR_CIBLE`, renvoie `args["app"]` tel quel (comportement S247) ; pour un nom par cible, renvoie `f"{_norm_cle(app)}|{sha256(utilisateur)[:16]}"`, ou `None` si `app` ou `utilisateur` n'est pas un texte non vide.

- [ ] **Step 1 : Tests qui échouent** — `core/test_approbations_cible.py` :

```python
"""Preuve « par cible » (S248 3b) : liée à l'utilisateur de l'approbation, à l'app ET à l'utilisateur visé."""
import os
import sys
import tempfile

os.environ["ASSISTANT_CONFIG_PATH"] = os.path.join(tempfile.mkdtemp(), "cfg.json")
os.environ.setdefault("GATEWAY_KEY", "sk-test-local")
sys.path.insert(0, os.path.dirname(__file__))

import pytest  # noqa: E402

import approbations  # noqa: E402

T0 = 1_000_000.0
PV = "paquet_verifie"


@pytest.fixture(autouse=True)
def _db(tmp_path, monkeypatch):
    monkeypatch.setattr(approbations, "DB", str(tmp_path / "a.db"))
    approbations.init_db()


def _demande(cible, app="studio", user="perso"):
    return approbations.creer("livraison_donnees_reinitialiser", {"app": app, "utilisateur": cible},
                              "Remise à zéro", "donnees", prerequis=(PV,), maintenant=T0,
                              utilisateur=user)


def _preuve(cible, app="studio", user="perso", pid="P1", expire=T0 + 3600):
    args = {"app": app, "utilisateur": cible}
    k = approbations.cle_preuve(PV, args)
    return approbations.enregistrer_preuve(PV, [k], pid, expire, utilisateur=user,
                                           maintenant=T0, app_id=k)


def test_cle_par_cible_ne_contient_pas_l_identite_en_clair():
    k = approbations.cle_preuve(PV, {"app": "Studio", "utilisateur": "claire"})
    assert k.startswith("studio|") and "claire" not in k and len(k) == len("studio|") + 16


def test_cle_inchangee_pour_les_preuves_par_app():
    assert approbations.cle_preuve("preuve_sauvegarde", {"app": "Calendrier", "utilisateur": "x"}) == "Calendrier"


@pytest.mark.parametrize("args", [None, {}, {"app": "studio"}, {"utilisateur": "c"},
                                  {"app": "", "utilisateur": "c"}, {"app": "studio", "utilisateur": "  "},
                                  {"app": "studio", "utilisateur": 5}, {"app": 3, "utilisateur": "c"}])
def test_args_incomplets_donnent_aucune_cle(args):
    assert approbations.cle_preuve(PV, args) is None


def test_sans_preuve_non_satisfait():
    assert _demande("claire")["prerequis"] == {PV: False}


def test_preuve_de_claire_satisfait_claire():
    _preuve("claire")
    assert _demande("claire")["prerequis"] == {PV: True}


def test_preuve_de_claire_ne_satisfait_pas_paul():
    _preuve("claire")
    assert _demande("paul")["prerequis"] == {PV: False}


def test_preuve_de_claire_ne_satisfait_pas_une_autre_app():
    _preuve("claire")
    assert _demande("claire", app="calendrier")["prerequis"] == {PV: False}


def test_preuve_par_app_ne_vaut_pas_preuve_par_cible():
    approbations.enregistrer_preuve(PV, ["studio"], "P0", T0 + 3600, utilisateur="perso", maintenant=T0)
    assert _demande("claire")["prerequis"] == {PV: False}


def test_preuve_enregistree_apres_la_demande_libere_seulement_la_bonne_cible():
    d_claire, d_paul = _demande("claire"), _demande("paul")
    liberees = _preuve("claire")
    assert liberees == [d_claire["id"]]
    assert approbations.lire(d_paul["id"])["prerequis"] == {PV: False}


def test_revocation_ne_touche_que_la_cible():
    _preuve("claire")
    _preuve("paul", pid="P2")
    d_c, d_p = _demande("claire"), _demande("paul")
    k = approbations.cle_preuve(PV, {"app": "studio", "utilisateur": "claire"})
    assert approbations.revoquer_preuve(PV, [k], utilisateur="perso", app_id=k) == [d_c["id"]]
    assert approbations.lire(d_p["id"])["prerequis"] == {PV: True}


def test_preuve_d_un_autre_utilisateur_d_approbation_ne_compte_pas():
    _preuve("claire", user="autre-admin")
    assert _demande("claire", user="perso")["prerequis"] == {PV: False}


def test_preuve_expiree_perdue_a_l_usage():
    _preuve("claire", expire=T0 + 50)
    d = _demande("claire")
    assert approbations.consommer_id(d["id"], "livraison_donnees_reinitialiser",
                                     {"app": "studio", "utilisateur": "claire"}, "donnees", "perso",
                                     maintenant=T0 + 100) is False


def test_approbation_pour_claire_ne_s_applique_pas_a_paul():
    """L'empreinte de l'approbation couvre les arguments : approuver claire n'autorise pas paul."""
    _preuve("claire")
    _preuve("paul", pid="P2")
    d = _demande("claire")
    approbations.approuver(d["id"], "perso", maintenant=T0 + 10)
    assert approbations.consommer("livraison_donnees_reinitialiser",
                                  {"app": "studio", "utilisateur": "paul"}, niveau="donnees",
                                  maintenant=T0 + 20, utilisateur="perso") is None


def test_mutation_cle_sans_cible_est_detectee(monkeypatch):
    """Si la clé ignorait l'utilisateur visé, l'isolation tomberait : ce test le prouverait."""
    monkeypatch.setattr(approbations, "cle_preuve", lambda nom, args: (args or {}).get("app"))
    _preuve("claire")
    assert _demande("paul")["prerequis"] == {PV: True}   # la mutation CASSE l'isolation…
    monkeypatch.undo()
    approbations.init_db()
```
Avant d'écrire les deux derniers tests, ouvrir `core/test_approbations_preuves.py` (lignes 160-245) pour reprendre les signatures EXACTES de `approuver`, `consommer`, `consommer_id` (le test d'expiration ci-dessus reprend celles de `test_approbations_preuves.py:164-171`) ; adapter si elles diffèrent. Pour la mutation, la clé du test précédent est réutilisée : garder ce test seulement s'il passe sans état partagé (la fixture `_db` isole déjà la base ; supprimer les deux dernières lignes `monkeypatch.undo()/init_db()` si inutiles).

- [ ] **Step 2 :** `cd core && python3 -m pytest test_approbations_cible.py -q -p no:cacheprovider` → FAIL (`cle_preuve` absente).

- [ ] **Step 3 : Implémenter** — dans `core/approbations.py`, après `_norm_cle` (ajouter `import hashlib` en tête si absent) :

```python
# Preuves liées à une CIBLE (utilisateur visé) en plus de l'app : S248 3b. Les autres preuves
# (`preuve_sauvegarde`, S247) restent liées à l'app seule.
PREUVES_PAR_CIBLE = frozenset({"paquet_verifie"})


def cle_preuve(nom: str, args: dict | None):
    """Clé sous laquelle une preuve `nom` est enregistrée/cherchée pour ces arguments.
    Hors `PREUVES_PAR_CIBLE` : l'`app` telle quelle (comportement S247). Par cible : `app|h` où
    `h = sha256(utilisateur)[:16]` (jamais l'identité en clair en base) ; `None` si l'app ou
    l'utilisateur visé manque (fail closed : aucune preuve ne peut s'y rattacher)."""
    a = args or {}
    if nom not in PREUVES_PAR_CIBLE:
        return a.get("app")
    app, cible = a.get("app"), a.get("utilisateur")
    if not (isinstance(app, str) and app.strip() and isinstance(cible, str) and cible.strip()):
        return None
    return f"{_norm_cle(app)}|{hashlib.sha256(cible.encode('utf-8')).hexdigest()[:16]}"
```
Puis remplacer les quatre sites :
- l.247 : `{p: _preuve_valide_c(c, p, cle_preuve(p, args), user, now) for p in prerequis}`
- l.503 : `_preuve_valide_c(c, nom, cle_preuve(nom, args), r["utilisateur"], now)`
- l.546 : `c, nom, cle_preuve(nom, _args_de_ligne(r)), user)` (remplace `json.loads(r["args"] or "{}").get("app")` ; `_args_de_ligne` gère déjà les JSON invalides, garder le `try/except` existant)
- l.583 : `_cle_canonique(c, nom, cle_preuve(nom, _args_de_ligne(r)), user)`

(`_norm_cle(None)` renvoie `""` : une clé `None` ne retrouve aucune preuve, `enregistrer_preuve` ignore les clés vides.)

- [ ] **Step 4 :** `python3 -m pytest test_approbations_cible.py test_approbations_preuves.py test_approbations.py test_approbations_garde.py test_approbations_preuves_garde.py -q -p no:cacheprovider` → PASS (les tests S247 prouvent la non-régression).

- [ ] **Step 5 : Commit** `git add core && git commit -m "feat(s248): preuve liée à la cible (app + utilisateur visé) pour paquet_verifie"`

---

### Task 2 : Cœur — enregistrement de la preuve par cible depuis le résultat de la brique

**Files :**
- Modify : `core/outils.py` (`_enregistrer_preuve_eventuelle`, ~l.604-636)
- Create : `core/test_approbations_cible_garde.py`

**Interfaces :**
- Consumes : `approbations.cle_preuve`, `approbations.PREUVES_PAR_CIBLE`.
- Produces : pour une capacité qui `fournit_preuve` un nom de `PREUVES_PAR_CIBLE`, la clé (et l'`app_id`) est `cle_preuve(nom, args)` ; les champs `app` / `app_id` du résultat sont IGNORÉS (un verdict ne peut pas élargir la portée de la preuve). `args` sans cible exploitable → aucune preuve enregistrée.

- [ ] **Step 1 : Tests qui échouent** — `core/test_approbations_cible_garde.py` (reprendre l'en-tête, `_Reg` et la fixture `env` de `test_approbations_preuves_garde.py`) :

```python
"""Câblage S248 3b : la preuve par cible vient du RÉSULTAT de la brique, la clé des arguments."""
import asyncio
import json
import os
import sys
import tempfile

os.environ["ASSISTANT_CONFIG_PATH"] = os.path.join(tempfile.mkdtemp(), "cfg.json")
os.environ.setdefault("GATEWAY_KEY", "sk-test-local")
sys.path.insert(0, os.path.dirname(__file__))

import pytest  # noqa: E402

import approbations  # noqa: E402
import outils  # noqa: E402


class _Reg:
    def __init__(self, briques):
        self.briques = briques


PARAMS = {"app": {"type": "string", "requis": True}, "utilisateur": {"type": "string", "requis": True}}
REGISTRE = _Reg({"livraison": {"nom": "livraison", "port": 6240, "capacites": [
    {"nom": "livraison_donnees_verifier", "chemin": "/v", "methode": "POST", "action": False,
     "fournit_preuve": "paquet_verifie", "description": "Vérifie.", "params": PARAMS},
    {"nom": "livraison_donnees_reinitialiser", "chemin": "/r", "methode": "POST", "action": True,
     "sensibilite": "donnees", "prerequis": ["paquet_verifie"], "description": "Reset.",
     "params": PARAMS},
]}})


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(approbations, "DB", str(tmp_path / "a.db"))
    approbations.init_db()
    etat = {"notifs": [], "resultat_verif": None, "executes": []}

    async def faux_notifier(registre, demande):
        etat["notifs"].append((demande["id"], dict(demande["prerequis"])))

    async def faux_executer(nom, args, registre):
        if nom == "livraison_donnees_verifier":
            return etat["resultat_verif"]
        etat["executes"].append((nom, args.get("utilisateur")))
        return '{"ok": true}'

    monkeypatch.setattr(outils, "_notifier_approbation", faux_notifier)
    monkeypatch.setattr(outils, "_executer", faux_executer)
    return etat


def _run(nom, args):
    return asyncio.run(outils.executer(nom, args, REGISTRE))


def _verdict(**kw):
    d = {"ok": True, "verdict": "valide", "preuve_id": "P1", "paquet_id": "P1",
         "expire_a": 4_000_000_000.0}
    d.update(kw)
    return json.dumps(d)


def test_verdict_valide_pour_claire_libere_la_demande_de_claire_seulement(env):
    _run("livraison_donnees_reinitialiser", {"app": "studio", "utilisateur": "claire"})
    _run("livraison_donnees_reinitialiser", {"app": "studio", "utilisateur": "paul"})
    env["resultat_verif"] = _verdict()
    _run("livraison_donnees_verifier", {"app": "studio", "utilisateur": "claire"})
    derniers = {n[0]: n[1] for n in env["notifs"]}
    assert list(derniers.values()).count({"paquet_verifie": True}) == 1
    assert env["notifs"][-1][1] == {"paquet_verifie": True}


def test_verdict_qui_pretend_viser_une_autre_app_ou_cible_est_ignore(env):
    """Un résultat portant `app`/`app_id` ne peut pas déplacer la preuve ailleurs que les ARGUMENTS."""
    env["resultat_verif"] = _verdict(app="calendrier", app_id="A9", utilisateur="paul")
    _run("livraison_donnees_verifier", {"app": "studio", "utilisateur": "claire"})
    _run("livraison_donnees_reinitialiser", {"app": "calendrier", "utilisateur": "claire"})
    _run("livraison_donnees_reinitialiser", {"app": "studio", "utilisateur": "paul"})
    _run("livraison_donnees_reinitialiser", {"app": "studio", "utilisateur": "claire"})
    assert [n[1] for n in env["notifs"]] == [{"paquet_verifie": False}, {"paquet_verifie": False},
                                             {"paquet_verifie": True}]


def test_verdict_invalide_revoque_la_preuve_de_la_cible(env):
    env["resultat_verif"] = _verdict()
    _run("livraison_donnees_verifier", {"app": "studio", "utilisateur": "claire"})
    env["resultat_verif"] = _verdict(verdict="invalide", preuve_id="P2")
    _run("livraison_donnees_verifier", {"app": "studio", "utilisateur": "claire"})
    _run("livraison_donnees_reinitialiser", {"app": "studio", "utilisateur": "claire"})
    assert env["notifs"][-1][1] == {"paquet_verifie": False}


def test_args_sans_utilisateur_n_enregistre_aucune_preuve(env):
    env["resultat_verif"] = _verdict()
    _run("livraison_donnees_verifier", {"app": "studio"})
    _run("livraison_donnees_reinitialiser", {"app": "studio", "utilisateur": "claire"})
    assert env["notifs"][-1][1] == {"paquet_verifie": False}


def test_execution_apres_approbation_pour_la_bonne_cible_seulement(env):
    env["resultat_verif"] = _verdict()
    _run("livraison_donnees_verifier", {"app": "studio", "utilisateur": "claire"})
    r = _run("livraison_donnees_reinitialiser", {"app": "studio", "utilisateur": "claire"})
    id_ = env["notifs"][-1][0]
    approbations.approuver(id_, "perso")
    _run("livraison_donnees_reinitialiser", {"app": "studio", "utilisateur": "claire"})
    assert env["executes"] == [("livraison_donnees_reinitialiser", "claire")]
```
(Avant d'écrire, ouvrir `test_approbations_preuves_garde.py` jusqu'à la fin pour reprendre l'idiome exact d'approbation + ré-exécution — `approuver(id_, ...)` selon sa signature réelle — et ajuster le dernier test ; l'identité d'approbation par défaut y est `"perso"`.)

- [ ] **Step 2 :** → FAIL (la clé est encore `args["app"]`).

- [ ] **Step 3 : Implémenter** — dans `_enregistrer_preuve_eventuelle`, remplacer la ligne `cles = [...]` et les appels qui utilisent `_id_app(d)` :

```python
        pid = d.get("preuve_id")
        if str(preuve) in approbations.PREUVES_PAR_CIBLE:
            # Preuve par cible : la clé vient des ARGUMENTS exécutés ; `app`/`app_id` du résultat
            # sont ignorés (un verdict ne peut pas élargir la portée de la preuve).
            cle = approbations.cle_preuve(str(preuve), args)
            if cle is None:
                return
            cles, app_id = [cle], cle
        else:
            cles = [(args or {}).get("app"), d.get("app"), d.get("app_id")]
            app_id = _id_app(d)
```
et utiliser `app_id=app_id` dans `revoquer_preuve(...)` et `enregistrer_preuve(...)` à la place de `app_id=_id_app(d)`.

- [ ] **Step 4 :** `python3 -m pytest test_approbations_cible_garde.py test_approbations_preuves_garde.py test_approbations_cible.py -q -p no:cacheprovider` puis `python3 -m pytest -q -p no:cacheprovider -x` dans `core` (suite complète) → PASS.

- [ ] **Step 5 : Commit** `git add core && git commit -m "feat(s248): enregistrement de la preuve par cible depuis le verdict de la brique"`

---

### Task 3 : Livraison — sélection du paquet vérifié et consommation

**Files :**
- Modify : `briques/livraison/paquets.py`, `briques/livraison/test_paquets.py`

**Interfaces :**
- Produces :
  - `dernier_verifie(app: str, h: str, maintenant: float | None = None, preuve_s: float | None = PREUVE_TTL_S) -> dict | None` : le paquet de (app, h) vérifié le plus récemment, non expiré (rétention) et — si `preuve_s` n'est pas `None` — vérifié depuis moins de `preuve_s` secondes ; ignore les paquets déjà `consomme_a`.
  - `marquer_consomme(paquet_id: str, maintenant: float | None = None) -> dict | None` : pose `consomme_a` (un paquet utilisé pour un reset ne peut plus autoriser un second reset).
  - L'enregistrement gagne la clé `consomme_a: None`.

- [ ] **Step 1 : Tests qui échouent** (ajouter à `test_paquets.py`)

```python
def _verifie(t_exp, t_ver, app="studio", h=H):
    r = _enreg(t=t_exp, app=app)
    P._ecrire_tout({**P._lire_tout(), r["id"]: {**P.lire(r["id"]), "h": h}})
    P.marquer_verifie(r["id"], t_ver)
    return r["id"]


def test_dernier_verifie_prend_le_plus_recent_verifie():
    a = _verifie(0.0, 100.0)
    b = _verifie(0.0, 200.0)
    assert P.dernier_verifie("studio", H, maintenant=300.0)["id"] == b
    _ = a


def test_dernier_verifie_ignore_non_verifie_expire_perime_consomme_autre_cible():
    _enreg(t=0.0)                                           # non vérifié
    assert P.dernier_verifie("studio", H, 10.0) is None
    vieux = _verifie(0.0, 1.0)                              # vérifié mais preuve de 6 h dépassée
    assert P.dernier_verifie("studio", H, 1.0 + 6 * 3600 + 1) is None
    assert P.dernier_verifie("studio", H, 1.0 + 6 * 3600 + 1, preuve_s=None)["id"] == vieux
    assert P.dernier_verifie("studio", H, 15 * 86400.0, preuve_s=None) is None   # rétention dépassée
    assert P.dernier_verifie("studio", "f" * 16, 10.0) is None
    assert P.dernier_verifie("autre", H, 10.0) is None
    P.marquer_consomme(vieux, 5.0)
    assert P.dernier_verifie("studio", H, 10.0, preuve_s=None) is None


def test_marquer_consomme_inconnu():
    assert P.marquer_consomme("0" * 32) is None
```
(Ajuster le helper `_verifie` : `_enreg` accepte déjà `app` ; le réécriture de `h` passe par les fonctions privées du module, déjà utilisées plus haut dans le même fichier.)

- [ ] **Step 2 :** → FAIL. **Step 3 : Implémenter** — dans `paquets.py` : ajouter `"consomme_a": None` au dict de `enregistrer`, puis :

```python
def dernier_verifie(app: str, h: str, maintenant: Optional[float] = None,
                    preuve_s: Optional[float] = PREUVE_TTL_S) -> Optional[dict]:
    now = maintenant if maintenant is not None else time.time()
    candidats = []
    for r in _lire_tout().values():
        if not (isinstance(r, dict) and r.get("app") == app and r.get("h") == h):
            continue
        v = r.get("verifie_a")
        if v is None or r.get("consomme_a") is not None or float(r.get("expire_a", 0)) <= now:
            continue
        if preuve_s is not None and float(v) + preuve_s <= now:
            continue
        candidats.append(r)
    return max(candidats, key=lambda r: float(r["verifie_a"])) if candidats else None


def marquer_consomme(paquet_id: str, maintenant: Optional[float] = None) -> Optional[dict]:
    tout = _lire_tout()
    r = tout.get(paquet_id)
    if not isinstance(r, dict):
        return None
    r["consomme_a"] = maintenant if maintenant is not None else time.time()
    _ecrire_tout(tout)
    return r
```

- [ ] **Step 4 :** `cd briques/livraison && python3 -m pytest test_paquets.py -q -p no:cacheprovider` → PASS. **Step 5 : Commit** `git commit -am "feat(s248): sélection du dernier paquet vérifié et consommation à l'usage"`

---

### Task 4 : Livraison — orchestration du reset et de la restitution

**Files :**
- Modify : `briques/livraison/donnees_utilisateur.py`
- Create : `briques/livraison/test_donnees_reset.py`

**Interfaces :**
- Consumes : `paquets.dernier_verifie/marquer_consomme/lire/journaliser/empreinte_utilisateur`, `chiffrement.dechiffrer`, `AppContrat.exporter/reinitialiser/importer`, `Executeur.lire`.
- Produces :
  - `class RefusDonnees(Exception)` : `.statut` (409 ou 404), `.message` (fixe, ≤ 200 car., sans donnée perso).
  - `async reinitialiser_donnees(app, ex, utilisateur, maintenant=None) -> dict` → `{"ok": True, "etat": "reinitialise", "paquet_id", "supprimes": {type: n}}`.
  - `async restituer_donnees(app, ex, utilisateur, paquet_id: str | None = None, maintenant=None) -> dict` → `{"ok": True, "etat": "restitue", "paquet_id", "comptages": {...}}`.
  - Verrou en mémoire par (app, h) : une seconde opération simultanée sur la même cible → `RefusDonnees(409)`.

- [ ] **Step 1 : Tests qui échouent** — `test_donnees_reset.py` (reprendre `FauxExecuteur`, `cle` et l'idiome `run` de `test_donnees_utilisateur.py`; ajouter un faux app à état) :

```python
import asyncio
import base64
import os

import pytest

import chiffrement
import donnees_utilisateur as D
import paquets as P
from contrats import ContratErreur


@pytest.fixture(autouse=True)
def cle(monkeypatch):
    monkeypatch.setenv("LIVRAISON_CHIFFREMENT_CLE", base64.b64encode(os.urandom(32)).decode())


class FauxExecuteur:
    def __init__(self):
        self.objets = {}

    async def deposer(self, cle, octets):
        self.objets[cle] = octets

    async def lire(self, cle):
        return self.objets[cle]

    async def supprimer(self, cle):
        self.objets.pop(cle, None)


class AppAEtat:
    """App en mémoire : `donnees` = comptages courants ; l'empreinte en dépend."""
    nom, version_schema = "studio", "1"

    def __init__(self, donnees=None, resurrection=False):
        self.donnees = dict(donnees or {"series": 2, "profils": 1})
        self.resurrection, self.appels = resurrection, []

    def _emp(self):
        return "emp:" + ",".join(f"{k}={v}" for k, v in sorted(self.donnees.items()))

    async def exporter(self, u):
        self.appels.append("exporter")
        return b"PAQUET:" + self._emp().encode(), {"empreinte": self._emp(), "comptages": dict(self.donnees)}

    async def verifier(self, u, paquet):
        return {"ok": True, "empreinte": paquet.decode().removeprefix("PAQUET:")}

    async def reinitialiser(self, u, empreinte):
        self.appels.append("reinitialiser")
        if empreinte != self._emp():
            raise ContratErreur("x", 409, "empreinte")
        suppr, self.donnees = dict(self.donnees), {k: 0 for k in self.donnees}
        if self.resurrection:                       # un handler async re-sauvegarde une série
            self.donnees["series"] = 1
        return {"ok": True, "supprimes": suppr}

    async def importer(self, u, paquet):
        self.appels.append("importer")
        emp = paquet.decode().removeprefix("PAQUET:emp:")
        self.donnees = {k: int(v) for k, v in (p.split("=") for p in emp.split(","))}
        return {"ok": True, "comptages": dict(self.donnees)}


def run(c):
    return asyncio.run(c)


def _verifie(app, ex, u="claire"):
    r = run(D.verifier_paquet(app, ex, u))
    assert r["verdict"] == "valide"
    return r


def test_reset_nominal_puis_restitution_redonne_l_etat_initial():
    ex, app = FauxExecuteur(), AppAEtat()
    v = _verifie(app, ex)
    r = run(D.reinitialiser_donnees(app, ex, "claire"))
    assert r["etat"] == "reinitialise" and r["supprimes"] == {"series": 2, "profils": 1}
    assert app.donnees == {"series": 0, "profils": 0}
    assert P.lire(v["paquet_id"])["consomme_a"] is not None
    back = run(D.restituer_donnees(app, ex, "claire"))
    assert back["etat"] == "restitue" and app.donnees == {"series": 2, "profils": 1}
    assert back["paquet_id"] == v["paquet_id"]


def test_reset_sans_paquet_verifie_refuse_et_ne_touche_pas_l_app():
    app = AppAEtat()
    with pytest.raises(D.RefusDonnees) as e:
        run(D.reinitialiser_donnees(app, FauxExecuteur(), "claire"))
    assert e.value.statut == 409 and "reinitialiser" not in app.appels


def test_reset_refuse_si_les_donnees_ont_change_depuis_la_verification():
    ex, app = FauxExecuteur(), AppAEtat()
    _verifie(app, ex)
    app.donnees["series"] = 3                        # Claire a écrit depuis
    with pytest.raises(D.RefusDonnees) as e:
        run(D.reinitialiser_donnees(app, ex, "claire"))
    assert "changé" in e.value.message and "reinitialiser" not in app.appels


def test_reset_refuse_si_paquet_stocke_illisible():
    ex, app = FauxExecuteur(), AppAEtat()
    v = _verifie(app, ex)
    cle_obj = P.lire(v["paquet_id"])["objet"]
    ex.objets[cle_obj] = ex.objets[cle_obj][:-1] + b"\x00"
    with pytest.raises(D.RefusDonnees) as e:
        run(D.reinitialiser_donnees(app, ex, "claire"))
    assert "illisible" in e.value.message and "reinitialiser" not in app.appels


def test_reset_refuse_si_preuve_de_plus_de_6h():
    ex, app = FauxExecuteur(), AppAEtat()
    v = run(D.verifier_paquet(app, ex, "claire", maintenant=1000.0))
    assert v["verdict"] == "valide"
    with pytest.raises(D.RefusDonnees):
        run(D.reinitialiser_donnees(app, ex, "claire", maintenant=1000.0 + 6 * 3600 + 1))


def test_un_paquet_ne_sert_qu_a_un_reset():
    ex, app = FauxExecuteur(), AppAEtat()
    _verifie(app, ex)
    run(D.reinitialiser_donnees(app, ex, "claire"))
    with pytest.raises(D.RefusDonnees):
        run(D.reinitialiser_donnees(app, ex, "claire"))


def test_resurrection_detectee_reset_jamais_declare_reussi():
    ex, app = FauxExecuteur(), AppAEtat(resurrection=True)
    _verifie(app, ex)
    with pytest.raises(D.RefusDonnees) as e:
        run(D.reinitialiser_donnees(app, ex, "claire"))
    assert e.value.statut == 409 and "incomplet" in e.value.message


def test_cible_differente_ne_voit_pas_le_paquet():
    ex, app = FauxExecuteur(), AppAEtat()
    _verifie(app, ex, "claire")
    with pytest.raises(D.RefusDonnees):
        run(D.reinitialiser_donnees(app, ex, "paul"))


def test_operation_concurrente_sur_la_meme_cible_refusee():
    ex, app = FauxExecuteur(), AppAEtat()
    _verifie(app, ex)

    async def deux():
        h = P.empreinte_utilisateur("claire")
        D._EN_COURS.add(("studio", h))
        try:
            await D.reinitialiser_donnees(app, ex, "claire")
        finally:
            D._EN_COURS.discard(("studio", h))
    with pytest.raises(D.RefusDonnees) as e:
        run(deux())
    assert "en cours" in e.value.message


def test_restituer_sans_paquet_404_et_paquet_id_explicite():
    ex, app = FauxExecuteur(), AppAEtat()
    with pytest.raises(D.RefusDonnees) as e:
        run(D.restituer_donnees(app, ex, "claire"))
    assert e.value.statut == 404
    v = _verifie(app, ex)
    run(D.reinitialiser_donnees(app, ex, "claire"))
    assert run(D.restituer_donnees(app, ex, "claire", paquet_id=v["paquet_id"]))["etat"] == "restitue"
    with pytest.raises(D.RefusDonnees):             # paquet d'un autre utilisateur
        run(D.restituer_donnees(app, ex, "paul", paquet_id=v["paquet_id"]))


def test_restitution_conflit_de_l_app_remonte_en_409():
    ex, app = FauxExecuteur(), AppAEtat()
    _verifie(app, ex)

    async def conflit(u, p):
        raise ContratErreur("x", 409, "conflit")
    app.importer = conflit
    with pytest.raises(D.RefusDonnees) as e:
        run(D.restituer_donnees(app, ex, "claire"))
    assert e.value.statut == 409 and "conflit" in e.value.message


def test_restitution_dont_l_empreinte_diverge_est_signalee():
    ex, app = FauxExecuteur(), AppAEtat()
    _verifie(app, ex)
    run(D.reinitialiser_donnees(app, ex, "claire"))

    async def importe_mal(u, p):
        app.donnees = {"series": 1, "profils": 0}
        return {"ok": True}
    app.importer = importe_mal
    with pytest.raises(D.RefusDonnees) as e:
        run(D.restituer_donnees(app, ex, "claire"))
    assert "incomplète" in e.value.message
```

- [ ] **Step 2 :** → FAIL. **Step 3 : Implémenter** — ajouter à `donnees_utilisateur.py` :

```python
class RefusDonnees(Exception):
    def __init__(self, statut: int, message: str):
        super().__init__(message)
        self.statut, self.message = statut, message


_EN_COURS: set = set()     # (app, h) ayant une opération en cours : un reset ne double jamais


def _tout_a_zero(comptages: dict) -> bool:
    return all(isinstance(v, int) and v == 0 for v in comptages.values())


async def _relire(ex, rec) -> bytes:
    try:
        return chiffrement.dechiffrer(await ex.lire(rec["objet"]), rec["objet"])
    except chiffrement.Illisible:
        raise RefusDonnees(409, "paquet stocké illisible (altéré ou clé changée) : "
                                "refais une vérification") from None


async def reinitialiser_donnees(app, ex, utilisateur: str, maintenant: Optional[float] = None) -> dict:
    from contrats import ContratErreur
    h = paquets.empreinte_utilisateur(utilisateur)
    cible = (app.nom, h)
    if cible in _EN_COURS:
        raise RefusDonnees(409, "une opération est déjà en cours pour cet utilisateur")
    _EN_COURS.add(cible)
    try:
        rec = paquets.dernier_verifie(app.nom, h, maintenant)           # preuve ≤ 6 h
        if rec is None:
            raise RefusDonnees(409, "aucun paquet vérifié et récent pour cet utilisateur : "
                                    "lance d'abord livraison_donnees_verifier")
        await _relire(ex, rec)                         # le paquet est TOUJOURS restituable
        try:
            _, meta = await app.exporter(utilisateur)
            if meta["empreinte"] != rec["empreinte"]:
                raise RefusDonnees(409, "les données ont changé depuis la vérification : "
                                        "relance livraison_donnees_verifier")
            r = await app.reinitialiser(utilisateur, rec["empreinte"])
            _, apres = await app.exporter(utilisateur)
        except ContratErreur as e:
            raise RefusDonnees(409 if e.statut in (409, 422) else 502,
                               f"l'application refuse : {e.raison or 'erreur'}") from None
        paquets.marquer_consomme(rec["id"], maintenant)
        if not _tout_a_zero(apres["comptages"]):
            paquets.journaliser("reinitialiser", app.nom, h, rec["id"], False, maintenant)
            raise RefusDonnees(409, "remise à zéro incomplète : des données sont réapparues (une "
                                    "opération de l'application était en cours) ; le paquet reste "
                                    "restituable, relance la vérification puis réessaie")
        paquets.journaliser("reinitialiser", app.nom, h, rec["id"], True, maintenant)
        return {"ok": True, "etat": "reinitialise", "paquet_id": rec["id"],
                "supprimes": r.get("supprimes", {})}
    finally:
        _EN_COURS.discard(cible)


async def restituer_donnees(app, ex, utilisateur: str, paquet_id: Optional[str] = None,
                            maintenant: Optional[float] = None) -> dict:
    from contrats import ContratErreur
    h = paquets.empreinte_utilisateur(utilisateur)
    cible = (app.nom, h)
    if cible in _EN_COURS:
        raise RefusDonnees(409, "une opération est déjà en cours pour cet utilisateur")
    _EN_COURS.add(cible)
    try:
        if paquet_id:
            rec = paquets.lire(paquet_id)
            valide = (rec and rec["app"] == app.nom and rec["h"] == h
                      and rec.get("verifie_a") is not None
                      and float(rec["expire_a"]) > (maintenant if maintenant is not None else time.time()))
            if not valide:
                raise RefusDonnees(404, "paquet introuvable, expiré ou non vérifié pour cet utilisateur")
        else:
            rec = paquets.dernier_verifie(app.nom, h, maintenant, preuve_s=None,
                                          inclure_consommes=True)
            if rec is None:
                raise RefusDonnees(404, "aucun paquet vérifié disponible pour cet utilisateur")
        clair = await _relire(ex, rec)
        try:
            r = await app.importer(utilisateur, clair)
            _, apres = await app.exporter(utilisateur)
        except ContratErreur as e:
            paquets.journaliser("restituer", app.nom, h, rec["id"], False, maintenant)
            raise RefusDonnees(409 if e.statut in (409, 422) else 502,
                               f"l'application refuse : {e.raison or 'erreur'}") from None
        if apres["empreinte"] != rec["empreinte"]:
            paquets.journaliser("restituer", app.nom, h, rec["id"], False, maintenant)
            raise RefusDonnees(409, "restitution incomplète : l'état restauré ne correspond pas "
                                    "au paquet")
        paquets.journaliser("restituer", app.nom, h, rec["id"], True, maintenant)
        return {"ok": True, "etat": "restitue", "paquet_id": rec["id"], "comptages": apres["comptages"]}
    finally:
        _EN_COURS.discard(cible)
```
(importer `time` est déjà fait en tête du module.) Et dans `paquets.dernier_verifie` ajouter le paramètre `inclure_consommes: bool = False` : si `False`, ignorer les paquets `consomme_a` (comportement Task 3) ; si `True`, ne pas les ignorer (la restitution doit pouvoir réutiliser le paquet consommé par le reset).

Compléter le test de Task 3 : `dernier_verifie(..., inclure_consommes=True)` retourne le paquet consommé.

- [ ] **Step 4 :** `python3 -m pytest test_donnees_reset.py test_paquets.py test_donnees_utilisateur.py -q -p no:cacheprovider` → PASS. **Step 5 : Commit** `git commit -am "feat(s248): reset et restitution par utilisateur (preuve fraîche, empreinte inchangée, comptages à zéro)"`

---

### Task 5 : Routes livraison, `preuve_id`, manifeste

**Files :**
- Modify : `briques/livraison/main.py`, `briques/livraison/donnees_utilisateur.py` (`verifier_paquet` : ajouter `preuve_id`), `briques/livraison/manifest.json`, `briques/livraison/test_api.py`, `briques/livraison/test_donnees_utilisateur.py`

**Interfaces :**
- Produces : `POST /contrats/{app}/reinitialiser` (202 non : réponse synchrone 200, durée < 60 s attendue ; si l'app est lente, le délai de 60 s des actions du Cœur s'applique et un 504 se lit « vérifie avec livraison_donnees_verifier avant de réessayer » comme pour S246), `POST /contrats/{app}/restituer` (corps `{"utilisateur", "paquet_id"?}`). `verifier_paquet` renvoie en plus `preuve_id == paquet_id`.
- Manifeste : `livraison_donnees_verifier` gagne `"fournit_preuve": "paquet_verifie"` ; nouveaux `livraison_donnees_reinitialiser` (`sensibilite: donnees`, `prerequis: ["paquet_verifie"]`) et `livraison_donnees_restituer` (`sensibilite: donnees`).

- [ ] **Step 1 : Tests qui échouent**

Dans `test_donnees_utilisateur.py` : `assert r["preuve_id"] == r["paquet_id"]` ajouté à `test_verifier_valide_relit_depuis_le_stockage`.

Dans `test_api.py` :

```python
def test_manifeste_outils_donnees_3b():
    import json, pathlib
    m = json.loads((pathlib.Path(__file__).parent / "manifest.json").read_text())
    caps = {x["nom"]: x for x in m["capacites"]}
    assert caps["livraison_donnees_verifier"]["fournit_preuve"] == "paquet_verifie"
    rz, rs = caps["livraison_donnees_reinitialiser"], caps["livraison_donnees_restituer"]
    assert (rz["sensibilite"], rz["prerequis"], rz["chemin"]) == ("donnees", ["paquet_verifie"],
                                                                   "/contrats/{app}/reinitialiser")
    assert (rs["sensibilite"], rs["chemin"]) == ("donnees", "/contrats/{app}/restituer")
    assert "prerequis" not in rs and rz["action"] is True and rs["action"] is True
    assert {"app", "utilisateur"} <= set(rz["params"]) and "paquet_id" in rs["params"]
```
et un test de route (mêmes faux que `test_donnees_utilisateur.py` ; reprendre `FauxApp` / `FauxExecuteur` en les important de ce module ou en les recopiant) :

```python
def test_routes_reset_et_restitution_codes(monkeypatch):
    monkeypatch.setenv("LIVRAISON_API_KEYS", "k")
    H = {"X-API-Key": "k"}
    for route in ("reinitialiser", "restituer"):
        assert c.post(f"/contrats/studio/{route}", json={"utilisateur": "claire"}).status_code == 401
    monkeypatch.setattr(main.contrats, "ouvrir", lambda nom: FauxApp())
    monkeypatch.setattr(main, "executeur", lambda: FauxExecuteur())
    r = c.post("/contrats/studio/reinitialiser", json={"utilisateur": "claire"}, headers=H)
    assert r.status_code == 409 and "paquet vérifié" in r.json()["detail"]
    assert "claire" not in r.text
    r = c.post("/contrats/studio/restituer", json={"utilisateur": "claire"}, headers=H)
    assert r.status_code == 404
```

- [ ] **Step 2 :** → FAIL. **Step 3 : Implémenter**

`verifier_paquet` : ajouter `"preuve_id": pid` au dict renvoyé.

`main.py` (importer `RefusDonnees` via `DU.RefusDonnees`), à la suite des routes 3a :

```python
class CorpsRestitution(CorpsUtilisateur):
    paquet_id: Optional[str] = Field(default=None, pattern=r"^[0-9a-f]{32}$")


async def _donnees_gardees(app_: str, utilisateur: str, fabrique):
    try:
        chiffrement._cle()
        app = contrats.ouvrir(app_)
        ex = executeur()
        return await fabrique(app, ex)
    except DU.RefusDonnees as e:
        raise HTTPException(e.statut, e.message) from None
    except (contrats.ContratErreur, chiffrement.CleAbsente, ExecuteurErreur, OSError) as e:
        raise _traduire(e) from None


@app.post("/contrats/{app_}/reinitialiser")
async def reinitialiser_donnees(app_: str, corps: CorpsUtilisateur, _: str = Depends(cle_api_fermee)):
    r = await _donnees_gardees(app_, corps.utilisateur,
                               lambda a, ex: DU.reinitialiser_donnees(a, ex, corps.utilisateur))
    return {"app": app_.strip().lower(), **r}


@app.post("/contrats/{app_}/restituer")
async def restituer_donnees(app_: str, corps: CorpsRestitution, _: str = Depends(cle_api_fermee)):
    r = await _donnees_gardees(app_, corps.utilisateur,
                               lambda a, ex: DU.restituer_donnees(a, ex, corps.utilisateur,
                                                                  corps.paquet_id))
    return {"app": app_.strip().lower(), **r}
```
(Les noms de fonctions de routes `reinitialiser_donnees` / `restituer_donnees` ne doivent pas écraser ceux de `DU` : ils sont accédés via `DU.`, aucun conflit ; vérifier qu'aucune route existante ne porte ces noms.)

Manifeste : dans `livraison_donnees_verifier` ajouter `"fournit_preuve": "paquet_verifie"` ; ajouter :

```json
{
  "nom": "livraison_donnees_reinitialiser",
  "description": "REMET À ZÉRO les données d'UN SEUL utilisateur d'une application à contrat de données (ex. le Studio), sans toucher aux autres. Exige d'abord un verdict VALIDE de livraison_donnees_verifier sur la MÊME application ET le MÊME utilisateur (identité identique au caractère près) ; les données sont ensuite effacées et le paquet vérifié permet de les restituer (livraison_donnees_restituer, 14 jours). Pas pour redémarrer ni réinitialiser une application entière (→ livraison_reset_app). N'affirme jamais que c'est fait sans le résultat « reinitialise » de l'outil. APPELLE CET OUTIL DIRECTEMENT quand l'utilisateur le demande : c'est l'appel qui crée la demande d'approbation et envoie les boutons Telegram. Ne dis JAMAIS « demande envoyée » sans avoir réellement appelé l'outil dans ce tour.",
  "methode": "POST",
  "chemin": "/contrats/{app}/reinitialiser",
  "params": {
    "app": {"type": "string", "description": "Nom de l'application à contrat de données. Ex : « studio ».", "requis": true},
    "utilisateur": {"type": "string", "description": "Identité exacte de l'utilisateur visé (la même que pour la vérification).", "requis": true}
  },
  "action": true,
  "sensibilite": "donnees",
  "prerequis": ["paquet_verifie"],
  "relayer_erreurs": true
},
{
  "nom": "livraison_donnees_restituer",
  "description": "RESTITUE à un utilisateur ses données mises de côté (paquet chiffré vérifié, conservé 14 jours) : réimporte son espace dans l'application. Refuse si une donnée existante appartient à quelqu'un d'autre. À utiliser après une remise à zéro, à la demande de l'utilisateur lui-même. APPELLE CET OUTIL DIRECTEMENT quand l'utilisateur le demande : c'est l'appel qui crée la demande d'approbation et envoie les boutons Telegram. Ne dis JAMAIS « demande envoyée » sans avoir réellement appelé l'outil dans ce tour.",
  "methode": "POST",
  "chemin": "/contrats/{app}/restituer",
  "params": {
    "app": {"type": "string", "description": "Nom de l'application à contrat de données. Ex : « studio ».", "requis": true},
    "utilisateur": {"type": "string", "description": "Identité exacte de l'utilisateur visé.", "requis": true},
    "paquet_id": {"type": "string", "description": "Identifiant d'un paquet précis (optionnel ; défaut : le dernier paquet vérifié)."}
  },
  "action": true,
  "sensibilite": "donnees",
  "relayer_erreurs": true
}
```
Supprimer l'assertion « pas de `fournit_preuve` avant 3b » du test de 3a (`test_manifeste_declare_les_outils_donnees_et_pas_de_preuve_avant_3b`) : elle est remplacée par `test_manifeste_outils_donnees_3b`.

- [ ] **Step 4 :** `cd briques/livraison && python3 -m pytest -q -p no:cacheprovider` puis `cd ../../core && python3 -m pytest -q -p no:cacheprovider -k "manifest or capacit or outils or approbation"` → PASS. **Step 5 : Commit** `git commit -am "feat(s248): outils livraison_donnees_reinitialiser/_restituer et preuve paquet_verifie"`

---

### Task 6 : Test de bout en bout contre le VRAI Studio (en processus)

**Files :**
- Create : `briques/livraison/test_donnees_studio_reel.py` (monorepo seulement : `pytest.skip` si `briques/studio` est absent)

**Interfaces :** aucune nouvelle ; ce test branche `AppContrat` sur l'ASGI du Studio via `httpx.ASGITransport` pour prouver le contrat réel (pas un faux).

- [ ] **Step 1 : Écrire le test**

```python
"""Livraison ↔ vrai Studio (ASGI en processus) : verifier → reset → restitution, autre utilisateur intact."""
import asyncio
import base64
import importlib
import os
import pathlib
import sys

import httpx
import pytest

STUDIO = pathlib.Path(__file__).resolve().parents[1] / "studio"
pytestmark = pytest.mark.skipif(not STUDIO.exists(), reason="hors monorepo (image Docker)")


@pytest.fixture
def studio(tmp_path, monkeypatch):
    """Charge le module `main` du Studio SOUS UN AUTRE NOM, sans écraser le `main` de livraison."""
    monkeypatch.setenv("STUDIO_SUPPORT_KEY", "cle-support-e2e")
    monkeypatch.delenv("STUDIO_KEY", raising=False)
    monkeypatch.setenv("LIVRAISON_CHIFFREMENT_CLE", base64.b64encode(os.urandom(32)).decode())
    anciens = {m: sys.modules.pop(m) for m in list(sys.modules)
               if m in ("main", "studio", "support", "stockage_pont", "contrat_donnees")}
    sys.path.insert(0, str(STUDIO))
    try:
        S = importlib.import_module("studio")
        stockage = importlib.import_module("stockage_pont")
        for sous in ("profils", "comptes", "pont"):
            os.makedirs(tmp_path / sous)
        monkeypatch.setattr(S, "ATELIERS_DIR", str(tmp_path))
        monkeypatch.setattr(S, "PROFILS_DIR", str(tmp_path / "profils"))
        monkeypatch.setattr(S, "COMPTES_DIR", str(tmp_path / "comptes"))
        monkeypatch.setattr(stockage, "ATELIERS_DIR", str(tmp_path))
        monkeypatch.setattr(stockage, "PONT_DIR", str(tmp_path / "pont"))
        yield importlib.import_module("main"), S
    finally:
        sys.path.remove(str(STUDIO))
        for m in ("main", "studio", "support", "stockage_pont", "contrat_donnees"):
            sys.modules.pop(m, None)
        sys.modules.update(anciens)
```
Puis un test qui : crée 1 série + 1 profil pour `claire` et 1 série pour `paul` via `S._save(...)` / `S._save_profil(...)` ; construit `AppContrat("studio", ENTREE, transport=httpx.ASGITransport(app=studio_main.app))` (avec `base_url` déjà `http://studio.test:6060` : mettre `url` = `http://studio.test`) ; utilise `FauxExecuteur` (stockage mémoire) ; déroule `verifier_paquet` → `reinitialiser_donnees` → vérifie que les fichiers de Claire ont disparu et que `paul` est intact → `restituer_donnees` → vérifie que l'export de Claire a la même empreinte qu'avant. Asserter aussi que `STUDIO_SUPPORT_KEY` absente donne `ContratErreur` 503 (`desactive`).

- [ ] **Step 2 :** `python3 -m pytest test_donnees_studio_reel.py -q -p no:cacheprovider` → PASS (si l'import croisé des modules `main` pose problème, le signaler et se replier sur un sous-processus `uvicorn` éphémère sur un port libre — ne pas affaiblir le test).
- [ ] **Step 3 :** suite complète livraison + Studio + shared + core → PASS (noter les comptages réels).
- [ ] **Step 4 : Commit** `git add briques/livraison && git commit -m "test(s248): livraison contre le vrai Studio — verifier, reset, restitution, voisin intact"`

---

### Task 7 : Revue, documentation, mise à jour de la mémoire

**Files :**
- Modify : `docs/GUIDE-contrat-donnees.md` (§7 « Hors parties 1+2 » → état réel ; §5 recette : « pour être pilotable par l'assistant : l'ajouter à `contrats.json` de livraison »), `docs/sprints/S248-contrat-app-reset-par-utilisateur.md` (statut), `briques/livraison/README.md`

- [ ] **Step 1 :** `/code-review high` sur la branche (zones risquées : `core/approbations.py`, `donnees_utilisateur.py`) ; corriger Critical/Important ; vérifier à la main toute affirmation forte de la revue avant de l'accepter.
- [ ] **Step 2 :** mettre à jour les docs ; commit `docs(s248): partie 3b codée`.
- [ ] **Step 3 :** mettre à jour la note mémoire `sprint-s248-contrat-donnees.md` (état, pièges découverts) et la ligne de `MEMORY.md`.

---

### Task 8 : Preuve LIVE (SLIVE) — à faire seulement après accord explicite de l'utilisateur

**Files :**
- Create : `docs/s248/preuve-donnees-utilisateur.md`

Régime « preuve Docker différé » : tout ce qui précède est codé et testé sans Docker ; cette tâche déploie et prouve. Prérequis de sécurité : sur le HP, `STUDIO_SUPPORT_KEY` n'est pas posée (routes 503) ; la poser ouvre les routes `/support/*` aux porteurs de cette clé : la générer longue et aléatoire, la ranger hors dépôt.

- [ ] **Step 1 : Construire sur le Mac** (build pip impossible sur le HP) `workplace/livraison:0.2.0` et `workplace/studio:0.6.1`, puis `docker save | ssh debian@192.168.1.89 docker load` ; garder `workplace/livraison:0.1.0` et `workplace/studio:0.6.0` comme retour arrière ; bumper les tags dans les deux `docker-compose.yml` (tags épinglés).
- [ ] **Step 2 : Exécuteur sur la VM 100** : copier `outils/executeur-restauration/executeur.py`, redémarrer le service systemd, vérifier `GET /sante` ; régler la limite du reverse proxy éventuel sur 80 Mio.
- [ ] **Step 3 : Clés** : `LIVRAISON_CHIFFREMENT_CLE` et `STUDIO_SUPPORT_KEY` dans `briques/livraison/.env` (0600), `STUDIO_SUPPORT_KEY` (même valeur) côté Studio ; copier `contrats.exemple.json` en `/data/contrats.json` (volume `livraison_data`) avec l'URL réelle du Studio ; `docker compose up -d` des deux briques (piège : `up -d` sans rebuild ne prend pas la nouvelle image — vérifier le tag réellement en service avec `docker inspect`).
- [ ] **Step 4 : Scénario sur un utilisateur TÉMOIN du Studio** (jamais un vrai compte) : créer 2 séries + 1 profil pour `temoin-a` et 1 série pour `temoin-b`, puis via l'assistant (Telegram) :
  1. `livraison_donnees_exporter` (approbation `reversible`) → noter `paquet_id`, comptages ;
  2. vérifier dans SeaweedFS que l'objet `contrat/studio/<h>/<id>.bin` existe et ne contient pas de texte clair (`strings` sans titre de série) ;
  3. `livraison_donnees_reinitialiser` AVANT vérification → demande en attente, prérequis `False`, aucun bouton ; puis `livraison_donnees_verifier` → verdict `valide`, renotification avec prérequis `True` ;
  4. refus croisé : demander le reset de `temoin-b` sans l'avoir vérifié → prérequis `False` (preuve de `temoin-a` non réutilisée) ;
  5. approuver le reset de `temoin-a` → `reinitialise` ; contrôler `temoin-a` à zéro et `temoin-b` intact (comptages + empreinte inchangée) ;
  6. `livraison_donnees_restituer` (approbation `donnees`) → empreinte de `temoin-a` identique à celle de l'étape 1 ;
  7. sabotages : (a) modifier un octet de l'objet dans SeaweedFS puis reset → refus « illisible » ; (b) écrire une série pour `temoin-a` entre vérification et reset → refus « les données ont changé » ; (c) laisser expirer (ou avancer l'horloge du registre) → purge supprime l'objet et l'entrée.
- [ ] **Step 5 :** consigner les sorties réelles (commandes, comptages, empreintes, extraits du journal `acces.jsonl` sans identité en clair) dans `docs/s248/preuve-donnees-utilisateur.md` ; nettoyer les utilisateurs témoins et les objets ; mettre `STUDIO_SUPPORT_KEY` hors service (la retirer) si l'usage n'est pas encore voulu ; commit `docs(s248): preuve LIVE des données utilisateur` ; mettre à jour la mémoire.

## Auto-revue (couverture de la spec)

- « Approbation Telegram (niveau `donnees`, prérequis = paquet vérifié) » → Tasks 1, 2, 5 ; « la preuve ne sert pas pour un autre utilisateur » → Task 1 (isolation + mutation) et Task 2 (verdict qui ment sur `app`/`utilisateur`) ; « exporter → vérifier → réinitialiser → importer → contrôle final » → Task 4 ; parade « comptages à zéro après reset » et résurrection → Task 4 ; restitution à tout moment pendant 14 jours, même après consommation du paquet par le reset → Tasks 3, 4 ; vérification contre le vrai Studio → Task 6 ; LIVE groupé → Task 8.
- Points d'attention pour l'exécutant : (1) l'identité visée figure dans le résumé de la demande Telegram — décision assumée (l'approbateur doit savoir qui est visé), à rappeler à l'utilisateur ; (2) si un autre outil du Cœur déclare un paramètre `utilisateur`, seule la preuve `paquet_verifie` en tient compte ; (3) `preuve_sauvegarde` et le reset d'app entière (S247) ne doivent pas bouger : les tests S247 sont la non-régression.
