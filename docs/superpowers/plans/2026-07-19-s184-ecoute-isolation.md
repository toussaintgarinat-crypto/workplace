# S184 — Isolation par personne de la brique `ecoute` Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Que chaque personne connectée au Cœur ait ses propres commandes de mot-clé de réveil sur mesure (historique + statut de paiement privés), sans authentification aujourd'hui être totalement absente sur ces routes qui manipulent de l'argent réel.

**Architecture:** Généraliser le motif déjà établi pour l'agenda (S182) — le Cœur forwarde l'identité de session en `X-User-Id`, gagée par une clé de service (`ECOUTE_KEY`) que seul le Cœur détient — à la brique `ecoute`. Ajouter une colonne `proprietaire` à la table `commandes` et filtrer dessus dans les routes sensibles ; le catalogue de mots-clés déjà livrés reste un bien partagé du foyer.

**Tech Stack:** FastAPI (Cœur + brique ecoute), SQLite (side-car `commandes.py`), pytest.

## Global Constraints

- Isolation par personne (motif agenda S182) pour les commandes ; le catalogue livré (`GET /noms`, WS `/ecoute`) reste partagé pour tout le foyer — spec section "Décisions de kickoff".
- Migration = colonne `proprietaire TEXT NOT NULL DEFAULT 'perso'` (alias, zéro rewrite des lignes existantes) — spec section "Modèle de données".
- `POST /paiement/webhook` et `GET /paiement/etat` restent inchangés (déjà corrects) — spec section "Routes impactées".
- 404 (pas 403) quand une commande appartient à un autre propriétaire — motif mail/restaurant, ne pas révéler l'existence — spec section "Routes impactées".
- Pas de migration de données réelles, pas de déploiement LIVE HP dans ce sprint (code + tests uniquement) — spec section "Hors périmètre".
- `make test-core` et la suite `briques/ecoute/` doivent rester au vert après chaque tâche.

---

### Task 1: Généraliser le forwarding `X-User-Id` à un ensemble de briques « cercle privé »

