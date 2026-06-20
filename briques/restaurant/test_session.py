"""S82 — rejoindre la table par PIN (multi-appareils).

Couvre : la règle pure de l'agrégat `SessionDeTable`, le réglage opt-in du restaurant,
le flux Démarrer / Rejoindre (avec & sans code, fail-closed), la garde des actions client
quand un code est exigé, le partage d'une session entre plusieurs appareils, et le fait
que la clôture FERME la session (les anciens jetons d'adhésion deviennent invalides).
La table OUVERTE (défaut historique) reste sans friction (rétrocompatibilité)."""
import uuid

from fastapi.testclient import TestClient

import domaine
import main

client = TestClient(main.app)


def _resto():
    email = f"sess-{uuid.uuid4().hex[:8]}@exemple.fr"
    r = client.post("/auth/inscription", json={
        "email": email, "mot_de_passe": "motdepasse1", "nom_restaurant": "Le Verrou"}).json()
    return r["session"], r["restaurant"]["id"]


def _h(s):
    return {"Authorization": f"Bearer {s}"}


def _table(h, resto, numero="1"):
    return client.post(f"/restaurants/{resto}/tables", headers=h, json={"numero": numero}).json()


def _plat(h, resto, **kw):
    return client.post(f"/restaurants/{resto}/plats", headers=h, json=kw).json()


def _activer_pin(h, resto):
    return client.patch(f"/restaurants/{resto}", headers=h, json={"pin_requis": True})


# ── Domaine pur (sans I/O) ───────────────────────────────────────
def test_session_ouverte_autorise_tout_le_monde():
    s = domaine.SessionDeTable(table_id="t1", numero=1, code_pin=None)
    assert not s.demarree
    assert s.autorise(None) and s.autorise("") and s.autorise("9999")


def test_session_protegee_exige_le_bon_pin():
    s = domaine.SessionDeTable(table_id="t1", numero=1, code_pin="4827")
    assert s.demarree
    assert s.autorise("4827")
    assert not s.autorise("0000")
    assert not s.autorise(None)


# ── Réglage opt-in du restaurant ─────────────────────────────────
def test_pin_requis_defaut_faux_et_bascule():
    session, resto = _resto()
    h = _h(session)
    assert client.get(f"/restaurants/{resto}", headers=h).json()["pin_requis"] is False
    r = _activer_pin(h, resto)
    assert r.status_code == 200 and r.json()["pin_requis"] is True


# ── Table OUVERTE (défaut) : aucune friction ─────────────────────
def test_table_ouverte_commande_sans_jeton():
    session, resto = _resto()
    h = _h(session)
    plat = _plat(h, resto, nom="Thé", prix_cents=300)
    code = _table(h, resto)["code"]
    vue = client.get(f"/t/{code}").json()
    assert vue["session"]["pin_requis"] is False
    # Aucun jeton : la commande passe (rétrocompatibilité totale).
    r = client.post(f"/t/{code}/commander",
                    json={"convive": "Léa", "plats": [{"plat_id": plat["id"], "quantite": 1}]})
    assert r.status_code == 200


# ── Flux PIN : démarrer / rejoindre ──────────────────────────────
def test_demarrer_genere_un_pin_et_une_seule_ouverture():
    session, resto = _resto()
    h = _h(session)
    _activer_pin(h, resto)
    code = _table(h, resto)["code"]

    vue = client.get(f"/t/{code}").json()
    assert vue["session"]["pin_requis"] is True and vue["session"]["demarree"] is False

    d = client.post(f"/t/{code}/demarrer").json()
    assert d["pin_requis"] is True
    assert len(d["pin"]) == domaine.LONGUEUR_PIN and d["pin"].isdigit()
    assert d["jeton"]

    # La table est maintenant démarrée → un 2e « démarrer » échoue (on rejoint, on ne ré-ouvre pas).
    assert client.post(f"/t/{code}/demarrer").status_code == 409
    assert client.get(f"/t/{code}").json()["session"]["demarree"] is True


def test_rejoindre_avec_bon_et_mauvais_pin():
    session, resto = _resto()
    h = _h(session)
    _activer_pin(h, resto)
    code = _table(h, resto)["code"]
    pin = client.post(f"/t/{code}/demarrer").json()["pin"]

    assert client.post(f"/t/{code}/rejoindre", json={"pin": "0000" if pin != "0000" else "1111"}).status_code == 403
    ok = client.post(f"/t/{code}/rejoindre", json={"pin": pin})
    assert ok.status_code == 200 and ok.json()["jeton"]


