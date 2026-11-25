# S247 partie 1 — spike Dokploy, prérequis « preuve de sauvegarde » (Cœur) et registre de preuves (brique) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** poser le socle de S247 : (a) lever les inconnues Dokploy par un spike prouvé en réel, (b) faire en sorte que le Cœur n'affiche le bouton « Approuver » d'une action `donnees` qu'après une **preuve de sauvegarde valide**, (c) donner à la brique `livraison` un registre de preuves qui refuse d'agir sans preuve fraîche.

**Architecture:** une capacité de manifeste peut déclarer `"prerequis": ["preuve_sauvegarde"]` (le Cœur crée alors l'approbation avec ce prérequis non satisfait → `prerequis_ok=false` → Telegram sans boutons, mécanisme S245 déjà en place) et une autre `"fournit_preuve": "preuve_sauvegarde"` (le Cœur lit le verdict dans **le résultat de la brique**, jamais dans ce que dit le LLM, enregistre la preuve par utilisateur + application, lève les demandes en attente et renotifie avec boutons). La brique garde sa propre vérité (`preuves_sauvegarde.json`, volume `livraison_data`) et refuse l'action même si le Cœur était contourné (défense en profondeur).

**Tech Stack:** Python 3.14 (poste) / 3.12 (conteneur), SQLite (Cœur), FastAPI + httpx (brique), pytest. Style : un fichier de test par module, aucun réseau réel, comptes vérifiés via junit XML (`rtk proxy python3 -m pytest … -p no:cacheprovider --junitxml=…`).

## Décisions de l'utilisateur (2026-11-25, en session)

1. **Destination des sauvegardes** : SeaweedFS du HP (S3, port hôte 9106) **+ copie USB** existante (S233/S236). La VM 100 n'est donc plus seule : ni autre machine, ni hors site pour S247.
2. **Défaut `/etat` après rollback** : *durcir davantage* — ne plus se fier au seul repère mémorisé, lire l'état réel du service. Faisabilité à établir par le spike (Task 1) ; code en partie 2.
3. **Miroir de tous les dépôts GitHub** : **sprint dédié, hors S247**. Seule la sauvegarde de Forgejo (point 4 de l'idée) entre en S247.

## Global Constraints

- Le champ de manifeste `prerequis` est **optionnel** ; les capacités sans ce champ gardent un comportement identique (non-régression : `core/test_approbations*.py` reste vert).
- Clé d'une preuve = nom de l'application tel que passé dans `args["app"]`, `strip().lower()` ; la brique renvoie aussi son `app` canonique et son `app_id`, enregistrés comme clés supplémentaires. **Fail closed** : une clé qui ne correspond pas = prérequis non satisfait.
- Une preuve vit au plus `PREUVE_TTL_MAX_S = 24 * 3600` côté Cœur ; la brique fixe sa propre échéance `PREUVE_TTL_S = 6 * 3600` (la plus courte l'emporte, le Cœur plafonne seulement).
- Le Cœur ne fait confiance qu'au JSON du résultat de la capacité `fournit_preuve` : `ok` vrai, `verdict == "valide"`, `preuve_id` non vide, `expire_a` numérique. Tout autre cas : aucune preuve.
- La brique n'accède jamais au socket Docker ; aucune réponse brute de Dokploy n'est relayée (liste blanche de champs) ; secrets jamais dans les logs ni les messages Telegram.
- Variables : `LIVRAISON_API_KEYS` (jamais `API_KEYS`), `LIVRAISON_DATA` (volume). Pas de secret littéral dans un compose.
- Branche de travail : `git switch -c sprint/s247-sauvegarde-verifiee` (depuis `main`, arbre propre au démarrage). Aucune clé d'approbation du HP n'est touchée.

---

### Task 1 : Spike Dokploy (obligatoire avant la partie 2)

**Files:**
- Create: `docs/s247/spike-dokploy.md`
- Create: `docs/s247/contrats/` (extraits d'OpenAPI et exemples réels, **sans secret**)

**Interfaces:**
- Produces : un document qui répond, **preuves à l'appui**, aux 6 questions ci-dessous. La partie 2 n'est écrite qu'à partir de ces réponses.

Contexte : Dokploy v0.31.4 sur la VM 100 (`http://100.124.176.122:3000`), clé owner dans `~/.workplace-secrets/s246-comptes.txt` (hors dépôt, ne jamais la copier dans un fichier suivi par git). Le contrat extrait `docs/s246/contrats/dokploy-v0.31.4.openapi.extrait.json` ne contient **aucune** route `docker.*` et seulement des sauvegardes pour **bases** (`backup.manualBackupPostgres|MySql|…`) et `compose`, pas pour une application simple.

- [ ] **Step 1 : télécharger la spec complète (659 routes) dans le scratchpad, pas dans le dépôt**

```bash
SC=/private/tmp/claude-502/-Users-garinat-t-Desktop-Workplace/193dcfa4-1ddb-4efb-9c27-a49354487bc8/scratchpad
mkdir -p "$SC/s247" && chmod 700 "$SC/s247"
# la clé est lue depuis le fichier de secrets, jamais affichée
KEY=$(grep -m1 -i 'dokploy.*api' ~/.workplace-secrets/s246-comptes.txt | awk '{print $NF}')
curl -s -H "x-api-key: $KEY" http://100.124.176.122:3000/api/settings.getOpenApiDocument -o "$SC/s247/openapi.json" \
  || echo "session requise : se connecter à Dokploy puis réessayer avec le cookie"
python3 -c "import json,sys;d=json.load(open('$SC/s247/openapi.json'));print(len(d['paths']))"
```
Expected : `659` (si la clé machine est refusée, l'API demande une session : utiliser le cookie de connexion du compte owner, comme en S246 T4).

- [ ] **Step 2 : lister les routes utiles aux 6 questions**

```bash
python3 - <<'EOF'
import json,os
d=json.load(open(os.environ.get("SC","")+"/s247/openapi.json")) if os.environ.get("SC") else json.load(open("openapi.json"))
for p in sorted(d["paths"]):
    if any(k in p for k in ("docker.","destination.","volumeBackups","mounts.","domain.","application.create","application.update","project.duplicate","project.all")):
        print(p)
EOF
```

- [ ] **Step 3 : répondre aux 6 questions dans `docs/s247/spike-dokploy.md`, chacune avec la commande, la réponse réelle (sans secret) et un verdict** :

  1. **Sauvegarde d'une base** : l'app témoin n'a pas de base. Créer dans le projet `temoin` un service Postgres jetable, une `destination` S3 pointant sur SeaweedFS du HP (`http://192.168.1.89:9106`, bucket dédié `dokploy-backups`, clés propres à ce bucket — jamais celles d'Oria), puis `backup.create` + `backup.manualBackupPostgres` ; relire `backup.listBackupFilesByBackupId`. Verdict : la sauvegarde atterrit-elle dans SeaweedFS (vérifier avec un `aws s3 ls` signé depuis le HP) ?
  2. **Volumes de fichiers** : existe-t-il `volumeBackups.*` ou équivalent dans cette version ? Sinon, comment sauvegarder un volume applicatif (alternative : montage lu par une tâche Ansible sur la VM 100) ?
  3. **Restauration jetable** : restaurer cette sauvegarde dans une instance jetable (nouveau service Postgres `jetable-<id>` dans `temoin`), comparer les comptages (lignes par table). Mesurer le temps.
  4. **Bleu/vert** : peut-on cloner une application (`application.create` + `saveGitProvider`/`saveBuildType` + copie d'environnement, ou `project.duplicate`) et **changer le domaine** (`domain.create|update`) sans toucher la bleue ? Prouver sur l'app témoin : verte déployée sur un domaine de test, bleue intacte, bascule, retour.
  5. **État réel du service** (pour durcir `/etat`) : quelle route renvoie l'image/tag réellement en service (`docker.getContainersByAppNameMatch`, `docker.getServiceContainersByAppName`… ou autre) avec la clé **limitée** du projet `temoin` ? Réponse attendue : nom de route, forme du JSON, champ « image ». Si aucune route n'est accessible à la clé limitée : le dire et proposer l'alternative (repère mémorisé conservé + contrôle croisé par le déploiement `done` le plus récent).
  6. **Sauvegarde de Forgejo** (dépôts + base + registre d'images) : `forgejo dump` dans le conteneur de la VM 100 vers un fichier, taille mesurée ; chemin d'envoi vers SeaweedFS (`aws s3 cp` ou `rclone`) depuis la VM 100 vers le LAN du HP — la garde `DOCKER-USER` et ufw laissent-elles sortir ? Mesurer l'espace disque restant de la VM 100 (60 Go partagés avec les images de rollback).

- [ ] **Step 4 : nettoyer ce que le spike a créé** (service Postgres jetable, destination, domaines de test, bucket), vérifier avec `project.all` que seul l'état d'avant subsiste, puis committer le document.

```bash
git add docs/s247/spike-dokploy.md docs/s247/contrats
git commit -m "docs(s247): spike Dokploy — sauvegardes, bleu/vert, état réel du service, sauvegarde Forgejo"
```

---

### Task 2 : Registre de preuves et prérequis à la création (Cœur)

**Files:**
- Modify: `core/approbations.py` (`creer` ~l.226 ; `exiger` ~l.604 ; nouvelles fonctions juste avant la section « Exécution », après `satisfaire_prerequis`)
- Test: `core/test_approbations_preuves.py` (nouveau)

**Interfaces:**
- Produces : `approbations.PREUVE_TTL_MAX_S: int` ; `approbations.enregistrer_preuve(nom: str, cles: list[str], preuve_id: str, expire_a: float, *, utilisateur: str | None = None, maintenant: float | None = None) -> list[str]` (ids des demandes **nouvellement** libérées, c.-à-d. dont TOUS les prérequis sont désormais réunis) ; `approbations.preuve_valide(nom: str, cle: str, utilisateur: str, maintenant: float) -> bool` ; `exiger(..., maintenant=None, *, prerequis: tuple[str, ...] = ())`.
- Consumes : `_conn`, `_utilisateur`, `satisfaire_prerequis(id_, nom) -> bool`, `creer(..., prerequis=...)` existants.

- [ ] **Step 1 : écrire les tests qui échouent** (`core/test_approbations_preuves.py`)

```python
"""Prérequis « preuve de sauvegarde » (S247) : la preuve est liée à l'utilisateur ET à l'app."""
import os
import sys
import tempfile

os.environ["ASSISTANT_CONFIG_PATH"] = os.path.join(tempfile.mkdtemp(), "cfg.json")
os.environ.setdefault("GATEWAY_KEY", "sk-test-local")
sys.path.insert(0, os.path.dirname(__file__))

import pytest  # noqa: E402

import approbations  # noqa: E402

T0 = 1_000_000.0


@pytest.fixture(autouse=True)
def _db(tmp_path, monkeypatch):
    monkeypatch.setattr(approbations, "DB", str(tmp_path / "a.db"))
    approbations.init_db()


def _demande(app="calendrier", user="perso", prerequis=("preuve_sauvegarde",)):
    return approbations.creer("livraison_reset_app", {"app": app}, "Remise à zéro", "donnees",
                              prerequis=prerequis, maintenant=T0, utilisateur=user)


def test_sans_preuve_le_prerequis_est_non_satisfait():
    assert _demande()["prerequis"] == {"preuve_sauvegarde": False}


def test_preuve_deja_valide_satisfait_des_la_creation():
    approbations.enregistrer_preuve("preuve_sauvegarde", ["calendrier"], "P1", T0 + 3600,
                                    utilisateur="perso", maintenant=T0)
    assert _demande()["prerequis"] == {"preuve_sauvegarde": True}


def test_preuve_d_une_autre_app_ne_compte_pas():
    approbations.enregistrer_preuve("preuve_sauvegarde", ["autre"], "P1", T0 + 3600,
                                    utilisateur="perso", maintenant=T0)
    assert _demande()["prerequis"] == {"preuve_sauvegarde": False}


def test_preuve_d_un_autre_utilisateur_ne_compte_pas():
    approbations.enregistrer_preuve("preuve_sauvegarde", ["calendrier"], "P1", T0 + 3600,
                                    utilisateur="marie", maintenant=T0)
    assert _demande(user="perso")["prerequis"] == {"preuve_sauvegarde": False}


def test_preuve_expiree_ne_compte_pas():
    approbations.enregistrer_preuve("preuve_sauvegarde", ["calendrier"], "P1", T0 + 10,
                                    utilisateur="perso", maintenant=T0)
    assert approbations.preuve_valide("preuve_sauvegarde", "calendrier", "perso", T0 + 11) is False


def test_preuve_deja_expiree_a_l_enregistrement_est_ignoree():
    assert approbations.enregistrer_preuve("preuve_sauvegarde", ["calendrier"], "P1", T0 - 1,
                                           utilisateur="perso", maintenant=T0) == []
    assert approbations.preuve_valide("preuve_sauvegarde", "calendrier", "perso", T0) is False


def test_echeance_plafonnee_a_24h():
    approbations.enregistrer_preuve("preuve_sauvegarde", ["calendrier"], "P1", T0 + 10 ** 9,
                                    utilisateur="perso", maintenant=T0)
    assert approbations.preuve_valide("preuve_sauvegarde", "calendrier", "perso",
                                      T0 + approbations.PREUVE_TTL_MAX_S - 1) is True
    assert approbations.preuve_valide("preuve_sauvegarde", "calendrier", "perso",
                                      T0 + approbations.PREUVE_TTL_MAX_S + 1) is False


def test_cle_insensible_a_la_casse_et_aux_espaces():
    approbations.enregistrer_preuve("preuve_sauvegarde", ["  Calendrier "], "P1", T0 + 3600,
                                    utilisateur="perso", maintenant=T0)
    assert _demande(app="CALENDRIER")["prerequis"] == {"preuve_sauvegarde": True}


def test_preuve_tardive_libere_la_demande_en_attente_et_la_renvoie():
    a = _demande()
    liberees = approbations.enregistrer_preuve("preuve_sauvegarde", ["calendrier"], "P1",
                                               T0 + 3600, utilisateur="perso", maintenant=T0 + 5)
    assert liberees == [a["id"]]
    assert approbations.lire(a["id"])["prerequis"] == {"preuve_sauvegarde": True}


def test_preuve_tardive_ne_libere_pas_la_demande_d_un_autre_utilisateur():
    a = _demande(user="marie")
    assert approbations.enregistrer_preuve("preuve_sauvegarde", ["calendrier"], "P1", T0 + 3600,
                                           utilisateur="perso", maintenant=T0 + 5) == []
    assert approbations.lire(a["id"])["prerequis"] == {"preuve_sauvegarde": False}


def test_demande_avec_deux_prerequis_n_est_liberee_que_quand_tous_le_sont():
    a = _demande(prerequis=("preuve_sauvegarde", "autre_preuve"))
    assert approbations.enregistrer_preuve("preuve_sauvegarde", ["calendrier"], "P1", T0 + 3600,
                                           utilisateur="perso", maintenant=T0 + 5) == []
    assert approbations.lire(a["id"])["prerequis"] == {"preuve_sauvegarde": True,
                                                       "autre_preuve": False}


def test_bouton_toujours_refuse_tant_que_le_prerequis_manque():
    a = _demande()
    ok, raison = approbations.armer(a["id"], "tg:42", maintenant=T0 + 1, utilisateur="perso")
    assert (ok, raison) == (False, "prerequis")
```

Run : `cd core && rtk proxy python3 -m pytest test_approbations_preuves.py -q -p no:cacheprovider`
Expected : FAIL (`AttributeError: module 'approbations' has no attribute 'enregistrer_preuve'`).

> Si `armer` a une autre signature que `(id_, par, maintenant=, utilisateur=)`, aligner le dernier test sur `test_armer_refuse_si_prerequis_non_reunis` de `core/test_approbations.py:390` (même appel) — c'est un test de non-régression, pas une nouvelle règle.

- [ ] **Step 2 : implémenter** — dans `core/approbations.py`, après `satisfaire_prerequis` :

```python
# ── Preuves (S247 : « sauvegarde vérifiée ») ─────────────────────────────────

PREUVE_TTL_MAX_S = 24 * 3600


def _norm_cle(cle) -> str:
    return str(cle or "").strip().lower()


def _assurer_preuves(c) -> None:
    c.execute("""CREATE TABLE IF NOT EXISTS preuves (
                    nom TEXT NOT NULL, cle TEXT NOT NULL, utilisateur TEXT NOT NULL,
                    preuve_id TEXT NOT NULL, expire_a REAL NOT NULL,
                    PRIMARY KEY (nom, cle, utilisateur))""")


def preuve_valide(nom: str, cle: str, utilisateur: str, maintenant: float) -> bool:
    with _conn() as c:
        _assurer_preuves(c)
        r = c.execute("SELECT expire_a FROM preuves WHERE nom=? AND cle=? AND utilisateur=?",
                      (nom, _norm_cle(cle), utilisateur)).fetchone()
    return bool(r and r["expire_a"] > maintenant)


def enregistrer_preuve(nom: str, cles: list[str], preuve_id: str, expire_a: float, *,
                       utilisateur: str | None = None,
                       maintenant: float | None = None) -> list[str]:
    """Enregistre une preuve (par utilisateur ET par clé d'app) puis lève ce prérequis sur les
    demandes `en_attente` de CET utilisateur visant cette app. Renvoie les ids des demandes dont
    tous les prérequis sont désormais réunis (à renotifier avec boutons)."""
    now = maintenant if maintenant is not None else time.time()
    user = _utilisateur(utilisateur)
    expire_a = min(float(expire_a), now + PREUVE_TTL_MAX_S)
    cles_n = {_norm_cle(k) for k in cles if _norm_cle(k)}
    if expire_a <= now or not cles_n or not preuve_id:
        return []
    with _conn() as c:
        _assurer_preuves(c)
        for k in cles_n:
            c.execute("INSERT OR REPLACE INTO preuves (nom, cle, utilisateur, preuve_id, expire_a) "
                      "VALUES (?,?,?,?,?)", (nom, k, user, preuve_id, expire_a))
        rows = c.execute(
            "SELECT id, prerequis, args FROM approbations WHERE statut='en_attente' "
            "AND utilisateur=? AND expire_a>?", (user, now)).fetchall()
    liberees = []
    for r in rows:
        try:
            cle_demande = _norm_cle(json.loads(r["args"] or "{}").get("app"))
            prereq = json.loads(r["prerequis"] or "{}")
        except (ValueError, AttributeError):
            continue
        if cle_demande in cles_n and prereq.get(nom) is False:
            if satisfaire_prerequis(r["id"], nom):
                liberees.append(r["id"])
    return liberees
```

Dans `creer`, avant le `with _conn() as c:` :

```python
    deja = {p: preuve_valide(p, (args or {}).get("app"), user, now) for p in prerequis}
```
et remplacer `json.dumps({p: False for p in prerequis})` par `json.dumps(deja)`.

Dans `exiger`, signature `def exiger(capacite, args, niveau, resume, maintenant=None, *, prerequis: tuple[str, ...] = ())` (garder les annotations existantes) et l'appel final devient :

```python
    demande = creer(capacite, args, resume, niveau, maintenant=now, utilisateur=user,
                    prerequis=prerequis)
```

- [ ] **Step 3 : tests verts + non-régression**

Run : `cd core && rtk proxy python3 -m pytest test_approbations_preuves.py test_approbations.py test_approbations_garde.py test_approbations_routes.py test_approbations_reprise.py -q -p no:cacheprovider --junitxml=/private/tmp/claude-502/-Users-garinat-t-Desktop-Workplace/193dcfa4-1ddb-4efb-9c27-a49354487bc8/scratchpad/s247-t2.xml`
Expected : 0 échec ; relever les comptes dans le junit (ne pas se fier au résumé d'un sous-agent).

- [ ] **Step 4 : test de mutation** — neutraliser le contrôle de clé (remplacer temporairement `cle_demande in cles_n` par `True`) : `test_preuve_tardive_ne_libere_pas…` et `test_preuve_d_une_autre_app…` doivent échouer ; restaurer.

- [ ] **Step 5 : commit**

```bash
git add core/approbations.py core/test_approbations_preuves.py
git commit -m "feat(approbations): preuves par utilisateur et par app, prérequis levés à la création ou à l'arrivée de la preuve"
```

---

### Task 3 : Câblage dans la garde du Cœur (`prerequis` / `fournit_preuve`)

**Files:**
- Modify: `core/outils.py` (`est_sensible` ~l.568 ; `executer` ~l.668-690)
- Test: `core/test_approbations_preuves_garde.py` (nouveau)

**Interfaces:**
- Consumes : `approbations.exiger(..., prerequis=)`, `approbations.enregistrer_preuve(...)`, `outils._capacites_dynamiques(registre) -> dict[str, dict]`, `outils.est_erreur(str) -> bool`, `outils._notifier_approbation(registre, demande)`.
- Produces : `outils.est_prerequis(nom, registre) -> tuple[str, ...]` ; champs de manifeste `prerequis: list[str]` (capacité gardée) et `fournit_preuve: str` (capacité de vérification).

- [ ] **Step 1 : tests qui échouent** (`core/test_approbations_preuves_garde.py`)

```python
"""Câblage S247 : la preuve vient du RÉSULTAT de la brique, jamais du LLM."""
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


REGISTRE = _Reg({"livraison": {"nom": "livraison", "port": 6240, "capacites": [
    {"nom": "livraison_verifier_sauvegarde", "chemin": "/v", "methode": "POST", "action": False,
     "fournit_preuve": "preuve_sauvegarde", "description": "Vérifie.",
     "params": {"app": {"type": "string", "requis": True}}},
    {"nom": "livraison_reset_app", "chemin": "/r", "methode": "POST", "action": True,
     "sensibilite": "donnees", "prerequis": ["preuve_sauvegarde"], "description": "Reset.",
     "params": {"app": {"type": "string", "requis": True}}},
]}})


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(approbations, "DB", str(tmp_path / "a.db"))
    approbations.init_db()
    etat = {"notifs": [], "resultat_verif": None, "executes": []}

    async def faux_notifier(registre, demande):
        etat["notifs"].append((demande["id"], dict(demande["prerequis"])))

    async def faux_executer(nom, args, registre):
        if nom == "livraison_verifier_sauvegarde":
            return etat["resultat_verif"]
        etat["executes"].append(nom)
        return '{"ok": true}'

    monkeypatch.setattr(outils, "_notifier_approbation", faux_notifier)
    monkeypatch.setattr(outils, "_executer", faux_executer)
    return etat


def _run(nom, args):
    return asyncio.run(outils.executer(nom, args, REGISTRE))


def _verdict(**kw):
    d = {"ok": True, "verdict": "valide", "preuve_id": "P1", "app": "calendrier",
         "app_id": "A1", "expire_a": 4_000_000_000.0}
    d.update(kw)
    return json.dumps(d)


def test_est_prerequis_lit_le_manifeste():
    assert outils.est_prerequis("livraison_reset_app", REGISTRE) == ("preuve_sauvegarde",)
    assert outils.est_prerequis("livraison_verifier_sauvegarde", REGISTRE) == ()
    assert outils.est_prerequis("inconnu", REGISTRE) == ()


def test_demande_sans_preuve_notifie_sans_prerequis_ok(env):
    _run("livraison_reset_app", {"app": "calendrier"})
    assert env["notifs"] == [(env["notifs"][0][0], {"preuve_sauvegarde": False})]
    assert env["executes"] == []


def test_verdict_valide_libere_et_renotifie_avec_prerequis_ok(env):
    _run("livraison_reset_app", {"app": "calendrier"})
    env["resultat_verif"] = _verdict()
    _run("livraison_verifier_sauvegarde", {"app": "calendrier"})
    assert env["notifs"][-1][1] == {"preuve_sauvegarde": True}
    assert len(env["notifs"]) == 2


def test_preuve_connue_a_la_creation_notifie_deja_satisfait(env):
    env["resultat_verif"] = _verdict()
    _run("livraison_verifier_sauvegarde", {"app": "calendrier"})
    _run("livraison_reset_app", {"app": "Calendrier"})
    assert env["notifs"][-1][1] == {"preuve_sauvegarde": True}


@pytest.mark.parametrize("resultat", [
    _verdict(verdict="invalide"),
    _verdict(ok=False),
    _verdict(preuve_id=""),
    json.dumps({"ok": True, "verdict": "valide", "preuve_id": "P1"}),      # pas d'expire_a
    _verdict(expire_a="demain"),
    "Erreur : brique injoignable",
    "pas du json",
])
def test_resultat_non_probant_n_enregistre_aucune_preuve(env, resultat):
    env["resultat_verif"] = resultat
    _run("livraison_verifier_sauvegarde", {"app": "calendrier"})
    _run("livraison_reset_app", {"app": "calendrier"})
    assert env["notifs"][-1][1] == {"preuve_sauvegarde": False}


def test_le_llm_ne_peut_pas_fabriquer_une_preuve_en_argument(env):
    _run("livraison_reset_app", {"app": "calendrier", "preuve_sauvegarde": True,
                                 "verdict": "valide"})
    assert env["notifs"][-1][1] == {"preuve_sauvegarde": False}
```

Run : `cd core && rtk proxy python3 -m pytest test_approbations_preuves_garde.py -q -p no:cacheprovider`
Expected : FAIL (`AttributeError: module 'outils' has no attribute 'est_prerequis'`).

- [ ] **Step 2 : implémenter** dans `core/outils.py`

Après `est_sensible` :

```python
def est_prerequis(nom: str, registre) -> tuple[str, ...]:
    """Prérequis déclarés par le manifeste d'une capacité gardée (S247). Une valeur qui n'est ni
    une liste ni un texte est ignorée : la garde `sensibilite` reste seule en vigueur."""
    brut = (_capacites_dynamiques(registre).get(nom) or {}).get("prerequis")
    if isinstance(brut, str):
        brut = [brut]
    if not isinstance(brut, list):
        return ()
    return tuple(str(p).strip() for p in brut if str(p).strip())


async def _enregistrer_preuve_eventuelle(nom: str, args: dict, resultat: str, registre) -> None:
    """Si `nom` déclare `fournit_preuve`, lit le verdict DANS le résultat de la brique (jamais
    dans les arguments), enregistre la preuve et renotifie les demandes libérées."""
    preuve = (_capacites_dynamiques(registre).get(nom) or {}).get("fournit_preuve")
    if not preuve or est_erreur(resultat):
        return
    try:
        d = json.loads(resultat)
        if d.get("verdict") != "valide" or not d.get("preuve_id"):
            return
        expire_a = float(d["expire_a"])
    except (ValueError, KeyError, TypeError, AttributeError):
        return
    cles = [(args or {}).get("app"), d.get("app"), d.get("app_id")]
    for id_ in approbations.enregistrer_preuve(str(preuve), [k for k in cles if k],
                                               str(d["preuve_id"]), expire_a):
        try:
            await _notifier_approbation(registre, approbations.lire(id_))
        except Exception as exc:  # noqa: BLE001 — ne doit jamais altérer le résultat
            logging.getLogger(__name__).warning("renotification d'approbation en échec : %s", exc)
```

Dans `executer`, remplacer l'appel `approbations.exiger(nom, args or {}, niveau, _resume_action(nom, args or {}))` par :

```python
            id_appr, refus, nouvelle = approbations.exiger(
                nom, args or {}, niveau, _resume_action(nom, args or {}),
                prerequis=est_prerequis(nom, registre))
```
et, juste après `resultat = await _executer(nom, args, registre)` (dans le `try`, **après** le bloc `except BaseException`, donc au même niveau que `if id_appr:` qui suit) ajouter :

```python
        await _enregistrer_preuve_eventuelle(nom, args, resultat, registre)
```

- [ ] **Step 3 : tests verts + non-régression de la garde**

Run : `cd core && rtk proxy python3 -m pytest test_approbations_preuves_garde.py test_approbations_garde.py test_approbations_bout_en_bout.py test_outils.py -q -p no:cacheprovider --junitxml=/private/tmp/claude-502/-Users-garinat-t-Desktop-Workplace/193dcfa4-1ddb-4efb-9c27-a49354487bc8/scratchpad/s247-t3.xml`
Expected : 0 échec (si `test_outils.py` n'existe pas sous ce nom, lancer `ls core/test_outil*.py` et prendre ceux qui existent).

- [ ] **Step 4 : test de mutation** — supprimer l'argument `prerequis=est_prerequis(...)` de l'appel à `exiger` : `test_demande_sans_preuve_notifie_sans_prerequis_ok` doit échouer (la demande n'aurait aucun prérequis → bouton immédiat). Restaurer.

- [ ] **Step 5 : commit**

```bash
git add core/outils.py core/test_approbations_preuves_garde.py
git commit -m "feat(outils): prérequis de manifeste et capacité fournissant une preuve (bouton Approuver seulement après verdict)"
```

---

### Task 4 : Registre de preuves de la brique `livraison` (+ route de lecture)

**Files:**
- Create: `briques/livraison/preuve.py`
- Modify: `briques/livraison/main.py` (après la route `rollback_app`)
- Test: `briques/livraison/test_preuve.py` (nouveau)

**Interfaces:**
- Produces : `preuve.PREUVE_TTL_S: int` ; `preuve.noter(app_id: str, preuve_id: str, verdict: str, comptages: dict, maintenant: float | None = None) -> dict` (renvoie l'enregistrement : `{"preuve_id","verdict","comptages","cree_a","expire_a"}`) ; `preuve.lire(app_id: str) -> dict | None` ; `preuve.valide(app_id: str, maintenant: float | None = None) -> dict | None` (l'enregistrement si verdict `valide` et non expiré, sinon `None`) ; route `GET /apps/{app}/preuve` → `{"app","app_id","valide","preuve_id","verdict","expire_a","comptages"}` ; `main.exiger_preuve(app_id) -> dict` (lève `HTTPException(409)` si aucune preuve valide — utilisé par la partie 2 pour `reset_app`/`basculer`).
- Consumes : `main._resoudre(d, app_) -> dict`, `main.fournisseur()`, `main.cle_api`, `DokployErreur`.

- [ ] **Step 1 : tests qui échouent** (`briques/livraison/test_preuve.py`)

```python
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

import main
import preuve
from dokploy import Dokploy
from faux_dokploy import fabrique_transport
from test_api import _etat

c = TestClient(main.app)
T0 = 1_000_000.0


@pytest.fixture
def e(monkeypatch):
    etat = _etat()
    monkeypatch.setattr(main, "fournisseur",
                        lambda: Dokploy("http://d.test", "k", transport=fabrique_transport(etat)))
    return etat


def test_sans_preuve_rien_de_valide():
    assert preuve.lire("A1") is None
    assert preuve.valide("A1", T0) is None


def test_preuve_valide_puis_expiree():
    r = preuve.noter("A1", "P1", "valide", {"agenda.evenements": 12}, maintenant=T0)
    assert r["expire_a"] == T0 + preuve.PREUVE_TTL_S
    assert preuve.valide("A1", T0 + 1)["preuve_id"] == "P1"
    assert preuve.valide("A1", T0 + preuve.PREUVE_TTL_S + 1) is None


def test_verdict_invalide_n_est_jamais_valide():
    preuve.noter("A1", "P2", "invalide", {}, maintenant=T0)
    assert preuve.valide("A1", T0 + 1) is None
    assert preuve.lire("A1")["verdict"] == "invalide"


def test_une_preuve_invalide_plus_recente_annule_la_precedente_valide():
    preuve.noter("A1", "P1", "valide", {}, maintenant=T0)
    preuve.noter("A1", "P2", "invalide", {}, maintenant=T0 + 5)
    assert preuve.valide("A1", T0 + 6) is None


def test_preuves_isolees_par_application():
    preuve.noter("A1", "P1", "valide", {}, maintenant=T0)
    assert preuve.valide("A2", T0 + 1) is None


def test_fichier_corrompu_vaut_aucune_preuve(tmp_path, monkeypatch):
    monkeypatch.setenv("LIVRAISON_DATA", str(tmp_path / "d"))
    (tmp_path / "d").mkdir()
    (tmp_path / "d" / "preuves_sauvegarde.json").write_text("{pas du json")
    assert preuve.valide("A1", T0) is None


def test_route_preuve_absente(e):
    r = c.get("/apps/calendrier/preuve")
    assert r.status_code == 200
    assert r.json()["valide"] is False and r.json()["app_id"] == "A1"


def test_route_preuve_valide_ne_fuit_que_la_liste_blanche(e):
    preuve.noter("A1", "P1", "valide", {"t": 3})
    d = c.get("/apps/Calendrier/preuve").json()
    assert d["valide"] is True and d["preuve_id"] == "P1" and d["comptages"] == {"t": 3}
    assert set(d) == {"app", "app_id", "valide", "preuve_id", "verdict", "expire_a", "comptages"}


def test_exiger_preuve_refuse_sans_preuve():
    with pytest.raises(HTTPException) as ex:
        main.exiger_preuve("A1")
    assert ex.value.status_code == 409


def test_exiger_preuve_accepte_une_preuve_fraiche():
    preuve.noter("A1", "P1", "valide", {})
    assert main.exiger_preuve("A1")["preuve_id"] == "P1"
```

Run : `cd briques/livraison && rtk proxy python3 -m pytest test_preuve.py -q -p no:cacheprovider`
Expected : FAIL (`ModuleNotFoundError: No module named 'preuve'`).

- [ ] **Step 2 : implémenter** `briques/livraison/preuve.py`

```python
"""Registre des preuves de sauvegarde par application (S247).

Une preuve = « la dernière sauvegarde de cette app a été restaurée dans une instance jetable et
les contrôles (santé, comptages) sont passés ». Elle est la condition de toute action `donnees`
(reset, bascule). Une preuve `invalide` plus récente ANNULE une preuve valide plus ancienne
(la dernière vérification fait foi). Toute erreur disque se lit comme « aucune preuve » : on
refuse d'agir, on ne devine pas.
"""
import json
import logging
import os
import time
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

PREUVE_TTL_S = 6 * 3600


def _chemin() -> Path:
    return Path(os.getenv("LIVRAISON_DATA", "/data")) / "preuves_sauvegarde.json"


def _lire_tout() -> dict:
    try:
        d = json.loads(_chemin().read_text())
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def lire(app_id: str) -> Optional[dict]:
    r = _lire_tout().get(app_id)
    return r if isinstance(r, dict) and r.get("preuve_id") else None


def valide(app_id: str, maintenant: Optional[float] = None) -> Optional[dict]:
    now = maintenant if maintenant is not None else time.time()
    r = lire(app_id)
    if r and r.get("verdict") == "valide" and float(r.get("expire_a", 0)) > now:
        return r
    return None


def noter(app_id: str, preuve_id: str, verdict: str, comptages: dict,
          maintenant: Optional[float] = None) -> dict:
    now = maintenant if maintenant is not None else time.time()
    rec = {"preuve_id": preuve_id, "verdict": verdict, "comptages": comptages,
           "cree_a": now, "expire_a": now + PREUVE_TTL_S if verdict == "valide" else now}
    tout = _lire_tout()
    tout[app_id] = rec
    p = _chemin()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(tout))
    tmp.replace(p)
    return rec
```

(Ici `noter` laisse remonter l'`OSError` : contrairement au repère de rollback, une preuve non écrite doit faire **échouer** la vérification, pas passer sous silence.)

Dans `main.py`, ajouter l'import `import preuve  # noqa: E402` à côté de `import repere_rollback`, puis après `rollback_app` :

```python
@app.get("/apps/{app_}/preuve")
async def preuve_app(app_: str, _: str = Depends(cle_api)):
    d = fournisseur()
    try:
        a = await _resoudre(d, app_)
    except DokployErreur as e:
        raise _erreur(e)
    r = preuve.lire(a["id"]) or {}
    return {"app": a["nom"], "app_id": a["id"], "valide": preuve.valide(a["id"]) is not None,
            "preuve_id": r.get("preuve_id"), "verdict": r.get("verdict"),
            "expire_a": r.get("expire_a"), "comptages": r.get("comptages")}


def exiger_preuve(app_id: str) -> dict:
    """Défense en profondeur : même si le Cœur était contourné, une action `donnees` sans
    preuve de sauvegarde fraîche est refusée par la brique elle-même."""
    r = preuve.valide(app_id)
    if not r:
        raise HTTPException(409, "aucune preuve de sauvegarde valide pour cette application : "
                                 "lance d'abord la vérification de sauvegarde")
    return r
```

- [ ] **Step 3 : tests verts + non-régression de la brique**

Run : `cd briques/livraison && rtk proxy python3 -m pytest -q -p no:cacheprovider --junitxml=/private/tmp/claude-502/-Users-garinat-t-Desktop-Workplace/193dcfa4-1ddb-4efb-9c27-a49354487bc8/scratchpad/s247-t4.xml`
Expected : 0 échec (les tests existants de la brique + les 10 nouveaux ; relever le total dans le junit).

- [ ] **Step 4 : test de mutation** — dans `preuve.valide`, retirer la condition `verdict == "valide"` : `test_verdict_invalide_n_est_jamais_valide` et `test_une_preuve_invalide_plus_recente…` doivent échouer. Restaurer.

- [ ] **Step 5 : commit**

```bash
git add briques/livraison/preuve.py briques/livraison/main.py briques/livraison/test_preuve.py
git commit -m "feat(livraison): registre de preuves de sauvegarde et refus sans preuve fraîche"
```

---

### Task 5 : Clôture de la partie 1 (docs + mémoire)

**Files:**
- Modify: `docs/sprints/S247-sauvegarde-verifiee-reset-app-entiere.md` (section « Décisions (2026-11-25) » + statut)
- Modify: `docs/sprints/EPOPEE-livraison-support-assistant.md` (ligne S247)

- [ ] **Step 1 : ajouter à la fiche S247** : les trois décisions ci-dessus ; la découverte que `exiger` n'acceptait aucun prérequis (désormais `prerequis=` + `fournit_preuve`) ; le fait que `satisfaire_prerequis` n'a toujours **pas de verrou** (limite 4 de S245b) — `enregistrer_preuve` l'appelle séquentiellement, un double appel concurrent reste idempotent (même valeur écrite) mais à revérifier si on parallélise.
- [ ] **Step 2 : commit** `docs(s247): décisions utilisateur et statut partie 1`.

---

## Partie 2 (à écrire APRÈS le spike — `docs/superpowers/plans/2026-11-25-s247-partie2-*.md`)

Ces tâches dépendent des réponses de la Task 1 ; elles ne sont volontairement pas détaillées ici (aucun contrat Dokploy n'est inventé), comme la partie 2 de S246 a suivi son spike :

- **A. Sauvegarde + vérification** (`livraison_sauvegarder`, `livraison_verifier_sauvegarde` avec `fournit_preuve: "preuve_sauvegarde"`, résultat `{ok, verdict, preuve_id, app, app_id, expire_a, comptages}` ; appelle `preuve.noter`) vers la destination S3 SeaweedFS ; faux serveur étendu + test de sabotage (sauvegarde corrompue → verdict `invalide`).
- **B. `livraison_reset_app`** (`sensibilite: donnees`, `prerequis: ["preuve_sauvegarde"]`, `exiger_preuve` en tête de route) : bleu/vert selon le verdict du spike (clone + domaine) ; rétention de la bleue (question ouverte n°1 de la fiche : proposer 7 jours) ; `livraison_basculer`, `livraison_retour_arriere`.
- **C. Durcissement de `/etat`** (décision n°2) : lire l'image réellement en service via la route trouvée au spike (Q5) ; croiser avec le repère ; `via_rollback` déduit du réel.
- **D. Sauvegarde de Forgejo** vers SeaweedFS (rôle Ansible `forgejo_backup` + timer sur la VM 100, rétention, vérification de restauration d'un dépôt) ; **nettoyage des images de rollback** du registre Forgejo (garder les N dernières versions par app).
- **E. Preuve LIVE groupée (SLIVE)** sur Calendrier Familial : cas nominal + sabotage (verte corrompue → bascule refusée, bleue intacte) ; premier rollback réel constatant `via_rollback`.

---

## Self-Review

- **Couverture de la fiche S247** : mise de côté / vérification / verte / bascule → partie 2 A-B (spike Q1-Q4 d'abord) ; lien S245 « bouton seulement après verdict » → Tasks 2-3 (+ défense en profondeur Task 4) ; diagnostic préalable, mode attente, capacités `livraison_*`, rétention, nettoyage registre, sauvegarde Forgejo → partie 2 (listées) ; miroir GitHub → exclu par décision. Pas de tâche sans fondement : la partie 2 est volontairement différée au spike.
- **Placeholders** : aucun « TBD » ; les seules inconnues sont déclarées comme questions de spike (Task 1) et non codées.
- **Cohérence des types** : `enregistrer_preuve(nom, cles: list[str], preuve_id, expire_a, *, utilisateur, maintenant) -> list[str]` (Task 2) est appelé tel quel en Task 3 ; `preuve.noter/lire/valide` (Task 4) cohérents avec `exiger_preuve` ; champs du verdict (`verdict`, `preuve_id`, `app`, `app_id`, `expire_a`) identiques entre `_enregistrer_preuve_eventuelle` (Task 3), `_verdict()` des tests et le contrat de la partie 2-A.
- **Point à vérifier à l'exécution** : la signature exacte d'`armer` dans le dernier test de la Task 2 (renvoi explicite vers `test_approbations.py:390`).
