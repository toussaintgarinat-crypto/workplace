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
    assert set(destinations.REGISTRE) == {"memoire", "dossier", "gdrive"}
    assert destinations.defaut() == "memoire"          # souverain par défaut


def test_destination_inconnue_pont_consenti():
    out = _run(destinations.archiver(_paquet(), "dropbox"))
    assert out["ok"] is False                          # jamais en silence
    assert "inconnue" in out["erreur"]


def test_gdrive_non_configure(monkeypatch):
    for v in ("GDRIVE_CLIENT_ID", "GDRIVE_CLIENT_SECRET", "GDRIVE_REFRESH_TOKEN"):
        monkeypatch.delenv(v, raising=False)
    out = _run(destinations.archiver(_paquet(), "gdrive"))
    assert out["ok"] is False
    assert "configuré" in out["erreur"].lower()        # échec rapide, sans réseau


def test_gdrive_mock(monkeypatch):
    monkeypatch.setenv("GDRIVE_CLIENT_ID", "cid")
    monkeypatch.setenv("GDRIVE_CLIENT_SECRET", "secret")
    monkeypatch.setenv("GDRIVE_REFRESH_TOKEN", "refresh")
    monkeypatch.setenv("GDRIVE_FOLDER_ID", "folder123")
    appels = []

    class _Rep:
        def __init__(self, data): self._d = data
        def raise_for_status(self): ...
        def json(self): return self._d

    class _Client:
        def __init__(self, *a, **k): ...
        async def __aenter__(self): return self
        async def __aexit__(self, *a): ...
        async def post(self, url, **k):
            appels.append((url, k))
            if "oauth2" in url:
                return _Rep({"access_token": "ya29.test"})
            return _Rep({"id": "drive-1", "name": "notes.md",
                         "webViewLink": "https://drive.google.com/file/d/drive-1"})

    monkeypatch.setattr(destinations.httpx, "AsyncClient", _Client)
    out = _run(destinations.archiver(_paquet(), "gdrive"))
    assert out["ok"] is True and out["destination"] == "gdrive"
    assert out["id"] == "drive-1" and "drive.google.com" in out["lien"]
    # token échangé puis upload multipart vers l'endpoint Drive
    assert any("oauth2.googleapis.com" in u for u, _ in appels)
    upload = [k for u, k in appels if "upload/drive" in u][0]
    assert upload["params"]["uploadType"] == "multipart"
    assert "folder123" in upload["content"].decode("utf-8")    # dossier cible inséré


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
