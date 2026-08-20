import asyncio
import io
import json
import tarfile
from pathlib import Path

import httpx
import pytest

import sauvegarde_usb


def _cadre_exec(type_flux: int, charge: bytes) -> bytes:
    """Construit une trame du format multiplexé Docker exec (Tty=false) :
    1 octet type + 3 octets réservés + 4 octets longueur (big-endian) + charge."""
    entete = bytes([type_flux, 0, 0, 0]) + len(charge).to_bytes(4, "big")
    return entete + charge


def test_demultiplexer_isole_stdout():
    brut = _cadre_exec(1, b"bonjour") + _cadre_exec(2, b"ignore-moi") + _cadre_exec(1, b" monde")
    assert sauvegarde_usb._demultiplexer(brut) == b"bonjour monde"


def test_demultiplexer_flux_vide():
    assert sauvegarde_usb._demultiplexer(b"") == b""


def test_exec_renvoie_code_et_stdout():
    # Async via asyncio.run — motif déjà en usage dans toute la suite core/ (cf.
    # core/test_muscle.py, core/test_amelioration_outils.py), pas de marqueur pytest.
    appels = []

    def handler(request: httpx.Request) -> httpx.Response:
        appels.append(request.url.path)
        if request.url.path == "/containers/abc123/exec":
            return httpx.Response(200, json={"Id": "exec1"})
        if request.url.path == "/exec/exec1/start":
            return httpx.Response(200, content=_cadre_exec(1, b"ok\n"))
        if request.url.path == "/exec/exec1/json":
            return httpx.Response(200, json={"ExitCode": 0})
        raise AssertionError(f"appel inattendu : {request.url.path}")

    async def go():
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://docker")
        async with client:
            return await sauvegarde_usb._exec(client, "abc123", ["echo", "ok"])

    code, sortie = asyncio.run(go())
    assert code == 0
    assert sortie == b"ok\n"
    assert appels == ["/containers/abc123/exec", "/exec/exec1/start", "/exec/exec1/json"]


def _reponse_containers_json(conteneurs: list[dict]) -> httpx.Response:
    return httpx.Response(200, json=conteneurs)


def test_decouvrir_sources_sqlite_et_postgres():
    def handler(request: httpx.Request) -> httpx.Response:
        chemin = request.url.path
        if chemin == "/containers/json":
            return _reponse_containers_json([
                {"Id": "sq1", "Names": ["/workplace_donnees"], "Image": "workplace/donnees:0.3.0"},
                {"Id": "pg1", "Names": ["/memoire-memoire-db-1"], "Image": "workplace/memoire-db-walg:0.1.0"},
            ])
        if chemin == "/containers/sq1/exec":
            return httpx.Response(200, json={"Id": "exec-find"})
        if chemin == "/exec/exec-find/start":
            return httpx.Response(200, content=_cadre_exec(1, b"/data/donnees.db\n"))
        if chemin == "/exec/exec-find/json":
            return httpx.Response(200, json={"ExitCode": 0})
        if chemin == "/containers/pg1/json":
            return httpx.Response(200, json={"Config": {"Env": [
                "POSTGRES_USER=memory", "POSTGRES_DB=memory", "PATH=/usr/bin"]}})
        raise AssertionError(f"appel inattendu : {chemin}")

    async def go():
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://docker")
        async with client:
            return await sauvegarde_usb.decouvrir_sources(client)

    sources = asyncio.run(go())

    assert {"brique": "workplace_donnees", "type": "sqlite", "conteneur_id": "sq1",
            "chemin": "/data/donnees.db"} in sources
    assert {"brique": "memoire-memoire-db-1", "type": "postgres", "conteneur_id": "pg1",
            "db": "memory", "user": "memory"} in sources


def test_decouvrir_sources_ignore_conteneur_sans_db():
    def handler(request: httpx.Request) -> httpx.Response:
        chemin = request.url.path
        if chemin == "/containers/json":
            return _reponse_containers_json(
                [{"Id": "vide1", "Names": ["/mesh_caddy"], "Image": "caddy:2"}])
        if chemin == "/containers/vide1/exec":
            return httpx.Response(200, json={"Id": "exec-find"})
        if chemin == "/exec/exec-find/start":
            return httpx.Response(200, content=_cadre_exec(1, b""))
        if chemin == "/exec/exec-find/json":
            return httpx.Response(200, json={"ExitCode": 1})
        raise AssertionError(f"appel inattendu : {chemin}")

    async def go():
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://docker")
        async with client:
            return await sauvegarde_usb.decouvrir_sources(client)

    assert asyncio.run(go()) == []


