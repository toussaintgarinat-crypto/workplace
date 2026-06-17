"""Outil « créer un personnage holistique » de l'assistant (brique personnages 5900).

Vérifie : l'outil est déclaré, la génération seule est NON destructive (pas de confirme),
l'enregistrement / l'ajout en série sont GARDÉS par confirme, et l'orchestration enchaîne
correctement géo → portrait → fiche → import (Studio). Briques mockées → aucun réseau.

Async via asyncio.run (motif du reste de la suite core/).
"""
import asyncio
import json
import os

import httpx

os.environ.setdefault("PERSONNAGES_URL", "http://perso.test")  # override → pas de registre
os.environ.setdefault("STUDIO_URL", "http://studio.test")

import outils  # noqa: E402

NOMS = {o["function"]["name"] for o in outils.OUTILS}


# ── Déclaration ──────────────────────────────────────────────────────────────
def test_outil_declare():
    assert "personnage_creer_holistique" in NOMS


# ── Stub httpx routé par sous-chaîne d'URL ───────────────────────────────────
class _Resp:
    def __init__(self, status=200, payload=None):
        self.status_code = status
        self._payload = payload if payload is not None else {}
        self.content = b"{}"
        self.text = ""

    def json(self):
        return self._payload


class _Router:
    """Renvoie la 1ʳᵉ réponse dont la sous-chaîne matche l'URL ; enregistre les appels."""
    def __init__(self, routes):
        self.routes = routes
        self.appels = []

    async def request(self, methode, url, json=None, params=None, headers=None, timeout=None):
        self.appels.append({"methode": methode, "url": url, "json": json,
                            "params": params, "headers": headers})
        for sous, resp in self.routes:
            if sous in url:
                return resp
        return _Resp(404, {"detail": "route absente"})

    def url_appelees(self):
        return [a["url"] for a in self.appels]


_PORTRAIT = {"traditions": {"signe_solaire": {"nom": "Vierge"}},
             "portrait": {"archetype": "Le Sage", "forces": ["clarté", "patience", "rigueur"],
                          "faiblesse": "orgueil", "pierre_equilibrage": {"pierre": "Améthyste"}},
             "empreinte": [{"cle": "Soleil", "valeur": "Vierge", "sens": "analyse"},
                           {"cle": "Lune", "valeur": "Cancer"}]}


def _routes_base():
    return [("/geo", _Resp(200, {"ville": "Toulouse, France", "latitude": 43.6, "longitude": 1.44})),
            ("/holistique/portrait", _Resp(200, _PORTRAIT)),
            ("importer-fiche", _Resp(200, {"id": "p1", "nom": "Vorn", "nom_naissance": "Aria Solis"})),
            ("/personnages/importer", _Resp(200, {"id": "p1", "nom": "Vorn", "nom_naissance": "Aria Solis"})),
            ("/fiches", _Resp(200, {"id": "f1", "nom": "Aria Solis", "nom_naissance": "Aria Solis",
                                    "archetype": "Le Sage"}))]


def _run(args, routes=None):
    cli = _Router(routes or _routes_base())
    out = json.loads(asyncio.run(outils._personnage_holistique(cli, None, args)))
    return out, cli


# ── Génération seule : non destructive, pas de confirme ──────────────────────
def test_generation_seule_renvoie_le_portrait_sans_rien_stocker():
    out, cli = _run({"prenoms": "Aria", "nom": "Solis", "date_naissance": "1990-09-05",
                     "ville": "Toulouse"})
    assert out["ok"] is True
    assert out["archetype"] == "Le Sage" and out["a_travailler"] == "orgueil"
    assert out["pierre"] == "Améthyste" and out["ville"] == "Toulouse, France"
    urls = cli.url_appelees()
    assert any("/geo" in u for u in urls) and any("/holistique/portrait" in u for u in urls)
    assert not any("/fiches" in u or "importer" in u for u in urls)   # rien stocké


