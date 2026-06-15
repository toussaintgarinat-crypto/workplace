"""Tests des destinations : choix explicite, dossier réel, mémoire (mock), pont consenti."""
import asyncio

import destinations
import rendu


def _run(coro):
    return asyncio.run(coro)


def _paquet():
    return rendu.paquet({"resume": "synthèse", "points_action": ["faire X"],
                         "themes": ["budget"], "decisions": ["valider Y"]},
                        {"texte": "texte transcrit", "langue": "fr"}, titre="Réunion")


def test_registre_et_defaut_souverain():
    assert set(destinations.REGISTRE) == {"memoire", "dossier"}
    assert destinations.defaut() == "memoire"          # souverain par défaut


def test_destination_inconnue_pont_consenti():
    out = _run(destinations.archiver(_paquet(), "gdrive"))
    assert out["ok"] is False                          # jamais en silence
    assert "inconnue" in out["erreur"]


def test_dossier_non_configure(monkeypatch):
    monkeypatch.delenv("NOTES_DOSSIER", raising=False)
    out = _run(destinations.archiver(_paquet(), "dossier"))
    assert out["ok"] is False
    assert "dossier" in out["erreur"].lower()          # erreur claire, pas en silence


def test_dossier_ecrit_un_markdown(tmp_path):
    out = _run(destinations.archiver(_paquet(), "dossier", dossier=str(tmp_path)))
    assert out["ok"] is True and out["destination"] == "dossier"
    fichiers = list(tmp_path.glob("*.md"))
    assert len(fichiers) == 1
    contenu = fichiers[0].read_text(encoding="utf-8")
    assert "# Réunion" in contenu and "valider Y" in contenu
    assert fichiers[0].name.endswith("-reunion.md")    # slug dans le nom


def test_memoire_mock(monkeypatch):
    envois = {}

    class _Rep:
        def raise_for_status(self): ...
        def json(self): return {"id": "n-1", "titre": "Réunion"}

    class _Client:
        def __init__(self, *a, **k): ...
        async def __aenter__(self): return self
        async def __aexit__(self, *a): ...
        async def post(self, url, json=None, **k):
            envois["url"] = url
            envois["corps"] = json
            return _Rep()

    monkeypatch.setattr(destinations.httpx, "AsyncClient", _Client)
    out = _run(destinations.archiver(_paquet(), "memoire"))
    assert out["ok"] is True and out["id"] == "n-1" and out["souverain"] is True
    assert envois["url"].endswith("/retenir")
    # le résumé part en Markdown, les listes en metadata structurée
    assert "## Décisions" in envois["corps"]["contenu"]
    assert envois["corps"]["metadata"]["points_action"] == ["faire X"]


def test_memoire_en_panne_pont_consenti(monkeypatch):
    class _Client:
        def __init__(self, *a, **k): ...
        async def __aenter__(self): return self
        async def __aexit__(self, *a): ...
        async def post(self, *a, **k): raise RuntimeError("mémoire down")

    monkeypatch.setattr(destinations.httpx, "AsyncClient", _Client)
    out = _run(destinations.archiver(_paquet(), "memoire"))
    assert out["ok"] is False
    assert "down" in out["erreur"]                      # erreur remontée, pas avalée