def test_decouvrir_sources_ignore_conteneur_en_echec():
    """Conteneur dont l'inspection ou l'exec échoue ne doit pas planter la découverte —
    les autres conteneurs (sains) doivent quand même être découverts. Teste la branche Postgres."""
    def handler(request: httpx.Request) -> httpx.Response:
        chemin = request.url.path
        if chemin == "/containers/json":
            return _reponse_containers_json([
                {"Id": "broken-pg", "Names": ["/db-broken"], "Image": "postgres:16"},
                {"Id": "good-sq", "Names": ["/donnees-ok"], "Image": "workplace/donnees:0.3.0"},
            ])
        # L'inspection du conteneur Postgres échoue (ex. race condition, arrêt soudain)
        if chemin == "/containers/broken-pg/json":
            return httpx.Response(500, json={"message": "Internal Server Error"})
        # Le conteneur SQLite fonctionne normalement
        if chemin == "/containers/good-sq/exec":
            return httpx.Response(200, json={"Id": "exec-find-ok"})
        if chemin == "/exec/exec-find-ok/start":
            return httpx.Response(200, content=_cadre_exec(1, b"/data/backup.db\n"))
        if chemin == "/exec/exec-find-ok/json":
            return httpx.Response(200, json={"ExitCode": 0})
        raise AssertionError(f"appel inattendu : {chemin}")

    async def go():
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://docker")
        async with client:
            return await sauvegarde_usb.decouvrir_sources(client)

    sources = asyncio.run(go())
    # Le conteneur brisé ne doit PAS être dans le résultat, mais le conteneur SQLite OK doit y être
    assert len(sources) == 1
    assert {"brique": "donnees-ok", "type": "sqlite", "conteneur_id": "good-sq",
            "chemin": "/data/backup.db"} in sources


def test_decouvrir_sources_ignore_echec_branche_sqlite():
    """Conteneur SQLite dont l'exec échoue ne doit pas planter la découverte —
    les autres conteneurs (sains) doivent quand même être découverts. Teste la branche SQLite."""
    def handler(request: httpx.Request) -> httpx.Response:
        chemin = request.url.path
        if chemin == "/containers/json":
            return _reponse_containers_json([
                {"Id": "broken-sq", "Names": ["/donnees-broken"], "Image": "workplace/donnees:0.3.0"},
                {"Id": "good-pg", "Names": ["/memoire-db"], "Image": "workplace/memoire-db-walg:0.1.0"},
            ])
        # Le conteneur SQLite échoue lors de l'exec find (ex. image sans shell, permissions)
        if chemin == "/containers/broken-sq/exec":
            return httpx.Response(500, json={"message": "Cannot create exec instance"})
        # Le conteneur Postgres fonctionne normalement
        if chemin == "/containers/good-pg/json":
            return httpx.Response(200, json={"Config": {"Env": [
                "POSTGRES_USER=memory", "POSTGRES_DB=memory", "PATH=/usr/bin"]}})
        raise AssertionError(f"appel inattendu : {chemin}")

    async def go():
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://docker")
        async with client:
            return await sauvegarde_usb.decouvrir_sources(client)

    sources = asyncio.run(go())
    # Le conteneur SQLite brisé ne doit PAS être dans le résultat, mais le conteneur Postgres OK doit y être
    assert len(sources) == 1
    assert {"brique": "memoire-db", "type": "postgres", "conteneur_id": "good-pg",
            "db": "memory", "user": "memory"} in sources


def test_verifier_sentinelle_absente_leve(tmp_path):
    with pytest.raises(RuntimeError, match="sentinelle"):
        sauvegarde_usb.verifier_sentinelle(tmp_path)


def test_verifier_sentinelle_presente_ne_leve_pas(tmp_path):
    (tmp_path / sauvegarde_usb.SENTINELLE_NOM).write_text("")
    sauvegarde_usb.verifier_sentinelle(tmp_path)  # ne doit rien lever


def test_verifier_espace_insuffisant_leve(tmp_path, monkeypatch):
    import shutil as shutil_mod

    class FauxUsage:
        free = 100

    monkeypatch.setattr(shutil_mod, "disk_usage", lambda _: FauxUsage())
    with pytest.raises(RuntimeError, match="Espace insuffisant"):
        sauvegarde_usb.verifier_espace(tmp_path, octets_requis=1_000_000)


