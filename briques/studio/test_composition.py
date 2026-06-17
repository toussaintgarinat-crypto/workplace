"""Tests — Composition de la brique personnages (5900) par le Studio (S52).

Le Studio COMPOSE le casting/la distribution de la brique sœur, avec un REPLI HONNÊTE
sur sa logique internalisée (S51) quand la brique est absente. Ici : les adaptateurs purs
(`fusionner_voix`), les ponts HTTP (mockés : succès + repli None) et le choix de source
côté `main._casting_stable`."""
import asyncio

import composition as C
import main as M
import studio as S


# ── Helpers de mock httpx (mêmes patrons que test_images) ────────
def _client_post(rep_json, boom=False):
    class FauxRep:
        status_code = 200
        def raise_for_status(self): pass
        def json(self): return rep_json

    class FauxClient:
        def __init__(self, *a, **k): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def post(self, *a, **k):
            if boom:
                raise RuntimeError("connection refused")
            return FauxRep()
        async def get(self, *a, **k):
            if boom:
                raise RuntimeError("connection refused")
            return FauxRep()
    return FauxClient


# ── fusionner_voix : recopie des voix figées (pur) ───────────────
def test_fusionner_voix_par_id():
    serie = {"personnages": [{"id": "p1", "nom": "Aria"}, {"id": "p2", "nom": "Vorn"}]}
    enrichis = [{"id": "p1", "nom": "Aria", "voix": {"fr": "Thomas"}},
                {"id": "p2", "nom": "Vorn", "voix": {"fr": "Marie"}}]
    assert C.fusionner_voix(serie, enrichis) is True
    assert serie["personnages"][0]["voix"]["fr"] == "Thomas"
    assert serie["personnages"][1]["voix"]["fr"] == "Marie"


def test_fusionner_voix_par_nom_si_pas_did():
    serie = {"personnages": [{"nom": "Aria"}]}
    enrichis = [{"nom": "ARIA", "voix": {"fr": "Thomas"}}]   # apparié par nom normalisé
    assert C.fusionner_voix(serie, enrichis) is True
    assert serie["personnages"][0]["voix"]["fr"] == "Thomas"


def test_fusionner_voix_idempotent_et_sans_ecrasement_par_vide():
    serie = {"personnages": [{"id": "p1", "nom": "Aria", "voix": {"fr": "Thomas"}}]}
    enrichis = [{"id": "p1", "voix": {"fr": ""}}]            # vide → on n'écrase pas
    assert C.fusionner_voix(serie, enrichis) is False
    assert serie["personnages"][0]["voix"]["fr"] == "Thomas"


# ── caster : pont vers /casting (succès + repli) ─────────────────
def test_caster_succes_retourne_casting_et_persos(monkeypatch):
    monkeypatch.setattr(C.httpx, "AsyncClient",
                        _client_post({"casting": {"ARIA": "Thomas"},
                                      "personnages": [{"id": "p1", "voix": {"fr": "Thomas"}}]}))
    res = asyncio.run(C.caster([{"id": "p1", "nom": "Aria"}], "fr", ["ARIA"], ["Thomas"]))
    assert res is not None
    casting, persos = res
    assert casting == {"ARIA": "Thomas"}
    assert persos[0]["voix"]["fr"] == "Thomas"


def test_caster_repli_none_si_injoignable(monkeypatch):
    monkeypatch.setattr(C.httpx, "AsyncClient", _client_post({}, boom=True))
    assert asyncio.run(C.caster([], "fr", ["A"], ["Thomas"])) is None


def test_caster_repli_none_si_casting_illisible(monkeypatch):
    monkeypatch.setattr(C.httpx, "AsyncClient", _client_post({"casting": "oups"}))
    assert asyncio.run(C.caster([], "fr", ["A"], ["Thomas"])) is None


# ── proposer_distribution : normalisation + repli ────────────────
def test_proposer_distribution_normalise_et_filtre(monkeypatch):
    monkeypatch.setattr(C.httpx, "AsyncClient", _client_post({"personnages": [
        {"nom": " Aria ", "role": "héroïne", "description": "brave"},
        {"nom": "", "role": "x"},               # sans nom → filtré
        "pas un dict",                            # ignoré
    ]}))
    out = asyncio.run(C.proposer_distribution("prem", "français", 4, ""))
    assert out == [{"nom": "Aria", "role": "héroïne", "description": "brave"}]


def test_proposer_distribution_repli_none_si_injoignable(monkeypatch):
    monkeypatch.setattr(C.httpx, "AsyncClient", _client_post({}, boom=True))
    assert asyncio.run(C.proposer_distribution("p", "français", 4)) is None


