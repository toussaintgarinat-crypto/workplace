"""Livraison <-> vrai Studio (ASGI en processus) : verifier -> reset -> restitution, voisin intact."""
import asyncio
import base64
import hashlib
import importlib
import os
import pathlib
import sys

import httpx
import pytest

import donnees_utilisateur as D
import paquets as P
from contrats import AppContrat, ContratErreur

STUDIO = pathlib.Path(__file__).resolve().parents[1] / "studio"
pytestmark = pytest.mark.skipif(not STUDIO.exists(), reason="hors monorepo (image Docker)")

CLE = "cle-support-e2e"
_MODULES = ("main", "studio", "support", "stockage_pont", "contrat_donnees")


class FauxExecuteur:
    def __init__(self):
        self.objets = {}

    async def deposer(self, cle, octets):
        self.objets[cle] = octets

    async def lire(self, cle):
        return self.objets[cle]

    async def supprimer(self, cle):
        self.objets.pop(cle, None)


class TransportEnregistreur(httpx.AsyncBaseTransport):
    def __init__(self, interne):
        self.interne, self.urls = interne, []

    async def handle_async_request(self, request):
        self.urls.append(str(request.url))
        return await self.interne.handle_async_request(request)


@pytest.fixture
def studio(tmp_path, monkeypatch):
    """Charge le Studio réel avec `briques/studio` en tête de sys.path, sans écraser le `main` de
    livraison : les modules homonymes sont retirés puis restaurés."""
    monkeypatch.setenv("STUDIO_SUPPORT_KEY", CLE)
    monkeypatch.delenv("STUDIO_KEY", raising=False)
    monkeypatch.setenv("LIVRAISON_CHIFFREMENT_CLE", base64.b64encode(os.urandom(32)).decode())
    monkeypatch.setenv("STUDIO_DIR", str(tmp_path / "volume"))   # les modules créent ce dossier à l'import
    monkeypatch.setenv("API_KEYS", "")
    os.makedirs(tmp_path / "volume")
    anciens = {m: sys.modules.pop(m) for m in _MODULES if m in sys.modules}
    sys.path.insert(0, str(STUDIO))
    try:
        S = importlib.import_module("studio")
        stockage = importlib.import_module("stockage_pont")
        for sous in ("profils", "comptes", "pont"):
            os.makedirs(tmp_path / "volume" / sous, exist_ok=True)
        vol = str(tmp_path / "volume")
        monkeypatch.setattr(S, "ATELIERS_DIR", vol)
        monkeypatch.setattr(S, "PROFILS_DIR", vol + "/profils")
        monkeypatch.setattr(S, "COMPTES_DIR", vol + "/comptes")
        monkeypatch.setattr(stockage, "ATELIERS_DIR", vol)
        monkeypatch.setattr(stockage, "PONT_DIR", vol + "/pont")
        yield importlib.import_module("main"), S, stockage, pathlib.Path(vol)
    finally:
        sys.path.remove(str(STUDIO))
        for m in _MODULES:
            sys.modules.pop(m, None)
        sys.modules.update(anciens)


def _bloc():
    import json
    return json.loads((STUDIO / "manifest.json").read_text())["contrat_donnees"]


def _entree():
    return {"url": "http://studio.test", "cle_env": "STUDIO_SUPPORT_KEY", "bloc": _bloc()}


def _peupler(S, stockage, u):
    sid, pid = f"serie-{u}", f"profil-{u}"
    S._save({"id": sid, "titre": f"Série de {u}", "cree_par": u, "episodes": []})
    S._save_profil({"id": pid, "nom": f"Enfant de {u}", "cible": "6-8", "cree_par": u})
    S._ajouter_evenement(pid, {"type": "ecoute", "serie_id": sid})
    S._save_compte(u, {"nom_famille": f"Famille {u}"})
    stockage.fixer_monde(sid, f"monde-{u}")