def test_verifier_espace_suffisant_ne_leve_pas(tmp_path, monkeypatch):
    import shutil as shutil_mod

    class FauxUsage:
        free = 10_000_000

    monkeypatch.setattr(shutil_mod, "disk_usage", lambda _: FauxUsage())
    sauvegarde_usb.verifier_espace(tmp_path, octets_requis=1_000_000)  # ne doit rien lever


def _tar_dun_fichier(nom: str, contenu: bytes) -> bytes:
    tampon = io.BytesIO()
    with tarfile.open(fileobj=tampon, mode="w") as tar:
        info = tarfile.TarInfo(name=nom)
        info.size = len(contenu)
        tar.addfile(info, io.BytesIO(contenu))
    return tampon.getvalue()


def test_sauvegarder_ecrit_manifest_et_fichiers(tmp_path, monkeypatch):
    (tmp_path / sauvegarde_usb.SENTINELLE_NOM).write_text("")

    def handler(request: httpx.Request) -> httpx.Response:
        chemin = request.url.path
        if chemin == "/containers/json":
            return _reponse_containers_json([
                {"Id": "sq1", "Names": ["/workplace_donnees"], "Image": "workplace/donnees:0.3.0"},
                {"Id": "pg1", "Names": ["/memoire-memoire-db-1"], "Image": "workplace/memoire-db-walg:0.1.0"},
            ])
        if chemin == "/containers/sq1/exec":
            return httpx.Response(200, json={"Id": "exec-find"})
        if chemin == "/exec/exec-find/start":
            return httpx.Response(200, content=_cadre_exec(1, b"/data/donnees.db\n"))
        if chemin == "/exec/exec-find/json":
            return httpx.Response(200, json={"ExitCode": 0})
        if chemin == "/containers/pg1/json":
            return httpx.Response(200, json={"Config": {"Env": [
                "POSTGRES_USER=memory", "POSTGRES_DB=memory"]}})
        if chemin == "/containers/sq1/archive":
            return httpx.Response(200, content=_tar_dun_fichier("donnees.db", b"contenu-sqlite"))
        if chemin == "/containers/pg1/exec":
            return httpx.Response(200, json={"Id": "exec-dump"})
        if chemin == "/exec/exec-dump/start":
            return httpx.Response(200, content=_cadre_exec(1, b"-- dump sql --\n"))
        if chemin == "/exec/exec-dump/json":
            return httpx.Response(200, json={"ExitCode": 0})
        raise AssertionError(f"appel inattendu : {chemin}")

    def _client_de_test():
        return httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://docker")

    monkeypatch.setattr(sauvegarde_usb, "_docker_client", _client_de_test)

    manifeste = asyncio.run(sauvegarde_usb.sauvegarder(tmp_path))

    assert (tmp_path / "manifest.json").exists()
    disque = json.loads((tmp_path / "manifest.json").read_text())
    assert disque == manifeste
    par_brique = {s["brique"]: s for s in manifeste["sources"]}
    assert par_brique["workplace_donnees"]["fichier"] == "donnees.db"
    assert (tmp_path / "workplace_donnees" / "donnees.db").read_bytes() == b"contenu-sqlite"
    assert par_brique["memoire-memoire-db-1"]["fichier"] == "memory.sql"
    assert (tmp_path / "memoire-memoire-db-1" / "memory.sql").read_bytes() == b"-- dump sql --\n"
    assert all("conteneur_id" not in s for s in manifeste["sources"])


def test_sauvegarder_refuse_sans_sentinelle(tmp_path):
    with pytest.raises(RuntimeError, match="sentinelle"):
        asyncio.run(sauvegarde_usb.sauvegarder(tmp_path))


