# S245b — Approbation liée à l'utilisateur, reprise après approbation, `CONNEXION_API_KEYS` : plan d'implémentation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal :** Fermer les limites 1, 2 et 3 d'S245 avant la première capacité sensible d'S246 : (1) une approbation n'est visible, approuvable et consommable que par l'utilisateur qui l'a demandée ; (2) la brique `connexion` a sa propre variable `CONNEXION_API_KEYS` ; (3) approuver **exécute** l'action (le Cœur reprend lui-même), sans dépendre du LLM.

**Architecture :** Le Cœur (`core/approbations.py`, SQLite) stocke `utilisateur`, `org_id` et les `args` exacts de la demande ; chaque lecture/consommation/décision filtre sur l'utilisateur. La brique `connexion` n'envoie la demande qu'aux approbateurs *liés à cet utilisateur* et transmet l'utilisateur de l'approbateur au Cœur, qui re-vérifie. À l'approbation, une tâche de fond `approbations_reprise.reprendre` rejoue `outils.executer` dans le contexte du demandeur ; la garde consomme *cette* approbation précise (ContextVar `REPRISE`), jamais une autre, et ne crée jamais de nouvelle demande.

**Tech Stack :** Python 3 / FastAPI / SQLite stdlib / httpx / pytest. Tests : `cd core && python3 -m pytest test_approbations*.py -q` ; `cd briques/connexion && python3 -m pytest -q` ; `make test-core` en fin de plan.

## Global Constraints

Décisions tranchées avec l'utilisateur le 2026-11-25 (S245b, Q1/Q2/Q3) — à respecter à la lettre :

- **Q1 = A** : seul le compte Telegram du demandeur peut recevoir et approuver sa demande. Chaque approbateur ne reçoit que les demandes de *son* utilisateur ; une demande sans utilisateur identifiable retombe sur `perso` (`contexte_tenant.UTILISATEUR_DEFAUT`).
- **Q2 = A** : `CONNEXION_API_KEYS` lue en priorité par `briques/connexion/main.py` ; repli sur `API_KEYS` **seulement si la variable est absente** de l'environnement. Variable présente mais vide = mode ouvert, comme aujourd'hui. Pas de fail-closed supplémentaire.
- **Q3 = A** : le Cœur exécute lui-même à l'approbation (bouton, ou code à 6 chiffres pour `destructif`), dans le contexte du demandeur. Les arguments sont persistés tant que la demande n'est pas terminée, puis purgés.
- **N'activer AUCUNE clé sur le HP** (`APPROBATIONS_CLE`, `CONNEXION_KEY`, `CONNEXION_API_KEYS`, `API_KEYS`, `TELEGRAM_WEBHOOK_SECRET`) : l'activation reste groupée avec la 1re capacité sensible d'S246. Ce plan ne touche ni le HP ni le `.env`.
- **Ne PAS remplir `API_KEYS`** (≈20 briques la lisent via `env_file`).
- Les capacités sans `sensibilite` gardent le gate conversationnel `accord_action.py`, inchangé.
- Le **code à 6 chiffres** d'un destructif ne quitte jamais l'app (jamais dans une réponse à clé, jamais sur Telegram) ; les **`args` ne sont jamais renvoyés** par une route ni envoyés au canal.
- Machine à états inchangée : `en_attente → approuvee | refusee | expiree`, `approuvee → executee | expiree`, `executee → echec`.
- Journal append-only inchangé. Code, commentaires, messages en **français**.
- Commits : fin de message = `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>` puis `Claude-Session: https://claude.ai/code/session_01HhWGGaLbPBnwM9KTfyyUQp`.

## Écarts et limites assumés (à reporter dans l'ADR, Task 8)

1. **Args en clair en base** jusqu'à l'état final : l'exécution exige les vrais arguments, donc ils ne peuvent pas être expurgés (le résumé affiché, lui, reste expurgé). Mitigation : purge (`args = NULL`) à toute sortie de `en_attente`/`approuvee` vers un état final, jamais exposés par une route.
2. **Pas de JWT à la reprise** : `user_token` n'est pas persisté. Une capacité qui exige le token Forge de l'utilisateur échouera à la reprise (état `echec`, message Telegram ⚠️). Le contexte repris porte `utilisateur` + `org_id`.
3. **Résultat non réinjecté dans le fil de conversation** : le résultat de la reprise est visible dans le message Telegram édité (✅/⚠️) et dans `approbations.resultat`. Le réinjecter dans le journal de conversation est reporté (hors périmètre).
4. **Au plus une exécution** : `consommer` marque `executee` *avant* d'exécuter. Un crash du Cœur pendant l'exécution laisse la demande `executee` sans résultat, sans rejeu automatique (sens sûr).
5. Limite 3 d'S245 (écran affichant le code destructif) et 4 (`satisfaire_prerequis` sans verrou, S247) : non traitées ici.

---

## File Structure

| Fichier | Responsabilité | Action |
|---|---|---|
| `core/approbations.py` | Persistance, machine à états, garde. Ajoute `utilisateur`/`org_id`/`args`, filtres par utilisateur, `REPRISE`, `consommer_id`, `args_de`, `a_reprendre` | Modifier |
| `core/approbations_reprise.py` | Exécution d'une approbation `approuvee` par le Cœur, dans le contexte du demandeur | Créer |
| `core/routers/approbations.py` | Routes : `utilisateur` obligatoire dans les corps, déclenchement de la reprise, liste filtrée, reprise des `approuvee` orphelines | Modifier |
| `core/approbations_canal.py` | Ajoute `utilisateur` à la charge de notification | Modifier |
| `core/outils.py` | Aucun changement de logique (le contexte tenant fournit l'utilisateur) ; test de câblage seulement | Test |
| `briques/connexion/correspondance.py` | `utilisateur_de`, `approbateurs_de` | Modifier |
| `briques/connexion/client_assistant.py` | Transmet `utilisateur` aux 3 appels d'approbation | Modifier |
| `briques/connexion/pont.py` | Résout l'utilisateur de l'approbateur, l'envoie au Cœur | Modifier |
| `briques/connexion/main.py` | `NotifApprobation.utilisateur`, filtre des destinataires, `CONNEXION_API_KEYS` | Modifier |
| `.env.example`, `briques/connexion/docker-compose.yml`, `briques/connexion/README.md` | Documentent `CONNEXION_API_KEYS` | Modifier |
| `core/test_approbations_utilisateur.py` | Tests du filtrage par utilisateur | Créer |
| `core/test_approbations_reprise.py` | Tests de la reprise | Créer |
| `docs/decisions/2026-11-25-approbation-telegram.md`, `docs/sprints/S245-*.md`, `S246-*.md`, `EPOPEE-*.md` | Documentation | Modifier |

---

### Task 0 : Branche de travail

**Files:** aucun.

- [ ] **Step 1 : Vérifier l'état et créer la branche**

```bash
cd /Users/garinat_t/Desktop/Workplace
git status --short | head
git checkout -b s245b-approbation-liee-utilisateur
```
Expected : arbre propre (aucune sortie du `status`), `Switched to a new branch 's245b-approbation-liee-utilisateur'`.

- [ ] **Step 2 : Mesurer la base de référence des tests**

```bash
cd core && python3 -m pytest test_approbations.py test_approbations_canal.py test_approbations_garde.py test_approbations_routes.py -q 2>&1 | tail -3
cd ../briques/connexion && python3 -m pytest -q 2>&1 | tail -3
```
Expected : tout vert (Cœur : les 4 fichiers ; connexion : 196 passed). Noter les chiffres ; ne pas se fier à un comptage de sous-agent.

---

### Task 1 : Cœur — `utilisateur`, `org_id`, `args` persistés ; filtres par utilisateur

**Files:**
- Modify: `core/approbations.py` (import, `init_db`, `_vue`, `_transition`, `creer`, `approuver`, `refuser`, `armer_saisie_code`, `valider_code_saisi`, `consommer`, `en_attente`, `_derniere`, `exiger`)
- Create: `core/test_approbations_utilisateur.py`
- Modify (appels existants) : `core/test_approbations.py`, `core/test_approbations_routes.py` (voir Step 6)

**Interfaces:**
- Produces :
  - `creer(capacite, args, resume, sensibilite, origine=None, prerequis=(), maintenant=None, *, utilisateur=None, org_id=None) -> dict` — `utilisateur`/`org_id` par défaut lus dans `contexte_tenant.contexte_actuel()`.
  - `approuver(id_, par, canal, maintenant=None, *, utilisateur: str) -> tuple[bool, str]` (idem `refuser`, `armer_saisie_code(id_, par, maintenant=None, *, utilisateur)`, `valider_code_saisi(par, code, maintenant=None, *, utilisateur)`). Demande d'un autre utilisateur ⇒ `(False, "introuvable")` (pas d'oracle) + événement journal `refus_autre_utilisateur`.
  - `consommer(capacite, args, niveau=None, maintenant=None, *, utilisateur=None) -> str | None`.
  - `en_attente(utilisateur: str | None = None) -> list[dict]` (`None` = toutes, usage interne).
  - `_vue()` **n'expose jamais** la colonne `args`.
  - Colonnes : `utilisateur TEXT NOT NULL DEFAULT 'perso'`, `org_id TEXT`, `args TEXT`.

- [ ] **Step 1 : Écrire les tests qui échouent**

Créer `core/test_approbations_utilisateur.py` :