def _instantane(vol):
    return {str(p.relative_to(vol)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(vol.rglob("*")) if p.is_file()}


def run(c):
    return asyncio.run(c)


@pytest.fixture
def monde(studio):
    main, S, stockage, vol = studio
    _peupler(S, stockage, "claire")
    claire = _instantane(vol)
    _peupler(S, stockage, "paul")
    tout = _instantane(vol)
    paul = {k: v for k, v in tout.items() if k not in claire}
    assert claire and paul
    transport = TransportEnregistreur(httpx.ASGITransport(app=main.app))
    app = AppContrat("studio", _entree(), transport=transport)
    return {"S": S, "stockage": stockage, "vol": vol, "app": app, "ex": FauxExecuteur(),
            "claire": claire, "paul": paul, "transport": transport}


def test_verifier_reset_restitution_voisin_intact(monde):
    app, ex, vol = monde["app"], monde["ex"], monde["vol"]
    # (1) vérification
    v = run(D.verifier_paquet(app, ex, "claire"))
    assert v["verdict"] == "valide", v
    _, avant = run(app.exporter("claire"))
    # (2) reset : Claire disparaît, Paul octet pour octet identique
    r = run(D.reinitialiser_donnees(app, ex, "claire"))
    assert r["etat"] == "reinitialise"
    apres = _instantane(vol)
    assert not (set(monde["claire"]) & set(apres)), "des fichiers de Claire ont survécu"
    assert {k: apres.get(k) for k in monde["paul"]} == monde["paul"], "Paul a été touché"
    # (3) restitution implicite : même empreinte, paquet marqué restitué, 2e appel refusé
    rest = run(D.restituer_donnees(app, ex, "claire"))
    assert rest["etat"] == "restitue"
    _, apres_rest = run(app.exporter("claire"))
    assert apres_rest["empreinte"] == avant["empreinte"]
    assert P.lire(v["paquet_id"]).get("restitue_a")
    with pytest.raises(D.RefusDonnees) as e:
        run(D.restituer_donnees(app, ex, "claire"))
    assert e.value.statut == 404
    assert {k: _instantane(vol).get(k) for k in monde["paul"]} == monde["paul"]
    # l'identité n'apparaît dans aucune URL envoyée
    assert monde["transport"].urls
    for u in monde["transport"].urls:
        assert "claire" not in u and "paul" not in u


def test_reset_sans_paquet_verifie_409_rien_efface(monde):
    avant = _instantane(monde["vol"])
    with pytest.raises(D.RefusDonnees) as e:
        run(D.reinitialiser_donnees(monde["app"], monde["ex"], "claire"))
    assert e.value.statut == 409
    assert _instantane(monde["vol"]) == avant


def test_ecriture_apres_verification_refuse_le_reset(monde):
    app, ex, S = monde["app"], monde["ex"], monde["S"]
    assert run(D.verifier_paquet(app, ex, "claire"))["verdict"] == "valide"
    S._save({"id": "serie-claire-bis", "titre": "Nouvelle", "cree_par": "claire", "episodes": []})
    avant = _instantane(monde["vol"])
    with pytest.raises(D.RefusDonnees) as e:
        run(D.reinitialiser_donnees(app, ex, "claire"))
    assert e.value.statut == 409 and "ont changé" in e.value.message
    assert _instantane(monde["vol"]) == avant


def test_cle_fausse_refusee_par_le_studio(studio, monkeypatch):
    main = studio[0]
    monkeypatch.setenv("STUDIO_SUPPORT_KEY", "autre-cle")
    app = AppContrat("studio", _entree(), transport=httpx.ASGITransport(app=main.app))
    monkeypatch.setenv("STUDIO_SUPPORT_KEY", CLE)       # le Studio relit sa clé à chaque appel
    with pytest.raises(ContratErreur) as e:
        run(app.exporter("claire"))
    assert e.value.raison == "cle_refusee" and e.value.statut == 401


def test_support_desactive_cote_studio_503(studio, monkeypatch):
    main = studio[0]
    app = AppContrat("studio", _entree(), transport=httpx.ASGITransport(app=main.app))
    monkeypatch.delenv("STUDIO_SUPPORT_KEY")
    with pytest.raises(ContratErreur) as e:
        run(app.exporter("claire"))
    assert e.value.raison == "desactive" and e.value.statut == 503


def test_cle_absente_cote_livraison_503_non_configure(monkeypatch):
    monkeypatch.delenv("STUDIO_SUPPORT_KEY", raising=False)
    with pytest.raises(ContratErreur) as e:
        AppContrat("studio", _entree())
    assert e.value.statut == 503
