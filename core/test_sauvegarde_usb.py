import asyncio

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