```python
"""S245b — l'approbation est liée à l'utilisateur qui l'a demandée (limite n°1 d'S245)."""
import os
import sqlite3
import sys

import pytest

sys.path.insert(0, os.path.dirname(__file__))

import approbations  # noqa: E402
import contexte_tenant  # noqa: E402

T0 = 1_000_000.0


@pytest.fixture(autouse=True)
def base_isolee(tmp_path, monkeypatch):
    monkeypatch.setattr(approbations, "DB", str(tmp_path / "a.db"))
    approbations.init_db()


def _demande(utilisateur, sens="reversible", args=None):
    return approbations.creer("app_redemarrer", args or {"app": "crm"}, "Redémarrer crm", sens,
                              origine="conversation", maintenant=T0, utilisateur=utilisateur)


def test_utilisateur_par_defaut_vient_du_contexte_tenant():
    jetons = contexte_tenant.definir_contexte(utilisateur="carol", org_id="org-9")
    try:
        d = approbations.creer("app_redemarrer", {"app": "crm"}, "r", "reversible",
                               maintenant=T0)
    finally:
        contexte_tenant.reinitialiser(jetons)
    assert d["utilisateur"] == "carol" and d["org_id"] == "org-9"


def test_sans_contexte_l_utilisateur_est_perso():
    d = approbations.creer("app_redemarrer", {"app": "crm"}, "r", "reversible", maintenant=T0)
    assert d["utilisateur"] == "perso"


def test_args_jamais_exposes_par_la_vue():
    d = _demande("alice", args={"app": "crm", "token": "SECRET"})
    assert "args" not in d
    assert all("args" not in x for x in approbations.en_attente())
    assert "SECRET" not in str(approbations.lire(d["id"]))


def test_deux_utilisateurs_ont_chacun_leur_demande_pour_la_meme_action():
    a, b = _demande("alice"), _demande("bob")
    assert a["id"] != b["id"]


def test_meme_utilisateur_meme_action_ne_double_pas():
    assert _demande("alice")["id"] == _demande("alice")["id"]


def test_un_autre_utilisateur_ne_peut_pas_approuver():
    d = _demande("alice")
    ok, raison = approbations.approuver(d["id"], "tg:2", "telegram", T0 + 1, utilisateur="bob")
    assert (ok, raison) == (False, "introuvable")
    assert approbations.lire(d["id"])["statut"] == "en_attente"
    assert "refus_autre_utilisateur" in [j["evenement"] for j in approbations.journal(d["id"])]


def test_un_autre_utilisateur_ne_peut_pas_refuser():
    d = _demande("alice")
    assert approbations.refuser(d["id"], "tg:2", "telegram", T0 + 1,
                                utilisateur="bob") == (False, "introuvable")
    assert approbations.lire(d["id"])["statut"] == "en_attente"


def test_le_demandeur_approuve():
    d = _demande("alice")
    assert approbations.approuver(d["id"], "tg:1", "telegram", T0 + 1,
                                  utilisateur="alice") == (True, "ok")


def test_bob_ne_consomme_pas_l_approbation_d_alice():
    d = _demande("alice")
    approbations.approuver(d["id"], "tg:1", "telegram", T0 + 1, utilisateur="alice")
    assert approbations.consommer("app_redemarrer", {"app": "crm"}, "reversible", T0 + 2,
                                  utilisateur="bob") is None
    assert approbations.consommer("app_redemarrer", {"app": "crm"}, "reversible", T0 + 2,
                                  utilisateur="alice") == d["id"]


def test_exiger_isole_les_utilisateurs():
    """Alice a une approbation valide : Bob, lui, déclenche SA propre demande."""
    d = _demande("alice")
    approbations.approuver(d["id"], "tg:1", "telegram", T0 + 1, utilisateur="alice")
    jetons = contexte_tenant.definir_contexte(utilisateur="bob")
    try:
        id_, refus, nouvelle = approbations.exiger("app_redemarrer", {"app": "crm"},
                                                   "reversible", "r", maintenant=T0 + 2)
    finally:
        contexte_tenant.reinitialiser(jetons)
    assert id_ is None and nouvelle is not None and nouvelle["utilisateur"] == "bob"
    assert approbations.lire(d["id"])["statut"] == "approuvee"      # celle d'Alice intacte


def test_en_attente_filtre_par_utilisateur():
    a, b = _demande("alice"), _demande("bob")
    assert [x["id"] for x in approbations.en_attente(utilisateur="alice")] == [a["id"]]
    assert {x["id"] for x in approbations.en_attente()} == {a["id"], b["id"]}


def test_code_destructif_autre_utilisateur_ne_peut_pas_armer():
    d = _demande("alice", sens="destructif")
    assert approbations.armer_saisie_code(d["id"], "tg:2", T0 + 1,
                                          utilisateur="bob") == (False, "introuvable")


def test_valider_code_autre_utilisateur_est_ignore():
    d = _demande("alice", sens="destructif")
    approbations.armer_saisie_code(d["id"], "tg:1", T0 + 1, utilisateur="alice")
    code = approbations.lire(d["id"])["code"]
    # Même `par`, mais présenté comme un autre utilisateur : traité comme « pas de saisie ».
    assert approbations.valider_code_saisi("tg:1", code, T0 + 2, utilisateur="bob") is None
    assert approbations.lire(d["id"])["statut"] == "en_attente"


def test_migration_d_une_base_s245_existante(tmp_path, monkeypatch):
    """Une base déjà déployée (sans les nouvelles colonnes) est migrée sans perte."""
    chemin = str(tmp_path / "ancienne.db")
    c = sqlite3.connect(chemin)
    c.execute("""CREATE TABLE approbations (
        id TEXT PRIMARY KEY, capacite TEXT NOT NULL, empreinte TEXT NOT NULL,
        resume TEXT NOT NULL, sensibilite TEXT NOT NULL, origine TEXT NOT NULL,
        statut TEXT NOT NULL, cree_a REAL NOT NULL, expire_a REAL NOT NULL, decide_a REAL,
        decide_par TEXT, canal TEXT, resultat TEXT, prerequis TEXT NOT NULL DEFAULT '{}',
        code TEXT, essais INTEGER NOT NULL DEFAULT 0, nb_relances INTEGER NOT NULL DEFAULT 0,
        relance_a REAL, messages TEXT NOT NULL DEFAULT '[]')""")
    c.execute("INSERT INTO approbations (id, capacite, empreinte, resume, sensibilite, origine, "
              "statut, cree_a, expire_a) VALUES ('a','cap','e','r','reversible','chat',"
              "'en_attente',1,2)")
    c.commit()
    c.close()
    monkeypatch.setattr(approbations, "DB", chemin)
    approbations.init_db()
    approbations.init_db()                      # idempotent
    ligne = approbations.lire("a")
    assert ligne["utilisateur"] == "perso" and "args" not in ligne
```

- [ ] **Step 2 : Lancer, constater l'échec**

Run : `cd core && python3 -m pytest test_approbations_utilisateur.py -q 2>&1 | tail -8`
Expected : FAIL (`TypeError: creer() got an unexpected keyword argument 'utilisateur'`, etc.).

- [ ] **Step 3 : Implémenter dans `core/approbations.py`**

3a. Imports (après `import accord_action`) :

```python
import contexte_tenant
```

3b. Après `avec_origine`, ajouter :

```python
def _utilisateur(explicite: str | None) -> str:
    """Utilisateur de la demande : l'explicite, sinon celui du tour courant (contexte tenant)."""
    return explicite or contexte_tenant.contexte_actuel().utilisateur
```

3c. Dans `init_db`, **à la fin du `with _conn() as c:`** (après la création de `saisie_code`), ajouter la migration :

```python
        # S245b : colonnes ajoutées à une base S245 déjà déployée (ALTER idempotent).
        existantes = {r["name"] for r in c.execute("PRAGMA table_info(approbations)")}
        for nom, ddl in (("utilisateur", "TEXT NOT NULL DEFAULT 'perso'"),
                         ("org_id", "TEXT"), ("args", "TEXT")):
            if nom not in existantes:
                c.execute(f"ALTER TABLE approbations ADD COLUMN {nom} {ddl}")
        c.execute("CREATE INDEX IF NOT EXISTS idx_appr_user ON approbations(utilisateur, statut)")
```

3d. `_vue` ne doit jamais exposer `args` :

```python
def _vue(row) -> dict:
    d = dict(row)
    d.pop("args", None)          # S245b : arguments réels jamais exposés (cf. `args_de`)
    d["prerequis"] = json.loads(d.get("prerequis") or "{}")
    d["messages"] = json.loads(d.get("messages") or "[]")
    return d
```

3e. `creer` — nouvelle signature et corps (remplacer la fonction entière) :

```python
def creer(capacite: str, args: dict, resume: str, sensibilite: str, origine: str | None = None,
          prerequis: tuple[str, ...] = (), maintenant: float | None = None, *,
          utilisateur: str | None = None, org_id: str | None = None) -> dict:
    """Crée une demande `en_attente`, ou renvoie celle déjà ouverte pour la même action ET le
    même utilisateur. Les `args` exacts sont conservés pour la reprise (purgés à l'état final)."""
    if sensibilite not in NIVEAUX_SENSIBLES:
        raise ValueError(f"sensibilité non approuvable : {sensibilite!r}")
    now = maintenant if maintenant is not None else time.time()
    emp = accord_action.empreinte(capacite, args)
    user = _utilisateur(utilisateur)
    org = org_id or contexte_tenant.contexte_actuel().org_id
    with _conn() as c:
        ex = c.execute(
            "SELECT * FROM approbations WHERE capacite=? AND empreinte=? AND sensibilite=? "
            "AND utilisateur=? AND statut IN ('en_attente','approuvee') AND expire_a>? "
            "ORDER BY cree_a DESC LIMIT 1", (capacite, emp, sensibilite, user, now)).fetchone()
        if ex:
            return _vue(ex)
        id_ = secrets.token_hex(16)
        code = f"{secrets.randbelow(10 ** 6):06d}" if sensibilite == "destructif" else None
        c.execute(
            "INSERT INTO approbations (id, capacite, empreinte, resume, sensibilite, origine, "
            "statut, cree_a, expire_a, prerequis, code, utilisateur, org_id, args) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (id_, capacite, emp, resume, sensibilite, origine or ORIGINE.get(), "en_attente",
             now, now + ttl_secondes(sensibilite),
             json.dumps({p: False for p in prerequis}), code, user, org,
             json.dumps(args or {}, sort_keys=True, default=str)))
        _journaliser(c, id_, "creee",
                     detail=f"{sensibilite}/{origine or ORIGINE.get()}/{user}", maintenant=now)
    return lire(id_)
```

3f. Contrôle de propriété — ajouter après `_expirer_une` :

```python
def _pas_a_lui(c, r, id_: str, par: str, canal: str, utilisateur: str, now: float) -> bool:
    """True (et journalise) si la demande appartient à un AUTRE utilisateur que `utilisateur`.
    L'appelant répond « introuvable » : on ne révèle pas l'existence d'une demande d'autrui."""
    if r["utilisateur"] == utilisateur:
        return False
    _journaliser(c, id_, "refus_autre_utilisateur", par, canal,
                 detail=f"demandeur={r['utilisateur']} approbateur={utilisateur}", maintenant=now)
    return True
```