# ── Garde des actions quand un code est exigé ────────────────────
def test_commande_refusee_sans_jeton_acceptee_avec():
    session, resto = _resto()
    h = _h(session)
    _activer_pin(h, resto)
    plat = _plat(h, resto, nom="Pizza", prix_cents=1400)
    code = _table(h, resto)["code"]
    jeton = client.post(f"/t/{code}/demarrer").json()["jeton"]
    cmd = {"convive": "Thomas", "plats": [{"plat_id": plat["id"], "quantite": 1}]}

    # Sans jeton : refus (fail-closed).
    assert client.post(f"/t/{code}/commander", json=cmd).status_code == 403
    assert client.get(f"/t/{code}/addition").status_code == 403
    # Avec le jeton d'adhésion : accepté.
    h2 = {"X-Table-Session": jeton}
    assert client.post(f"/t/{code}/commander", json=cmd, headers=h2).status_code == 200
    assert client.get(f"/t/{code}/addition", headers=h2).status_code == 200


def test_jeton_d_une_autre_table_est_rejete():
    session, resto = _resto()
    h = _h(session)
    _activer_pin(h, resto)
    code_a = _table(h, resto, "A")["code"]
    code_b = _table(h, resto, "B")["code"]
    jeton_a = client.post(f"/t/{code_a}/demarrer").json()["jeton"]
    client.post(f"/t/{code_b}/demarrer")
    plat = _plat(h, resto, nom="Eau", prix_cents=200)
    # Le jeton de la table A ne vaut RIEN sur la table B.
    r = client.post(f"/t/{code_b}/commander", headers={"X-Table-Session": jeton_a},
                    json={"convive": "X", "plats": [{"plat_id": plat["id"], "quantite": 1}]})
    assert r.status_code == 403


# ── Multi-appareils : même session partagée ──────────────────────
def test_plusieurs_appareils_partagent_la_session():
    session, resto = _resto()
    h = _h(session)
    _activer_pin(h, resto)
    plat = _plat(h, resto, nom="Café", prix_cents=200)
    table = _table(h, resto)
    code = table["code"]

    # Appareil 1 démarre, appareil 2 rejoint avec le PIN.
    d = client.post(f"/t/{code}/demarrer").json()
    j1 = d["jeton"]
    j2 = client.post(f"/t/{code}/rejoindre", json={"pin": d["pin"]}).json()["jeton"]

    client.post(f"/t/{code}/commander", headers={"X-Table-Session": j1},
                json={"convive": "Thomas", "plats": [{"plat_id": plat["id"], "quantite": 1}]})
    client.post(f"/t/{code}/commander", headers={"X-Table-Session": j2},
                json={"convive": "Sarah", "plats": [{"plat_id": plat["id"], "quantite": 1}]})
    # Les deux appareils voient la MÊME addition (2 convives, une seule session).
    etat = client.get(f"/t/{code}/addition", headers={"X-Table-Session": j2}).json()
    assert {c["convive"] for c in etat["convives"]} == {"Thomas", "Sarah"}


# ── Clôture : ferme la session, invalide les anciens jetons ──────
def test_cloture_ferme_la_session():
    session, resto = _resto()
    h = _h(session)
    _activer_pin(h, resto)
    plat = _plat(h, resto, nom="Soda", prix_cents=400)
    table = _table(h, resto)
    code, tid = table["code"], table["id"]
    jeton = client.post(f"/t/{code}/demarrer").json()["jeton"]
    client.post(f"/t/{code}/commander", headers={"X-Table-Session": jeton},
                json={"convive": "Léa", "plats": [{"plat_id": plat["id"], "quantite": 1}]})

    # Le restaurateur clôt (force : départ assumé) → nouvelle session, PIN effacé.
    assert client.post(f"/restaurants/{resto}/tables/{tid}/cloturer", headers=h,
                       json={"force": True}).status_code == 200
    assert client.get(f"/t/{code}").json()["session"]["demarree"] is False
    # L'ancien jeton (lié à l'ancien numéro de session) ne vaut plus rien.
    r = client.post(f"/t/{code}/commander", headers={"X-Table-Session": jeton},
                    json={"convive": "Léa", "plats": [{"plat_id": plat["id"], "quantite": 1}]})
    assert r.status_code == 403
