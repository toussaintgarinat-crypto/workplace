"""Branchement du RAIL de paiement (S166) : le paiement en ligne du restaurant passe par la
brique paiements quand le rail est activé, et RETOMBE honnêtement sur le mock sinon.

La brique paiements est simulée par un faux client httpx (FauxRail) : on teste la logique de
branchement de `rail.py` + `/t/{code}/payer` sans réseau ni brique 6020 réelle."""
import os

import pytest

import rail

# ── Faux rail (brique paiements simulée) ─────────────────────────
class _Rep:
    def __init__(self, code, corps):
        self.status_code = code
        self._corps = corps

    def json(self):
        return self._corps

    def raise_for_status(self):
        if self.status_code >= 400:
            raise rail.httpx.HTTPStatusError("boom", request=None, response=None)


class FauxRail:
    """Émule les endpoints de la brique paiements utilisés par rail.py. État partagé par test :
    `injoignable` (lève), et `peut_encaisser` (le compte est-il onboardé ?)."""
    injoignable = False
    peut_encaisser = True
    dernier_encaissement = None

    def __init__(self, *a, **k):
        pass

    def __enter__(self):
        if FauxRail.injoignable:
            raise rail.httpx.ConnectError("rail down")
        return self

    def __exit__(self, *a):
        return False

    def post(self, url, headers=None, json=None):
        if url.endswith("/comptes-connectes"):
            return _Rep(201, {"id": "acct_1", "statut": "incomplet"})
        if url.endswith("/onboarding"):
            return _Rep(200, {"url": "http://rail/demo/onboarding/acct_1", "mode": "mock"})
        if url.endswith("/paiements"):
            if not FauxRail.peut_encaisser:
                return _Rep(409, {"detail": "onboarding non terminé"})
            FauxRail.dernier_encaissement = json
            return _Rep(201, {"id": "pay_1", "montant_cents": json["montant_cents"],
                              "statut": "paye", "mode": "mock"})
        return _Rep(404, {})

    def get(self, url, headers=None):
        if "/comptes-connectes/" in url:
            statut = "actif" if FauxRail.peut_encaisser else "incomplet"
            return _Rep(200, {"statut": statut, "peut_encaisser": FauxRail.peut_encaisser})
        return _Rep(404, {})


@pytest.fixture(autouse=True)
def _brancher_faux_rail(monkeypatch):
    """Rail configuré (URL+clé) + client httpx remplacé par le faux. État réinitialisé."""
    monkeypatch.setenv("PAIEMENTS_URL", "http://rail")
    monkeypatch.setenv("PAIEMENTS_API_KEY", "cle-tenant-resto")
    monkeypatch.setattr(rail.httpx, "Client", FauxRail)
    FauxRail.injoignable = False
    FauxRail.peut_encaisser = True
    FauxRail.dernier_encaissement = None
    yield


# ── Helpers : monter un resto (table ouverte) avec une pizza commandée ──
from fastapi.testclient import TestClient  # noqa: E402

import main  # noqa: E402

client = TestClient(main.app)


def _resto_avec_table_commandee():
    """Resto + table ouverte + une pizza à 20 € commandée par Marc. Renvoie (entêtes resto,
    code de table, id resto). Table ouverte → le client commande/paie sans header de session."""
    email = f"r{os.urandom(4).hex()}@ex.fr"
    insc = client.post("/auth/inscription", json={
        "email": email, "mot_de_passe": "motdepasse12", "nom_restaurant": "Chez Léa"}).json()
    h = {"Authorization": f"Bearer {insc['session']}"}
    rid = insc["restaurant"]["id"]
    plat = client.post(f"/restaurants/{rid}/plats", headers=h,
                       json={"nom": "Pizza", "prix_cents": 2000}).json()
    table = client.post(f"/restaurants/{rid}/tables", headers=h, json={"numero": "1"}).json()
    code = table["code"]
    client.post(f"/t/{code}/commander",
                json={"convive": "Marc", "plats": [{"plat_id": plat["id"], "quantite": 1}]})
    return h, code, rid


def test_rail_activation_cree_compte_et_onboarding():
    h, code, rid = _resto_avec_table_commandee()
    r = client.post(f"/restaurants/{rid}/rail/activer", headers=h).json()
    assert r["compte_id"] == "acct_1"
    assert "onboarding" in r["onboarding_url"]
    # État du rail : configuré, compte rattaché, peut encaisser (faux compte actif).
    etat = client.get(f"/restaurants/{rid}/rail", headers=h).json()
    assert etat["configure"] is True and etat["compte_id"] == "acct_1"
    assert etat["peut_encaisser"] is True


def test_paiement_passe_par_le_rail_quand_actif():
    h, code, rid = _resto_avec_table_commandee()
    client.post(f"/restaurants/{rid}/rail/activer", headers=h)
    r = client.post(f"/t/{code}/payer", json={"convive": "Marc"}).json()
    # Encaissement réel via le rail → moyen "rail", demo=False, et le rail a bien été appelé.
    assert r["demo"] is False and r["paiement"]["moyen"] == "rail"
    assert r["paiement"]["montant_cents"] == 2000
    assert FauxRail.dernier_encaissement["montant_cents"] == 2000
    assert FauxRail.dernier_encaissement["compte_connecte_id"] == "acct_1"


def test_repli_mock_si_rail_non_active():
    h, code, rid = _resto_avec_table_commandee()   # rail configuré mais pas activé pour ce resto
    r = client.post(f"/t/{code}/payer", json={"convive": "Marc"}).json()
    assert r["demo"] is True and r["paiement"]["moyen"] == "mock"
    assert FauxRail.dernier_encaissement is None        # le rail n'a pas été sollicité


def test_repli_mock_si_rail_injoignable():
    h, code, rid = _resto_avec_table_commandee()
    client.post(f"/restaurants/{rid}/rail/activer", headers=h)
    FauxRail.injoignable = True                          # le rail tombe au moment de payer
    r = client.post(f"/t/{code}/payer", json={"convive": "Marc"}).json()
    # Repli HONNÊTE : le paiement est enregistré en mock, jamais présenté comme réel.
    assert r["demo"] is True and r["paiement"]["moyen"] == "mock"


def test_repli_mock_si_compte_pas_encore_onboarde():
    h, code, rid = _resto_avec_table_commandee()
    client.post(f"/restaurants/{rid}/rail/activer", headers=h)
    FauxRail.peut_encaisser = False                     # rail refuse (409) : onboarding pas fini
    r = client.post(f"/t/{code}/payer", json={"convive": "Marc"}).json()
    assert r["demo"] is True and r["paiement"]["moyen"] == "mock"


def test_rail_activer_sans_config_renvoie_503(monkeypatch):
    h, code, rid = _resto_avec_table_commandee()
    monkeypatch.delenv("PAIEMENTS_API_KEY", raising=False)   # rail plus configuré
    assert client.post(f"/restaurants/{rid}/rail/activer", headers=h).status_code == 503
    # Et le paiement retombe en mock sans erreur.
    assert client.post(f"/t/{code}/payer", json={"convive": "Marc"}).json()["demo"] is True