# ── fiches holistiques enregistrées : liste + lecture (succès + repli) ───
def test_lister_fiches_holistiques_normalise(monkeypatch):
    monkeypatch.setattr(C.httpx, "AsyncClient", _client_post([
        {"id": "f1", "nom": "Aria", "nom_naissance": "Lyssandre", "archetype": "Le Sage",
         "cree_le": "2026-06-17"},
        {"nom": "sans id"},                       # sans id → filtré
        "pas un dict",                            # ignoré
    ]))
    out = asyncio.run(C.lister_fiches_holistiques())
    assert out == [{"id": "f1", "nom": "Aria", "nom_naissance": "Lyssandre",
                    "archetype": "Le Sage", "cree_le": "2026-06-17"}]


def test_lister_fiches_holistiques_repli_none_si_injoignable(monkeypatch):
    monkeypatch.setattr(C.httpx, "AsyncClient", _client_post([], boom=True))
    assert asyncio.run(C.lister_fiches_holistiques()) is None


def test_lire_fiche_holistique_succes(monkeypatch):
    monkeypatch.setattr(C.httpx, "AsyncClient", _client_post(
        {"id": "f1", "nom": "Aria", "nom_naissance": "Lyssandre",
         "donnees": {"portrait": {"archetype": "Le Sage"}}}))
    f = asyncio.run(C.lire_fiche_holistique("f1"))
    assert f["nom_naissance"] == "Lyssandre" and f["donnees"]["portrait"]["archetype"] == "Le Sage"


def test_lire_fiche_holistique_repli_none_si_injoignable(monkeypatch):
    monkeypatch.setattr(C.httpx, "AsyncClient", _client_post({}, boom=True))
    assert asyncio.run(C.lire_fiche_holistique("f1")) is None


# ── personnages_joignable ────────────────────────────────────────
def test_joignable_vrai_si_service_personnages(monkeypatch):
    monkeypatch.setattr(C.httpx, "AsyncClient", _client_post({"service": "personnages"}))
    assert asyncio.run(C.personnages_joignable()) is True


def test_joignable_faux_si_injoignable(monkeypatch):
    monkeypatch.setattr(C.httpx, "AsyncClient", _client_post({}, boom=True))
    assert asyncio.run(C.personnages_joignable()) is False


# ── main._casting_stable : choix de source + repli honnête ───────
def _serie():
    return {"titre": "T", "bible": {}, "episodes": [],
            "personnages": [{"id": "p1", "nom": "Aria"}, {"id": "p2", "nom": "Vorn"}]}


def test_casting_stable_via_brique(monkeypatch):
    async def faux_caster(personnages, langue, intervenants, pool):
        return {"ARIA": "Thomas", "VORN": "Marie"}, [
            {"id": "p1", "voix": {"fr": "Thomas"}}, {"id": "p2", "voix": {"fr": "Marie"}}]
    monkeypatch.setattr(M.composition, "caster", faux_caster)
    monkeypatch.setattr(M.S, "_save", lambda serie: None)   # pas d'écriture disque
    serie = _serie()
    casting, source = asyncio.run(
        M._casting_stable(serie, "fr", [("ARIA", "a"), ("VORN", "b")], ["Thomas", "Marie"]))
    assert source == "personnages"
    assert casting["ARIA"] == "Thomas"
    assert serie["personnages"][0]["voix"]["fr"] == "Thomas"   # voix re-persistée


def test_casting_stable_repli_interne_si_brique_absente(monkeypatch):
    async def brique_ko(*a, **k): return None
    monkeypatch.setattr(M.composition, "caster", brique_ko)
    serie = _serie()
    casting, source = asyncio.run(
        M._casting_stable(serie, "fr", [("ARIA", "a"), ("VORN", "b")], ["Thomas", "Marie"]))
    assert source == "studio"
    assert casting["ARIA"] in ("Thomas", "Marie") and casting["VORN"] in ("Thomas", "Marie")


def test_casting_stable_repli_si_intervenant_manquant(monkeypatch):
    """La brique répond mais oublie un intervenant → on retombe sur le casting interne complet."""
    async def faux_caster(*a, **k):
        return {"ARIA": "Thomas"}, [{"id": "p1", "voix": {"fr": "Thomas"}}]   # VORN manquant
    monkeypatch.setattr(M.composition, "caster", faux_caster)
    monkeypatch.setattr(M.S, "_save", lambda serie: None)
    serie = _serie()
    casting, source = asyncio.run(
        M._casting_stable(serie, "fr", [("ARIA", "a"), ("VORN", "b")], ["Thomas", "Marie"]))
    assert source == "studio"
    assert "VORN" in casting
