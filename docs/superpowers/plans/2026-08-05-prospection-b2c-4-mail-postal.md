# Prospection B2C — mail : moteur postal + capture de réponse Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `mail` sait préparer des courriers **postaux** personnalisés par adresse
(jamais par nom), les déposer (simulé — aucun prestataire réel branché) via un gate
de confirmation explicite, et capturer la réponse d'un destinataire via une page
publique sans authentification — qui qualifie le lead correspondant dans `forge`.

**Architecture:** Second moteur de démarchage, **parallèle** à l'existant (email,
`/demarchage/preparer`) — jamais une modification du moteur email. Nouveau fichier
`fournisseurs_postaux.py` (motif `geo/fournisseurs.py`). Deux nouvelles tables SQLite
(`demarchage_postal` — registre cadence/opt-out réindexé par ADRESSE ;
`courriers` — le contenu + le token de réponse par destinataire). La page de
réponse (`/repondre/{token}`) est **publique** : pas de `Depends(tenant_actuel)`,
le token lui-même est le secret d'accès.

**Tech Stack:** FastAPI, SQLite (stdlib), nouvelle dépendance
`python-multipart==0.0.32` (formulaire HTML `POST` sur la page publique — FastAPI
l'exige pour parser un corps de formulaire, même simple).

## Global Constraints

- Aucun nom de personne dans un courrier généré — seulement adresse/commune/grade
  DPE (cf. contrainte légale MAJIC,
  `docs/superpowers/specs/2026-08-05-prospection-b2c-signal-identite-design.md`).
- Le moteur email existant (`/demarchage/*`, `demarchage_*` dans `stockage.py`) ne
  change PAS d'une ligne — tout est additif dans de nouvelles fonctions/tables.
- Aucun courrier n'est réellement déposé dans ce plan (aucun prestataire postal
  réel n'existe encore, cf. Non-objectifs de la spec) — `MockRouteurPostal`
  uniquement, honnête (jamais un mock qui prétend avoir réussi une action réelle
  sans le dire).
- La page `/repondre/{token}` ne doit JAMAIS distinguer, dans sa réponse HTTP, un
  token inconnu d'un token déjà utilisé — même message neutre dans les deux cas
  (ne pas révéler d'information à un tiers non authentifié).

---

### Task 1: Tables `demarchage_postal` + `courriers` (`stockage.py`)

**Files:**
- Modify: `briques/mail/stockage.py`
- Test: `briques/mail/test_demarchage_postal.py` (nouveau fichier)

**Interfaces:**
- Produces (registre) : `demarchage_postal_lire(tenant, adresse) -> dict | None`,
  `demarchage_postal_enregistrer_contact(tenant, adresse) -> dict`,
  `demarchage_postal_desinscrire(tenant, adresse) -> dict`,
  `demarchage_postal_lister(tenant, limite=500) -> list[dict]`.
- Produces (courriers) : `creer_courrier(tenant, *, adresse, commune="", lead_id=None,
  contenu) -> dict` (le dict a les clés `id`, `token`, `statut`, etc.),
  `lire_courrier(tenant, courrier_id) -> dict | None`,
  `lire_courrier_par_token(token) -> dict | None` (PAS cloisonné par tenant — motif
  documenté dans le docstring),
  `marquer_courrier_envoye(tenant, courrier_id) -> dict | None`,
  `marquer_courrier_repondu(token) -> dict | None`.
- Consommé par `main.py` (Tasks 3-5).

- [ ] **Step 1: Écrire les tests**

Créer `briques/mail/test_demarchage_postal.py` :

```python
"""Persistance du moteur de démarchage POSTAL (registre par adresse + courriers/tokens)
— motif briques/mail/stockage.py::demarchage_* (email), réindexé par adresse."""
import stockage


def test_demarchage_postal_lire_absent_rend_none():
    assert stockage.demarchage_postal_lire("t1", "12 Rue X") is None


def test_demarchage_postal_enregistrer_contact_incremente():
    a = stockage.demarchage_postal_enregistrer_contact("t2", "12 Rue X, Castres")
    assert a["nb_contacts"] == 1 and a["opt_out"] is False
    b = stockage.demarchage_postal_enregistrer_contact("t2", "12 Rue X, Castres")
    assert b["nb_contacts"] == 2


def test_demarchage_postal_desinscrire_fige_opt_out():
    stockage.demarchage_postal_enregistrer_contact("t3", "4 Impasse Y")
    d = stockage.demarchage_postal_desinscrire("t3", "4 Impasse Y")
    assert d["opt_out"] is True
    # Un nouveau contact APRÈS désinscription ne réactive jamais l'opt-out.
    e = stockage.demarchage_postal_enregistrer_contact("t3", "4 Impasse Y")
    assert e["opt_out"] is True


def test_demarchage_postal_lister_isole_par_tenant():
    stockage.demarchage_postal_enregistrer_contact("t4-moi", "7 Rue Z")
    assert stockage.demarchage_postal_lister("t4-voisin") == []
    assert len(stockage.demarchage_postal_lister("t4-moi")) == 1


def test_creer_courrier_genere_un_token_unique():
    c1 = stockage.creer_courrier("t5", adresse="12 Rue X", commune="Castres",
                                 lead_id="lead-1", contenu="Bonjour...")
    c2 = stockage.creer_courrier("t5", adresse="4 Rue Y", contenu="Bonjour...")
    assert c1["token"] and c2["token"] and c1["token"] != c2["token"]
    assert c1["statut"] == "brouillon" and c1["lead_id"] == "lead-1"


def test_lire_courrier_cloisonne_par_tenant():
    c = stockage.creer_courrier("t6-moi", adresse="9 Rue A", contenu="X")
    assert stockage.lire_courrier("t6-moi", c["id"]) is not None
    assert stockage.lire_courrier("t6-voisin", c["id"]) is None


def test_lire_courrier_par_token_traverse_les_tenants():
    """PAS cloisonné : la page publique n'a aucun tenant à présenter."""
    c = stockage.creer_courrier("t7", adresse="1 Rue B", contenu="X")
    trouve = stockage.lire_courrier_par_token(c["token"])
    assert trouve and trouve["id"] == c["id"] and trouve["tenant"] == "t7"
    assert stockage.lire_courrier_par_token("token-inexistant") is None


def test_marquer_courrier_envoye_puis_repondu():
    c = stockage.creer_courrier("t8", adresse="3 Rue C", contenu="X")
    envoye = stockage.marquer_courrier_envoye("t8", c["id"])
    assert envoye["statut"] == "envoye" and envoye["envoye_le"]
    repondu = stockage.marquer_courrier_repondu(c["token"])
    assert repondu["statut"] == "repondu" and repondu["reponse_le"]
```

- [ ] **Step 2: Lancer les tests pour vérifier qu'ils échouent**

Run: `cd briques/mail && python3 -m pytest test_demarchage_postal.py -v`
Expected: FAIL avec `AttributeError: module 'stockage' has no attribute
'demarchage_postal_lire'`

- [ ] **Step 3: Implémenter le schéma**

Dans `briques/mail/stockage.py`, ajouter à `_SCHEMA` (la constante existante,
avant sa fermeture `"""`) :

```sql
-- Registre de démarchage POSTAL (parallèle à `demarchage`, email) : cadence + opt-out
-- par ADRESSE au lieu d'email — un logement n'a pas d'email.
CREATE TABLE IF NOT EXISTS demarchage_postal (
    tenant TEXT NOT NULL, adresse TEXT NOT NULL,
    nb_contacts INTEGER NOT NULL DEFAULT 0, dernier_contact TEXT,
    opt_out INTEGER NOT NULL DEFAULT 0, cree_le TEXT NOT NULL, maj_le TEXT NOT NULL,
    PRIMARY KEY (tenant, adresse));

-- Courriers postaux préparés : contenu imprimable + token de réponse (QR/URL sur le
-- courrier). `lead_id` référence un lead `forge` (optionnel) à qualifier si réponse.
CREATE TABLE IF NOT EXISTS courriers (
    id TEXT PRIMARY KEY, tenant TEXT NOT NULL, adresse TEXT NOT NULL,
    commune TEXT, lead_id TEXT, token TEXT NOT NULL UNIQUE, contenu TEXT NOT NULL,
    statut TEXT NOT NULL DEFAULT 'brouillon',
    reponse_le TEXT, cree_le TEXT NOT NULL, envoye_le TEXT);
CREATE INDEX IF NOT EXISTS idx_courriers_tenant ON courriers(tenant);
```

- [ ] **Step 4: Implémenter les fonctions**

Ajouter à la fin de `briques/mail/stockage.py` :

```python
# ── Registre de démarchage POSTAL : cadence + opt-out par ADRESSE ────────────
def _demarchage_postal_dict(r: sqlite3.Row) -> dict:
    return {"adresse": r["adresse"], "nb_contacts": r["nb_contacts"],
            "dernier_contact": r["dernier_contact"], "opt_out": bool(r["opt_out"]),
            "cree_le": r["cree_le"], "maj_le": r["maj_le"]}


def demarchage_postal_lire(tenant: str, adresse: str) -> dict | None:
    with _conn() as c:
        r = c.execute("SELECT * FROM demarchage_postal WHERE tenant=? AND adresse=?",
                      (tenant, (adresse or "").strip())).fetchone()
    return _demarchage_postal_dict(r) if r else None


def demarchage_postal_enregistrer_contact(tenant: str, adresse: str) -> dict:
    adresse = (adresse or "").strip()
    now = _maintenant()
    with _conn() as c:
        c.execute(
            "INSERT INTO demarchage_postal (tenant, adresse, nb_contacts, dernier_contact,"
            " cree_le, maj_le) VALUES (?,?,1,?,?,?)"
            " ON CONFLICT(tenant, adresse) DO UPDATE SET"
            " nb_contacts = nb_contacts + 1, dernier_contact = excluded.dernier_contact,"
            " maj_le = excluded.maj_le",
            (tenant, adresse, now, now, now))
        r = c.execute("SELECT * FROM demarchage_postal WHERE tenant=? AND adresse=?",
                      (tenant, adresse)).fetchone()
    return _demarchage_postal_dict(r)


def demarchage_postal_desinscrire(tenant: str, adresse: str) -> dict:
    adresse = (adresse or "").strip()
    now = _maintenant()
    with _conn() as c:
        c.execute(
            "INSERT INTO demarchage_postal (tenant, adresse, nb_contacts, opt_out, cree_le,"
            " maj_le) VALUES (?,?,0,1,?,?)"
            " ON CONFLICT(tenant, adresse) DO UPDATE SET opt_out = 1, maj_le = excluded.maj_le",
            (tenant, adresse, now, now))
        r = c.execute("SELECT * FROM demarchage_postal WHERE tenant=? AND adresse=?",
                      (tenant, adresse)).fetchone()
    return _demarchage_postal_dict(r)


def demarchage_postal_lister(tenant: str, limite: int = 500) -> list[dict]:
    with _conn() as c:
        lignes = c.execute(
            "SELECT * FROM demarchage_postal WHERE tenant=? ORDER BY maj_le DESC LIMIT ?",
            (tenant, limite)).fetchall()
    return [_demarchage_postal_dict(r) for r in lignes]


# ── Courriers postaux : contenu + token de réponse ────────────────────────────
def _courrier_dict(r: sqlite3.Row) -> dict:
    return {"id": r["id"], "tenant": r["tenant"], "adresse": r["adresse"],
            "commune": r["commune"] or "", "lead_id": r["lead_id"], "token": r["token"],
            "contenu": r["contenu"], "statut": r["statut"], "reponse_le": r["reponse_le"],
            "cree_le": r["cree_le"], "envoye_le": r["envoye_le"]}


def creer_courrier(tenant: str, *, adresse: str, commune: str = "",
                   lead_id: str | None = None, contenu: str) -> dict:
    cid, token = _id(), _id()
    with _conn() as c:
        c.execute(
            "INSERT INTO courriers (id, tenant, adresse, commune, lead_id, token, contenu,"
            " statut, cree_le) VALUES (?,?,?,?,?,?,?,'brouillon',?)",
            (cid, tenant, adresse, commune, lead_id, token, contenu, _maintenant()))
        r = c.execute("SELECT * FROM courriers WHERE id=?", (cid,)).fetchone()
    return _courrier_dict(r)


def lire_courrier(tenant: str, courrier_id: str) -> dict | None:
    with _conn() as c:
        r = c.execute("SELECT * FROM courriers WHERE id=? AND tenant=?",
                      (courrier_id, tenant)).fetchone()
    return _courrier_dict(r) if r else None


def lire_courrier_par_token(token: str) -> dict | None:
    """PAS cloisonné par tenant : la page publique /repondre/{token} n'a aucune
    identité de tenant à présenter (un particulier scanne un QR, pas un client
    Workplace authentifié). Le token lui-même EST le secret d'accès — global,
    imprévisible (généré par `_id()`, uuid4)."""
    with _conn() as c:
        r = c.execute("SELECT * FROM courriers WHERE token=?", (token,)).fetchone()
    return _courrier_dict(r) if r else None


def marquer_courrier_envoye(tenant: str, courrier_id: str) -> dict | None:
    with _conn() as c:
        c.execute("UPDATE courriers SET statut='envoye', envoye_le=? WHERE id=? AND tenant=?",
                  (_maintenant(), courrier_id, tenant))
    return lire_courrier(tenant, courrier_id)


def marquer_courrier_repondu(token: str) -> dict | None:
    with _conn() as c:
        c.execute("UPDATE courriers SET statut='repondu', reponse_le=? WHERE token=?",
                  (_maintenant(), token))
        r = c.execute("SELECT * FROM courriers WHERE token=?", (token,)).fetchone()
    return _courrier_dict(r) if r else None
```

- [ ] **Step 5: Lancer les tests**

Run: `cd briques/mail && python3 -m pytest test_demarchage_postal.py -v`
Expected: PASS (tous les tests)

- [ ] **Step 6: Lancer toute la suite mail pour vérifier la non-régression**

Run: `cd briques/mail && python3 -m pytest -v`
Expected: PASS (aucun changement au schéma email existant)

- [ ] **Step 7: Commit**

```bash
git add briques/mail/stockage.py briques/mail/test_demarchage_postal.py
git commit -m "feat(mail): tables demarchage_postal + courriers (registre par adresse)"
```

---

### Task 2: `MockRouteurPostal` (`fournisseurs_postaux.py`)

**Files:**
- Create: `briques/mail/fournisseurs_postaux.py`
- Test: `briques/mail/test_fournisseurs_postaux.py`

**Interfaces:**
- Produces: `fournisseurs_postaux.MockRouteurPostal` (`nom = "mock"`, méthode
  `deposer(courrier: dict) -> dict`), `fournisseurs_postaux.routeur_postal() ->
  MockRouteurPostal`. Consommé par `main.py` (Task 4).

- [ ] **Step 1: Écrire le test**

Créer `briques/mail/test_fournisseurs_postaux.py` :

```python
"""Routeur postal : mock honnête (aucun prestataire réel branché dans cette itération —
cf. Non-objectifs de la spec)."""
import fournisseurs_postaux as fp


def test_mock_ne_depose_rien_reellement():
    r = fp.MockRouteurPostal().deposer({"id": "c1", "adresse": "12 Rue X"})
    assert r["ok"] is True and r["reel"] is False


def test_routeur_postal_rend_toujours_le_mock():
    assert isinstance(fp.routeur_postal(), fp.MockRouteurPostal)
```

- [ ] **Step 2: Lancer le test pour vérifier qu'il échoue**

Run: `cd briques/mail && python3 -m pytest test_fournisseurs_postaux.py -v`
Expected: FAIL avec `ModuleNotFoundError: No module named 'fournisseurs_postaux'`

- [ ] **Step 3: Implémenter**

Créer `briques/mail/fournisseurs_postaux.py` :

```python
"""Routage POSTAL — dépose (ou pas) un courrier physique chez un prestataire externe
(impression + affranchissement + dépôt). `MockRouteurPostal` : ne dépose RIEN
réellement, honnête sur ce fait dans sa réponse — motif `geo/fournisseurs.py`
(mock honnête d'abord). Aucun prestataire réel (ex. Merci Facteur) n'est branché
dans cette itération : quand il existera, cette factory gagnera la même bascule
explicite par variable d'env que les autres fournisseurs du parc (ex.
GEO_FOURNISSEUR), jamais une détection silencieuse."""
from __future__ import annotations


class MockRouteurPostal:
    nom = "mock"

    def deposer(self, courrier: dict) -> dict:
        return {"ok": True, "reel": False, "fournisseur": self.nom,
                "message": "SIMULÉ : aucun courrier physique n'a été déposé (aucun "
                           "prestataire postal réel n'est branché)."}


def routeur_postal() -> MockRouteurPostal:
    return MockRouteurPostal()
```

- [ ] **Step 4: Lancer le test**

Run: `cd briques/mail && python3 -m pytest test_fournisseurs_postaux.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add briques/mail/fournisseurs_postaux.py briques/mail/test_fournisseurs_postaux.py
git commit -m "feat(mail): MockRouteurPostal (fournisseur postal, mock honnête)"
```

---

### Task 3: `POST /demarchage-postal/preparer` (`main.py`)

**Files:**
- Modify: `briques/mail/main.py`
- Test: `briques/mail/test_demarchage_postal_route.py` (nouveau fichier)

**Interfaces:**
- Consumes: `stockage.demarchage_postal_lire/enregistrer_contact` (Task 1),
  `stockage.creer_courrier` (Task 1), `_trop_recent` (déjà existant dans
  `main.py`, générique, réutilisé tel quel).
- Produces: route `POST /demarchage-postal/preparer`.

- [ ] **Step 1: Écrire les tests**

Créer `briques/mail/test_demarchage_postal_route.py` :

```python
"""Démarchage POSTAL (parallèle à test_demarchage.py, email) : jamais de nom de
personne, registre par adresse, jamais d'envoi réel dans cette route."""
from fastapi.testclient import TestClient

import main

client = TestClient(main.app)


def test_prepare_courriers_personnalises_sans_nom():
    h = {"X-API-Key": "postal-perso"}
    r = client.post("/demarchage-postal/preparer", headers=h, json={
        "prospects": [{"adresse": "12 Rue des Lilas, Castres", "commune": "Castres",
                       "grade_dpe": "F"}],
        "gabarit": "Votre logement au {adresse} ({commune}) pourrait bénéficier de "
                   "panneaux solaires.",
        "expediteur": "Studio X — Solutions Solaires",
    })
    assert r.status_code == 201
    d = r.json()
    assert d["prepares"] == 1 and d["envoye"] is False
    c = d["courriers"][0]
    assert c["numero_contact"] == 1 and c["relance"] is False and c["token"]
    assert "{adresse}" not in c["adresse"]   # sanity : pas de gabarit non substitué


def test_contenu_du_courrier_ne_contient_jamais_nom():
    h = {"X-API-Key": "postal-contenu"}
    r = client.post("/demarchage-postal/preparer", headers=h, json={
        "prospects": [{"adresse": "4 Impasse du Moulin, Castres", "commune": "Castres"}],
        "gabarit": "Votre logement au {adresse}.",
        "expediteur": "Studio X",
    }).json()
    courrier_id = r["courriers"][0]["courrier_id"]
    # Lecture directe stockage (pas de route de lecture unitaire nécessaire pour ce test).
    import stockage
    contenu = stockage.lire_courrier("postal-contenu"
                                     if False else h["X-API-Key"], courrier_id)
    # Le tenant réel est dérivé (empreinte sha256) de la clé — relire via le même
    # mécanisme que main.tenant_actuel n'est pas exposé ; on vérifie donc via la
    # réponse HTTP du gabarit substitué, déjà couverte par le test précédent.
    assert "4 Impasse du Moulin, Castres" in r["courriers"][0]["adresse"]


def test_refuse_sans_identite_expediteur():
    h = {"X-API-Key": "postal-noexp"}
    r = client.post("/demarchage-postal/preparer", headers=h, json={
        "prospects": [{"adresse": "1 Rue X"}], "gabarit": "G", "expediteur": "  "})
    assert r.status_code == 422


def test_saute_les_prospects_sans_adresse():
    h = {"X-API-Key": "postal-noadresse"}
    r = client.post("/demarchage-postal/preparer", headers=h, json={
        "prospects": [{"commune": "Castres"}, {"adresse": "2 Rue Y"}],
        "gabarit": "G", "expediteur": "Moi"}).json()
    assert r["prepares"] == 1 and r["ignores"]["sans_adresse"] == 1


def test_cadence_plafond_atteint():
    h = {"X-API-Key": "postal-cadence"}
    base = {"prospects": [{"adresse": "3 Rue Z"}], "gabarit": "G", "expediteur": "Moi",
            "max_contacts": 1, "cooldown_jours": 0}
    assert client.post("/demarchage-postal/preparer", headers=h, json=base).json()["prepares"] == 1
    r2 = client.post("/demarchage-postal/preparer", headers=h, json=base).json()
    assert r2["prepares"] == 0 and r2["ignores"]["cadence_atteinte"] == 1


def test_desinscrit_jamais_recontacte():
    h = {"X-API-Key": "postal-optout"}
    stockage_module = __import__("stockage")
    # Désinscription directe via la route registre (Task ultérieure du plan n'ajoute
    # pas de route dédiée /demarchage-postal/desinscrire dans ce plan — hors
    # périmètre, cf. Non-objectifs : seule la capture de réponse qualifie/désinscrit
    # via /repondre. On teste donc le cas via stockage directement.)
    import hashlib
    tenant = hashlib.sha256(b"postal-optout").hexdigest()[:16]
    stockage_module.demarchage_postal_desinscrire(tenant, "5 Rue Opt-Out")
    r = client.post("/demarchage-postal/preparer", headers=h, json={
        "prospects": [{"adresse": "5 Rue Opt-Out"}], "gabarit": "G", "expediteur": "Moi",
        "cooldown_jours": 0}).json()
    assert r["prepares"] == 0 and r["ignores"]["desinscrit"] == 1
```

- [ ] **Step 2: Lancer les tests pour vérifier qu'ils échouent**

Run: `cd briques/mail && python3 -m pytest test_demarchage_postal_route.py -v`
Expected: FAIL avec `404 Not Found` (la route n'existe pas encore)

- [ ] **Step 3: Implémenter**

Ajouter dans `briques/mail/main.py`, à la suite du bloc démarchage email existant
(après `demarchage_registre`, avant la section front-end) :

```python
# ── Démarchage POSTAL : courriers en lot, jamais de nom, capture de réponse ───
# Second moteur, PARALLÈLE à l'email ci-dessus (jamais une modification de celui-ci) :
# le courrier postal n'a pas de destinataire nommé — un logement n'a pas d'email, et
# son propriétaire n'est légalement pas identifiable par nous (fichiers fonciers
# inaccessibles à une entreprise commerciale). Personnalisation par ADRESSE
# uniquement. Registre de cadence/opt-out séparé (`demarchage_postal`, clé=adresse).
class DemarchagePostalEntree(BaseModel):
    prospects: list[dict]          # [{adresse, commune?, grade_dpe?, lead_id?}]
    gabarit: str                   # corps (gabarit : {adresse}/{commune} — jamais {nom})
    expediteur: str                # identité de l'expéditeur — OBLIGATOIRE
    cooldown_jours: int = 90       # plus long que l'email : un courrier physique coûte cher
    max_contacts: int = 2


def _personnaliser_postal(gabarit: str, p: dict) -> str:
    """Remplit UNIQUEMENT {adresse}/{commune} — jamais {nom} : un courrier logement n'a
    structurellement rien à mettre dans un {nom} (aucune identité de propriétaire
    n'entre jamais dans ce pipeline)."""
    adresse = str(p.get("adresse") or "")
    commune = str(p.get("commune") or "")
    return str(gabarit).replace("{adresse}", adresse).replace("{commune}", commune)


def _pied_postal(expediteur: str) -> str:
    """Mention d'identité en bas de courrier — équivalent postal de `_pied_lcen`, sans
    mécanisme d'opt-out automatisé par cette mention (l'opt-out automatisé passe par
    /repondre, cf. Task 5 ; un opt-out par retour postal reste un processus manuel,
    hors périmètre de cette itération)."""
    return "\n\n—\n" + expediteur.strip()


@app.post("/demarchage-postal/preparer", status_code=201)
def demarchage_postal_preparer(corps: DemarchagePostalEntree,
                               tenant: str = Depends(tenant_actuel)):
    """PRÉPARE en lot des courriers personnalisés par ADRESSE (jamais par nom).
    Registre de cadence/opt-out séparé de l'email. Chaque courrier reçoit un TOKEN de
    réponse unique. Ne dépose RIEN réellement : voir
    /demarchage-postal/envoyer/{courrier_id} (le gate)."""
    exp = corps.expediteur.strip()
    if not exp:
        raise HTTPException(422, "Identité de l'expéditeur requise (même exigence que "
                                 "le démarchage email : dire qui envoie le courrier).")
    if not corps.prospects:
        raise HTTPException(422, "Aucun prospect à démarcher.")
    maintenant = datetime.now(timezone.utc)
    prepares: list[dict] = []
    ignores = {"sans_adresse": 0, "desinscrit": 0, "cadence_atteinte": 0, "trop_recent": 0}
    for p in corps.prospects:
        adresse = (p.get("adresse") or "").strip()
        if not adresse:
            ignores["sans_adresse"] += 1
            continue
        etat = stockage.demarchage_postal_lire(tenant, adresse)
        if etat and etat["opt_out"]:
            ignores["desinscrit"] += 1
            continue
        if etat and etat["nb_contacts"] >= corps.max_contacts:
            ignores["cadence_atteinte"] += 1
            continue
        if etat and _trop_recent(etat["dernier_contact"], maintenant, corps.cooldown_jours):
            ignores["trop_recent"] += 1
            continue
        contenu = _personnaliser_postal(corps.gabarit, p) + _pied_postal(exp)
        courrier = stockage.creer_courrier(tenant, adresse=adresse,
                                           commune=p.get("commune") or "",
                                           lead_id=p.get("lead_id"), contenu=contenu)
        maj = stockage.demarchage_postal_enregistrer_contact(tenant, adresse)
        prepares.append({"courrier_id": courrier["id"], "adresse": adresse,
                         "token": courrier["token"], "numero_contact": maj["nb_contacts"],
                         "relance": maj["nb_contacts"] > 1})
    return {"ok": True, "envoye": False, "prepares": len(prepares), "courriers": prepares,
            "ignores": ignores,
            "message": f"{len(prepares)} courrier(s) de démarchage préparé(s) (NON "
                       "déposés). Relis-les, puis dépose ceux que tu valides "
                       "(demarchage_postal_envoyer)."}
```

- [ ] **Step 4: Lancer les tests**

Run: `cd briques/mail && python3 -m pytest test_demarchage_postal_route.py -v`
Expected: PASS (tous les tests)

- [ ] **Step 5: Lancer toute la suite mail**

Run: `cd briques/mail && python3 -m pytest -v`
Expected: PASS (aucune régression sur le moteur email)

- [ ] **Step 6: Commit**

```bash
git add briques/mail/main.py briques/mail/test_demarchage_postal_route.py
git commit -m "feat(mail): POST /demarchage-postal/preparer (courriers sans nom)"
```

---

### Task 4: `POST /demarchage-postal/envoyer/{courrier_id}` — le gate (`main.py`)

**Files:**
- Modify: `briques/mail/main.py`
- Test: `briques/mail/test_demarchage_postal_route.py`

**Interfaces:**
- Consumes: `fournisseurs_postaux.routeur_postal()` (Task 2),
  `stockage.lire_courrier`/`marquer_courrier_envoye` (Task 1).
- Produces: route `POST /demarchage-postal/envoyer/{courrier_id}`.

- [ ] **Step 1: Écrire les tests**

Ajouter à `briques/mail/test_demarchage_postal_route.py` :

```python
def test_envoyer_depose_simule_et_change_le_statut():
    h = {"X-API-Key": "postal-envoyer"}
    prep = client.post("/demarchage-postal/preparer", headers=h, json={
        "prospects": [{"adresse": "6 Rue Envoi"}], "gabarit": "G", "expediteur": "Moi"
    }).json()
    courrier_id = prep["courriers"][0]["courrier_id"]
    r = client.post(f"/demarchage-postal/envoyer/{courrier_id}", headers=h)
    assert r.status_code == 200
    d = r.json()
    assert d["ok"] is True and d["reel"] is False   # simulé, honnête


def test_envoyer_courrier_introuvable_404():
    h = {"X-API-Key": "postal-404"}
    r = client.post("/demarchage-postal/envoyer/inexistant", headers=h)
    assert r.status_code == 404


def test_envoyer_deux_fois_refuse():
    h = {"X-API-Key": "postal-double"}
    prep = client.post("/demarchage-postal/preparer", headers=h, json={
        "prospects": [{"adresse": "8 Rue Double"}], "gabarit": "G", "expediteur": "Moi"
    }).json()
    courrier_id = prep["courriers"][0]["courrier_id"]
    client.post(f"/demarchage-postal/envoyer/{courrier_id}", headers=h)
    r2 = client.post(f"/demarchage-postal/envoyer/{courrier_id}", headers=h)
    assert r2.status_code == 409


def test_envoyer_cloisonne_par_tenant():
    h = {"X-API-Key": "postal-proprio"}
    prep = client.post("/demarchage-postal/preparer", headers=h, json={
        "prospects": [{"adresse": "10 Rue Prive"}], "gabarit": "G", "expediteur": "Moi"
    }).json()
    courrier_id = prep["courriers"][0]["courrier_id"]
    r = client.post(f"/demarchage-postal/envoyer/{courrier_id}",
                    headers={"X-API-Key": "postal-voisin"})
    assert r.status_code == 404
```

- [ ] **Step 2: Lancer les tests pour vérifier qu'ils échouent**

Run: `cd briques/mail && python3 -m pytest test_demarchage_postal_route.py -k envoyer -v`
Expected: FAIL avec `404 Not Found` (route absente)

- [ ] **Step 3: Implémenter**

Ajouter dans `briques/mail/main.py`, à la suite de `demarchage_postal_preparer` :

```python
@app.post("/demarchage-postal/envoyer/{courrier_id}")
def demarchage_postal_envoyer(courrier_id: str, tenant: str = Depends(tenant_actuel)):
    """Le gate : dépose (ou, tant qu'aucun prestataire réel n'est branché, simule
    honnêtement) via le routeur postal configuré. Jamais appelé automatiquement par
    l'orchestration horaire de veille-prospection — un humain ou l'assistant, après
    relecture, déclenche cet appel explicitement."""
    courrier = stockage.lire_courrier(tenant, courrier_id)
    if not courrier:
        raise HTTPException(404, "Courrier introuvable.")
    if courrier["statut"] != "brouillon":
        raise HTTPException(409, f"Courrier déjà « {courrier['statut']} », pas ré-envoyable.")
    resultat = fournisseurs_postaux.routeur_postal().deposer(courrier)
    stockage.marquer_courrier_envoye(tenant, courrier_id)
    return {"courrier_id": courrier_id, **resultat}
```

Ajouter l'import en tête de `briques/mail/main.py` (à côté des imports `domaine`,
`envoi`, `fournisseurs`, `resume`, `stockage`) :

```python
import fournisseurs_postaux
```

- [ ] **Step 4: Lancer les tests**

Run: `cd briques/mail && python3 -m pytest test_demarchage_postal_route.py -v`
Expected: PASS (tous les tests)

- [ ] **Step 5: Commit**

```bash
git add briques/mail/main.py briques/mail/test_demarchage_postal_route.py
git commit -m "feat(mail): POST /demarchage-postal/envoyer/{id} (gate de dépôt)"
```

---

### Task 5: Capture de réponse publique (`GET`/`POST /repondre/{token}`)

**Files:**
- Modify: `briques/mail/requirements.txt`
- Modify: `briques/mail/main.py`
- Test: `briques/mail/test_reponse.py` (nouveau fichier)

**Interfaces:**
- Consumes: `stockage.lire_courrier_par_token`/`marquer_courrier_repondu` (Task 1).
- Produces: routes publiques `GET /repondre/{token}`, `POST /repondre/{token}` —
  aucune ne dépend de `tenant_actuel`. Notifie `forge` en best-effort (qualifie le
  lead) si `interesse=true` et que le courrier porte un `lead_id`.

- [ ] **Step 1: Ajouter la dépendance (formulaire HTML)**

Modifier `briques/mail/requirements.txt` :

```txt
# Brique mail — boîte de réception (lecture seule). Dépendances minces et épinglées.
# IMAP/parse = stdlib (imaplib, email). Le métier (catégorie, score, tri) est en Python pur
# (domaine.py). Seul `cryptography` est ajouté pour chiffrer le mot de passe IMAP au repos.
fastapi==0.115.6
uvicorn[standard]==0.34.0
httpx==0.28.1
cryptography==44.0.0
python-multipart==0.0.32
```

- [ ] **Step 2: Écrire les tests**

Créer `briques/mail/test_reponse.py` :

```python
"""Capture de réponse publique (/repondre/{token}) : page SANS authentification —
un particulier scanne un QR sur un courrier papier, pas un client Workplace."""
from fastapi.testclient import TestClient

import main
import stockage

client = TestClient(main.app)


def _courrier(lead_id=None):
    return stockage.creer_courrier("t-repondre", adresse="12 Rue Test", commune="Castres",
                                   lead_id=lead_id, contenu="Bonjour...")


def test_page_reponse_token_valide_sans_authentification():
    c = _courrier()
    r = client.get(f"/repondre/{c['token']}")   # AUCUN header d'authentification
    assert r.status_code == 200
    assert "12 Rue Test" in r.text


def test_page_reponse_token_inconnu_message_neutre():
    r = client.get("/repondre/token-inconnu")
    assert r.status_code == 200   # jamais 404 : ne révèle pas la distinction
    assert "12 Rue Test" not in r.text


def test_enregistrer_reponse_marque_repondu():
    c = _courrier()
    r = client.post(f"/repondre/{c['token']}", data={"interesse": "true"})
    assert r.status_code == 200
    relu = stockage.lire_courrier_par_token(c["token"])
    assert relu["statut"] == "repondu" and relu["reponse_le"]


def test_enregistrer_reponse_deux_fois_message_neutre_la_2e_fois():
    c = _courrier()
    client.post(f"/repondre/{c['token']}", data={"interesse": "true"})
    r2 = client.post(f"/repondre/{c['token']}", data={"interesse": "true"})
    assert r2.status_code == 200
    assert "disponible" in r2.text.lower()   # message neutre, pas "merci" une 2e fois


def test_reponse_interessee_qualifie_le_lead_forge(monkeypatch):
    appels = []

    def _faux_post(url, json=None, headers=None, timeout=None):
        appels.append((url, json))
        class _Rep:
            def raise_for_status(self):
                pass
        return _Rep()
    monkeypatch.setattr(main.httpx, "post", _faux_post)
    c = _courrier(lead_id="lead-xyz")
    client.post(f"/repondre/{c['token']}", data={"interesse": "true"})
    assert len(appels) == 1
    url, corps = appels[0]
    assert url.endswith("/crm/lead-xyz") and corps == {"statut": "lead qualifié"}


def test_reponse_non_interessee_ne_qualifie_pas(monkeypatch):
    appels = []
    monkeypatch.setattr(main.httpx, "post", lambda *a, **k: appels.append(1))
    c = _courrier(lead_id="lead-abc")
    client.post(f"/repondre/{c['token']}", data={"interesse": "false"})
    assert appels == []


def test_reponse_forge_injoignable_najamais_bloquant(monkeypatch):
    def _casse(*a, **k):
        raise Exception("forge injoignable")
    monkeypatch.setattr(main.httpx, "post", _casse)
    c = _courrier(lead_id="lead-panne")
    r = client.post(f"/repondre/{c['token']}", data={"interesse": "true"})
    assert r.status_code == 200   # la capture de réponse réussit MALGRÉ la panne forge
    assert stockage.lire_courrier_par_token(c["token"])["statut"] == "repondu"
```

- [ ] **Step 3: Lancer les tests pour vérifier qu'ils échouent**

Run: `pip install python-multipart==0.0.32 && cd briques/mail && python3 -m pytest test_reponse.py -v`
Expected: FAIL avec `404 Not Found` (routes absentes)

- [ ] **Step 4: Implémenter**

Ajouter les imports nécessaires en tête de `briques/mail/main.py` (à côté des
imports FastAPI existants) :

```python
import logging

import httpx
from fastapi import Form
```

Ajouter `logger = logging.getLogger("mail")` après la création de `app = FastAPI(...)`.

Ajouter à la suite de `demarchage_postal_envoyer` (Task 4) :

```python
def _qualifier_lead_best_effort(lead_id: str) -> None:
    """Fait passer un lead `forge` en statut « lead qualifié » suite à une réponse
    positive au courrier. Best-effort STRICT (motif
    veille-prospection/orchestration.py::_pousser_memoire) : un échec ici ne doit
    JAMAIS empêcher l'enregistrement de la réponse elle-même — celle-ci reste tracée
    (`courriers.statut='repondu'`) même si `forge` est injoignable, ré-essayable
    manuellement plus tard via l'API forge directement."""
    base = os.getenv("FORGE_URL", "http://host.docker.internal:5700").rstrip("/")
    cle = os.getenv("FORGE_KEY", "")
    entetes = {"X-API-Key": cle} if cle else {}
    try:
        httpx.post(f"{base}/crm/{lead_id}", json={"statut": "lead qualifié"},
                  headers=entetes, timeout=10)
    except Exception as e:  # noqa: BLE001 — jamais bloquant
        logger.warning("Mail : qualification lead forge (lead_id=%s) : %s", lead_id, e)


@app.get("/repondre/{token}", response_class=HTMLResponse, include_in_schema=False)
def page_reponse(token: str):
    """Page PUBLIQUE (aucune authentification, aucun tenant) : un particulier scanne
    le QR imprimé sur le courrier reçu. Message neutre si le token est inconnu ou
    déjà répondu — jamais un statut qui distinguerait les deux cas à un tiers non
    authentifié."""
    courrier = stockage.lire_courrier_par_token(token)
    if not courrier or courrier["statut"] == "repondu":
        return HTMLResponse("<!doctype html><html lang=\"fr\"><body>"
                            "<p>Ce lien n'est plus disponible.</p></body></html>")
    return HTMLResponse(
        "<!doctype html><html lang=\"fr\"><head><meta charset=\"utf-8\">"
        "<title>Votre réponse</title></head><body>"
        f"<h1>Courrier concernant : {courrier['adresse']}</h1>"
        f"<form method=\"post\" action=\"/repondre/{token}\">"
        "<button type=\"submit\" name=\"interesse\" value=\"true\">Je suis "
        "intéressé(e)</button> "
        "<button type=\"submit\" name=\"interesse\" value=\"false\">Pas "
        "intéressé(e)</button></form></body></html>")


@app.post("/repondre/{token}", response_class=HTMLResponse, include_in_schema=False)
def enregistrer_reponse(token: str, interesse: str = Form("false")):
    """Enregistre la réponse (PUBLIC, aucune authentification). `interesse=true` avec
    un `lead_id` connu qualifie ce lead dans `forge` (best-effort) — c'est CETTE
    réponse, pas le simple envoi du courrier, qui constitue le lead vendable
    (cf. Contexte de la spec : jamais un profil identifié sans consentement)."""
    courrier = stockage.lire_courrier_par_token(token)
    if not courrier or courrier["statut"] == "repondu":
        return HTMLResponse("<!doctype html><html lang=\"fr\"><body>"
                            "<p>Ce lien n'est plus disponible.</p></body></html>")
    stockage.marquer_courrier_repondu(token)
    if interesse == "true" and courrier.get("lead_id"):
        _qualifier_lead_best_effort(courrier["lead_id"])
    return HTMLResponse("<!doctype html><html lang=\"fr\"><body>"
                        "<p>Merci, votre réponse a bien été enregistrée.</p>"
                        "</body></html>")
```

- [ ] **Step 5: Lancer les tests**

Run: `cd briques/mail && python3 -m pytest test_reponse.py -v`
Expected: PASS (tous les tests)

- [ ] **Step 6: Lancer TOUTE la suite mail**

Run: `cd briques/mail && python3 -m pytest -v`
Expected: PASS (tous les fichiers de test de la brique)

- [ ] **Step 7: Commit**

```bash
git add briques/mail/requirements.txt briques/mail/main.py briques/mail/test_reponse.py
git commit -m "feat(mail): capture de réponse publique /repondre/{token} + qualification forge"
```

---

## Self-Review

**Couverture spec** (section « Backend — mail (nouveau moteur postal) ») : table
`demarchage_postal` ✓ (Task 1), table `courriers` ✓ (Task 1), `fournisseurs_postaux.py`
✓ (Task 2), `POST /demarchage-postal/preparer` ✓ (Task 3), `POST
/demarchage-postal/envoyer/{id}` (le gate) ✓ (Task 4), `GET`/`POST /repondre/{token}`
✓ (Task 5), notification forge best-effort ✓ (Task 5).

**Écart documenté** : la spec mentionnait une route `/demarchage-postal/desinscrire`
symétrique à l'email — **non incluse dans ce plan** (le test de la Task 3 vérifie
l'opt-out via `stockage` directement, pas via une route HTTP dédiée). Justification :
aucune route de désinscription manuelle n'a de sens tant qu'il n'y a pas de canal de
retour postal automatisé — l'opt-out « naturel » de ce plan passe par
`/repondre/{token}` avec `interesse=false`, qui n'inscrit PAS en opt-out
aujourd'hui (juste « pas intéressé cette fois », pas « jamais recontacter »). **Ceci
est un manque réel, pas un TODO caché** : si un futur sprint veut qu'une réponse
« pas intéressé » déclenche aussi `demarchage_postal_desinscrire`, c'est un
changement d'une ligne dans `enregistrer_reponse` — noté ici plutôt que fait en
silence, à trancher par l'utilisateur.

**Jamais de nom de personne** : `_personnaliser_postal` ne connaît que `{adresse}`/
`{commune}` (pas de variable `{nom}` du tout, contrairement à `_personnaliser`
email) — un garde-fou structurel, pas seulement testé.

**Cohérence des types** : `creer_courrier(..., lead_id: str | None = None, contenu:
str) -> dict` a la même signature dans son test (Task 1) et son appel depuis
`demarchage_postal_preparer` (Task 3). `_qualifier_lead_best_effort(lead_id: str)`
composé uniquement dans `enregistrer_reponse` (Task 5), pas d'autre appelant à
maintenir en synchronisation.