def test_infos_minimales_requises():
    out, _ = _run({"prenoms": "", "date_naissance": ""})
    assert out["ok"] is False and "prénoms" in out["message"]


def test_portrait_indisponible_si_brique_ko():
    routes = [("/holistique/portrait", _Resp(502, {"detail": "moteur en panne"}))]
    out, _ = _run({"prenoms": "Aria", "date_naissance": "1990-09-05"}, routes)
    assert out["ok"] is False


# ── Actions gardées par confirme ─────────────────────────────────────────────
def test_enregistrer_demande_confirmation():
    out, cli = _run({"prenoms": "Aria", "date_naissance": "1990-09-05", "enregistrer": True})
    assert out["confirmation_requise"] is True
    assert cli.appels == []   # rien n'a été appelé avant l'accord


def test_serie_demande_confirmation():
    out, _ = _run({"prenoms": "Aria", "date_naissance": "1990-09-05", "serie_id": "s1"})
    assert out["confirmation_requise"] is True


# ── Enregistrement confirmé ──────────────────────────────────────────────────
def test_enregistrer_confirme_cree_la_fiche():
    out, cli = _run({"prenoms": "Aria", "nom": "Solis", "date_naissance": "1990-09-05",
                     "enregistrer": True, "confirme": True})
    assert out["fiche_enregistree"] == "f1"
    # le nom complet est bien envoyé à /fiches
    appel_fiche = next(a for a in cli.appels if "/fiches" in a["url"])
    assert appel_fiche["json"]["nom"] == "Aria Solis"
    assert appel_fiche["json"]["portrait"]["archetype"] == "Le Sage"


# ── Ajout en série : import par id si enregistré, push sinon ──────────────────
def test_enregistrer_et_ajouter_serie_importe_par_id():
    out, cli = _run({"prenoms": "Aria", "nom": "Solis", "date_naissance": "1990-09-05",
                     "enregistrer": True, "serie_id": "s1", "nom_scene": "Vorn",
                     "confirme": True})
    assert out["fiche_enregistree"] == "f1"
    assert out["importe_dans_serie"]["nom"] == "Vorn"
    appel_imp = next(a for a in cli.appels if "importer-fiche" in a["url"])
    assert appel_imp["json"] == {"fiche_id": "f1", "nom": "Vorn"}


def test_ajouter_serie_sans_enregistrer_pousse_la_fiche():
    out, cli = _run({"prenoms": "Aria", "nom": "Solis", "date_naissance": "1990-09-05",
                     "serie_id": "s1", "nom_scene": "Vorn", "confirme": True})
    assert "fiche_enregistree" not in out
    appel = next(a for a in cli.appels if a["url"].endswith("/personnages/importer"))
    charge = appel["json"]
    assert charge["nom"] == "Vorn" and charge["nom_naissance"] == "Aria Solis"
    assert charge["archetype"] == "Le Sage"
    assert charge["empreinte"] == ["Soleil : Vierge", "Lune : Cancer"]


# ── Helper _personnages_appel : auth + dégradation ───────────────────────────
def test_personnages_appel_envoie_la_cle():
    os.environ["PERSONNAGES_KEY"] = "secret"
    try:
        cli = _Router([("/sante", _Resp(200, {"service": "personnages"}))])
        asyncio.run(outils._personnages_appel(cli, None, "GET", "/sante"))
        assert cli.appels[-1]["headers"] == {"X-API-Key": "secret"}
    finally:
        os.environ.pop("PERSONNAGES_KEY", None)


def test_personnages_appel_hors_ligne_degrade():
    class _Boom:
        async def request(self, *a, **k):
            raise httpx.ConnectError("injoignable")
    out = json.loads(asyncio.run(outils._personnages_appel(_Boom(), None, "GET", "/sante")))
    assert out["ok"] is False and "injoignable" in out["message"].lower()