def test_sauvegarder_echec_partiel(tmp_path, monkeypatch):
    """Une source échoue (pg_dump code non-zéro) tandis qu'une autre réussit.
    Vérifie que le manifeste contient `ignore: true` pour celle qui échoue,
    et une entrée normale pour celle qui réussit."""
    (tmp_path / sauvegarde_usb.SENTINELLE_NOM).write_text("")

    # Track exec calls to pg-broken to distinguish size vs dump
    class HandlerState:
        pg_exec_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        chemin = request.url.path
        if chemin == "/containers/json":
            return _reponse_containers_json([
                {"Id": "sq1", "Names": ["/workplace_donnees"], "Image": "workplace/donnees:0.3.0"},
                {"Id": "pg-broken", "Names": ["/memoire-broken"], "Image": "workplace/memoire-db-walg:0.1.0"},
            ])
        # SQLite path (should succeed)
        if chemin == "/containers/sq1/exec":
            return httpx.Response(200, json={"Id": "exec-find"})
        if chemin == "/exec/exec-find/start":
            return httpx.Response(200, content=_cadre_exec(1, b"/data/donnees.db\n"))
        if chemin == "/exec/exec-find/json":
            return httpx.Response(200, json={"ExitCode": 0})
        if chemin == "/containers/sq1/archive":
            return httpx.Response(200, content=_tar_dun_fichier("donnees.db", b"contenu-sqlite"))
        # Postgres inspection (for source discovery and size calculation)
        if chemin == "/containers/pg-broken/json":
            return httpx.Response(200, json={"Config": {"Env": [
                "POSTGRES_USER=memory", "POSTGRES_DB=memory"]}})
        # Postgres exec calls: first is for size calculation, second is for dump
        if chemin == "/containers/pg-broken/exec":
            HandlerState.pg_exec_count += 1
            if HandlerState.pg_exec_count == 1:
                # First exec: size calculation (psql)
                return httpx.Response(200, json={"Id": "exec-size"})
            else:
                # Second exec: dump (pg_dump) — will fail
                return httpx.Response(200, json={"Id": "exec-dump"})
        if chemin == "/exec/exec-size/start":
            return httpx.Response(200, content=_cadre_exec(1, b"1024\n"))
        if chemin == "/exec/exec-size/json":
            return httpx.Response(200, json={"ExitCode": 0})
        # Postgres dump fails
        if chemin == "/exec/exec-dump/start":
            return httpx.Response(200, content=_cadre_exec(2, b"ERROR: permission denied\n"))
        if chemin == "/exec/exec-dump/json":
            return httpx.Response(200, json={"ExitCode": 1})
        raise AssertionError(f"appel inattendu : {chemin}")

    def _client_de_test():
        return httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://docker")

    monkeypatch.setattr(sauvegarde_usb, "_docker_client", _client_de_test)

    manifeste = asyncio.run(sauvegarde_usb.sauvegarder(tmp_path))

    par_brique = {s["brique"]: s for s in manifeste["sources"]}

    # SQLite (successful) should have normal entry
    assert par_brique["workplace_donnees"]["ignore"] is False
    assert par_brique["workplace_donnees"]["fichier"] == "donnees.db"
    assert par_brique["workplace_donnees"]["raison"] is None
    assert (tmp_path / "workplace_donnees" / "donnees.db").exists()
    assert (tmp_path / "workplace_donnees" / "donnees.db").read_bytes() == b"contenu-sqlite"

    # Postgres (failed) should have ignore: true with reason
    assert par_brique["memoire-broken"]["ignore"] is True
    assert par_brique["memoire-broken"]["fichier"] is None
    assert par_brique["memoire-broken"]["raison"] is not None
    assert "pg_dump" in par_brique["memoire-broken"]["raison"]


