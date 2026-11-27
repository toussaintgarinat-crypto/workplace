import asyncio
import json
import os
import pathlib

import httpx
import pytest

import contrats
from contrats import AppContrat, ContratErreur

BLOC = {"version_schema": "1",
        "exporter": {"methode": "POST", "chemin": "/support/exporter"},
        "reinitialiser": {"methode": "POST", "chemin": "/support/reinitialiser"},
        "importer": {"methode": "POST", "chemin": "/support/importer"}}
ENTREE = {"url": "http://studio.test:6060", "cle_env": "STUDIO_SUPPORT_KEY", "bloc": BLOC}


def _ecrire(monkeypatch, tmp_path, contenu):
    p = tmp_path / "contrats.json"
    p.write_text(json.dumps(contenu))
    monkeypatch.setenv("LIVRAISON_CONTRATS", str(p))


def test_lire_valide_et_insensible_a_la_casse(monkeypatch, tmp_path):
    _ecrire(monkeypatch, tmp_path, {"studio": ENTREE})
    assert contrats.lire(" Studio ")["url"] == "http://studio.test:6060"
    assert contrats.lire("inconnu") is None


@pytest.mark.parametrize("mut", [
    lambda e: e.update(cle_env="DOKPLOY_API_KEY"),
    lambda e: e.update(cle_env="EXECUTEUR_KEY"),
    lambda e: e.update(cle_env="studio_support_key"),
    lambda e: e.update(url="ftp://x"),
    lambda e: e.update(url="http://x/chemin"),
    lambda e: e.update(url="http://user:pw@x:1"),
    lambda e: e["bloc"].update(version_schema="un"),
    lambda e: e["bloc"]["exporter"].update(chemin="/support/%2e%2e/x"),
    lambda e: e.update(extra=1),
    lambda e: e.pop("bloc"),
])
def test_entree_invalide_refusee(monkeypatch, tmp_path, mut):
    e = json.loads(json.dumps(ENTREE))
    mut(e)
    _ecrire(monkeypatch, tmp_path, {"studio": e})
    assert contrats.lire("studio") is None


def test_registre_absent_ou_illisible(monkeypatch, tmp_path):
    monkeypatch.setenv("LIVRAISON_CONTRATS", str(tmp_path / "absent.json"))
    assert contrats.lire("studio") is None
    (tmp_path / "x.json").write_text("{pas du json")
    monkeypatch.setenv("LIVRAISON_CONTRATS", str(tmp_path / "x.json"))
    assert contrats.lire("studio") is None


def test_ouvrir_sans_cle_configuree(monkeypatch, tmp_path):
    _ecrire(monkeypatch, tmp_path, {"studio": ENTREE})
    monkeypatch.delenv("STUDIO_SUPPORT_KEY", raising=False)
    with pytest.raises(ContratErreur) as e:
        contrats.ouvrir("studio")
    assert e.value.statut == 503


def _app(handler, monkeypatch):
    monkeypatch.setenv("STUDIO_SUPPORT_KEY", "cle-support")
    return AppContrat("studio", ENTREE, transport=httpx.MockTransport(handler))


def test_exporter_renvoie_paquet_et_metadonnees(monkeypatch):
    def h(req):
        assert req.headers["x-support-key"] == "cle-support"
        assert json.loads(req.content) == {"utilisateur": "claire"}
        return httpx.Response(200, content=b"PAQUET", headers={
            "X-Empreinte": "abc", "X-Comptages": json.dumps({"series": 2})})
    paquet, meta = asyncio.run(_app(h, monkeypatch).exporter("claire"))
    assert paquet == b"PAQUET" and meta == {"empreinte": "abc", "comptages": {"series": 2}}


def test_exporter_sans_entetes_refuse(monkeypatch):
    with pytest.raises(ContratErreur):
        asyncio.run(_app(lambda r: httpx.Response(200, content=b"P"), monkeypatch).exporter("c"))


def test_verifier_envoie_les_octets_et_l_utilisateur_en_query(monkeypatch):
    def h(req):
        assert req.url.path == "/support/verifier" and req.url.params["utilisateur"] == "claire"
        assert req.content == b"PAQUET"
        return httpx.Response(200, json={"ok": True, "empreinte": "abc", "comptages": {}})
    assert asyncio.run(_app(h, monkeypatch).verifier("claire", b"PAQUET"))["empreinte"] == "abc"


@pytest.mark.parametrize("statut,raison", [(409, "empreinte"), (422, "signature"),
                                           (401, "cle_refusee"), (503, "desactive")])
def test_erreurs_ne_portent_que_la_raison(monkeypatch, statut, raison):
    corps = {"detail": raison if statut in (409, 422) else "SECRET claire@x.fr"}
    app = _app(lambda r: httpx.Response(statut, json=corps), monkeypatch)
    with pytest.raises(ContratErreur) as e:
        asyncio.run(app.reinitialiser("claire", "e"))
    assert e.value.statut == statut and e.value.raison == raison
    assert "SECRET" not in e.value.message and "claire" not in e.value.message


def test_injoignable(monkeypatch):
    def h(req):
        raise httpx.ConnectError("x")
    with pytest.raises(ContratErreur) as e:
        asyncio.run(_app(h, monkeypatch).importer("c", b"P"))
    assert e.value.statut is None and "injoignable" in e.value.message


def test_exemple_a_jour_avec_le_manifeste_du_studio():
    racine = pathlib.Path(__file__).resolve().parents[2]
    manifeste = racine / "briques" / "studio" / "manifest.json"
    if not manifeste.exists():
        pytest.skip("hors monorepo (image Docker)")
    exemple = json.loads((pathlib.Path(__file__).parent / "contrats.exemple.json").read_text())
    assert exemple["studio"]["bloc"] == json.loads(manifeste.read_text())["contrat_donnees"]