**Files:**
- Modify: `core/contexte_tenant.py:88-91` (renomme `entetes_agenda` → `entetes_par_personne`)
- Modify: `core/contexte_tenant.py:17-18` (docstring module)
- Modify: `core/outils_communs.py:41-70` (introduit `BRIQUES_PAR_PERSONNE`)
- Modify: `core/agenda.py:31` (met à jour l'appelant)
- Test: `core/test_contexte_tenant.py:30,40,137-146`

**Interfaces:**
- Consumes: rien de nouveau.
- Produces: `contexte_tenant.entetes_par_personne() -> dict` (remplace `entetes_agenda`, même
  comportement : `{"X-User-Id": <utilisateur du contexte ou "perso">}`) ; `outils_communs.BRIQUES_PAR_PERSONNE: set[str]` (contient `"agenda"`, `"ecoute"`) consommé par `_entetes_brique`. Les tâches suivantes ajouteront `"ecoute"` à ce set (déjà fait ici) et s'appuieront sur `entetes_par_personne`.

- [ ] **Step 1: Étendre le test existant pour attendre `entetes_par_personne` et `ecoute`**

Dans `core/test_contexte_tenant.py`, remplacer la ligne 30 :
```python
    assert ct.entetes_agenda() == {"X-User-Id": "perso"}
```
par :
```python
    assert ct.entetes_par_personne() == {"X-User-Id": "perso"}
```

Remplacer la ligne 40 :
```python
    assert ct.entetes_agenda() == {"X-User-Id": "alice"}
```
par :
```python
    assert ct.entetes_par_personne() == {"X-User-Id": "alice"}
```

Remplacer la fonction `test_entetes_brique_agenda_forwarde_identite` (lignes 137-146) par :
```python
def test_entetes_brique_par_personne_forwarde_identite():
    """S182 (agenda) + S184 (ecoute) : la surface /service (outils de l'assistant) doit
    porter X-User-Id = utilisateur connecté pour les briques « cercle privé » ; les autres
    briques ne le portent pas."""
    _reset_complet()
    import outils_communs
    ct.definir_contexte(utilisateur="claire")
    assert outils_communs._entetes_brique("agenda")["X-User-Id"] == "claire"
    assert outils_communs._entetes_brique("ecoute")["X-User-Id"] == "claire"
    # Une autre brique (ex. restaurant) ne reçoit PAS X-User-Id (elle l'ignorerait).
    assert "X-User-Id" not in outils_communs._entetes_brique("restaurant")
```

- [ ] **Step 2: Lancer les tests pour vérifier qu'ils échouent**

Run: `cd core && VAULT_SECRET=test GATEWAY_KEY=test python3 -m pytest test_contexte_tenant.py -v`
Expected: FAIL — `AttributeError: module 'contexte_tenant' has no attribute 'entetes_par_personne'` (et l'assertion sur `"ecoute"` échouerait aussi une fois le rename fait, tant que `_entetes_brique` ne connaît pas encore `"ecoute"`).

- [ ] **Step 3: Renommer la fonction dans `core/contexte_tenant.py`**

Remplacer (lignes 86-91) :
```python
# ── En-têtes sortants S2S ────────────────────────────────────────────────────────

def entetes_agenda() -> dict:
    """Identité pour la brique agenda : ``X-User-Id`` (scope par utilisateur)."""
    return {"X-User-Id": _utilisateur.get() or UTILISATEUR_DEFAUT}
```
par :
```python
# ── En-têtes sortants S2S ────────────────────────────────────────────────────────

def entetes_par_personne() -> dict:
    """Identité pour les briques « cercle privé » (agenda S182, ecoute S184) : ``X-User-Id``
    (scope par utilisateur connecté, pas par organisation/tenant)."""
    return {"X-User-Id": _utilisateur.get() or UTILISATEUR_DEFAUT}
```

Dans le docstring du module (lignes 17-18), remplacer :
```python
Granularité (décision S121) : ``donnees`` est scopé par **organisation**
(``X-Org-ID`` / claim ``org_id``), ``agenda`` par **utilisateur** (``X-User-Id``).
```
par :
```python
Granularité (décision S121, étendue S184) : ``donnees`` est scopé par **organisation**
(``X-Org-ID`` / claim ``org_id``) ; les briques « cercle privé » (``agenda``, ``ecoute``) par
**utilisateur** (``X-User-Id``).
```

- [ ] **Step 4: Généraliser `_entetes_brique` dans `core/outils_communs.py`**

Remplacer (lignes 41-70) :
```python
# ── Outils DYNAMIQUES : le système nerveux découvert (S64) ────────────────────
# Les capacités déclarées dans les manifests (S63) deviennent de vrais outils du LLM,
# routés ici sans une ligne de dispatch en dur. Garde-fous : un nom déjà servi par un
# outil CÂBLÉ gagne toujours (zéro régression) ; liste blanche et kill-switch d'env
# permettent de borner ce que le LLM voit (souveraineté du « plan de contrôle »).


def _entetes_brique(brique: str) -> dict:
    """En-têtes de service pour piloter une brique au nom de l'appelant (S167).

    - ``{BRIQUE}_KEY`` → ``X-API-Key`` : prouve qu'on a le droit d'emprunter la surface
      ``/service`` (motif muscle.py). Sans clé, la brique reste en mode ouvert.
    - ``ADMIN_COMPTE_ID`` (défaut ``admin``) → ``X-Compte-Id`` : identité de l'appelant.
      La brique lit le ``role`` de ce compte EN BASE pour décider du périmètre (admin =
      accès total ; tenant = ses ressources). Mono-user aujourd'hui → toujours l'admin ;
      multi-user demain → l'id de l'utilisateur courant, sans rien changer côté brique.
      Cf. ADR docs/decisions/2026-07-13-surface-de-service-role-admin.md.
    """
    entetes: dict = {"X-Compte-Id": os.environ.get("ADMIN_COMPTE_ID", "admin")}
    cle = os.environ.get(f"{brique.upper()}_KEY")
    if cle:
        entetes["X-API-Key"] = cle
    # S182 « chacun son agenda » : les outils de l'assistant empruntent la surface
    # /service ; on forwarde l'identité de l'utilisateur connecté (contexte de tenant) en
    # X-User-Id pour que l'agenda serve SES données au lieu du pin « perso ». Ciblé sur
    # l'agenda (seule brique qui honore X-User-Id derrière AGENDA_KEY) ; les autres
    # briques ignorent cet en-tête.
    if brique.lower() == "agenda":
        entetes.update(contexte_tenant.entetes_agenda())
    return entetes
```
par :
```python
# ── Outils DYNAMIQUES : le système nerveux découvert (S64) ────────────────────
# Les capacités déclarées dans les manifests (S63) deviennent de vrais outils du LLM,
# routés ici sans une ligne de dispatch en dur. Garde-fous : un nom déjà servi par un
# outil CÂBLÉ gagne toujours (zéro régression) ; liste blanche et kill-switch d'env
# permettent de borner ce que le LLM voit (souveraineté du « plan de contrôle »).

# Briques « cercle privé » (S182 agenda, S184 ecoute) : le Cœur forwarde l'identité de
# l'utilisateur connecté en X-User-Id, gagée par {BRIQUE}_KEY (seul le Cœur la détient).
# Les autres briques ignorent cet en-tête (motif tenant/bundle-client, cf. X-Compte-Id).
BRIQUES_PAR_PERSONNE = {"agenda", "ecoute"}


def _entetes_brique(brique: str) -> dict:
    """En-têtes de service pour piloter une brique au nom de l'appelant (S167).

    - ``{BRIQUE}_KEY`` → ``X-API-Key`` : prouve qu'on a le droit d'emprunter la surface
      ``/service`` (motif muscle.py). Sans clé, la brique reste en mode ouvert.
    - ``ADMIN_COMPTE_ID`` (défaut ``admin``) → ``X-Compte-Id`` : identité de l'appelant.
      La brique lit le ``role`` de ce compte EN BASE pour décider du périmètre (admin =
      accès total ; tenant = ses ressources). Mono-user aujourd'hui → toujours l'admin ;
      multi-user demain → l'id de l'utilisateur courant, sans rien changer côté brique.
      Cf. ADR docs/decisions/2026-07-13-surface-de-service-role-admin.md.
    """
    entetes: dict = {"X-Compte-Id": os.environ.get("ADMIN_COMPTE_ID", "admin")}
    cle = os.environ.get(f"{brique.upper()}_KEY")
    if cle:
        entetes["X-API-Key"] = cle
    if brique.lower() in BRIQUES_PAR_PERSONNE:
        entetes.update(contexte_tenant.entetes_par_personne())
    return entetes
```

- [ ] **Step 5: Mettre à jour l'appelant dans `core/agenda.py`**

Remplacer (ligne 31) :
```python
    e = contexte_tenant.entetes_agenda()  # {"X-User-Id": <utilisateur courant ou perso>}
```
par :
```python
    e = contexte_tenant.entetes_par_personne()  # {"X-User-Id": <utilisateur courant ou perso>}
```

- [ ] **Step 6: Lancer les tests pour vérifier qu'ils passent**

Run: `cd core && VAULT_SECRET=test GATEWAY_KEY=test python3 -m pytest test_contexte_tenant.py -v`
Expected: PASS — tous les tests, y compris les 2 renommés/étendus.

- [ ] **Step 7: Lancer la suite complète du Cœur**

Run: `cd /Users/garinat_t/Desktop/Workplace && VAULT_SECRET=test GATEWAY_KEY=test make test-core`
Expected: PASS — aucune régression (confirme qu'aucun autre appelant de `entetes_agenda` n'a été oublié).

- [ ] **Step 8: Commit**

```bash
git add core/contexte_tenant.py core/outils_communs.py core/agenda.py core/test_contexte_tenant.py
git commit -m "refactor(core): généralise le forward X-User-Id à un ensemble de briques (S184)

entetes_agenda() → entetes_par_personne() ; BRIQUES_PAR_PERSONNE = {agenda, ecoute}.
Prépare l'isolation par personne de la brique ecoute (commandes de mot-clé sur mesure)."
```

---

### Task 2: Colonne `proprietaire` + isolation par personne dans `MagasinCommandes`

**Files:**
- Modify: `briques/ecoute/commandes.py` (méthodes `init_db`, `_en_cours_pour_marque`, `lister`, `get`, `creer`, `vue`)
- Test: `briques/ecoute/test_commandes.py`

**Interfaces:**
- Consumes: rien de nouveau (module autonome, pas de dépendance sur Task 1).
- Produces (consommé par Task 4) : `MagasinCommandes.creer(nom_marque: str, proprietaire: str = "perso") -> dict` (renvoie `{"deja_disponible": True, "modele": slug}` si le modèle est déjà livré, sinon une ligne de commande incluant la clé `"proprietaire"`) ; `MagasinCommandes.lister(statut: str | None = None, proprietaire: str | None = None) -> list[dict]` ; `MagasinCommandes.get(cid: str, proprietaire: str | None = None) -> dict | None` (renvoie `None` si la commande appartient à un autre propriétaire) ; `vue(c: dict) -> dict` inclut désormais la clé `"proprietaire"`.

- [ ] **Step 1: Écrire les tests qui échouent**

Ajouter dans `briques/ecoute/test_commandes.py`, juste après `test_idempotent_pas_de_doublon` (après la ligne 37) :

```python
def test_creer_scope_par_proprietaire(magasin):
    """Deux propriétaires peuvent chacun commander la même marque sans se voir."""
    c_alice = magasin.creer("Acme Corp", proprietaire="alice")
    c_bob = magasin.creer("Acme Corp", proprietaire="bob")
    assert c_alice["id"] != c_bob["id"]
    assert c_alice["proprietaire"] == "alice"
    assert c_bob["proprietaire"] == "bob"


def test_creer_deja_livree_court_circuite(magasin):
    c = magasin.creer("Acme", proprietaire="alice")
    magasin.marquer_payee(c["id"])
    magasin.changer_etat(c["id"], "en_entrainement")
    magasin.changer_etat(c["id"], "livree")
    # Bob commande la même marque déjà livrée : pas de nouvelle commande, pas de paiement.
    resultat = magasin.creer("Acme", proprietaire="bob")
    assert resultat == {"deja_disponible": True, "modele": "acme"}


def test_lister_filtre_par_proprietaire(magasin):
    magasin.creer("Acme", proprietaire="alice")
    magasin.creer("Ibiza", proprietaire="bob")
    assert [c["nom_marque"] for c in magasin.lister(proprietaire="alice")] == ["Acme"]
    assert [c["nom_marque"] for c in magasin.lister(proprietaire="bob")] == ["Ibiza"]
    assert len(magasin.lister()) == 2  # sans filtre (usage interne) : tout le monde


def test_get_filtre_par_proprietaire(magasin):
    c = magasin.creer("Acme", proprietaire="alice")
    assert magasin.get(c["id"], proprietaire="bob") is None
    assert magasin.get(c["id"], proprietaire="alice")["id"] == c["id"]
    assert magasin.get(c["id"]) is not None  # sans filtre : accès interne


def test_livrees_reste_global_malgre_proprietaires_differents(magasin):
    """Catalogue partagé : livrees() n'est jamais filtré par propriétaire."""
    c = magasin.creer("Acme", proprietaire="alice")
    magasin.marquer_payee(c["id"])
    magasin.changer_etat(c["id"], "en_entrainement")
    magasin.changer_etat(c["id"], "livree")
    assert [x["id"] for x in magasin.livrees()] == [c["id"]]
```

- [ ] **Step 2: Lancer les tests pour vérifier qu'ils échouent**

Run: `cd briques/ecoute && python3 -m pytest test_commandes.py -v -k "proprietaire or court_circuite"`
Expected: FAIL — `TypeError: creer() got an unexpected keyword argument 'proprietaire'` (et `lister()`/`get()` ne prennent pas encore ce paramètre).

- [ ] **Step 3: Migrer la table (`init_db`)**

Dans `briques/ecoute/commandes.py`, remplacer la méthode `init_db` :
```python
    def init_db(self) -> None:
        with self._c() as c:
            c.execute("""
                CREATE TABLE IF NOT EXISTS commandes (
                    id            TEXT PRIMARY KEY,
                    nom_marque    TEXT NOT NULL,
                    modele        TEXT NOT NULL,       -- slug = stem du fichier ONNX livré
                    statut        TEXT NOT NULL,
                    prix_cents    INTEGER NOT NULL,
                    devise        TEXT NOT NULL,
                    stripe_session_id TEXT,
                    factice       INTEGER DEFAULT 0,   -- 1 = modèle stand-in (pas un vrai entraînement GPU)
                    relances      INTEGER DEFAULT 0,
                    message       TEXT,
                    cree_le       TEXT NOT NULL,
                    maj_le        TEXT NOT NULL
                )
            """)
```
par :
```python
    def init_db(self) -> None:
        with self._c() as c:
            c.execute("""
                CREATE TABLE IF NOT EXISTS commandes (
                    id            TEXT PRIMARY KEY,
                    nom_marque    TEXT NOT NULL,
                    modele        TEXT NOT NULL,       -- slug = stem du fichier ONNX livré
                    statut        TEXT NOT NULL,
                    prix_cents    INTEGER NOT NULL,
                    devise        TEXT NOT NULL,
                    stripe_session_id TEXT,
                    factice       INTEGER DEFAULT 0,   -- 1 = modèle stand-in (pas un vrai entraînement GPU)
                    relances      INTEGER DEFAULT 0,
                    message       TEXT,
                    cree_le       TEXT NOT NULL,
                    maj_le        TEXT NOT NULL,
                    proprietaire  TEXT NOT NULL DEFAULT 'perso'  -- S184 : isolation par personne
                )
            """)
            colonnes = {row["name"] for row in c.execute("PRAGMA table_info(commandes)")}
            if "proprietaire" not in colonnes:
                c.execute(
                    "ALTER TABLE commandes ADD COLUMN proprietaire TEXT NOT NULL DEFAULT 'perso'"
                )
```

- [ ] **Step 4: Scoper `_en_cours_pour_marque` par propriétaire**

Remplacer :
```python
    def _en_cours_pour_marque(self, modele: str) -> dict | None:
        """Une commande NON terminale pour ce slug (idempotence : pas de doublon)."""
        with self._c() as c:
            row = c.execute(
                "SELECT * FROM commandes WHERE modele = ? AND statut NOT IN ('livree','echec') "
                "ORDER BY cree_le DESC LIMIT 1",
                (modele,),
            ).fetchone()
        return dict(row) if row else None
```
par :
```python
    def _en_cours_pour_marque(self, modele: str, proprietaire: str) -> dict | None:
        """Une commande NON terminale pour ce slug ET ce propriétaire (idempotence par
        personne, S184 : deux propriétaires peuvent chacun commander la même marque)."""
        with self._c() as c:
            row = c.execute(
                "SELECT * FROM commandes WHERE modele = ? AND proprietaire = ? "
                "AND statut NOT IN ('livree','echec') ORDER BY cree_le DESC LIMIT 1",
                (modele, proprietaire),
            ).fetchone()
        return dict(row) if row else None
```

- [ ] **Step 5: Ajouter le filtre optionnel à `lister`**

Remplacer :
```python
    def lister(self, statut: str | None = None) -> list[dict]:
        with self._c() as c:
            if statut:
                rows = c.execute(
                    "SELECT * FROM commandes WHERE statut = ? ORDER BY cree_le", (statut,)
                ).fetchall()
            else:
                rows = c.execute("SELECT * FROM commandes ORDER BY cree_le").fetchall()
        return [dict(r) for r in rows]
```
par :
```python
    def lister(self, statut: str | None = None, proprietaire: str | None = None) -> list[dict]:
        """Sans `proprietaire` (None) : aucun filtre — usage interne (file d'entraînement,
        catalogue partagé `livrees()`). Avec `proprietaire` : isolation par personne (S184)."""
        clauses: list[str] = []
        params: list[str] = []
        if statut:
            clauses.append("statut = ?")
            params.append(statut)
        if proprietaire is not None:
            clauses.append("proprietaire = ?")
            params.append(proprietaire)
        where = f"WHERE {' AND '.join(clauses)} " if clauses else ""
        with self._c() as c:
            rows = c.execute(f"SELECT * FROM commandes {where}ORDER BY cree_le", params).fetchall()
        return [dict(r) for r in rows]
```

- [ ] **Step 6: Ajouter le filtre optionnel à `get`**

Remplacer :
```python
    def get(self, cid: str) -> dict | None:
        with self._c() as c:
            row = c.execute("SELECT * FROM commandes WHERE id = ?", (cid,)).fetchone()
        return dict(row) if row else None
```
par :
```python
    def get(self, cid: str, proprietaire: str | None = None) -> dict | None:
        """Sans `proprietaire` (None) : accès interne, pas de filtre. Avec : renvoie None
        si la commande appartient à quelqu'un d'autre (S184 — la route appelante fait 404,
        pas 403, motif mail/restaurant : ne pas révéler l'existence)."""
        with self._c() as c:
            row = c.execute("SELECT * FROM commandes WHERE id = ?", (cid,)).fetchone()
        c_dict = dict(row) if row else None
        if c_dict and proprietaire is not None and c_dict["proprietaire"] != proprietaire:
            return None
        return c_dict
```

- [ ] **Step 7: Ajouter le propriétaire à `creer`**

Remplacer :
```python
    def creer(self, nom_marque: str) -> dict:
        """Crée une commande `en_attente_paiement`. **Idempotent** : si une commande
        non terminale existe déjà pour cette marque, on la rend (pas de double-débit)."""
        self.init_db()
        slug = slugifier(nom_marque)
        if not slug:
            raise ValueError("Nom de marque vide ou non prononçable.")
        existante = self._en_cours_pour_marque(slug)
        if existante:
            return existante
        maintenant = datetime.utcnow().isoformat()
        cid = str(uuidlib.uuid4())
        with self._c() as c:
            c.execute(
                "INSERT INTO commandes (id, nom_marque, modele, statut, prix_cents, devise, "
                "stripe_session_id, factice, relances, message, cree_le, maj_le) "
                "VALUES (?,?,?,?,?,?,?,0,0,?,?,?)",
                (cid, nom_marque, slug, "en_attente_paiement", PRIX_CENTS, DEVISE,
                 None, None, maintenant, maintenant),
            )
        return self.get(cid)
```
par :
```python
    def creer(self, nom_marque: str, proprietaire: str = "perso") -> dict:
        """Crée une commande `en_attente_paiement` pour `proprietaire`. **Idempotent** par
        (marque, propriétaire) : si CE propriétaire a déjà une commande non terminale pour
        cette marque, on la rend (pas de double-débit) — un autre propriétaire peut commander
        la même marque indépendamment (S184).

        Si la marque est déjà **livrée** (catalogue partagé, peu importe qui l'a payée),
        court-circuite : `{"deja_disponible": True, "modele": slug}`, aucune nouvelle
        commande ni paiement (évite de refacturer un modèle déjà entraîné et public)."""
        self.init_db()
        slug = slugifier(nom_marque)
        if not slug:
            raise ValueError("Nom de marque vide ou non prononçable.")
        if any(c["modele"] == slug for c in self.livrees()):
            return {"deja_disponible": True, "modele": slug}
        existante = self._en_cours_pour_marque(slug, proprietaire)
        if existante:
            return existante
        maintenant = datetime.utcnow().isoformat()
        cid = str(uuidlib.uuid4())
        with self._c() as c:
            c.execute(
                "INSERT INTO commandes (id, nom_marque, modele, statut, prix_cents, devise, "
                "stripe_session_id, factice, relances, message, cree_le, maj_le, proprietaire) "
                "VALUES (?,?,?,?,?,?,?,0,0,?,?,?,?)",
                (cid, nom_marque, slug, "en_attente_paiement", PRIX_CENTS, DEVISE,
                 None, None, maintenant, maintenant, proprietaire),
            )
        return self.get(cid)
```

- [ ] **Step 8: Ajouter `proprietaire` à la projection `vue`**

Dans la fonction `vue(c: dict) -> dict`, ajouter la clé (n'importe où dans le dict retourné, par exemple juste après `"devise": c["devise"],`) :
```python
        "proprietaire": c.get("proprietaire", "perso"),
```

- [ ] **Step 9: Lancer tous les tests de `test_commandes.py`**

Run: `cd briques/ecoute && python3 -m pytest test_commandes.py -v`
Expected: PASS — les 5 nouveaux tests ET les tests déjà existants (`test_creer_en_attente`,
`test_idempotent_pas_de_doublon`, `test_transitions_gardees`, `test_marquer_payee_idempotent`,
`test_changer_etat_idempotent_meme_etat`, `test_incr_relance`, `test_livrees_et_session`,
`test_vue_projection`) — tous inchangés, `proprietaire` a partout un défaut rétrocompatible.

- [ ] **Step 10: Commit**

```bash
git add briques/ecoute/commandes.py briques/ecoute/test_commandes.py
git commit -m "feat(ecoute): colonne proprietaire + isolation par personne dans MagasinCommandes (S184)

creer/lister/get prennent un propriétaire optionnel (défaut 'perso', rétrocompat).
Catalogue livré (livrees()) reste global. Court-circuite une 2e commande pour une
marque déjà livrée (évite un double paiement)."
```

---

### Task 3: Dépendances d'identité `briques/ecoute/auth.py`

**Files:**
- Create: `briques/ecoute/auth.py`
- Test: `briques/ecoute/test_auth.py`

**Interfaces:**
- Consumes: rien (module autonome).
- Produces (consommé par Task 4) : `auth.identite(x_api_key: str | None, authorization: str | None, x_user_id: str | None) -> str` (dépendance FastAPI, renvoie le propriétaire courant, lève `HTTPException(401)` si `ECOUTE_KEY` est configurée et que la clé présentée ne correspond pas) ; `auth.service_key(x_api_key: str | None, authorization: str | None) -> None` (dépendance FastAPI, protège une route de service sans notion de personne).

- [ ] **Step 1: Écrire les tests qui échouent**

Créer `briques/ecoute/test_auth.py` :
```python
"""Identité de l'appelant pour ecoute (S184) — motif agenda S182 : cercle privé par personne."""
import pytest
from fastapi import HTTPException

import auth


def test_sans_cle_configuree_repli_perso(monkeypatch):
    monkeypatch.delenv("ECOUTE_KEY", raising=False)
    assert auth.identite(x_api_key=None, authorization=None, x_user_id=None) == "perso"
    assert auth.identite(x_api_key=None, authorization=None, x_user_id="alice") == "alice"


def test_avec_cle_configuree_et_bonne_cle_honore_x_user_id(monkeypatch):
    monkeypatch.setenv("ECOUTE_KEY", "cle-coeur")
    assert auth.identite(x_api_key="cle-coeur", authorization=None, x_user_id="alice") == "alice"
    assert auth.identite(x_api_key="cle-coeur", authorization=None, x_user_id=None) == "perso"


def test_avec_cle_configuree_mauvaise_cle_401(monkeypatch):
    monkeypatch.setenv("ECOUTE_KEY", "cle-coeur")
    with pytest.raises(HTTPException) as exc:
        auth.identite(x_api_key="mauvaise", authorization=None, x_user_id="alice")
    assert exc.value.status_code == 401


def test_avec_cle_configuree_sans_cle_presentee_401(monkeypatch):
    monkeypatch.setenv("ECOUTE_KEY", "cle-coeur")
    with pytest.raises(HTTPException) as exc:
        auth.identite(x_api_key=None, authorization=None, x_user_id="alice")
    assert exc.value.status_code == 401


def test_bearer_authorization_accepte(monkeypatch):
    monkeypatch.setenv("ECOUTE_KEY", "cle-coeur")
    assert auth.identite(
        x_api_key=None, authorization="Bearer cle-coeur", x_user_id="bob") == "bob"


def test_service_key_sans_cle_configuree_ouvert(monkeypatch):
    monkeypatch.delenv("ECOUTE_KEY", raising=False)
    auth.service_key(x_api_key=None, authorization=None)  # ne lève pas


def test_service_key_avec_cle_valide_ok(monkeypatch):
    monkeypatch.setenv("ECOUTE_KEY", "cle-coeur")
    auth.service_key(x_api_key="cle-coeur", authorization=None)  # ne lève pas


def test_service_key_avec_mauvaise_cle_401(monkeypatch):
    monkeypatch.setenv("ECOUTE_KEY", "cle-coeur")
    with pytest.raises(HTTPException) as exc:
        auth.service_key(x_api_key="mauvaise", authorization=None)
    assert exc.value.status_code == 401
```

- [ ] **Step 2: Lancer les tests pour vérifier qu'ils échouent**

Run: `cd briques/ecoute && python3 -m pytest test_auth.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'auth'`.

- [ ] **Step 3: Créer `briques/ecoute/auth.py`**

```python
"""Identité de l'appelant pour les commandes de mot-clé sur mesure (S184).

Motif copié de l'agenda (S182, `briques/agenda/backend/auth.py` branche S2S) : `ECOUTE_KEY`
est le gage de confiance du Cœur — seul lui la détient et peut donc forwarder l'identité de
l'utilisateur connecté via `X-User-Id`. Sans clé configurée, la brique reste en mode ouvert
(dev/démo, convention du monorepo) : l'identité retombe sur `X-User-Id` si présent, sinon
`"perso"` (repli mono-user historique).
"""
from __future__ import annotations

import os
from typing import Optional

from fastapi import Header, HTTPException


def _presentee(x_api_key: Optional[str], authorization: Optional[str]) -> Optional[str]:
    return x_api_key or (authorization or "").removeprefix("Bearer ").strip() or None


def identite(x_api_key: Optional[str] = Header(None),
             authorization: Optional[str] = Header(None),
             x_user_id: Optional[str] = Header(None)) -> str:
    """Propriétaire courant pour les routes `/commandes*` : isolation par personne."""
    cle_configuree = os.environ.get("ECOUTE_KEY")
    if not cle_configuree:
        return x_user_id or "perso"
    if _presentee(x_api_key, authorization) != cle_configuree:
        raise HTTPException(401, "Clé API manquante ou invalide (header X-API-Key).")
    return x_user_id or "perso"


def service_key(x_api_key: Optional[str] = Header(None),
                authorization: Optional[str] = Header(None)) -> None:
    """Garde `/entrainement/traiter` : credential de service (l'horloge S29), pas une
    identité personne — cette route traite la file pour tout le monde."""
    cle_configuree = os.environ.get("ECOUTE_KEY")
    if not cle_configuree:
        return
    if _presentee(x_api_key, authorization) != cle_configuree:
        raise HTTPException(401, "Clé API manquante ou invalide (header X-API-Key).")
```

- [ ] **Step 4: Lancer les tests pour vérifier qu'ils passent**

Run: `cd briques/ecoute && python3 -m pytest test_auth.py -v`
Expected: PASS — les 8 tests.

- [ ] **Step 5: Commit**

```bash
git add briques/ecoute/auth.py briques/ecoute/test_auth.py
git commit -m "feat(ecoute): auth.py — identite()/service_key(), motif S182 (S184)"
```

---

### Task 4: Câblage des routes + isolation de bout en bout

**Files:**
- Modify: `briques/ecoute/main.py` (routes `/commandes*` et `/entrainement/traiter`)
- Create: `briques/ecoute/conftest.py`
- Create: `briques/ecoute/test_isolation.py`
- Modify: `briques/ecoute/manifest.json` (tâche `file-entrainement-wakeword`)
- Modify: `briques/ecoute/docker-compose.yml` (commentaire `ECOUTE_KEY`)
- Modify: `core/docker-compose.yml` (commentaire `ECOUTE_KEY`)

**Interfaces:**
- Consumes: `auth.identite` et `auth.service_key` (Task 3) ; `MagasinCommandes.creer/lister/get`
  avec `proprietaire` (Task 2) ; `BRIQUES_PAR_PERSONNE`/`entetes_par_personne` (Task 1, déjà
  actif côté Cœur — rien à modifier ici, `_entetes_brique("ecoute")` forwarde déjà X-User-Id).
- Produces: rien de nouveau pour d'autres tâches (dernière tâche du sprint).

- [ ] **Step 1: Créer `briques/ecoute/conftest.py`**

```python
"""Config de test : DB temporaire AVANT tout import des modules (S184, motif mail/conftest.py)."""
import os
import tempfile

_db = os.path.join(tempfile.gettempdir(), "ecoute_test.db")
os.environ["COMMANDES_DB"] = _db
os.environ.pop("ECOUTE_KEY", None)  # mode ouvert par défaut ; test_isolation.py la fixe elle-même

if os.path.exists(_db):
    os.remove(_db)
```

- [ ] **Step 2: Écrire `briques/ecoute/test_isolation.py` (échouera tant que main.py n'est pas câblé)**

```python
"""Cloisonnement par personne (S184) : commandes de mot-clé sur mesure privées, catalogue
partagé. Motif copié de briques/mail/test_isolation.py, adapté à l'identité par X-User-Id
sous une clé de service partagée (ECOUTE_KEY) — pas une clé par tenant."""
import os

import pytest
from fastapi.testclient import TestClient

os.environ["ECOUTE_KEY"] = "cle-coeur-test"

import main  # noqa: E402 (import après avoir posé ECOUTE_KEY)

client = TestClient(main.app)
ALICE = {"X-API-Key": "cle-coeur-test", "X-User-Id": "alice"}
BOB = {"X-API-Key": "cle-coeur-test", "X-User-Id": "bob"}


@pytest.fixture(autouse=True)
def _sans_stripe(monkeypatch):
    monkeypatch.delenv("STRIPE_SECRET_KEY", raising=False)
    monkeypatch.delenv("STRIPE_WEBHOOK_SECRET", raising=False)


def test_sans_cle_commandes_401():
    assert client.get("/commandes").status_code == 401


def test_commande_d_alice_invisible_pour_bob():
    cree = client.post("/commandes", json={"nom_marque": "Acme Alice"}, headers=ALICE).json()
    cid = cree["commande"]["id"]
    assert client.get(f"/commandes/{cid}", headers=BOB).status_code == 404
    assert client.get(f"/commandes/{cid}", headers=ALICE).status_code == 200


def test_liste_des_commandes_filtree_par_personne():
    client.post("/commandes", json={"nom_marque": "Marque Alice"}, headers=ALICE)
    client.post("/commandes", json={"nom_marque": "Marque Bob"}, headers=BOB)
    marques_alice = {c["nom_marque"] for c in client.get("/commandes", headers=ALICE).json()}
    marques_bob = {c["nom_marque"] for c in client.get("/commandes", headers=BOB).json()}
    assert "Marque Alice" in marques_alice and "Marque Alice" not in marques_bob
    assert "Marque Bob" in marques_bob and "Marque Bob" not in marques_alice


def test_bob_ne_peut_pas_payer_la_commande_d_alice():
    cree = client.post("/commandes", json={"nom_marque": "Payer Alice"}, headers=ALICE).json()
    cid = cree["commande"]["id"]
    assert client.post(f"/commandes/{cid}/payer", headers=BOB).status_code == 404


def test_noms_reste_partage_entre_alice_et_bob():
    assert client.get("/noms", headers=ALICE).json() == client.get("/noms", headers=BOB).json()


def test_entrainement_traiter_exige_la_cle_de_service():
    assert client.post("/entrainement/traiter").status_code == 401
    r = client.post("/entrainement/traiter", headers={"X-API-Key": "cle-coeur-test"})
    assert r.status_code == 200
    assert "resume" in r.json()
```

- [ ] **Step 3: Lancer les tests pour vérifier qu'ils échouent**

Run: `cd briques/ecoute && python3 -m pytest test_isolation.py -v`
Expected: FAIL — `test_sans_cle_commandes_401` échoue (`assert 200 == 401`, les routes ne sont
pas encore protégées) ; les tests suivants échouent aussi (pas de filtrage par propriétaire).

- [ ] **Step 4: Câbler `briques/ecoute/main.py`**

Ajouter l'import (juste après `from detecteur import Detecteur, MOT_DEFAUT, SEUIL_DEFAUT`, en
haut du fichier) :
```python
import auth
```

Remplacer la section « Palier payant : commandes » :
```python
class CommandeBody(BaseModel):
    nom_marque: str


@app.get("/paiement/etat", tags=["paiement"])
async def paiement_etat():
    """État honnête de la config Stripe (jamais la clé) — mock vs test/live."""
    return paiement.etat()


@app.post("/commandes", tags=["commandes"])
async def creer_commande(body: CommandeBody):
    """Commande un nom de marque sur mesure : crée la commande (idempotente) et émet un
    lien de paiement Stripe (réel ou mock honnête)."""
    try:
        commande = MAGASIN.creer(body.nom_marque)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    # Émet/rafraîchit le lien de paiement tant que c'est en attente.
    checkout = None
    if commande["statut"] == "en_attente_paiement":
        try:
            checkout = paiement.creer_checkout(commande)
        except RuntimeError as e:
            raise HTTPException(status_code=502, detail=str(e))
        commande = MAGASIN.attacher_session(commande["id"], checkout["session_id"])
    return {"commande": cmd.vue(commande), "paiement": checkout}


@app.get("/commandes", tags=["commandes"])
async def lister_commandes(statut: str | None = None):
    MAGASIN.init_db()
    return [cmd.vue(c) for c in MAGASIN.lister(statut)]


@app.get("/commandes/{cid}", tags=["commandes"])
async def get_commande(cid: str):
    c = MAGASIN.get(cid)
    if not c:
        raise HTTPException(status_code=404, detail="Commande inconnue.")
    return cmd.vue(c)


@app.post("/commandes/{cid}/payer", tags=["commandes"])
async def payer_mock(cid: str):
    """Confirmation **mock** (mode dev sans Stripe). En mode live, c'est le webhook signé
    qui confirme → ici on refuse (409) pour ne pas court-circuiter la signature (cf. S21)."""
    if paiement.resoudre_cle():
        raise HTTPException(status_code=409,
                            detail="Stripe configuré : le paiement se confirme par le webhook signé, pas ici.")
    c = MAGASIN.get(cid)
    if not c:
        raise HTTPException(status_code=404, detail="Commande inconnue.")
    return cmd.vue(MAGASIN.marquer_payee(cid))
```
par :
```python
class CommandeBody(BaseModel):
    nom_marque: str


@app.get("/paiement/etat", tags=["paiement"])
async def paiement_etat():
    """État honnête de la config Stripe (jamais la clé) — mock vs test/live."""
    return paiement.etat()


@app.post("/commandes", tags=["commandes"])
async def creer_commande(body: CommandeBody, proprietaire: str = Depends(auth.identite)):
    """Commande un nom de marque sur mesure au nom de `proprietaire` (S184 : isolation par
    personne) : crée la commande (idempotente par personne) et émet un lien de paiement
    Stripe (réel ou mock honnête). Si la marque est déjà livrée (catalogue partagé), aucune
    nouvelle commande n'est créée."""
    try:
        commande = MAGASIN.creer(body.nom_marque, proprietaire=proprietaire)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if commande.get("deja_disponible"):
        return {"commande": None, "paiement": None, "deja_disponible": True,
                "message": f"« {body.nom_marque} » est déjà disponible dans le catalogue."}
    # Émet/rafraîchit le lien de paiement tant que c'est en attente.
    checkout = None
    if commande["statut"] == "en_attente_paiement":
        try:
            checkout = paiement.creer_checkout(commande)
        except RuntimeError as e:
            raise HTTPException(status_code=502, detail=str(e))
        commande = MAGASIN.attacher_session(commande["id"], checkout["session_id"])
    return {"commande": cmd.vue(commande), "paiement": checkout}


@app.get("/commandes", tags=["commandes"])
async def lister_commandes(statut: str | None = None,
                           proprietaire: str = Depends(auth.identite)):
    MAGASIN.init_db()
    return [cmd.vue(c) for c in MAGASIN.lister(statut, proprietaire=proprietaire)]


@app.get("/commandes/{cid}", tags=["commandes"])
async def get_commande(cid: str, proprietaire: str = Depends(auth.identite)):
    c = MAGASIN.get(cid, proprietaire=proprietaire)
    if not c:
        raise HTTPException(status_code=404, detail="Commande inconnue.")
    return cmd.vue(c)


@app.post("/commandes/{cid}/payer", tags=["commandes"])
async def payer_mock(cid: str, proprietaire: str = Depends(auth.identite)):
    """Confirmation **mock** (mode dev sans Stripe). En mode live, c'est le webhook signé
    qui confirme → ici on refuse (409) pour ne pas court-circuiter la signature (cf. S21)."""
    if paiement.resoudre_cle():
        raise HTTPException(status_code=409,
                            detail="Stripe configuré : le paiement se confirme par le webhook signé, pas ici.")
    c = MAGASIN.get(cid, proprietaire=proprietaire)
    if not c:
        raise HTTPException(status_code=404, detail="Commande inconnue.")
    return cmd.vue(MAGASIN.marquer_payee(cid))
```

Ajouter l'import `Depends` s'il n'est pas déjà présent dans la ligne d'import FastAPI en haut
du fichier (vérifier : `from fastapi import FastAPI, HTTPException, Request, WebSocket,
WebSocketDisconnect` ne contient PAS `Depends` — l'ajouter) :
```python
from fastapi import (Depends, FastAPI, HTTPException, Request, WebSocket,
                     WebSocketDisconnect)
```

Remplacer la route `/entrainement/traiter` :
```python
@app.post("/entrainement/traiter", tags=["entrainement"])
async def traiter():
    """Tâche périodique appelée par l'**horloge S29** (déclarée au manifest) : avance la
    file (payee→entraînement→livrée) et relance les impayées. Idempotente."""
    return entrainement.traiter_file(MAGASIN)
```
par :
```python
@app.post("/entrainement/traiter", tags=["entrainement"])
async def traiter(_cle: None = Depends(auth.service_key)):
    """Tâche périodique appelée par l'**horloge S29** (déclarée au manifest) : avance la
    file (payee→entraînement→livrée) et relance les impayées. Idempotente. Gardée par
    ECOUTE_KEY (S184) : credential de service, pas une identité personne."""
    return entrainement.traiter_file(MAGASIN)
```

- [ ] **Step 5: Lancer les tests d'isolation**

Run: `cd briques/ecoute && python3 -m pytest test_isolation.py -v`
Expected: PASS — les 6 tests.

- [ ] **Step 6: Lancer toute la suite de la brique**

Run: `cd briques/ecoute && python3 -m pytest -v`
Expected: PASS — tous les fichiers (`test_catalogue.py`, `test_commandes.py`, `test_detecteur.py`,
`test_entrainement.py`, `test_paiement.py`, `test_auth.py`, `test_isolation.py`).

- [ ] **Step 7: Déclarer `ECOUTE_KEY` pour la tâche horloge dans le manifest**

Dans `briques/ecoute/manifest.json`, dans l'objet de la tâche `file-entrainement-wakeword`,
ajouter le champ `entete_token_env` (motif identique à `briques/geo/manifest.json`) :
```json
    {
      "nom": "file-entrainement-wakeword",
      "description": "Avance la file des noms de marque (payée→entraînement→livrée) et relance les commandes impayées.",
      "methode": "POST",
      "chemin": "/entrainement/traiter",
      "cadence_heures": 0.25,
      "idempotent": true,
      "entete_token_env": "ECOUTE_KEY",
      "tolere_echec": true
    }
```

- [ ] **Step 8: Documenter `ECOUTE_KEY` dans les docker-compose (motif AGENDA_KEY)**

Dans `briques/ecoute/docker-compose.yml`, dans le bloc `environment:`, ajouter (juste avant la
ligne `# ENTRAINEUR_CMD...`) :
```yaml
      # ECOUTE_KEY (S184, pilotage /commandes par le Cœur en X-API-Key + X-User-Id) vient du
      # .env racine via env_file — NE PAS la redéclarer en `ECOUTE_KEY=${ECOUTE_KEY:-}` (piège
      # « env shadow » : chaîne VIDE qui écraserait la vraie valeur → brique vue mono-user).
```

Dans `core/docker-compose.yml`, juste après le commentaire existant sur `AGENDA_KEY` (repéré
par le texte "AGENDA_KEY vide ⇒ la surface /service"), ajouter :
```yaml
      # Idem pour ECOUTE_KEY (S184, commandes de mot-clé sur mesure) : vient du .env racine,
      # ne pas la redéclarer ici.
```

- [ ] **Step 9: Lancer la suite complète du Cœur une dernière fois**

Run: `cd /Users/garinat_t/Desktop/Workplace && VAULT_SECRET=test GATEWAY_KEY=test make test-core`
Expected: PASS.

- [ ] **Step 10: Commit**

```bash
git add briques/ecoute/main.py briques/ecoute/conftest.py briques/ecoute/test_isolation.py \
        briques/ecoute/manifest.json briques/ecoute/docker-compose.yml core/docker-compose.yml
git commit -m "feat(ecoute): isolation par personne des commandes de mot-clé sur mesure (S184)

/commandes* exige l'identité (ECOUTE_KEY + X-User-Id, motif agenda S182) ; 404 (pas 403)
sur la commande d'un autre propriétaire. /entrainement/traiter gardé par ECOUTE_KEY (credential
de service). /noms et le WS /ecoute restent partagés (catalogue du foyer)."
```