3g. `approuver` : signature `def approuver(id_: str, par: str, canal: str, maintenant: float | None = None, *, utilisateur: str) -> tuple[bool, str]:` et, juste après `if not r: return False, "introuvable"`, ajouter :

```python
        if _pas_a_lui(c, r, id_, par, canal, utilisateur, now):
            return False, "introuvable"
```
`refuser` : même signature (`*, utilisateur: str`) et même bloc au même endroit.

`armer_saisie_code` : signature `(id_: str, par: str, maintenant: float | None = None, *, utilisateur: str)` et bloc `if _pas_a_lui(c, r, id_, par, "telegram", utilisateur, now): return False, "introuvable"` après le `if not r`.

`valider_code_saisi` : signature `(par: str, code: str, maintenant: float | None = None, *, utilisateur: str)`. Après `r = c.execute("SELECT * FROM approbations WHERE id=?", (id_,)).fetchone()` et **avant** le `if not r or r["statut"] != "en_attente"`, ajouter :

```python
        if r and r["utilisateur"] != utilisateur:
            c.execute("DELETE FROM saisie_code WHERE approbateur=?", (par,))
            _journaliser(c, id_, "refus_autre_utilisateur", par, "telegram",
                         detail=f"demandeur={r['utilisateur']} approbateur={utilisateur}",
                         maintenant=now)
            return None
```

3h. `consommer` — ajouter le filtre utilisateur (remplacer la fonction) :

```python
def consommer(capacite: str, args: dict, niveau: str | None = None,
              maintenant: float | None = None, *, utilisateur: str | None = None) -> str | None:
    """Consomme une approbation `approuvee` de même empreinte ET du même utilisateur. ATOMIQUE :
    l'UPDATE conditionnel est l'arbitre. Si `niveau` est donné, seule une approbation de CE
    niveau est consommable (un `reversible` ne débloque jamais un `destructif`)."""
    now = maintenant if maintenant is not None else time.time()
    emp = accord_action.empreinte(capacite, args)
    user = _utilisateur(utilisateur)
    filtre = "" if niveau is None else " AND sensibilite=?"
    extra = () if niveau is None else (niveau,)
    with _conn() as c:
        ids = [r["id"] for r in c.execute(
            "SELECT id FROM approbations WHERE capacite=? AND empreinte=? AND utilisateur=? "
            "AND statut='approuvee' AND expire_a>?" + filtre + " ORDER BY decide_a",
            (capacite, emp, user, now, *extra))]
        for id_ in ids:
            cur = c.execute(
                "UPDATE approbations SET statut='executee' "
                "WHERE id=? AND statut='approuvee' AND expire_a>?" + filtre,
                (id_, now, *extra))
            if cur.rowcount == 1:
                _journaliser(c, id_, "executee", maintenant=now)
                return id_
    return None
```

3i. `en_attente` :

```python
def en_attente(utilisateur: str | None = None) -> list[dict]:
    """Demandes ouvertes. `utilisateur=None` : toutes (usage interne) ; sinon seulement les siennes."""
    with _conn() as c:
        if utilisateur is None:
            rows = c.execute("SELECT * FROM approbations WHERE statut='en_attente' "
                             "ORDER BY cree_a").fetchall()
        else:
            rows = c.execute("SELECT * FROM approbations WHERE statut='en_attente' "
                             "AND utilisateur=? ORDER BY cree_a", (utilisateur,)).fetchall()
    return [_vue(r) for r in rows]
```

3j. `_derniere` et `exiger` : `_derniere(capacite, args, statuts, niveau, utilisateur)` ajoute `AND utilisateur=?` dans la requête (paramètre inséré après `niveau` dans le tuple) ; dans `exiger`, calculer `user = _utilisateur(None)` en tête, passer `utilisateur=user` à `consommer`, à `_derniere` (deux appels) et à `creer`.

- [ ] **Step 4 : Lancer les nouveaux tests**

Run : `cd core && python3 -m pytest test_approbations_utilisateur.py -q 2>&1 | tail -5`
Expected : tous PASS.

- [ ] **Step 5 : Mettre à jour les appels existants (signatures kw-only requises)**

Run : `cd core && grep -n "approuver(\|refuser(\|armer_saisie_code(\|valider_code_saisi(" test_approbations.py test_approbations_garde.py test_approbations_canal.py`
Pour chaque appel **direct à `approbations.…`** (pas les routes HTTP), ajouter `utilisateur="perso"` (la demande de test est créée sans contexte ⇒ `perso`). Les routes sont traitées en Task 2.

- [ ] **Step 6 : Lancer les tests unitaires existants**

Run : `cd core && python3 -m pytest test_approbations.py test_approbations_garde.py test_approbations_canal.py test_approbations_utilisateur.py -q 2>&1 | tail -5`
Expected : tout vert. (Les tests de routes échouent encore : normal, Task 2.)

- [ ] **Step 7 : Commit**

```bash
git add core/approbations.py core/test_approbations_utilisateur.py core/test_approbations.py core/test_approbations_garde.py core/test_approbations_canal.py
git commit -m "feat(approbations): demande liée à l'utilisateur (visible, approuvable et consommable par lui seul), args persistés non exposés

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01HhWGGaLbPBnwM9KTfyyUQp"
```

---

### Task 2 : Cœur — routes : utilisateur obligatoire, liste filtrée, charge de notification

**Files:**
- Modify: `core/routers/approbations.py`, `core/approbations_canal.py`
- Modify (tests) : `core/test_approbations_routes.py`, `core/test_approbations_canal.py`

**Interfaces:**
- Consumes : `approbations.approuver/refuser/armer_saisie_code/valider_code_saisi(..., utilisateur=)`, `approbations.en_attente(utilisateur=)` (Task 1).
- Produces : corps `Decision`, `Armer`, `Saisie` avec `utilisateur: str` obligatoire (≥ 1 caractère) ; `charge_notification()` inclut `"utilisateur"`.

- [ ] **Step 1 : Écrire les tests qui échouent**

Dans `core/test_approbations_routes.py`, ajouter en fin de fichier (réutilise les fixtures `client`, `demande`, helper `_decision`, `ENT` déjà définis ; relire les lignes 60-110 du fichier pour confirmer leurs noms) :

```python
def test_decision_exige_le_champ_utilisateur(client, demande):
    r = client.post(f"/approbations/{demande['id']}/decision", headers=ENT,
                    json={"decision": "ok", "par": "tg:42"})
    assert r.status_code == 422


def test_decision_d_un_autre_utilisateur_est_introuvable(client, demande):
    r = client.post(f"/approbations/{demande['id']}/decision", headers=ENT,
                    json={"decision": "ok", "par": "tg:42", "utilisateur": "intrus"})
    assert r.json()["ok"] is False and r.json()["raison"] == "introuvable"
    assert approbations.lire(demande["id"])["statut"] == "en_attente"


def test_decision_du_demandeur_passe(client, demande):
    r = client.post(f"/approbations/{demande['id']}/decision", headers=ENT,
                    json={"decision": "ok", "par": "tg:42",
                          "utilisateur": demande["utilisateur"]})
    assert r.json()["ok"] is True
```

Dans `core/test_approbations_canal.py`, ajouter :

```python
def test_charge_notification_porte_l_utilisateur():
    demande = {"id": "a" * 32, "resume": "r", "sensibilite": "reversible", "prerequis": {},
               "expire_a": 1.0, "utilisateur": "alice"}
    assert approbations_canal.charge_notification(demande)["utilisateur"] == "alice"
```
(Vérifier en tête de `test_approbations_canal.py` que `approbations_canal` est bien importé ; sinon ajouter `import approbations_canal`.)

- [ ] **Step 2 : Lancer, constater l'échec**

Run : `cd core && python3 -m pytest test_approbations_routes.py test_approbations_canal.py -q 2>&1 | tail -8`
Expected : FAIL (422 attendu non obtenu ; `KeyError: 'utilisateur'`) + échecs des anciens tests dont les corps n'ont pas encore `utilisateur`.

- [ ] **Step 3 : Implémenter**

`core/approbations_canal.py`, `charge_notification` :

```python
    return {"id": demande["id"], "resume": demande["resume"],
            "sensibilite": demande["sensibilite"],
            "utilisateur": demande["utilisateur"],
            "prerequis_ok": all(prerequis.values()) if prerequis else True,
            "relance": relance, "expire_a": demande["expire_a"]}
```

`core/routers/approbations.py` :

```python
from fastapi import APIRouter, Depends, Header, HTTPException, Path, Request
from pydantic import BaseModel, Field

import contexte_tenant
```
Corps :

```python
class Decision(BaseModel):
    decision: Literal["ok", "ko"]
    par: str
    utilisateur: str = Field(min_length=1)   # compte Workplace LIÉ à l'approbateur (connexion)
    canal: str = "telegram"


class Armer(BaseModel):
    par: str
    utilisateur: str = Field(min_length=1)


class Saisie(BaseModel):
    par: str
    code: str
    utilisateur: str = Field(min_length=1)
```
Routes :

```python
@router.post("/{id_}/decision", dependencies=[Depends(exiger_cle)])
async def decision(body: Decision, id_: str = Path(pattern=_ID_RE)):
    agir = approbations.approuver if body.decision == "ok" else approbations.refuser
    ok, raison = agir(id_, body.par, body.canal, utilisateur=body.utilisateur)
    lue = await _maj(id_) if raison != "introuvable" else None
    return {"ok": ok, "raison": raison, "statut": lue and lue["statut"],
            "sensibilite": lue and lue["sensibilite"]}


@router.post("/{id_}/code/armer", dependencies=[Depends(exiger_cle)])
async def armer(body: Armer, id_: str = Path(pattern=_ID_RE)):
    ok, raison = approbations.armer_saisie_code(id_, body.par, utilisateur=body.utilisateur)
    return {"ok": ok, "raison": raison}


@router.post("/code", dependencies=[Depends(exiger_cle)])
async def code(body: Saisie):
    r = approbations.valider_code_saisi(body.par, body.code, utilisateur=body.utilisateur)
    if r is None:
        return {"pris_en_charge": False}
    await _maj(r["approbation_id"])
    return {"pris_en_charge": True, **r}


@router.get("/en_attente", dependencies=[Depends(auth.exiger_session_api)])
async def en_attente(request: Request):
    """Demandes ouvertes DE L'UTILISATEUR DE LA SESSION. Le `code` d'un destructif n'est exposé
    QU'ICI (session obligatoire) : c'est le canal distinct de Telegram qui fait sa valeur."""
    utilisateur = auth.sub_session_optionnel(request) or contexte_tenant.UTILISATEUR_DEFAUT
    return {"approbations": approbations.en_attente(utilisateur=utilisateur)}
```
Mettre à jour la docstring du module : le `par` ET `utilisateur` sont vérifiés par la brique `connexion` ; le Cœur re-vérifie que `utilisateur` == demandeur.

