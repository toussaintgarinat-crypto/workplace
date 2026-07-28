"""S211 — le Cœur porte ETL_KEY sur TOUS ses appels à la brique ETL.

La brique ETL est passée de « grande ouverte sur 5200 » à « fermée par API_KEYS ».
Le contrat manifeste (capacités `etl_*`) passe déjà par `outils_communs._entetes_brique`,
mais cinq chemins CÂBLÉS l'ignoraient : usine à applications, cycle de vie (décrocher /
reprendre), rappels proactifs, dépôt de document du front, et les outils `documents`.
Un seul oublié = un 401 silencieux sur un chemin rarement emprunté — donc un test par
chemin, pas un test sur le helper.

Aucun réseau : `httpx.AsyncClient` est remplacé par un faux qui capture les en-têtes.
"""
import asyncio
import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(__file__))

import cycle_de_vie  # noqa: E402
import orchestrateur  # noqa: E402
import outils_communs  # noqa: E402
import proactif  # noqa: E402

CLE = "cle-etl-de-service"


class _FauxClient:
    """Capture (méthode, url, headers) de chaque appel, sans réseau."""

    def __init__(self, reponses=None):
        self.appels = []
        self._reponses = reponses or {}

    def __call__(self, *a, **k):
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    def _reponse(self, url):
        charge = next((c for motif, c in self._reponses.items() if motif in url), {})
        return SimpleNamespace(status_code=200, json=lambda: charge, text="",
                               raise_for_status=lambda: None)

    async def get(self, url, **k):
        self.appels.append(("GET", url, k.get("headers") or {}))
        return self._reponse(url)

    async def post(self, url, **k):
        self.appels.append(("POST", url, k.get("headers") or {}))
        return self._reponse(url)

    async def patch(self, url, **k):
        self.appels.append(("PATCH", url, k.get("headers") or {}))
        return self._reponse(url)

    async def delete(self, url, **k):
        self.appels.append(("DELETE", url, k.get("headers") or {}))
        return self._reponse(url)


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def _cles_etl(faux):
    """Clés X-API-Key vues sur les appels visant l'ETL (au moins un appel exigé)."""
    vus = [h.get("X-API-Key") for m, u, h in faux.appels if "etl" in u]
    assert vus, f"aucun appel vers l'ETL capturé — appels : {faux.appels}"
    return vus


# ── Le helper, source unique du nommage ──────────────────────────────────────

def test_entetes_brique_derive_le_nom_de_variable(monkeypatch):
    monkeypatch.setenv("ETL_KEY", CLE)
    assert orchestrateur.entetes_brique("etl") == {"X-API-Key": CLE}
    # Tiret → underscore, motif déjà vérifié côté outils_communs.
    monkeypatch.setenv("VEILLE_INFO_KEY", "vi")
    assert orchestrateur.entetes_brique("veille-info") == {"X-API-Key": "vi"}


def test_entetes_brique_sans_cle_ne_pose_pas_den_tete(monkeypatch):
    """Déploiement non configuré : pas d'en-tête vide qui ferait échouer une brique ouverte."""
    monkeypatch.delenv("ETL_KEY", raising=False)
    assert orchestrateur.entetes_brique("etl") == {}


def test_outils_communs_utilise_la_meme_source(monkeypatch):
    monkeypatch.setenv("ETL_KEY", CLE)
    assert outils_communs._entetes_brique("etl")["X-API-Key"] == CLE


# ── Les cinq chemins câblés ──────────────────────────────────────────────────

def test_usine_ingestion_porte_la_cle(monkeypatch):
    """Étape « ingestion » de l'usine à applications (dépôt puis liste)."""
    monkeypatch.setenv("ETL_KEY", CLE)
    monkeypatch.setattr(orchestrateur, "_maj_etape", lambda *a, **k: None)
    monkeypatch.setattr(orchestrateur, "_maj", lambda *a, **k: None)
    faux = _FauxClient({"/ingerer": {"id": "doc-1"}})

    _run(orchestrateur._etape_ingestion(
        faux, "http://etl", [("a.pdf", b"x", "application/pdf")], "liv-1"))

    assert _cles_etl(faux) == [CLE]


def test_usine_ingestion_sans_fichier_porte_la_cle(monkeypatch):
    """Variante « auditer les documents déjà présents » : autre appel, même exigence."""
    monkeypatch.setenv("ETL_KEY", CLE)
    monkeypatch.setattr(orchestrateur, "_maj_etape", lambda *a, **k: None)
    monkeypatch.setattr(orchestrateur, "_maj", lambda *a, **k: None)
    faux = _FauxClient({"/documents": {"documents": [{"id": "doc-9"}]}})

    _run(orchestrateur._etape_ingestion(faux, "http://etl", [], "liv-1"))

    assert _cles_etl(faux) == [CLE]


def test_cycle_de_vie_reinjecter_porte_la_cle(monkeypatch):
    """« Reprendre » une entreprise décrochée : réimport des documents."""
    monkeypatch.setenv("ETL_KEY", CLE)
    monkeypatch.setattr(cycle_de_vie, "_bases", lambda registre: {
        "etl": "http://etl", "audit": "http://audit",
        "generateur": "http://gen", "donnees": "http://donnees"})
    faux = _FauxClient({"/documents/import": {"id": "doc-1"}})
    monkeypatch.setattr(cycle_de_vie.httpx, "AsyncClient", faux)

    _run(cycle_de_vie._reinjecter(None, {"documents": [{"nom": "a.txt"}]}))

    assert _cles_etl(faux) == [CLE]


def test_proactif_documents_a_classer_porte_la_cle(monkeypatch):
    """Tick proactif « documents à classer » — sans clé, le rappel disparaît en silence."""
    monkeypatch.setenv("ETL_KEY", CLE)
    monkeypatch.setattr(proactif.orchestrateur, "_brique_base",
                        lambda registre, nom: "http://etl")
    faux = _FauxClient({"/documents": {"documents": []}})
    monkeypatch.setattr(proactif.httpx, "AsyncClient", faux)

    _run(proactif._check_documents(SimpleNamespace(briques={"etl": {"port": 5200}})))

    assert _cles_etl(faux) == [CLE]


def test_outils_documents_portent_la_cle(monkeypatch):
    """Outils câblés du domaine « documents » : lecture, liste, dossiers, ingestion, classement."""
    monkeypatch.setenv("ETL_KEY", CLE)
    import outils_domaines.documents as documents
    monkeypatch.setattr(documents, "_base", lambda registre, nom: f"http://{nom}")
    registre = SimpleNamespace(briques={"etl": {"port": 5200}})

    for outil, args in (
        ("chercher_documents", {}),
        ("lister_dossiers", {}),
        ("lire_document", {"doc_id": "d1"}),
        ("ingerer_document", {"url": "http://exemple.test/a", "confirme": True}),
        ("classer_document", {"doc_id": "d1", "categorie": "devis", "confirme": True}),
    ):
        faux = _FauxClient({"/documents": {"documents": []}, "/dossiers": {}})
        _run(documents.dispatch(outil, args, registre, faux))
        assert _cles_etl(faux) == [CLE], f"outil {outil} sans clé"