def test_sauvegarder_taille_octets_est_taille_reelle(tmp_path, monkeypatch):
    """Vérifie que taille_octets dans le manifeste est la taille réelle du fichier écrit,
    pas une estimation pré-écriture. Important car pour Postgres, la taille du dump SQL
    (logique) est généralement bien plus petite que pg_database_size (brute avec index/bloat)."""
    (tmp_path / sauvegarde_usb.SENTINELLE_NOM).write_text("")

    def handler(request: httpx.Request) -> httpx.Response:
        chemin = request.url.path
        if chemin == "/containers/json":
            return _reponse_containers_json([
                {"Id": "sq1", "Names": ["/workplace_donnees"], "Image": "workplace/donnees:0.3.0"},
                {"Id": "pg1", "Names": ["/memoire-memoire-db-1"], "Image": "workplace/memoire-db-walg:0.1.0"},
            ])
        if chemin == "/containers/sq1/exec":
            return httpx.Response(200, json={"Id": "exec-find"})
        if chemin == "/exec/exec-find/start":
            return httpx.Response(200, content=_cadre_exec(1, b"/data/donnees.db\n"))
        if chemin == "/exec/exec-find/json":
            return httpx.Response(200, json={"ExitCode": 0})
        if chemin == "/containers/pg1/json":
            return httpx.Response(200, json={"Config": {"Env": [
                "POSTGRES_USER=memory", "POSTGRES_DB=memory"]}})
        if chemin == "/containers/sq1/archive":
            return httpx.Response(200, content=_tar_dun_fichier("donnees.db", b"contenu-sqlite"))
        if chemin == "/containers/pg1/exec":
            return httpx.Response(200, json={"Id": "exec-dump"})
        if chemin == "/exec/exec-dump/start":
            return httpx.Response(200, content=_cadre_exec(1, b"-- dump sql --\n"))
        if chemin == "/exec/exec-dump/json":
            return httpx.Response(200, json={"ExitCode": 0})
        raise AssertionError(f"appel inattendu : {chemin}")

    def _client_de_test():
        return httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://docker")

    monkeypatch.setattr(sauvegarde_usb, "_docker_client", _client_de_test)

    manifeste = asyncio.run(sauvegarde_usb.sauvegarder(tmp_path))

    par_brique = {s["brique"]: s for s in manifeste["sources"]}

    # SQLite: taille réelle du fichier écrit
    assert par_brique["workplace_donnees"]["taille_octets"] == len(b"contenu-sqlite")

    # Postgres: taille réelle du dump SQL écrit, pas pg_database_size pré-écriture
    # Le dump SQL fait 16 octets (b"-- dump sql --\n")
    assert par_brique["memoire-memoire-db-1"]["taille_octets"] == len(b"-- dump sql --\n")


def test_restaurer_sqlite_et_postgres(tmp_path, monkeypatch):
    (tmp_path / sauvegarde_usb.SENTINELLE_NOM).write_text("")
    (tmp_path / "workplace_donnees").mkdir()
    (tmp_path / "workplace_donnees" / "donnees.db").write_bytes(b"contenu-sqlite")
    (tmp_path / "memoire-memoire-db-1").mkdir()
    (tmp_path / "memoire-memoire-db-1" / "memory.sql").write_bytes(b"-- dump --")
    (tmp_path / "manifest.json").write_text(json.dumps({
        "horodatage": "2026-08-20T18:00:00+00:00",
        "sources": [
            {"brique": "workplace_donnees", "type": "sqlite", "chemin": "/data/donnees.db",
             "fichier": "donnees.db", "taille_octets": 14, "ignore": False, "raison": None},
            {"brique": "memoire-memoire-db-1", "type": "postgres", "db": "memory",
             "user": "memory", "fichier": "memory.sql", "taille_octets": 10,
             "ignore": False, "raison": None},
            {"brique": "brique-arretee", "type": "sqlite", "chemin": "/data/x.db",
             "fichier": "x.db", "taille_octets": 1, "ignore": False, "raison": None},
        ],
    }))

    appels_put = []

    def handler(request: httpx.Request) -> httpx.Response:
        chemin = request.url.path
        if chemin == "/containers/json":
            return _reponse_containers_json([
                {"Id": "sq1", "Names": ["/workplace_donnees"], "Image": "workplace/donnees:0.3.0"},
                {"Id": "pg1", "Names": ["/memoire-memoire-db-1"], "Image": "workplace/memoire-db-walg:0.1.0"},
            ])
        if chemin in ("/containers/sq1/archive", "/containers/pg1/archive") and request.method == "PUT":
            appels_put.append(chemin)
            return httpx.Response(200)
        if chemin == "/containers/pg1/exec":
            return httpx.Response(200, json={"Id": "exec-psql"})
        if chemin == "/exec/exec-psql/start":
            return httpx.Response(200, content=_cadre_exec(1, b""))
        if chemin == "/exec/exec-psql/json":
            return httpx.Response(200, json={"ExitCode": 0})
        raise AssertionError(f"appel inattendu : {request.method} {chemin}")

    def _client_de_test():
        return httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://docker")

    monkeypatch.setattr(sauvegarde_usb, "_docker_client", _client_de_test)

    resultat = asyncio.run(sauvegarde_usb.restaurer(tmp_path))
    par_brique = {r["brique"]: r for r in resultat["resultats"]}

    assert par_brique["workplace_donnees"]["ok"] is True
    assert par_brique["memoire-memoire-db-1"]["ok"] is True
    assert par_brique["brique-arretee"]["ok"] is False
    assert "introuvable" in par_brique["brique-arretee"]["message"]
    assert appels_put == ["/containers/sq1/archive", "/containers/pg1/archive"]