- [ ] **Step 4 : Mettre à jour les anciens tests de routes**

Run : `cd core && grep -n '"par":' test_approbations_routes.py`
Pour chaque corps JSON posté aux routes `decision`, `code/armer`, `code`, ajouter `"utilisateur": "perso"` (le helper `_decision` : l'ajouter au dict envoyé). Tests de `GET /approbations/en_attente` : la session de test a pour `sub` celui défini dans le fichier ; si la liste revient vide, créer les demandes avec `utilisateur=<sub de la session de test>` (ou `perso` si `sub_session_optionnel` renvoie `None`).

- [ ] **Step 5 : Lancer**

Run : `cd core && python3 -m pytest test_approbations*.py -q 2>&1 | tail -5`
Expected : tout vert.

- [ ] **Step 6 : Commit**

```bash
git add core/routers/approbations.py core/approbations_canal.py core/test_approbations_routes.py core/test_approbations_canal.py
git commit -m "feat(approbations): routes liées à l'utilisateur (corps obligatoire, liste filtrée par session)

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01HhWGGaLbPBnwM9KTfyyUQp"
```

---

### Task 3 : Brique `connexion` — destinataires liés à l'utilisateur, identité transmise au Cœur

**Files:**
- Modify: `briques/connexion/correspondance.py`, `client_assistant.py`, `pont.py`, `main.py`
- Modify (tests) : `briques/connexion/test_correspondance.py`, `test_pont.py`, `test_main.py`, `test_client_assistant.py`

**Interfaces:**
- Produces :
  - `correspondance.utilisateur_de(reseau, id_externe) -> str | None` — utilisateur d'une entrée **liée** (`statut == "lie"`), sinon `None`.
  - `correspondance.approbateurs_de(reseau, utilisateur) -> list[str]` — approbateurs (mêmes conditions que `approbateurs`) dont l'utilisateur lié est `utilisateur`.
  - `client_assistant.decider_approbation(id_, decision, par, utilisateur)`, `armer_code(id_, par, utilisateur)`, `soumettre_code(par, code, utilisateur)`.
  - `NotifApprobation.utilisateur: str` (obligatoire).

- [ ] **Step 1 : Écrire les tests qui échouent**

`briques/connexion/test_correspondance.py` — ajouter (relire les premières lignes du fichier pour l'alias d'import du module, ex. `K`/`correspondance`, et utiliser le même) :

```python
def test_utilisateur_de_et_approbateurs_de():
    K.lier("faux", "u-a1", "alice")
    K.definir_approbateur("faux", "u-a1", True)
    K.lier("faux", "u-b1", "bob")
    K.definir_approbateur("faux", "u-b1", True)
    K.lier("faux", "u-a2", "alice")                       # lié, PAS approbateur
    assert K.utilisateur_de("faux", "u-a1") == "alice"
    assert K.utilisateur_de("faux", "inconnu") is None
    assert K.approbateurs_de("faux", "alice") == ["u-a1"]
    assert K.approbateurs_de("faux", "bob") == ["u-b1"]
    assert K.approbateurs_de("faux", "personne") == []


def test_utilisateur_de_ignore_une_entree_non_liee():
    K.resoudre("faux", "u-attente", "X")                  # statut en_attente
    assert K.utilisateur_de("faux", "u-attente") is None
```

`briques/connexion/test_main.py` — ajouter (le helper `_notif` reçoit `"utilisateur": "u-ok@wp"` par défaut dans son dict, voir Step 3) :

```python
def test_notifier_ne_cible_que_les_approbateurs_du_demandeur(tg):
    K.lier("telegram", "na", "alice")
    K.definir_approbateur("telegram", "na", True)
    K.lier("telegram", "nb", "bob")
    K.definir_approbateur("telegram", "nb", True)
    r = client.post("/approbation/notifier", json=_notif(utilisateur="alice"), headers=_H)
    assert [m["chat_id"] for m in r.json()["messages"]] == ["na"]
    assert [b[0] for b in tg.boutons] == ["na"]


def test_notifier_exige_l_utilisateur(tg):
    corps = _notif()
    corps.pop("utilisateur")
    assert client.post("/approbation/notifier", json=corps, headers=_H).status_code == 422
```

`briques/connexion/test_pont.py` — ajouter après les tests de callback :

```python
def test_callback_transmet_l_utilisateur_lie_de_l_approbateur(monkeypatch):
    faux, coeur = _installer(monkeypatch, decision={"ok": True, "raison": "ok"})
    _approbateur("cb-u1")                                  # lié à « cb-u1@wp »
    _run(pont.traiter_callback("faux", _cb("cb-u1")))
    assert coeur.utilisateurs == ["cb-u1@wp"]
```

- [ ] **Step 2 : Lancer, constater l'échec**

Run : `cd briques/connexion && python3 -m pytest test_correspondance.py test_main.py test_pont.py -q 2>&1 | tail -8`
Expected : FAIL (`AttributeError: utilisateur_de`, `coeur.utilisateurs`, etc.).

- [ ] **Step 3 : Implémenter**

`correspondance.py` (après `approbateurs`) :

```python
def utilisateur_de(reseau: str, id_externe: str) -> str | None:
    """Utilisateur Workplace d'un interlocuteur **lié** (S245b), sinon None."""
    e = table().get(_cle(reseau, str(id_externe)))
    if e and e.get("statut") == "lie" and e.get("utilisateur"):
        return e["utilisateur"]
    return None


def approbateurs_de(reseau: str, utilisateur: str) -> list[str]:
    """Approbateurs d'un réseau dont le compte lié est `utilisateur` (S245b : une demande
    n'est envoyée qu'à l'approbateur de son demandeur)."""
    return [i for i in approbateurs(reseau) if utilisateur_de(reseau, i) == utilisateur]
```

`client_assistant.py` :

```python
async def decider_approbation(id_: str, decision: str, par: str, utilisateur: str) -> dict:
    return await _poster_approbation(
        f"/approbations/{id_}/decision",
        {"decision": decision, "par": par, "utilisateur": utilisateur, "canal": "telegram"})


async def armer_code(id_: str, par: str, utilisateur: str) -> dict:
    return await _poster_approbation(f"/approbations/{id_}/code/armer",
                                     {"par": par, "utilisateur": utilisateur})


async def soumettre_code(par: str, code: str, utilisateur: str) -> dict:
    return await _poster_approbation("/approbations/code",
                                     {"par": par, "code": code, "utilisateur": utilisateur})
```

`pont.py`, `traiter_callback` — étendre la condition d'ignorance et passer l'utilisateur :

```python
    utilisateur = correspondance.utilisateur_de(reseau, cb.from_id)
    if (ad is None or not m or cb.chat_type != "private" or cb.chat_id != cb.from_id
            or not correspondance.est_approbateur(reseau, cb.from_id) or not utilisateur):
        ... (inchangé : log + return ignore)
    ...
        rep = await client_assistant.decider_approbation(id_, decision, par, utilisateur)
        ...
            armement = await client_assistant.armer_code(id_, par, utilisateur)
```
`_tenter_code` — après la vérification `est_approbateur` :

```python
    utilisateur = correspondance.utilisateur_de(reseau, entrant.id_externe)
    if not utilisateur:
        return None
    ...
        r = await client_assistant.soumettre_code(f"{reseau}:{entrant.id_externe}", texte, utilisateur)
```

`main.py` :

```python
class NotifApprobation(BaseModel):
    id: str = Field(pattern=r"^[0-9a-f]{32}$")
    utilisateur: str = Field(min_length=1)    # S245b : seul l'approbateur de CE compte reçoit
    resume: str
    ...
```
et dans `approbation_notifier` : `for dest in correspondance.approbateurs_de("telegram", body.utilisateur):`.

- [ ] **Step 4 : Mettre à jour les tests existants**

- `test_main.py` : dans `_notif`, ajouter `"utilisateur": "u-ok@wp"` au dict de base ; dans la fixture/ helper `_approb(ident)` l'utilisateur lié est `f"{ident}@wp"` : les tests existants `n1`, `n2`… doivent donc passer `utilisateur=f"{ident}@wp"`. Plus simple : changer `_approb` pour lier **tous** les approbateurs de test au même utilisateur `"u-ok@wp"` (`K.lier("telegram", ident, "u-ok@wp")`) et le test `n3` (lié non approbateur) en `K.lier("telegram", "n3", "u-ok@wp")`. Le nouveau test ci-dessus lie explicitement `alice`/`bob`.
- `test_pont.py`, `_Coeur` : enregistrer l'utilisateur sans changer les tuples existants :

```python
        self.utilisateurs = []

        async def _d(id_, decision, par, utilisateur):
            self.utilisateurs.append(utilisateur)
            self.decisions.append((id_, decision, par))
            return self._decision

        async def _a(id_, par, utilisateur):
            self.armements.append((id_, par))
            return self._armer

        async def _c(par, code, utilisateur):
            self.codes.append((par, code))
            ...
```
- `test_client_assistant.py` : relire les tests d'approbation (`grep -n "approbation\|armer\|soumettre" test_client_assistant.py`) et ajouter l'argument `utilisateur` aux appels + vérifier qu'il figure dans le corps posté.

- [ ] **Step 5 : Lancer toute la suite connexion**

Run : `cd briques/connexion && python3 -m pytest -q 2>&1 | tail -5`
Expected : tout vert (≥ 196 + nouveaux tests ; relever le chiffre réel).

- [ ] **Step 6 : Commit**

```bash
git add briques/connexion
git commit -m "feat(connexion): demande envoyée au seul approbateur du demandeur, identité de l'approbateur transmise au Cœur

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01HhWGGaLbPBnwM9KTfyyUQp"
```

---

### Task 4 : `CONNEXION_API_KEYS` (variable propre à la brique connexion)

**Files:**
- Modify: `briques/connexion/main.py:43-62`, `briques/connexion/test_main.py`, `.env.example`, `briques/connexion/docker-compose.yml`, `briques/connexion/README.md`

**Interfaces:**
- Produces : `main.API_KEYS: set[str]` (nom conservé : les tests le patchent) calculé par `_lire_cles_api()` ; règle : `CONNEXION_API_KEYS` **présente dans l'environnement** (même vide) l'emporte ; absente ⇒ repli sur `API_KEYS`.

- [ ] **Step 1 : Écrire les tests qui échouent**

Dans `briques/connexion/test_main.py` ajouter :

```python
def test_cles_api_priorite_a_connexion_api_keys(monkeypatch):
    monkeypatch.setenv("CONNEXION_API_KEYS", "c1, c2")
    monkeypatch.setenv("API_KEYS", "autre")
    assert main._lire_cles_api() == {"c1", "c2"}


def test_cles_api_repli_sur_api_keys_si_variable_absente(monkeypatch):
    monkeypatch.delenv("CONNEXION_API_KEYS", raising=False)
    monkeypatch.setenv("API_KEYS", "k9")
    assert main._lire_cles_api() == {"k9"}


def test_cles_api_variable_presente_mais_vide_ne_replie_pas(monkeypatch):
    """Q2 = A : présente-vide = mode ouvert, on n'hérite PAS d'API_KEYS."""
    monkeypatch.setenv("CONNEXION_API_KEYS", "")
    monkeypatch.setenv("API_KEYS", "k9")
    assert main._lire_cles_api() == set()
```

- [ ] **Step 2 : Lancer, constater l'échec**

Run : `cd briques/connexion && python3 -m pytest test_main.py -q -k cles_api 2>&1 | tail -5`
Expected : FAIL (`AttributeError: module 'main' has no attribute '_lire_cles_api'`).

- [ ] **Step 3 : Implémenter**

`main.py`, remplacer la ligne 43 :

```python
def _lire_cles_api() -> set[str]:
    """Clés de CETTE brique. `CONNEXION_API_KEYS` (S245b) l'emporte dès qu'elle est PRÉSENTE
    dans l'environnement, même vide (vide = mode ouvert). Absente : repli sur `API_KEYS`
    (usage autonome historique). Raison d'être : `API_KEYS` est lue par ≈20 briques via
    `env_file` — la renseigner les fermerait toutes."""
    brut = os.environ.get("CONNEXION_API_KEYS")
    if brut is None:
        brut = os.getenv("API_KEYS", "")
    return {k.strip() for k in brut.split(",") if k.strip()}


API_KEYS = _lire_cles_api()
```
et dans `cle_api_fermee` : message `"Route désactivée : configure CONNEXION_API_KEYS."`. Mettre à jour la docstring de `cle_api` (« Mode ouvert si `CONNEXION_API_KEYS` (ou, à défaut, `API_KEYS`) est vide »).

- [ ] **Step 4 : Documenter**

- `.env.example` : près des lignes `APPROBATIONS_CLE` / `CONNEXION_KEY`, ajouter (commentaire + variable **vide**, aucune valeur) :
```
# S245b — clés d'accès de la brique connexion UNIQUEMENT (le Cœur et les briques qui l'appellent
# envoient CONNEXION_KEY). À poser à l'activation d'S246, avec la même valeur que CONNEXION_KEY.
# Ne PAS renseigner API_KEYS à la place : ≈20 briques la lisent et se fermeraient. Vide = ouvert.
CONNEXION_API_KEYS=
```
- `briques/connexion/docker-compose.yml` (commentaire lignes 31-33) : remplacer « et API_KEYS (doit inclure CONNEXION_KEY du Cœur) » par « et CONNEXION_API_KEYS (doit inclure CONNEXION_KEY du Cœur ; repli sur API_KEYS si absente) ». **Ne pas** ajouter de ligne `CONNEXION_API_KEYS=${…}` (piège env-shadow : l'interpolation lit le shell, pas l'env_file).
- `briques/connexion/README.md` : une ligne dans la section configuration, même contenu.

- [ ] **Step 5 : Lancer**

Run : `cd briques/connexion && python3 -m pytest -q 2>&1 | tail -3`
Expected : tout vert.

- [ ] **Step 6 : Commit**

```bash
git add briques/connexion .env.example
git commit -m "feat(connexion): variable CONNEXION_API_KEYS propre à la brique (repli sur API_KEYS si absente)

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01HhWGGaLbPBnwM9KTfyyUQp"
```

---

### Task 5 : Cœur — garde en mode reprise, purge des `args`, anti-redemande

**Files:**
- Modify: `core/approbations.py`
- Create: `core/test_approbations_reprise.py` (première moitié)
- Modify (tests) : `core/test_approbations.py`, `core/test_approbations_garde.py` (textes de messages)

**Interfaces:**
- Produces :
  - `approbations.REPRISE: ContextVar[str | None]` (défaut `None`) et `avec_reprise(id_)` (context manager).
  - `approbations.consommer_id(id_, capacite, args, niveau, utilisateur, maintenant=None) -> bool` — consomme *cette* approbation si `approuvee`, non expirée, même empreinte/utilisateur/niveau.
  - `approbations.args_de(id_) -> dict | None` — arguments réels (usage interne uniquement).
  - `approbations.a_reprendre(maintenant=None, delai_s=60) -> list[str]` — ids `approuvee`, non expirées, avec args, décidées depuis > `delai_s`.
  - `exiger(...)` : si `REPRISE` posé ⇒ consomme cet id précis, ne crée **jamais** de demande.
  - `DELAI_APRES_EXECUTION_S = 300` : une action déjà `executee` récemment ⇒ message « déjà exécutée », pas de redemande.
  - Les `args` passent à `NULL` à tout passage vers `refusee|expiree|echec|executee`.

- [ ] **Step 1 : Écrire les tests qui échouent**

Créer `core/test_approbations_reprise.py` :

```python
"""S245b — reprise après approbation : garde en mode reprise, purge des args, anti-redemande."""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(__file__))

import approbations  # noqa: E402

T0 = 1_000_000.0
ARGS = {"app": "crm", "token": "SECRET-ARG"}


@pytest.fixture(autouse=True)
def base_isolee(tmp_path, monkeypatch):
    monkeypatch.setattr(approbations, "DB", str(tmp_path / "a.db"))
    approbations.init_db()


def _approuvee(utilisateur="alice", sens="reversible", args=None):
    d = approbations.creer("app_redemarrer", args or ARGS, "r", sens, origine="coagent",
                           maintenant=T0, utilisateur=utilisateur)
    ok, _ = approbations.approuver(d["id"], "tg:1", "telegram", T0 + 1, utilisateur=utilisateur)
    assert ok
    return d["id"]


def test_args_de_rend_les_vrais_arguments():
    id_ = _approuvee()
    assert approbations.args_de(id_) == ARGS


def test_args_purges_quand_la_demande_est_refusee():
    d = approbations.creer("app_redemarrer", ARGS, "r", "reversible", maintenant=T0,
                           utilisateur="alice")
    approbations.refuser(d["id"], "tg:1", "telegram", T0 + 1, utilisateur="alice")
    assert approbations.args_de(d["id"]) is None


def test_args_purges_quand_la_demande_expire():
    d = approbations.creer("app_redemarrer", ARGS, "r", "reversible", maintenant=T0,
                           utilisateur="alice")
    approbations.expirer_perimees(maintenant=T0 + 10 ** 6)
    assert approbations.args_de(d["id"]) is None


def test_args_purges_a_la_consommation_puis_a_l_echec():
    id_ = _approuvee()
    assert approbations.consommer_id(id_, "app_redemarrer", ARGS, "reversible", "alice",
                                     T0 + 2) is True
    assert approbations.args_de(id_) is None
    approbations.conclure(id_, False, "boom")
    assert approbations.lire(id_)["statut"] == "echec"


def test_consommer_id_usage_unique():
    id_ = _approuvee()
    assert approbations.consommer_id(id_, "app_redemarrer", ARGS, "reversible", "alice", T0 + 2)
    assert not approbations.consommer_id(id_, "app_redemarrer", ARGS, "reversible", "alice",
                                         T0 + 3)


def test_consommer_id_refuse_autre_utilisateur_autre_action_ou_niveau():
    id_ = _approuvee()
    assert not approbations.consommer_id(id_, "app_redemarrer", ARGS, "reversible", "bob", T0 + 2)
    assert not approbations.consommer_id(id_, "app_reset", ARGS, "reversible", "alice", T0 + 2)
    assert not approbations.consommer_id(id_, "app_redemarrer", {"app": "autre"}, "reversible",
                                         "alice", T0 + 2)
    assert not approbations.consommer_id(id_, "app_redemarrer", ARGS, "destructif", "alice",
                                         T0 + 2)
    assert approbations.lire(id_)["statut"] == "approuvee"


def test_exiger_en_reprise_consomme_exactement_cet_id_sans_jamais_creer_de_demande():
    from contextvars import copy_context
    id_ = _approuvee()
    autre = _approuvee(args={"app": "x"})      # une 2e approbation, autre action

    def _reprise():
        with approbations.avec_reprise(id_):
            return approbations.exiger("app_redemarrer", ARGS, "reversible", "r",
                                       maintenant=T0 + 2)

    # `utilisateur` du contexte = « perso » par défaut : on fixe celui du demandeur.
    import contexte_tenant
    jetons = contexte_tenant.definir_contexte(utilisateur="alice")
    try:
        got, refus, nouvelle = copy_context().run(_reprise)
    finally:
        contexte_tenant.reinitialiser(jetons)
    assert (got, refus, nouvelle) == (id_, None, None)
    assert approbations.lire(autre)["statut"] == "approuvee"


def test_exiger_en_reprise_sans_approbation_valide_refuse_sans_creer():
    import contexte_tenant
    d = approbations.creer("app_redemarrer", ARGS, "r", "reversible", maintenant=T0,
                           utilisateur="alice")                    # encore en_attente
    jetons = contexte_tenant.definir_contexte(utilisateur="alice")
    try:
        with approbations.avec_reprise(d["id"]):
            got, refus, nouvelle = approbations.exiger("app_redemarrer", ARGS, "reversible",
                                                       "r", maintenant=T0 + 2)
    finally:
        contexte_tenant.reinitialiser(jetons)
    assert got is None and nouvelle is None and "reprise" in refus.lower()
    assert len(approbations.en_attente()) == 1                       # aucune nouvelle demande


def test_message_d_attente_n_invite_plus_a_rappeler_l_outil():
    _, refus, _ = approbations.exiger("app_redemarrer", ARGS, "reversible", "r",
                                      maintenant=T0)
    assert "AUTOMATIQUEMENT" in refus and "MÊMES arguments" not in refus


def test_action_deja_executee_recemment_n_est_pas_redemandee():
    id_ = _approuvee(utilisateur="perso")
    approbations.consommer_id(id_, "app_redemarrer", ARGS, "reversible", "perso", T0 + 2)
    approbations.conclure(id_, True, '{"ok": true}')
    got, refus, nouvelle = approbations.exiger("app_redemarrer", ARGS, "reversible", "r",
                                               maintenant=T0 + 60)
    assert got is None and nouvelle is None and "déjà été exécutée" in refus
    # Passé le délai, une nouvelle demande est de nouveau possible.
    _, _, nouvelle = approbations.exiger("app_redemarrer", ARGS, "reversible", "r",
                                         maintenant=T0 + 2 + approbations.DELAI_APRES_EXECUTION_S + 1)
    assert nouvelle is not None


def test_a_reprendre_liste_les_approuvees_orphelines():
    id_ = _approuvee()                                   # décidée à T0+1
    assert approbations.a_reprendre(maintenant=T0 + 30, delai_s=60) == []      # trop récente
    assert approbations.a_reprendre(maintenant=T0 + 100, delai_s=60) == [id_]
    approbations.consommer_id(id_, "app_redemarrer", ARGS, "reversible", "alice", T0 + 101)
    assert approbations.a_reprendre(maintenant=T0 + 200, delai_s=60) == []
```

- [ ] **Step 2 : Lancer, constater l'échec**

Run : `cd core && python3 -m pytest test_approbations_reprise.py -q 2>&1 | tail -8`
Expected : FAIL (`AttributeError: ... 'args_de'`, `avec_reprise`, …).

- [ ] **Step 3 : Implémenter dans `core/approbations.py`**

3a. Constantes et ContextVar (près de `ORIGINE`) :

```python
# Après exécution réussie, la même action (même utilisateur) n'est pas redemandée pendant ce
# délai : le LLM qui « rappelle l'outil » par habitude ne déclenche pas un 2e cycle humain.
DELAI_APRES_EXECUTION_S = 300
# Pose l'id de l'approbation en cours de REPRISE (exécution par le Cœur après approbation).
REPRISE: ContextVar[str | None] = ContextVar("approbation_reprise", default=None)


@contextmanager
def avec_reprise(id_: str):
    jeton = REPRISE.set(id_)
    try:
        yield
    finally:
        REPRISE.reset(jeton)
```

3b. Purge des args dans `_transition` (remplacer le corps) :

```python
_ETATS_FINAUX = ("refusee", "expiree", "echec")


def _transition(c, id_: str, de: str, vers: str, **colonnes) -> bool:
    """Seul point où `statut` change. Atomique : 0 ligne modifiée = quelqu'un a gagné avant.
    Toute sortie vers un état final purge les `args` réels (S245b)."""
    if vers not in _TRANSITIONS.get(de, set()):
        raise ValueError(f"transition interdite : {de} -> {vers}")
    if vers in _ETATS_FINAUX:
        colonnes = {**colonnes, "args": None}
    sets = "".join(f", {k}=?" for k in colonnes)
    cur = c.execute(f"UPDATE approbations SET statut=?{sets} WHERE id=? AND statut=?",
                    (vers, *colonnes.values(), id_, de))
    return cur.rowcount == 1
```
Dans `consommer`, l'UPDATE devient `"UPDATE approbations SET statut='executee', args=NULL WHERE id=? ..."`.

3c. Nouvelles fonctions (section « Exécution », après `consommer`) :

```python
def consommer_id(id_: str, capacite: str, args: dict, niveau: str, utilisateur: str,
                 maintenant: float | None = None) -> bool:
    """Consomme CETTE approbation (reprise après approbation) : `approuvee`, non expirée,
    même capacité/empreinte/niveau/utilisateur. ATOMIQUE, usage unique."""
    now = maintenant if maintenant is not None else time.time()
    emp = accord_action.empreinte(capacite, args)
    with _conn() as c:
        cur = c.execute(
            "UPDATE approbations SET statut='executee', args=NULL "
            "WHERE id=? AND capacite=? AND empreinte=? AND sensibilite=? AND utilisateur=? "
            "AND statut='approuvee' AND expire_a>?",
            (id_, capacite, emp, niveau, utilisateur, now))
        if cur.rowcount != 1:
            return False
        _journaliser(c, id_, "executee", detail="reprise", maintenant=now)
    return True


def args_de(id_: str) -> dict | None:
    """Arguments RÉELS d'une demande non terminée (None si purgés/absents). Usage interne :
    ne jamais renvoyer ce résultat par une route ni l'envoyer au canal."""
    with _conn() as c:
        r = c.execute("SELECT args FROM approbations WHERE id=?", (id_,)).fetchone()
    if not r or r["args"] is None:
        return None
    try:
        v = json.loads(r["args"])
    except (TypeError, ValueError):
        return None
    return v if isinstance(v, dict) else None


def a_reprendre(maintenant: float | None = None, delai_s: int = 60) -> list[str]:
    """Approuvées, non expirées, avec args, décidées depuis plus de `delai_s` : leur reprise
    n'a pas abouti (Cœur redémarré entre l'approbation et l'exécution)."""
    now = maintenant if maintenant is not None else time.time()
    with _conn() as c:
        rows = c.execute(
            "SELECT id FROM approbations WHERE statut='approuvee' AND args IS NOT NULL "
            "AND expire_a>? AND decide_a<=? ORDER BY decide_a", (now, now - delai_s)).fetchall()
    return [r["id"] for r in rows]
```

3d. `exiger` : au tout début du corps (après `now`/`user`), ajouter le mode reprise :

```python
    rid = REPRISE.get()
    if rid:
        if consommer_id(rid, capacite, args, niveau, user, now):
            return rid, None, None
        return None, (
            f"Reprise de l'approbation {rid[:8]} impossible (expirée, déjà utilisée ou "
            "arguments différents) : action NON exécutée."), None
```
Après le bloc « refus récent », **avant** `creer`, ajouter :

```python
    faite = _derniere(capacite, args, ("executee",), niveau, user)
    if faite and (faite["decide_a"] or 0) + DELAI_APRES_EXECUTION_S > now:
        return None, (
            f"Action `{capacite}` : cette action vient déjà d'être exécutée après approbation "
            "(résultat dans le message Telegram de l'humain). Ne la redemande pas."), None
```
Remplacer le texte de fin de `exiger` : `"... Dis-lui que tu attends son approbation. Quand il aura approuvé, l'action s'exécutera AUTOMATIQUEMENT : ne rappelle pas l'outil et ne cherche pas à la relancer."` ; idem pour le message « demande déjà ouverte » : retirer toute invitation à rappeler (il dit déjà « n'insiste pas »). (`_derniere` ordonne par `cree_a DESC` ; l'utilisation de `decide_a` pour `executee` est valable car posée à l'approbation.)

- [ ] **Step 4 : Corriger les tests dont le texte change**

Run : `cd core && grep -n "MÊME\|rappelle" test_approbations*.py`
Adapter les assertions de texte (`MÊME outil` → `AUTOMATIQUEMENT`).

- [ ] **Step 5 : Lancer**

Run : `cd core && python3 -m pytest test_approbations*.py -q 2>&1 | tail -5`
Expected : tout vert.

- [ ] **Step 6 : Commit**

```bash
git add core/approbations.py core/test_approbations*.py
git commit -m "feat(approbations): garde en mode reprise (consommation d'un id précis), purge des args, pas de redemande après exécution

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01HhWGGaLbPBnwM9KTfyyUQp"
```

---

### Task 6 : Cœur — l'exécution à l'approbation (`approbations_reprise.py`) + déclenchement par les routes

**Files:**
- Create: `core/approbations_reprise.py`
- Modify: `core/routers/approbations.py` (déclenchement après `decision` ok et `code` ok ; reprise des orphelines dans `relancer`)
- Modify: `core/test_approbations_reprise.py` (ajouts), `core/test_approbations_routes.py`

**Interfaces:**
- Consumes : `approbations.avec_reprise`, `args_de`, `a_reprendre`, `avec_origine`, `lire` ; `outils.executer(nom, args, registre)` ; `contexte_tenant.definir_contexte/reinitialiser`.
- Produces :
  - `async approbations_reprise.reprendre(registre, id_) -> str` — renvoie `"executee" | "ignoree" | "sans_args"`.
  - `approbations_reprise.lancer(registre, id_) -> None` — planifie `reprendre` en tâche de fond (référence conservée).

- [ ] **Step 1 : Écrire les tests qui échouent**

Ajouter à `core/test_approbations_reprise.py` :

```python
import asyncio  # noqa: E402

import approbations_canal  # noqa: E402
import approbations_reprise  # noqa: E402
import contexte_tenant  # noqa: E402
import outils  # noqa: E402


class _Reg:
    def __init__(self, briques):
        self.briques = briques


REGISTRE = _Reg({"dokploy": {"nom": "dokploy", "port": 6300, "capacites": [
    {"nom": "app_redemarrer", "chemin": "/redemarrer", "methode": "POST", "action": True,
     "sensibilite": "reversible", "description": "Redémarre une app.",
     "params": {"app": {"type": "string", "requis": True}}}]}})


@pytest.fixture
def faux_outils(monkeypatch):
    vu = {"appels": [], "contexte": [], "maj": [], "notifs": []}

    async def _executer(nom, args, registre):
        ctx = contexte_tenant.contexte_actuel()
        vu["appels"].append((nom, dict(args)))
        vu["contexte"].append((ctx.utilisateur, ctx.org_id, approbations.ORIGINE.get()))
        return '{"ok": true}'

    async def _maj(registre, demande):
        vu["maj"].append(demande["statut"])

    async def _notifier(registre, demande):
        vu["notifs"].append(demande["id"])

    monkeypatch.setattr(outils, "_executer", _executer)
    monkeypatch.setattr(approbations_canal, "mettre_a_jour", _maj)
    monkeypatch.setattr(outils, "_notifier_approbation", _notifier)
    return vu


def _demande_approuvee(utilisateur="alice", org="org-1"):
    d = approbations.creer("app_redemarrer", {"app": "crm"}, "r", "reversible",
                           origine="incident", utilisateur=utilisateur, org_id=org)
    ok, _ = approbations.approuver(d["id"], "tg:1", "telegram", utilisateur=utilisateur)
    assert ok
    return d["id"]


def test_reprendre_execute_dans_le_contexte_du_demandeur(faux_outils):
    id_ = _demande_approuvee()
    assert asyncio.run(approbations_reprise.reprendre(REGISTRE, id_)) == "executee"
    assert faux_outils["appels"] == [("app_redemarrer", {"app": "crm", "confirme": True})]
    assert faux_outils["contexte"] == [("alice", "org-1", "incident")]
    assert approbations.lire(id_)["statut"] == "executee"
    assert faux_outils["maj"] == ["executee"]          # message Telegram édité à l'état final
    assert faux_outils["notifs"] == []                 # AUCUNE nouvelle demande


def test_reprendre_ne_fuit_pas_le_contexte(faux_outils):
    id_ = _demande_approuvee()
    asyncio.run(approbations_reprise.reprendre(REGISTRE, id_))
    assert contexte_tenant.contexte_actuel().utilisateur == "perso"
    assert approbations.REPRISE.get() is None


def test_reprendre_deux_fois_n_execute_qu_une_fois(faux_outils):
    id_ = _demande_approuvee()

    async def deux():
        return await asyncio.gather(approbations_reprise.reprendre(REGISTRE, id_),
                                    approbations_reprise.reprendre(REGISTRE, id_))

    asyncio.run(deux())
    assert len(faux_outils["appels"]) == 1


def test_reprendre_ignore_une_demande_non_approuvee(faux_outils):
    d = approbations.creer("app_redemarrer", {"app": "crm"}, "r", "reversible",
                           utilisateur="alice")
    assert asyncio.run(approbations_reprise.reprendre(REGISTRE, d["id"])) == "ignoree"
    assert faux_outils["appels"] == []


def test_reprendre_sans_args_ne_fait_rien(faux_outils):
    id_ = _demande_approuvee()
    import sqlite3
    c = sqlite3.connect(approbations.DB)
    c.execute("UPDATE approbations SET args=NULL WHERE id=?", (id_,))
    c.commit()
    c.close()
    assert asyncio.run(approbations_reprise.reprendre(REGISTRE, id_)) == "sans_args"
    assert faux_outils["appels"] == []


def test_echec_d_execution_passe_en_echec(monkeypatch, faux_outils):
    async def _boom(nom, args, registre):
        return '{"erreur": "dokploy injoignable"}'

    monkeypatch.setattr(outils, "_executer", _boom)
    id_ = _demande_approuvee()
    asyncio.run(approbations_reprise.reprendre(REGISTRE, id_))
    assert approbations.lire(id_)["statut"] == "echec"
    assert faux_outils["maj"] == ["echec"]


def test_exception_dans_l_outil_ne_remonte_pas(monkeypatch, faux_outils):
    async def _crash(nom, args, registre):
        raise RuntimeError("kaboom")

    monkeypatch.setattr(outils, "_executer", _crash)
    id_ = _demande_approuvee()
    assert asyncio.run(approbations_reprise.reprendre(REGISTRE, id_)) == "echec"
    assert approbations.lire(id_)["statut"] == "echec"
```

- [ ] **Step 2 : Lancer, constater l'échec**

Run : `cd core && python3 -m pytest test_approbations_reprise.py -q 2>&1 | tail -6`
Expected : FAIL (`ModuleNotFoundError: approbations_reprise`).

- [ ] **Step 3 : Implémenter `core/approbations_reprise.py`**

```python
"""Reprise après approbation (S245b) : le Cœur exécute lui-même l'action approuvée.

Avant S245b, approuver ne faisait que passer la demande à `approuvee` : il fallait que le LLM
rappelle l'outil dans les 5 min, et le co-agent / les incidents n'avaient aucune reprise.
Ici, à l'approbation (bouton, ou code à 6 chiffres), on rejoue `outils.executer` dans le contexte
du DEMANDEUR (utilisateur, organisation, origine) avec les arguments exacts persistés.

## Garanti
- Une seule exécution : la garde consomme CETTE approbation par un UPDATE conditionnel
  (`approbations.consommer_id`) ; deux reprises concurrentes (ou un rappel du LLM) n'exécutent
  qu'une fois.
- Jamais de nouvelle demande : en mode reprise, `exiger` ne crée rien.
- Au plus une exécution : `executee` est posé AVANT l'exécution (un crash ne rejoue pas).

## NON garanti
- Le JWT de l'utilisateur n'est pas persisté : une capacité qui l'exige échoue (état `echec`).
- Le résultat n'est pas réinjecté dans le fil de conversation (visible dans le message Telegram
  édité et dans `approbations.resultat`)."""
import asyncio
import logging

import approbations
import contexte_tenant
import outils

log = logging.getLogger(__name__)

_TACHES: set[asyncio.Task] = set()          # références fortes (sinon le GC peut tuer la tâche)


async def reprendre(registre, id_: str) -> str:
    """Exécute l'approbation `id_` si elle est `approuvee`. Ne lève jamais."""
    demande = approbations.lire(id_)
    if not demande or demande["statut"] != "approuvee":
        return "ignoree"
    args = approbations.args_de(id_)
    if args is None:
        log.warning("approbation %s : reprise impossible (arguments absents)", id_[:8])
        return "sans_args"
    jetons = contexte_tenant.definir_contexte(utilisateur=demande["utilisateur"],
                                              org_id=demande.get("org_id"))
    try:
        with approbations.avec_origine(demande["origine"]), approbations.avec_reprise(id_):
            await outils.executer(demande["capacite"], args, registre)
    except Exception as exc:  # noqa: BLE001 — jamais remonter dans une tâche de fond
        log.warning("approbation %s : reprise en échec (%s)", id_[:8], type(exc).__name__)
        approbations.conclure(id_, False, f"reprise : {type(exc).__name__}")
        return "echec"
    finally:
        contexte_tenant.reinitialiser(jetons)
    return "executee"


def lancer(registre, id_: str) -> None:
    """Planifie `reprendre` en tâche de fond : la route de décision répond sans attendre."""
    tache = asyncio.get_running_loop().create_task(reprendre(registre, id_))
    _TACHES.add(tache)
    tache.add_done_callback(_TACHES.discard)
```

Remarque pour l'exécutant : `outils.executer` appelle `approbations.exiger` (mode reprise ⇒ `consommer_id`), puis `conclure` + `mettre_a_jour` ; ce sont ces appels qui produisent `executee`/`echec` et l'édition Telegram. Dans le cas `exception`, `conclure(id_, False, …)` fait `executee → echec` (no-op si la demande n'était pas encore `executee`, car `_transition` exige l'état `executee`).

- [ ] **Step 4 : Lancer**

Run : `cd core && python3 -m pytest test_approbations_reprise.py -q 2>&1 | tail -6`
Expected : tout PASS. Si `test_reprendre_deux_fois…` est instable, vérifier que `consommer_id` est bien l'UPDATE conditionnel (Task 5) — c'est lui l'arbitre.

- [ ] **Step 5 : Écrire les tests de routes qui échouent**

Dans `core/test_approbations_routes.py` ajouter (fixtures `client`, `demande`, `demande_destructive`, `ENT` ; relire `lignes 60-110` pour les noms exacts) :

```python
@pytest.fixture
def reprises(monkeypatch):
    import approbations_reprise
    vues = []
    monkeypatch.setattr(approbations_reprise, "lancer", lambda registre, id_: vues.append(id_))
    return vues


def test_approuver_declenche_la_reprise(client, demande, reprises):
    client.post(f"/approbations/{demande['id']}/decision", headers=ENT,
                json={"decision": "ok", "par": "tg:42", "utilisateur": demande["utilisateur"]})
    assert reprises == [demande["id"]]


def test_refuser_ne_declenche_pas_de_reprise(client, demande, reprises):
    client.post(f"/approbations/{demande['id']}/decision", headers=ENT,
                json={"decision": "ko", "par": "tg:42", "utilisateur": demande["utilisateur"]})
    assert reprises == []


def test_decision_en_echec_ne_declenche_pas_de_reprise(client, demande, reprises):
    client.post(f"/approbations/{demande['id']}/decision", headers=ENT,
                json={"decision": "ok", "par": "tg:42", "utilisateur": "intrus"})
    assert reprises == []


def test_code_bon_declenche_la_reprise(client, demande_destructive, reprises):
    id_ = demande_destructive["id"]
    u = demande_destructive["utilisateur"]
    client.post(f"/approbations/{id_}/code/armer", headers=ENT, json={"par": "tg:42",
                                                                      "utilisateur": u})
    code = approbations.lire(id_)["code"]
    client.post("/approbations/code", headers=ENT,
                json={"par": "tg:42", "code": code, "utilisateur": u})
    assert reprises == [id_]


def test_code_faux_ne_declenche_pas_de_reprise(client, demande_destructive, reprises):
    id_ = demande_destructive["id"]
    u = demande_destructive["utilisateur"]
    client.post(f"/approbations/{id_}/code/armer", headers=ENT, json={"par": "tg:42",
                                                                      "utilisateur": u})
    client.post("/approbations/code", headers=ENT,
                json={"par": "tg:42", "code": "000000", "utilisateur": u})
    assert reprises == []


def test_relancer_reprend_les_approuvees_orphelines(client, demande, reprises, monkeypatch):
    approbations.approuver(demande["id"], "tg:42", "telegram", time.time() - 3600,
                           utilisateur=demande["utilisateur"])
    # `approuver` a fixé expire_a = max(expire_a, now + 300) : la demande reste valide (TTL 1440 min).
    client.post("/approbations/relancer", headers=ENT)
    assert reprises == [demande["id"]]
```

- [ ] **Step 6 : Câbler les routes**

`core/routers/approbations.py` : `import approbations_reprise` ; dans `decision`, après `lue = await _maj(...)` :

```python
    if body.decision == "ok" and ok:
        approbations_reprise.lancer(registre, id_)
```
Dans `code`, après `await _maj(...)` :

```python
    if r.get("ok") and r.get("raison") == "ok":
        approbations_reprise.lancer(registre, r["approbation_id"])
```
Dans `relancer`, après la boucle des relances :

```python
    reprises = approbations.a_reprendre()
    for id_ in reprises:
        approbations_reprise.lancer(registre, id_)
    return {"expirees": perimees, "relancees": relancees, "reprises": reprises}
```
(et mettre à jour le test existant de `relancer` s'il compare le dict complet : ajouter `"reprises": []`.) Compléter la docstring du module : « l'approbation déclenche l'exécution par le Cœur (S245b) ».

⚠ `lancer` est appelé dans une route `async` (boucle active) : `asyncio.get_running_loop()` est valide. Dans les tests de routes (TestClient) la boucle existe aussi ; les tests ci-dessus remplacent `lancer`.

- [ ] **Step 7 : Lancer tout le Cœur approbations**

Run : `cd core && python3 -m pytest test_approbations*.py -q 2>&1 | tail -5`
Expected : tout vert.

- [ ] **Step 8 : Commit**

```bash
git add core/approbations_reprise.py core/routers/approbations.py core/test_approbations_reprise.py core/test_approbations_routes.py
git commit -m "feat(approbations): le Cœur exécute l'action approuvée (reprise dans le contexte du demandeur), reprise des orphelines par l'horloge

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01HhWGGaLbPBnwM9KTfyyUQp"
```

---

### Task 7 : Preuve de bout en bout (Cœur seul, sans Docker)

**Files:**
- Create: `core/test_approbations_bout_en_bout.py`

**Interfaces:** Consomme `outils.executer`, `approbations.*`, `approbations_reprise.reprendre`. Prouve la chaîne demande → approbation par le bon utilisateur → exécution automatique → pas de double exécution.

- [ ] **Step 1 : Écrire le test**

```python
"""S245b — parcours complet côté Cœur : demande → approbation → exécution par le Cœur."""
import asyncio
import os
import sys
import tempfile

os.environ["ASSISTANT_CONFIG_PATH"] = os.path.join(tempfile.mkdtemp(), "cfg.json")
os.environ.setdefault("GATEWAY_KEY", "sk-test-local")
sys.path.insert(0, os.path.dirname(__file__))

import pytest  # noqa: E402

import approbations  # noqa: E402
import approbations_canal  # noqa: E402
import approbations_reprise  # noqa: E402
import contexte_tenant  # noqa: E402
import outils  # noqa: E402
from test_approbations_garde import REGISTRE  # noqa: E402


@pytest.fixture(autouse=True)
def _env(tmp_path, monkeypatch):
    monkeypatch.setattr(approbations, "DB", str(tmp_path / "a.db"))
    approbations.init_db()
    vu = {"exec": [], "notifs": []}

    async def _exe(nom, args, registre):
        vu["exec"].append((nom, contexte_tenant.contexte_actuel().utilisateur))
        return '{"ok": true}'

    async def _notif(registre, demande):
        vu["notifs"].append(demande["utilisateur"])

    async def _maj(registre, demande):
        pass

    monkeypatch.setattr(outils, "_executer", _exe)
    monkeypatch.setattr(outils, "_notifier_approbation", _notif)
    monkeypatch.setattr(approbations_canal, "mettre_a_jour", _maj)
    return vu


def _en_tant_que(utilisateur, coro_fn):
    jetons = contexte_tenant.definir_contexte(utilisateur=utilisateur)
    try:
        return asyncio.run(coro_fn())
    finally:
        contexte_tenant.reinitialiser(jetons)


def test_parcours_complet_alice(_env):
    # 1. Alice (co-agent) demande : refus + demande créée pour ELLE.
    refus = _en_tant_que("alice", lambda: outils.executer("app_redemarrer", {"app": "crm"}, REGISTRE))
    assert "NON exécutée" in refus and _env["notifs"] == ["alice"] and _env["exec"] == []
    (demande,) = approbations.en_attente(utilisateur="alice")
    assert approbations.en_attente(utilisateur="bob") == []

    # 2. Bob tente d'approuver : refusé. Alice approuve.
    assert approbations.approuver(demande["id"], "tg:2", "telegram",
                                  utilisateur="bob") == (False, "introuvable")
    assert approbations.approuver(demande["id"], "tg:1", "telegram",
                                  utilisateur="alice") == (True, "ok")

    # 3. Le Cœur exécute, en tant qu'Alice, sans nouveau cycle d'approbation.
    assert asyncio.run(approbations_reprise.reprendre(REGISTRE, demande["id"])) == "executee"
    assert _env["exec"] == [("app_redemarrer", "alice")] and _env["notifs"] == ["alice"]

    # 4. Le LLM qui rappelle l'outil juste après ne relance rien.
    refus2 = _en_tant_que("alice", lambda: outils.executer("app_redemarrer", {"app": "crm"}, REGISTRE))
    assert "déjà" in refus2 and len(_env["exec"]) == 1 and _env["notifs"] == ["alice"]
    assert approbations.args_de(demande["id"]) is None            # args purgés
```

- [ ] **Step 2 : Lancer**

Run : `cd core && python3 -m pytest test_approbations_bout_en_bout.py -q 2>&1 | tail -6`
Expected : PASS. (Importer `REGISTRE` depuis un autre fichier de test est toléré ici ; si `pytest` signale un conflit d'import, copier la constante.)

- [ ] **Step 3 : Suite complète du Cœur et de connexion**

```bash
cd /Users/garinat_t/Desktop/Workplace && make test-core 2>&1 | tail -6
cd briques/connexion && python3 -m pytest -q 2>&1 | tail -3
```
Expected : Cœur ≈ 1251 + nouveaux tests passed, **3 xfailed préexistants** inchangés, 0 failed ; connexion tout vert. Relever les chiffres réels (ne pas reprendre un comptage de sous-agent).

- [ ] **Step 4 : Commit**

```bash
git add core/test_approbations_bout_en_bout.py
git commit -m "test(approbations): parcours complet S245b (demande, mauvais approbateur, reprise, pas de double exécution)

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01HhWGGaLbPBnwM9KTfyyUQp"
```

---

### Task 8 : Documentation, ADR, mémoire

**Files:**
- Modify: `docs/decisions/2026-11-25-approbation-telegram.md`, `docs/sprints/S245-socle-approbation-telegram.md`, `docs/sprints/S246-forgejo-dokploy-exploitation.md`, `docs/sprints/EPOPEE-livraison-support-assistant.md`
- Modify: `/Users/garinat_t/.claude/projects/-Users-garinat-t-Desktop-Workplace/memory/sprint-s245-socle-approbation-telegram.md` et `MEMORY.md`

- [ ] **Step 1 : ADR** — ajouter une section « S245b (2026-11-25) » : les 3 décisions (Q1=A, Q2=A, Q3=A), et les **Écarts et limites assumés** 1-5 listés plus haut, mot pour mot.

- [ ] **Step 2 : Fichier S245** — dans « Ce que ça ne garantit pas », barrer/remplacer : limite « non liée à un utilisateur » → « fermée en S245b » ; « pas d'exécution automatique » → « fermée en S245b (reprise par le Cœur) » ; `API_KEYS` partagée → « fermée en S245b (`CONNEXION_API_KEYS`) ». Conserver les limites restantes (écran du code, `satisfaire_prerequis`, webhook sans secret).

- [ ] **Step 3 : Fichier S246** — en tête, ajouter « **S245b livré (2026-11-25)** : approbation liée à l'utilisateur, reprise par le Cœur, `CONNEXION_API_KEYS`. L'activation des clés sur le HP reste différée à la fin d'S246. » et remplacer la procédure d'activation (`API_KEYS`) par : poser `CONNEXION_API_KEYS` (= `CONNEXION_KEY`) dans le `.env` racine du HP.

- [ ] **Step 4 : Épopée** — ligne S245 du tableau : état « codé + revu + S245b (liaison utilisateur, reprise, `CONNEXION_API_KEYS`) ; LIVE à prouver ».

- [ ] **Step 5 : Mémoire** — mettre à jour `sprint-s245-socle-approbation-telegram.md` (frontmatter `description` + corps) : limites 1, 2 et le piège `API_KEYS` marqués fermés par S245b ; procédure d'activation corrigée (`CONNEXION_API_KEYS`) ; limites restantes (3, 4, 5). Mettre à jour la ligne correspondante de `MEMORY.md`. Ne pas créer de doublon.

- [ ] **Step 6 : Commit**

```bash
git add docs
git commit -m "docs(s245b): ADR, S245/S246 et épopée à jour (limites fermées, procédure d'activation)

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01HhWGGaLbPBnwM9KTfyyUQp"
```

(La mémoire vit hors dépôt : pas de `git add`.)

- [ ] **Step 7 : Revue finale avant merge**

Relire la branche en entier (`git diff main...HEAD`) ; vérifier à la main : (a) aucune route ne renvoie `args` ; (b) aucun appel `approuver/refuser/armer_saisie_code/valider_code_saisi` sans `utilisateur` ; (c) `grep -rn "API_KEYS" .env.example` ne montre aucune valeur renseignée ; (d) `git status` ne montre aucun changement du `.env`. Puis `superpowers:finishing-a-development-branch` — **pas de déploiement HP, pas de pose de clés**.

---

## Auto-revue (spec ↔ plan)

- **Q1 = A** (seul le demandeur) : Task 1 (filtres Cœur), Task 2 (routes + liste par session), Task 3 (destinataires `approbateurs_de`, `utilisateur_de` côté pont, re-vérification Cœur), Task 7 (parcours).
- **Q2 = A** (variable présente-vide = ouvert, repli si absente) : Task 4, test dédié aux 3 cas.
- **Q3 = A** (Cœur exécute, contexte du demandeur, args purgés) : Task 5 (garde/purge/anti-redemande), Task 6 (reprise + déclenchement bouton **et** code destructif + orphelines), écarts honnêtes (args en clair, pas de JWT, pas de réinjection dans le fil).
- **Contrainte « pas de clés sur le HP »** : Global Constraints + Task 8 Step 7 ; aucun fichier `.env` touché, `.env.example` seulement (valeur vide).
- **Cohérence des noms** : `utilisateur` (kw-only) dans `approuver/refuser/armer_saisie_code/valider_code_saisi/consommer`, `avec_reprise`/`REPRISE`/`consommer_id`/`args_de`/`a_reprendre`, `approbations_reprise.reprendre/lancer`, `correspondance.utilisateur_de/approbateurs_de`, `client_assistant.*(…, utilisateur)` — identiques dans toutes les tâches.
